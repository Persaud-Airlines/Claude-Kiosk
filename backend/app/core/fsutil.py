"""Cross-platform file helpers (POSIX permissions do not restrict access on Windows)."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("detechtive.fs")

# Well-known SIDs, so the command works on every Windows language edition.
_SYSTEM_SID = "*S-1-5-18"
_ADMINS_SID = "*S-1-5-32-544"


def restrict_to_owner(path: Path) -> None:
    """Limit a secret file to the current user, SYSTEM (the service account) and Administrators."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    user = os.environ.get("USERNAME")
    grants = ["/grant:r", f"{_SYSTEM_SID}:F", "/grant:r", f"{_ADMINS_SID}:F"]
    if user:
        grants += ["/grant:r", f"{user}:F"]
    result = subprocess.run(["icacls", str(path), "/inheritance:r", *grants],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log.warning("Could not restrict permissions on %s: %s", path, result.stderr.strip())
