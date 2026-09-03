#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DOMAIN = "powerwall_combined_bridge"
SUPERVISOR_HTTP = "http://supervisor"
SUPERVISOR_WS = "ws://supervisor/core/websocket"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure the Home Assistant Powerwall Combined Bridge integration is configured.",
    )
    parser.add_argument("--port", type=int, required=True, help="Bridge port exposed by the add-on")
    parser.add_argument("--scan-interval", type=int, required=True, help="Polling interval for the integration")
    parser.add_argument(
        "--local-bridge-url",
        required=True,
        help="Health URL reachable from inside the add-on container, used to wait for bridge startup",
    )
    parser.add_argument(
        "--restart-core",
        action="store_true",
        help="Restart Home Assistant Core before attempting to create the config entry",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for Home Assistant Core and the bridge to become ready",
    )
    return parser.parse_args()


def http_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 10,
) -> Any:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else {}


def wait_for_bridge(url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            http_json(url)
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError(f"Bridge did not become ready at {url}")


def wait_for_homeassistant_api(token: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            http_json(f"{SUPERVISOR_HTTP}/core/api/config", token=token, timeout=5)
            return
        except Exception as err:
            last_error = err
            time.sleep(2)
    raise TimeoutError(f"Timed out waiting for Home Assistant HTTP API: {last_error}")


def wait_for_config_flow_handler(token: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    last_log_at = 0.0
    while time.monotonic() < deadline:
        try:
            handlers = http_json(
                f"{SUPERVISOR_HTTP}/core/api/config/config_entries/flow_handlers",
                token=token,
                timeout=10,
            )
            if isinstance(handlers, list) and DOMAIN in handlers:
                return
            now = time.monotonic()
            if now - last_log_at >= 15:
                handler_count = len(handlers) if isinstance(handlers, list) else 0
                print(
                    f"Waiting for Home Assistant to load {DOMAIN} config flow; {handler_count} handlers currently available",
                    flush=True,
                )
                last_log_at = now
        except Exception as err:
            last_error = err
            now = time.monotonic()
            if now - last_log_at >= 15:
                print(f"Waiting for Home Assistant to load {DOMAIN} config flow: {err}", flush=True)
                last_log_at = now
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for Home Assistant to load {DOMAIN} config flow: {last_error}")


def supervisor_hostname_candidates(port: int) -> list[str]:
    token = os.environ.get("SUPERVISOR_TOKEN")
    candidates: list[str] = []
    if token:
        try:
            payload = http_json(f"{SUPERVISOR_HTTP}/addons/self/info", token=token)
            data = payload.get("data", payload)
            for key in ("ip_address", "hostname", "alias", "slug"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    candidates.append(f"http://{value}:{port}/status")
                    candidates.append(f"http://{value.replace('_', '-')}:{port}/status")
            aliases = data.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str) and alias:
                        candidates.append(f"http://{alias}:{port}/status")
                        candidates.append(f"http://{alias.replace('_', '-')}:{port}/status")
            repository = data.get("repository")
            slug = data.get("slug")
            if isinstance(repository, str) and isinstance(slug, str) and repository and slug and "://" not in repository:
                combined = f"{repository}_{slug}"
                candidates.append(f"http://{combined}:{port}/status")
                candidates.append(f"http://{combined.replace('_', '-')}:{port}/status")
        except Exception:
            pass

    candidates.append(f"http://homeassistant.local:{port}/status")

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def restart_home_assistant_core(token: str) -> None:
    request = urllib.request.Request(
        f"{SUPERVISOR_HTTP}/core/restart",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return
    except (TimeoutError, socket.timeout, http.client.RemoteDisconnected, ConnectionResetError) as err:
        print(f"Home Assistant Core restart request interrupted as Core stopped responding: {err}", flush=True)
        return
    except urllib.error.URLError as err:
        reason = getattr(err, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout, ConnectionResetError, http.client.RemoteDisconnected)):
            print(f"Home Assistant Core restart request interrupted as Core stopped responding: {reason}", flush=True)
            return
        raise


def ensure_config_entry(token: str, resource_candidates: list[str], scan_interval: int, timeout: int) -> str:
    wait_for_homeassistant_api(token, timeout)
    wait_for_config_flow_handler(token, timeout)

    flow = http_json(
        f"{SUPERVISOR_HTTP}/core/api/config/config_entries/flow",
        method="POST",
        token=token,
        data={"handler": DOMAIN},
        timeout=15,
    )

    if flow.get("type") == "abort":
        return f"Config flow aborted: {flow.get('reason')}"
    if flow.get("type") != "form":
        raise RuntimeError(f"Unexpected config flow init result: {flow}")

    flow_id = flow["flow_id"]
    print(f"Trying Home Assistant bridge URL candidates: {resource_candidates}", flush=True)
    for resource in resource_candidates:
        result = http_json(
            f"{SUPERVISOR_HTTP}/core/api/config/config_entries/flow/{flow_id}",
            method="POST",
            token=token,
            data={
                "resource": resource,
                "scan_interval": scan_interval,
            },
            timeout=15,
        )

        result_type = result.get("type")
        if result_type == "create_entry":
            return f"Created Home Assistant integration entry using {resource}"
        if result_type == "abort":
            return f"Home Assistant integration already configured ({result.get('reason')})"
        if result_type == "form":
            errors = result.get("errors") or {}
            if errors.get("base") == "cannot_connect":
                print(f"Bridge URL candidate failed: {resource}", flush=True)
                continue
            raise RuntimeError(f"Config flow returned unexpected form errors: {errors}")
        raise RuntimeError(f"Unexpected config flow result: {result}")

    raise RuntimeError(f"Unable to connect Home Assistant integration to any bridge URL candidate: {resource_candidates}")


def main_with_args(args: argparse.Namespace) -> int:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not available; skipping automatic Home Assistant integration setup", file=sys.stderr)
        return 1

    wait_for_bridge(args.local_bridge_url, args.timeout)

    if args.restart_core:
        print("Restarting Home Assistant Core to load updated custom integration", flush=True)
        restart_home_assistant_core(token)

    resource_candidates = supervisor_hostname_candidates(args.port)
    result = ensure_config_entry(token, resource_candidates, args.scan_interval, args.timeout)
    print(result, flush=True)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return main_with_args(args)
    except Exception as err:
        print(f"Automatic Home Assistant integration setup failed: {err}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())