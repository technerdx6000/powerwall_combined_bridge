#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Home Assistant add-on options into bridge config JSON.")
    parser.add_argument("--options", required=True, help="Path to /data/options.json")
    parser.add_argument("--output", required=True, help="Path to rendered bridge config JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options = json.loads(Path(args.options).read_text(encoding="utf-8"))

    powerwalls = {}
    for item in options.get("powerwalls", []):
        powerwalls[item["name"]] = {
            "host": item["host"],
            "din": item["din"],
            "rsa_key_path": options["rsa_key_path"],
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

    Path(args.output).write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())