"""Garmin Connect authentication with MFA support and token persistence."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from garminconnect import Garmin


DEFAULT_TOKEN_DIR = os.path.expanduser("~/.garminconnect")


def login_interactive(
    email: str | None = None,
    password: str | None = None,
    token_dir: str = DEFAULT_TOKEN_DIR,
) -> Garmin:
    """Authenticate interactively (prompts for MFA if needed).

    Tries saved tokens first.  Falls back to email/password login with
    optional MFA prompt.  Persists new tokens on success.
    """
    # 1. Try resuming from saved tokens
    client = _try_resume(token_dir)
    if client is not None:
        return client

    # 2. Need credentials
    email = email or os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = password or os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")

    if not email or not password:
        print("Error: email and password are required.", file=sys.stderr)
        sys.exit(1)

    client = Garmin(email=email, password=password, is_cn=False, prompt_mfa=_prompt_mfa)
    client.login()
    # Use UUID displayName for API URLs (see _try_resume comment)
    profile = client.garth.profile or {}
    client.display_name = profile.get("displayName") or client.get_full_name()
    client.garth.dump(token_dir)
    print(f"Tokens saved to {token_dir}")
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


def _prompt_mfa() -> str:
    """Prompt the user for an MFA code."""
    return input("Enter MFA code: ").strip()
