"""DE-TECH-TIVE TECHNOLOGIES Inc — Master / Host API server."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.config import get_settings, validate_production_settings
from .core.database import get_engine, get_sessionmaker
from .core.security import hash_password
from .models import Role, User
from .routers import admin, auth, billing, exemptions, kiosk, kiosks, schools, students, users, ws
from .services import flagging

log = logging.getLogger("detechtive")
VERSION = "1.0.0"


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    base = Path(__file__).resolve().parent.parent
    cfg = Config(str(base / "alembic.ini"))
    cfg.set_main_option("script_location", str(base / "alembic"))
    command.upgrade(cfg, "head")


async def bootstrap_supersudo() -> None:
    s = get_settings()
    async with get_sessionmaker()() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        if count or not s.bootstrap_supersudo_email:
            return
        password = s.bootstrap_supersudo_password
        generated = False
        if not password:
            password = secrets.token_urlsafe(14) + "!A1"
            generated = True
        db.add(User(email=s.bootstrap_supersudo_email.lower(), full_name="Platform Administrator",
                    role=Role.SUPERSUDO, password_hash=hash_password(password)))
        await db.commit()
        if generated:
            data_dir = Path(os.path.dirname(s.sqlite_path) or ".")
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "INITIAL_ADMIN_PASSWORD.txt"
            path.write_text(f"email: {s.bootstrap_supersudo_email}\npassword: {password}\n"
                            "Delete this file after your first login and change the password.\n")
            os.chmod(path, 0o600)
            log.warning("Created SUPERSUDO %s; initial password written to %s", s.bootstrap_supersudo_email, path)
        else:
            log.warning("Created SUPERSUDO %s from BOOTSTRAP_SUPERSUDO_PASSWORD", s.bootstrap_supersudo_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    problems = validate_production_settings(s)
    if problems:
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    get_engine()
    if os.environ.get("SKIP_MIGRATIONS") != "1":
        await asyncio.to_thread(run_migrations)
    await bootstrap_supersudo()
    stop = asyncio.Event()
    task = None
    if s.environment != "test":
        task = asyncio.create_task(flagging.background_loop(stop))
    yield
    stop.set()
    if task:
        await task


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(
        title="DE-TECH-TIVE TECHNOLOGIES Inc API",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None if s.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if s.is_production else "/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Token", "X-Device-UID", "X-Pairing-Secret"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        else:
            h.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://checkout.stripe.com",
            )
        if s.secure_cookies:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - defensive
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    for r in (auth, kiosk, kiosks, schools, students, exemptions, users, billing, admin, ws):
        app.include_router(r.router)

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok", "version": VERSION}

    dist = Path(__file__).resolve().parent.parent / (s.serve_frontend_dist or "__none__")
    if s.serve_frontend_dist and dist.is_dir() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                raise StarletteHTTPException(404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
