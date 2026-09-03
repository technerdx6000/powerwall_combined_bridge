#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys

from pypowerwall.tesla_auth import _refresh_access_token, login as tesla_login, save_token
from pypowerwall.v1r_register import (
    OWNER_API_BASE,
    OWNER_AUTHFILE,
    _TokenExpiredError,
    generate_rsa_key,
    step3_get_site_id,
    step4_register_key,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Headless Powerwall 3 v1r registration helper using pypowerwall internals.",
    )
    parser.add_argument(
        "--authpath",
        default=".pypowerwall-auth",
        help="Directory for RSA keys and cached Tesla auth.",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Tesla account email used for Owner API login.",
    )
    return parser.parse_args()


def owner_api_login_headless(email: str | None = None, authpath: str = "", force_reauth: bool = False) -> str:
    authfile = os.path.join(authpath, OWNER_AUTHFILE) if authpath else OWNER_AUTHFILE

    print("=" * 70)
    print("  Tesla Owner API - Headless Login")
    print("=" * 70)
    print()

    if force_reauth:
        if os.path.exists(authfile):
            os.remove(authfile)
            print(f"  Removed expired token cache ({authfile})")
        print("  Please provide fresh tokens.")
        print()
    else:
        print("  This flow skips pywebview and uses token paste mode.")
        print("  Run 'python3 -m pypowerwall authtoken' on a machine with a working browser/webview,")
        print("  then paste the refresh token and access token here when prompted.")
        print()

    if os.path.exists(authfile) and not force_reauth:
        try:
            with open(authfile, encoding="utf-8") as handle:
                cache = json.load(handle)
            if email and email in cache:
                cached_email = email
            elif cache:
                cached_email = list(cache.keys())[0]
            else:
                cached_email = None

            if cached_email:
                sso = cache[cached_email].get("sso", {})
                access_token = sso.get("access_token")
                refresh_token = sso.get("refresh_token")
                expires_at = sso.get("expires_at", 0)

                import time as _time

                if access_token and expires_at > _time.time() + 300:
                    print(f"  Using cached credentials from {authfile}")
                    return access_token

                if refresh_token:
                    print("  Cached token expired, refreshing...")
                    new_data = _refresh_access_token(refresh_token)
                    access_token = new_data.get("access_token", access_token)
                    sso.update(new_data)
                    sso["expires_at"] = int(_time.time() + new_data.get("expires_in", 28800))
                    cache[cached_email]["sso"] = sso
                    with open(os.open(authfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
                        json.dump(cache, handle, indent=2)
                    os.chmod(authfile, 0o600)
                    print("  Token refreshed successfully.")
                    return access_token
        except Exception as exc:
            print(f"  Could not use cached credentials: {exc}")

    refresh_token, detected_email, token_data = tesla_login(
        email=email,
        headless=True,
        debug=False,
    )

    actual_email = detected_email or email
    if not actual_email:
        actual_email = input("  Tesla account email: ").strip()

    if not token_data:
        token_data = {
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 28800,
        }

    save_token(token_data, path=authfile, email=actual_email)

    try:
        with open(authfile, encoding="utf-8") as handle:
            cache = json.load(handle)
        access_token = cache[actual_email]["sso"]["access_token"]
    except Exception:
        access_token = _refresh_access_token(refresh_token).get("access_token")

    if not access_token:
        raise RuntimeError("Could not retrieve access token from headless login flow")

    print(f"\n  Login successful, credentials cached to {authfile}")
    return access_token


def main() -> int:
    args = parse_args()
    authpath = args.authpath
    email = args.email or None

    print("=" * 70)
    print("  Powerwall v1r Headless Registration Helper")
    print("=" * 70)
    print()

    _, public_key_der = generate_rsa_key(authpath=authpath)
    private_key_file = os.path.join(authpath, "tedapi_rsa_private.pem")

    for attempt in range(2):
        token = owner_api_login_headless(email=email, authpath=authpath, force_reauth=(attempt > 0))
        try:
            site_id, _gateway_din = step3_get_site_id(token, OWNER_API_BASE)
            break
        except _TokenExpiredError as exc:
            if attempt == 0:
                print(f"\n  Token expired ({exc}).")
                print("  Retrying with fresh tokens...")
            else:
                print("\n  ERROR: Authentication failed after token refresh.")
                return 1

    step4_register_key(token, site_id, public_key_der, OWNER_API_BASE, private_key_file=private_key_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())