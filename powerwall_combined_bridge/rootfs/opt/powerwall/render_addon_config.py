#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Home Assistant add-on options into bridge config JSON.")
    parser.add_argument("--options", required=True, help="Path to /data/options.json")
    parser.add_argument("--output", required=True, help="Path to rendered bridge config JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options_path = Path(args.options)
    output_path = Path(args.output)
    options = json.loads(options_path.read_text(encoding="utf-8"))

    rsa_key_path = options["rsa_key_path"]
    inline_key_b64 = (options.get("rsa_private_key_base64") or "").strip()
    if inline_key_b64:
        key_bytes = base64.b64decode(inline_key_b64)
        inline_key_path = output_path.with_name("tedapi_rsa_private.pem")
        inline_key_path.write_bytes(key_bytes)
        inline_key_path.chmod(0o600)
        rsa_key_path = str(inline_key_path)

    powerwalls = {}
    for item in options.get("powerwalls", []):
        powerwalls[item["name"]] = {
            "host": item["host"],
            "din": item["din"],
            "rsa_key_path": rsa_key_path,
        }

    rendered = {
        "powerwalls": powerwalls,
        "shelly": {
            "enabled": options.get("shelly_enabled", False),
            "base_url": options.get("shelly_base_url", ""),
            "em_id": options.get("shelly_em_id", 0),
            "auth_type": options.get("shelly_auth_type", "basic"),
            "username": options.get("shelly_username", ""),
            "password": options.get("shelly_password", ""),
            "timeout": 10,
        },
    }

    output_path.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())