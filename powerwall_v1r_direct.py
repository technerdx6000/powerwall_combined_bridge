#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

from pypowerwall.tedapi import TEDAPI, lookup
from pypowerwall.tedapi.tedapi_v1r import TEDAPIv1r


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only direct Powerwall v1r helper using an RSA-verified key.",
    )
    parser.add_argument("--host", required=True, help="Powerwall host IP, for example 192.168.1.68")
    parser.add_argument("--din", required=True, help="Gateway DIN for the selected energy site")
    parser.add_argument(
        "--rsa-key-path",
        default=".pypowerwall-auth/tedapi_rsa_private.pem",
        help="Path to the verified RSA private key PEM",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Gateway password used only if the transport ever needs to fall back to login",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the primary JSON output",
    )
    parser.add_argument(
        "--artifact",
        choices=["config", "firmware", "status", "components", "controller", "pw3_vitals", "vitals", "summary", "all"],
        default="summary",
        help="Which read-only artifact to fetch. Defaults to summary.",
    )
    parser.add_argument(
        "--output-dir",
        default="probe-output/direct-v1r",
        help="Directory for multi-file output when using --artifact all.",
    )
    return parser.parse_args()


def json_dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=False)


def extract_grid_status(status: dict[str, Any] | None) -> str | None:
    if status is None:
        return None
    alerts = lookup(status, ["control", "alerts", "active"]) or []
    if "SystemConnectedToGrid" in alerts:
        return "SystemGridConnected"
    grid_state = lookup(status, ["esCan", "bus", "ISLANDER", "ISLAND_GridConnection", "ISLAND_GridConnected"])
    if not grid_state:
        return None
    if grid_state == "ISLAND_GridConnected_Connected":
        return "SystemGridConnected"
    return "SystemIslandedActive"


def build_summary(client: TEDAPI, config: dict[str, Any], firmware_details: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    site_info = config.get("site_info", {}) if isinstance(config, dict) else {}
    installer = config.get("installer", {}) if isinstance(config, dict) else {}
    battery_blocks = config.get("battery_blocks", []) if isinstance(config, dict) else []
    system = firmware_details.get("system", {}) if isinstance(firmware_details, dict) else {}

    return {
        "host": client.gw_ip,
        "din": client.din,
        "site_name": site_info.get("site_name"),
        "timezone": site_info.get("timezone"),
        "country": site_info.get("country"),
        "grid_code": site_info.get("grid_code"),
        "backup_reserve_percent": site_info.get("backup_reserve_percent"),
        "export_rule": site_info.get("customer_preferred_export_rule"),
        "default_real_mode": config.get("default_real_mode") if isinstance(config, dict) else None,
        "firmware_version": system.get("version", {}).get("text") if isinstance(system.get("version"), dict) else None,
        "gateway_part_number": system.get("gateway", {}).get("partNumber"),
        "gateway_serial_number": system.get("gateway", {}).get("serialNumber"),
        "battery_level_percent": client.battery_level(force=True),
        "grid_status": extract_grid_status(status),
        "current_power_w": client.current_power(force=True),
        "battery_blocks": [
            {
                "vin": block.get("vin"),
                "type": block.get("type"),
                "phase": block.get("phase"),
                "max_current": block.get("max_current"),
                "pvi_power_status": block.get("pvi_power_status"),
                "battery_power_status": block.get("battery_power_status"),
            }
            for block in battery_blocks
        ],
        "installer": {
            "company": installer.get("company"),
            "email": installer.get("email"),
            "customer_id": installer.get("customer_id"),
            "verified_config": installer.get("verified_config"),
        },
    }


def make_seeded_client(host: str, din: str, rsa_key_path: str, password: str) -> TEDAPI:
    previous_level = logging.getLogger("pypowerwall.tedapi").level
    logging.getLogger("pypowerwall.tedapi").setLevel(logging.CRITICAL)
    try:
        client = TEDAPI(
            gw_pwd="unused-direct-v1r",
            host=host,
            v1r=True,
            password=password,
            rsa_key_path=rsa_key_path,
            timeout=10,
        )
    finally:
        logging.getLogger("pypowerwall.tedapi").setLevel(previous_level)
    client.din = din
    client.pw3 = True
    return client


def fetch_artifact(client: TEDAPI, transport: TEDAPIv1r, artifact: str, din: str) -> Any:
    if artifact == "config":
        return transport.get_config_v1r(din)
    if artifact == "firmware":
        return client.get_firmware_version(force=True, details=True)
    if artifact == "status":
        return client.get_status(force=True)
    if artifact == "components":
        return client.get_components(force=True)
    if artifact == "controller":
        return client.get_device_controller(force=True)
    if artifact == "pw3_vitals":
        return client.get_pw3_vitals(force=True)
    if artifact == "vitals":
        return client.vitals(force=True)
    if artifact == "summary":
        config = transport.get_config_v1r(din)
        client.pwcache["config"] = config
        client.pwcachetime["config"] = __import__("time").time()
        firmware = client.get_firmware_version(force=True, details=True)
        status = client.get_status(force=True)
        return build_summary(client, config, firmware, status)
    raise ValueError(f"Unsupported artifact: {artifact}")


def main() -> int:
    args = parse_args()
    password = args.password or os.getenv("PW_GW_PWD", "unused-direct-v1r")

    transport = TEDAPIv1r(
        host=args.host,
        password=password,
        rsa_key_path=args.rsa_key_path,
        timeout=10,
    )

    client = make_seeded_client(args.host, args.din, args.rsa_key_path, password)

    if args.artifact == "all":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = ["summary", "config", "firmware", "status", "components", "controller", "pw3_vitals", "vitals"]
        for artifact in artifacts:
            data = fetch_artifact(client, transport, artifact, args.din)
            if data is None:
                print(f"{artifact}: no data")
                continue
            output_path = output_dir / f"{artifact}.json"
            output_path.write_text(json_dump(data) + "\n", encoding="utf-8")
            print(f"saved {artifact} -> {output_path}")
        return 0

    data = fetch_artifact(client, transport, args.artifact, args.din)
    if data is None:
        raise SystemExit(f"No data returned for artifact '{args.artifact}'.")

    payload = json_dump(data)
    print(payload)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        print(f"\nSaved {args.artifact} to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())