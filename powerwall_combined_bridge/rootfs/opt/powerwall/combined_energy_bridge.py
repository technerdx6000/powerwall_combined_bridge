#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from powerwall_v1r_direct import default_password, fetch_artifact, make_seeded_client
from pypowerwall.tedapi.tedapi_v1r import TEDAPIv1r


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine direct Powerwall v1r data with an optional Shelly EM meter for Home Assistant.",
    )
    parser.add_argument("--config", required=True, help="Path to bridge configuration JSON")
    parser.add_argument("--once", action="store_true", help="Print a single snapshot JSON and exit")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host for serve mode")
    parser.add_argument("--port", type=int, default=8676, help="HTTP bind port for serve mode")
    parser.add_argument("--interval", type=int, default=15, help="Refresh interval in seconds for serve mode")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_url(base_url: str, method: str, params: dict[str, Any] | None = None) -> str:
    normalized = base_url.rstrip("/")
    url = f"{normalized}/rpc/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def build_shelly_opener(config: dict[str, Any]) -> urllib.request.OpenerDirector:
    handlers: list[Any] = []
    username = config.get("username")
    password = config.get("password")
    auth_type = (config.get("auth_type") or "").lower()
    if username and password and auth_type in {"basic", "digest"}:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, config["base_url"], username, password)
        if auth_type == "basic":
            handlers.append(urllib.request.HTTPBasicAuthHandler(password_mgr))
        else:
            handlers.append(urllib.request.HTTPDigestAuthHandler(password_mgr))
    return urllib.request.build_opener(*handlers)


def shelly_rpc(config: dict[str, Any], method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    opener = build_shelly_opener(config)
    request = urllib.request.Request(build_url(config["base_url"], method, params), method="GET")
    with opener.open(request, timeout=config.get("timeout", 10)) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_shelly_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    em_id = int(config.get("em_id", 0))
    device = shelly_rpc(config, "Shelly.GetDeviceInfo")
    em_status = shelly_rpc(config, "EM.GetStatus", {"id": em_id})
    return {
        "device": device,
        "em": em_status,
        "summary": {
            "device_id": device.get("id"),
            "model": device.get("model"),
            "firmware_version": device.get("ver"),
            "total_current_a": em_status.get("total_current"),
            "total_active_power_w": em_status.get("total_act_power"),
            "total_apparent_power_va": em_status.get("total_aprt_power"),
            "phase_a": {
                "voltage_v": em_status.get("a_voltage"),
                "current_a": em_status.get("a_current"),
                "active_power_w": em_status.get("a_act_power"),
                "apparent_power_va": em_status.get("a_aprt_power"),
                "pf": em_status.get("a_pf"),
                "freq_hz": em_status.get("a_freq"),
            },
            "phase_b": {
                "voltage_v": em_status.get("b_voltage"),
                "current_a": em_status.get("b_current"),
                "active_power_w": em_status.get("b_act_power"),
                "apparent_power_va": em_status.get("b_aprt_power"),
                "pf": em_status.get("b_pf"),
                "freq_hz": em_status.get("b_freq"),
            },
            "phase_c": {
                "voltage_v": em_status.get("c_voltage"),
                "current_a": em_status.get("c_current"),
                "active_power_w": em_status.get("c_act_power"),
                "apparent_power_va": em_status.get("c_aprt_power"),
                "pf": em_status.get("c_pf"),
                "freq_hz": em_status.get("c_freq"),
            },
            "neutral_current_a": em_status.get("n_current"),
            "errors": em_status.get("errors", []),
        },
    }


def safe_number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def current_power_map(site_summary: Any) -> dict[str, Any]:
    if not isinstance(site_summary, dict):
        return {}
    current_power = site_summary.get("current_power_w")
    if not isinstance(current_power, dict):
        return {}
    return current_power


def summary_error_message(site_config: dict[str, Any], summary: Any) -> str:
    key_path = site_config.get("rsa_key_path", "<unknown>")
    if not isinstance(summary, dict):
        return f"ValueError: summary response was empty; check RSA key at {key_path}"
    if not isinstance(summary.get("current_power_w"), dict):
        if summary.get("site_name") is None and not summary.get("firmware_version"):
            return (
                "ValueError: current_power_w was unavailable; likely wrong or unverified RSA key "
                f"at {key_path}"
            )
        return "ValueError: current_power_w was unavailable; this site contributes 0 W to totals"
    return ""


def combine_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    sites: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for site_name, site_config in config.get("powerwalls", {}).items():
        try:
            password = site_config.get("password") or default_password()
            transport = TEDAPIv1r(
                host=site_config["host"],
                password=password,
                rsa_key_path=site_config.get("rsa_key_path", "/config/tedapi_rsa_private.pem"),
                timeout=int(site_config.get("timeout", 10)),
            )
            client = make_seeded_client(
                site_config["host"],
                site_config["din"],
                site_config.get("rsa_key_path", "/config/tedapi_rsa_private.pem"),
                password,
            )
            summary = fetch_artifact(client, transport, "summary", site_config["din"])
            sites[site_name] = summary
            issue = summary_error_message(site_config, summary)
            if issue:
                errors[site_name] = issue
        except Exception as exc:
            errors[site_name] = f"{type(exc).__name__}: {exc}"

    shelly = None
    shelly_summary = None
    if config.get("shelly", {}).get("enabled"):
        try:
            shelly = fetch_shelly_snapshot(config["shelly"])
            shelly_summary = shelly["summary"]
        except Exception as exc:
            errors["shelly"] = f"{type(exc).__name__}: {exc}"

    house_power_values = [current_power_map(item) for item in sites.values()]
    total_solar = sum(safe_number(item.get("SOLAR")) for item in house_power_values)
    total_home = sum(safe_number(item.get("LOAD")) for item in house_power_values)
    total_battery = sum(safe_number(item.get("BATTERY")) for item in house_power_values)
    total_site_sum = sum(safe_number(item.get("SITE")) for item in house_power_values)
    grid_w = shelly_summary.get("total_active_power_w") if shelly_summary else total_site_sum
    grid_source = "shelly_em" if shelly_summary else "powerwall_site_sum"

    totals = {
        "solar_w": total_solar,
        "home_w": total_home,
        "battery_w": total_battery,
        "grid_w": grid_w,
        "grid_source": grid_source,
        "powerwall_site_sum_w": total_site_sum,
        "balance_w": total_solar + total_battery + safe_number(grid_w) - total_home,
    }

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sites": sites,
        "shelly": shelly,
        "totals": totals,
        "errors": errors,
    }


@dataclass
class SnapshotStore:
    config: dict[str, Any]
    interval: int
    snapshot: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def refresh(self) -> None:
        latest = combine_snapshot(self.config)
        with self.lock:
            self.snapshot = latest

    def get_snapshot(self) -> dict[str, Any]:
        with self.lock:
            if self.snapshot is None:
                self.snapshot = combine_snapshot(self.config)
            return self.snapshot

    def run(self) -> None:
        while True:
            try:
                self.refresh()
            except Exception:
                pass
            time.sleep(self.interval)


def make_handler(store: SnapshotStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/status", "/health"}:
                self.send_response(404)
                self.end_headers()
                return
            payload = store.get_snapshot()
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    args = parse_args()
    config = load_config(args.config)

    if args.once:
        print(json.dumps(combine_snapshot(config), indent=2))
        return 0

    store = SnapshotStore(config=config, interval=args.interval)
    store.refresh()
    thread = threading.Thread(target=store.run, daemon=True)
    thread.start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"Serving combined energy snapshot on http://{args.host}:{args.port}/status")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())