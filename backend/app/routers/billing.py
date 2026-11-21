"""Stripe billing — $19.99 / month / school.

Safety-first grace policy: subscription status NEVER gates kiosk sign-ins, the emergency locator or the
lockdown roll-call. A past-due / cancelled school only sees a billing banner in the admin portal.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.config import get_settings
from ..core.database import get_db
from ..core.deps import get_school_or_404, require_roles, resolve_billing_school_id
from ..models import Role, School, StripeWebhookEvent, SubscriptionStatus, User
from ..schemas import CheckoutRequest, UrlResponse

log = logging.getLogger("detechtive.billing")
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
require_billing_admin = require_roles(Role.SUPERSUDO, Role.PRINCIPAL, Role.SCHOOL_ADMIN)

STATUS_MAP = {
    "active": SubscriptionStatus.active,
    "trialing": SubscriptionStatus.trialing,
    "past_due": SubscriptionStatus.past_due,
    "canceled": SubscriptionStatus.canceled,
    "unpaid": SubscriptionStatus.unpaid,
    "incomplete": SubscriptionStatus.incomplete,
    "incomplete_expired": SubscriptionStatus.canceled,
    "paused": SubscriptionStatus.past_due,
}


def _stripe_ready() -> None:
    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe is not configured on this server")
    stripe.api_key = s.stripe_secret_key


def _line_item() -> dict:
    s = get_settings()
    if s.stripe_price_id_school_monthly:
        return {"price": s.stripe_price_id_school_monthly, "quantity": 1}
    return {
        "price_data": {
            "currency": "usd",
            "unit_amount": s.school_monthly_price_cents,
            "recurring": {"interval": "month"},
            "product_data": {"name": "DE-TECH-TIVE School Subscription (per school)"},
        },
        "quantity": 1,
    }


@router.post("/create-checkout-session", response_model=UrlResponse)
async def create_checkout_session(
    body: CheckoutRequest, request: Request, user: User = Depends(require_billing_admin), db: AsyncSession = Depends(get_db)
):
    _stripe_ready()
    s = get_settings()
    school = await get_school_or_404(db, resolve_billing_school_id(user, body.school_id))
    if school.subscription_status in (SubscriptionStatus.active, SubscriptionStatus.trialing) and school.stripe_subscription_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "School already has an active subscription; use the billing portal")
    if not school.stripe_customer_id:
        customer = stripe.Customer.create(
            name=school.name, email=user.email, metadata={"school_id": str(school.id)},
            idempotency_key=f"customer-{school.id}",
        )
        school.stripe_customer_id = customer["id"]
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=school.stripe_customer_id,
        client_reference_id=str(school.id),
        line_items=[_line_item()],
        metadata={"school_id": str(school.id)},
        subscription_data={"metadata": {"school_id": str(school.id)}},
        allow_promotion_codes=True,
        success_url=f"{s.frontend_base_url}/billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{s.frontend_base_url}/billing?status=cancelled",
    )
    await audit(db, "UPDATE_SUBSCRIPTION", request=request, actor_user_id=user.id, school_id=school.id,
                details={"step": "checkout_session_created"})
    await db.commit()
    return UrlResponse(url=session["url"])


@router.post("/create-portal-session", response_model=UrlResponse)
async def create_portal_session(
    body: CheckoutRequest, request: Request, user: User = Depends(require_billing_admin), db: AsyncSession = Depends(get_db)
):
    _stripe_ready()
    s = get_settings()
    school = await get_school_or_404(db, resolve_billing_school_id(user, body.school_id))
    if not school.stripe_customer_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No Stripe customer yet; start a subscription first")
    portal = stripe.billing_portal.Session.create(customer=school.stripe_customer_id, return_url=f"{s.frontend_base_url}/billing")
    await audit(db, "OPEN_BILLING_PORTAL", request=request, actor_user_id=user.id, school_id=school.id, commit=True)
    return UrlResponse(url=portal["url"])


@router.get("/status")
async def billing_status(
    school_id: uuid.UUID | None = None, user: User = Depends(require_billing_admin), db: AsyncSession = Depends(get_db)
):
    school = await get_school_or_404(db, resolve_billing_school_id(user, school_id))
    s = get_settings()
    return {
        "school_id": str(school.id),
        "subscription_status": school.subscription_status.value,
        "current_period_end": school.subscription_current_period_end,
        "has_customer": bool(school.stripe_customer_id),
        "price_cents": s.school_monthly_price_cents,
        "stripe_configured": bool(s.stripe_secret_key),
        "banner": school.subscription_status in (SubscriptionStatus.past_due, SubscriptionStatus.unpaid,
                                                 SubscriptionStatus.canceled, SubscriptionStatus.none,
                                                 SubscriptionStatus.incomplete),
    }


# ------------------------------------------------------------------------------- webhook
def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=timezone.utc) if value else None


def _period_end(sub: dict) -> datetime | None:
    if sub.get("current_period_end"):
        return _ts(sub["current_period_end"])
    items = (sub.get("items") or {}).get("data") or []
    if items and items[0].get("current_period_end"):  # newer API versions moved it onto items
        return _ts(items[0]["current_period_end"])
    return None


async def _school_for(db: AsyncSession, *, school_id: str | None = None, subscription_id: str | None = None,
                      customer_id: str | None = None) -> School | None:
    if school_id:
        try:
            school = await db.get(School, uuid.UUID(school_id))
            if school:
                return school
        except ValueError:
            pass
    if subscription_id:
        school = (await db.execute(select(School).where(School.stripe_subscription_id == subscription_id))).scalar_one_or_none()
        if school:
            return school
    if customer_id:
        return (await db.execute(select(School).where(School.stripe_customer_id == customer_id))).scalar_one_or_none()
    return None


def _apply_subscription(school: School, sub: dict) -> None:
    school.stripe_subscription_id = sub.get("id") or school.stripe_subscription_id
    if sub.get("customer"):
        school.stripe_customer_id = sub["customer"]
    school.subscription_status = STATUS_MAP.get(sub.get("status", ""), school.subscription_status)
    school.subscription_current_period_end = _period_end(sub) or school.subscription_current_period_end


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook secret not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature or "", s.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")

    event = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    try:
        async with db.begin_nested():
            db.add(StripeWebhookEvent(id=event["id"], event_type=event["type"]))
    except IntegrityError:
        return {"received": True, "duplicate": True}

    etype = event["type"]
    obj = event["data"]["object"]
    school: School | None = None

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        school = await _school_for(db, school_id=meta.get("school_id") or obj.get("client_reference_id"),
                                   customer_id=obj.get("customer"))
        if school:
            school.stripe_customer_id = obj.get("customer") or school.stripe_customer_id
            school.stripe_subscription_id = obj.get("subscription") or school.stripe_subscription_id
            if obj.get("payment_status") in ("paid", "no_payment_required"):
                school.subscription_status = SubscriptionStatus.active
            if s.stripe_secret_key and school.stripe_subscription_id:
                try:
                    stripe.api_key = s.stripe_secret_key
                    _apply_subscription(school, stripe.Subscription.retrieve(school.stripe_subscription_id).to_dict())
                except stripe.StripeError:
                    log.warning("could not refresh subscription %s", school.stripe_subscription_id)
    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        school = await _school_for(db, school_id=(obj.get("metadata") or {}).get("school_id"),
                                   subscription_id=obj.get("id"), customer_id=obj.get("customer"))
        if school:
            _apply_subscription(school, obj)
            if etype == "customer.subscription.deleted":
                school.subscription_status = SubscriptionStatus.canceled
    elif etype in ("invoice.paid", "invoice.payment_succeeded"):
        sub_id = obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        school = await _school_for(db, subscription_id=sub_id, customer_id=obj.get("customer"))
        if school:
            school.subscription_status = SubscriptionStatus.active
            lines = (obj.get("lines") or {}).get("data") or []
            if lines and (lines[0].get("period") or {}).get("end"):
                school.subscription_current_period_end = _ts(lines[0]["period"]["end"])
    elif etype == "invoice.payment_failed":
        sub_id = obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        school = await _school_for(db, subscription_id=sub_id, customer_id=obj.get("customer"))
        if school:
            school.subscription_status = SubscriptionStatus.past_due

    if school:
        await audit(db, "UPDATE_SUBSCRIPTION", school_id=school.id, target=f"stripe:{event['id']}",
                    details={"type": etype, "status": school.subscription_status.value})
    await db.commit()
    return {"received": True}
