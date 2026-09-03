#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import websockets


DOMAIN = "powerwall_combined_bridge"
SUPERVISOR_HTTP = "http://supervisor"
SUPERVISOR_WS = "ws://supervisor/core/websocket"


class WsCommandError(RuntimeError):
    """Raised when a Home Assistant websocket command fails."""

    def __init__(self, code: str | None, message: str | None) -> None:
        self.code = code or "unknown"
        self.message = message or "Unknown websocket error"
        super().__init__(f"{self.code}: {self.message}")


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


def http_json(url: str, *, method: str = "GET", token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_bridge(url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            http_json(url)
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError(f"Bridge did not become ready at {url}")


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


async def ws_connect(token: str, timeout: int):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            websocket = await websockets.connect(SUPERVISOR_WS, open_timeout=10)
            auth_required = json.loads(await websocket.recv())
            if auth_required.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected websocket greeting: {auth_required}")
            await websocket.send(json.dumps({"type": "auth", "access_token": token}))
            auth_response = json.loads(await websocket.recv())
            if auth_response.get("type") != "auth_ok":
                raise RuntimeError(f"Websocket authentication failed: {auth_response}")
            return websocket
        except Exception as err:
            last_error = err
            await asyncio.sleep(2)
    raise TimeoutError(f"Timed out waiting for Home Assistant websocket: {last_error}")


async def ws_command(websocket, message_id: int, message_type: str, **payload: Any) -> dict[str, Any]:
    await websocket.send(json.dumps({"id": message_id, "type": message_type, **payload}))
    while True:
        response = json.loads(await websocket.recv())
        if response.get("id") != message_id:
            continue
        if response.get("type") != "result":
            return response
        if not response.get("success", False):
            error = response.get("error", {})
            raise WsCommandError(error.get("code"), error.get("message"))
        return response.get("result")


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
    with urllib.request.urlopen(request, timeout=10):
        return


async def ensure_config_entry(token: str, resource_candidates: list[str], scan_interval: int, timeout: int) -> str:
    websocket = await ws_connect(token, timeout)
    try:
        deadline = time.monotonic() + timeout
        flow = None
        while time.monotonic() < deadline:
            try:
                flow = await ws_command(
                    websocket,
                    1,
                    "config_entries/flow/init",
                    handler=DOMAIN,
                    context={"source": "user"},
                )
                break
            except WsCommandError as err:
                if err.code in {"not_found", "unknown_command", "invalid_format"} or "handler" in err.message.lower():
                    print(f"Waiting for Home Assistant to load {DOMAIN} config flow: {err}", flush=True)
                    await asyncio.sleep(3)
                    continue
                raise

        if flow is None:
            raise TimeoutError(f"Timed out waiting for Home Assistant to load {DOMAIN} config flow")

        if flow.get("type") == "abort":
            return f"Config flow aborted: {flow.get('reason')}"
        if flow.get("type") != "form":
            raise RuntimeError(f"Unexpected config flow init result: {flow}")

        flow_id = flow["flow_id"]
        next_id = 2
        print(f"Trying Home Assistant bridge URL candidates: {resource_candidates}", flush=True)
        for resource in resource_candidates:
            result = await ws_command(
                websocket,
                next_id,
                "config_entries/flow/configure",
                flow_id=flow_id,
                user_input={
                    "resource": resource,
                    "scan_interval": scan_interval,
                },
            )
            next_id += 1

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
    finally:
        await websocket.close()

    raise RuntimeError(f"Unable to connect Home Assistant integration to any bridge URL candidate: {resource_candidates}")


async def async_main(args: argparse.Namespace) -> int:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not available; skipping automatic Home Assistant integration setup", file=sys.stderr)
        return 1

    wait_for_bridge(args.local_bridge_url, args.timeout)

    if args.restart_core:
        print("Restarting Home Assistant Core to load updated custom integration", flush=True)
        restart_home_assistant_core(token)

    resource_candidates = supervisor_hostname_candidates(args.port)
    result = await ensure_config_entry(token, resource_candidates, args.scan_interval, args.timeout)
    print(result, flush=True)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(async_main(args))
    except Exception as err:
        print(f"Automatic Home Assistant integration setup failed: {err}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())