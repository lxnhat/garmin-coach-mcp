"""Garmin Connect authentication with MFA support and token persistence.

Designed for both interactive (terminal) and non-interactive (exec) use.
All credentials must be provided via flags or env vars -- no input() calls.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from garminconnect import Garmin


DEFAULT_TOKEN_DIR = os.path.expanduser("~/.garminconnect")

# Exit code when MFA is required (caller should re-run with --mfa-code)
EXIT_MFA_REQUIRED = 2


def login(
    email: str | None = None,
    password: str | None = None,
    mfa_code: str | None = None,
    token_dir: str = DEFAULT_TOKEN_DIR,
) -> Garmin:
    """Authenticate with Garmin Connect.

    Tries saved tokens first.  Falls back to email/password login.
    If MFA is required and no mfa_code is provided, exits with code 2.
    """
    # 1. Try resuming from saved tokens
    client = _try_resume(token_dir)
    if client is not None:
        return client

    # 2. Need credentials
    email = email or os.environ.get("GARMIN_EMAIL")
    password = password or os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print(
            "Error: email and password are required.\n"
            "Provide via --email/--password flags or GARMIN_EMAIL/GARMIN_PASSWORD env vars.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Build MFA handler
    def _handle_mfa() -> str:
        if mfa_code:
            return mfa_code
        # No MFA code provided -- signal the caller to retry with --mfa-code
        print(
            "MFA required. Re-run with --mfa-code CODE.\n"
            "Check your authenticator app or email for the code.",
            file=sys.stderr,
        )
        sys.exit(EXIT_MFA_REQUIRED)

    # 4. Login
    client = Garmin(email=email, password=password, is_cn=False, prompt_mfa=_handle_mfa)
    client.login()

    # Use UUID displayName for API URLs (fullName with spaces causes 403)
    profile = client.garth.profile or {}
    client.display_name = profile.get("displayName") or client.get_full_name()

    # 5. Persist tokens
    Path(token_dir).mkdir(parents=True, exist_ok=True)
    client.garth.dump(token_dir)
    return client


def login_from_tokens(token_dir: str = DEFAULT_TOKEN_DIR) -> Garmin:
    """Resume from saved tokens (non-interactive).  Raises on failure."""
    client = _try_resume(token_dir)
    if client is None:
        raise RuntimeError(
            f"No valid tokens at {token_dir}. "
            "Run garmin-coach-auth to authenticate first."
        )
    return client


# ── helpers ──────────────────────────────────────────────────────────────────


def _try_resume(token_dir: str) -> Garmin | None:
    """Try to resume a session from saved tokens.  Returns None on failure."""
    if not Path(token_dir).exists():
        return None
    try:
        client = Garmin()
        client.login(token_dir)
        # Use the UUID displayName (not fullName) — Garmin's API requires
        # the UUID in URL paths; fullName with spaces causes 403 errors.
        profile = client.garth.profile or {}
        client.display_name = profile.get("displayName") or client.get_full_name()
        return client
    except Exception:
        return None
