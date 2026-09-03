#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import socket
import ssl
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_HOSTNAMES = ["powerwall", "teg", "powerpack"]

DISCOVERY_ENDPOINTS = [
    "/",
    "/api",
    "/api/",
    "/api/status",
    "/api/site_info/site_name",
    "/api/system_status/soe",
    "/api/system_status/grid_status",
    "/api/meters/aggregates",
    "/api/sitemaster",
    "/api/powerwalls",
    "/api/customer/registration",
    "/favicon.ico",
    "/robots.txt",
]

EXTENDED_ENDPOINTS = [
    "/api/site_info",
    "/api/system_status",
    "/api/meters",
    "/api/meters/site",
    "/api/meters/solar",
    "/api/meters/readings",
    "/api/system/update/status",
    "/api/config",
    "/api/networks",
    "/api/solars",
    "/api/generators",
    "/api/devices/vitals",
    "/api/installer",
    "/api/system/testing",
]

WIRED_AUTH_ENDPOINTS = [
    "/api/customer",
    "/api/generators/disconnect_types",
    "/api/meters/status",
    "/api/operation",
    "/api/powerwalls/status",
    "/api/site_info/grid_codes",
    "/api/system_status/grid_faults",
]

SENSITIVE_ARG_KEYS = {"bearer_token", "cookie", "gateway_password", "login_password"}

ENV_DEFAULTS = {
    "login_password": "PW_LOGIN_PASSWORD",
    "gateway_password": "PW_GATEWAY_PASSWORD",
    "bearer_token": "PW_BEARER_TOKEN",
    "cookie": "PW_COOKIE",
    "email": "PW_EMAIL",
}


class SocketResponseAdapter:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def makefile(self, mode: str):
        return self.sock.makefile(mode)


@dataclass
class TransportResult:
    scheme: str
    port: int
    host_header: str
    sni_name: str | None
    success: bool
    error: str | None = None
    status: int | None = None
    location: str | None = None
    cert_sha256: str | None = None
    tls_version: str | None = None
    alpn: str | None = None


@dataclass
class EndpointResult:
    path: str
    method: str
    scheme: str
    host_header: str
    sni_name: str | None
    timestamp: str
    status: int | None = None
    reason: str | None = None
    content_type: str | None = None
    body_length: int = 0
    body_sha256: str | None = None
    classification: str = "untested"
    schema_summary: str | None = None
    preview: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Tesla Powerwall 3 local API probe for transport and endpoint discovery.",
    )
    parser.add_argument("--target-ip", required=True, help="Home-LAN IP to probe, for example 192.168.1.68")
    parser.add_argument(
        "--hostnames",
        nargs="*",
        default=[],
        help="Additional hostnames to try as SNI and Host values. Defaults to powerwall, teg, powerpack.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between endpoint requests to avoid stressing the device",
    )
    parser.add_argument(
        "--output-dir",
        default="probe-output",
        help="Directory to write JSON and Markdown reports into",
    )
    parser.add_argument(
        "--mode",
        choices=["transport", "discovery", "full"],
        default="full",
        help="transport only, discovery endpoints only, or full sweep",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for HTTPS requests. Recommended for first contact with self-signed devices.",
    )
    parser.add_argument(
        "--allow-auth-probe",
        action="store_true",
        help="Permit one controlled POST to /api/login/Basic if the auth surface appears present.",
    )
    parser.add_argument(
        "--login-username",
        default="customer",
        help="Username to use for the one-time login probe. Defaults to customer.",
    )
    parser.add_argument(
        "--login-password",
        help="Explicit password to try once with username customer during the auth probe",
    )
    parser.add_argument(
        "--gateway-password",
        help="Full gateway QR-label password. If provided without --login-password, the last 5 characters are used for the one-time login probe.",
    )
    parser.add_argument(
        "--serial",
        help="Powerwall serial number. If provided with --allow-auth-probe and no --login-password, the last 5 characters are used once.",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Optional email field to include in the one-time login probe",
    )
    parser.add_argument(
        "--max-preview-bytes",
        type=int,
        default=240,
        help="Maximum body preview bytes to store in the report",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["GET"],
        type=str.upper,
        choices=["GET", "HEAD", "OPTIONS"],
        help="Safe methods to use when sweeping endpoints. Defaults to GET.",
    )
    parser.add_argument(
        "--extra-endpoint",
        action="append",
        default=[],
        help="Additional endpoint path to probe. May be repeated.",
    )
    parser.add_argument(
        "--bearer-token",
        help="Optional bearer token for authenticated read-only sweeps.",
    )
    parser.add_argument(
        "--cookie",
        help="Optional Cookie header value for authenticated read-only sweeps.",
    )
    args = parser.parse_args()
    apply_env_defaults(args)
    return args


def apply_env_defaults(args: argparse.Namespace) -> None:
    for field_name, env_name in ENV_DEFAULTS.items():
        current_value = getattr(args, field_name, None)
        if current_value not in {None, ""}:
            continue
        env_value = os.getenv(env_name)
        if env_value not in {None, ""}:
            setattr(args, field_name, env_value)


def build_host_candidates(target_ip: str, extra_hostnames: list[str]) -> list[str]:
    candidates: list[str] = [target_ip]
    for name in [*DEFAULT_HOSTNAMES, *extra_hostnames]:
        stripped = name.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    return candidates


def make_ssl_context(insecure: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    context.set_alpn_protocols(["http/1.1"])
    return context


def format_error(exc: Exception) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return repr(exc)


def build_raw_request(
    method: str,
    path: str,
    host_header: str,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    lines = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host_header}",
        "User-Agent: powerwall-probe/0.1",
        "Accept: application/json, text/plain, */*",
        "Connection: close",
    ]
    for key, value in (extra_headers or {}).items():
        lines.append(f"{key}: {value}")
    if body is not None:
        lines.append("Content-Type: application/json")
        lines.append(f"Content-Length: {len(body)}")
    request = "\r\n".join(lines).encode("ascii") + b"\r\n\r\n"
    if body is not None:
        request += body
    return request


def open_http_socket(target_ip: str, port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((target_ip, port), timeout=timeout)
    sock.settimeout(timeout)
    return sock


def open_https_socket(
    target_ip: str,
    port: int,
    timeout: float,
    sni_name: str,
    insecure: bool,
) -> tuple[ssl.SSLSocket, dict[str, Any]]:
    raw_sock = socket.create_connection((target_ip, port), timeout=timeout)
    raw_sock.settimeout(timeout)
    context = make_ssl_context(insecure)
    tls_sock = context.wrap_socket(raw_sock, server_hostname=sni_name)
    cert_bin = tls_sock.getpeercert(binary_form=True)
    cert_sha256 = hashlib.sha256(cert_bin).hexdigest() if cert_bin else None
    metadata = {
        "cert_sha256": cert_sha256,
        "tls_version": tls_sock.version(),
        "alpn": tls_sock.selected_alpn_protocol(),
    }
    return tls_sock, metadata


def read_http_response(sock: socket.socket, method: str) -> tuple[int, str, dict[str, str], bytes]:
    adapter = SocketResponseAdapter(sock)
    response = http.client.HTTPResponse(adapter, method=method)
    response.begin()
    body = response.read()
    headers = {key: value for key, value in response.getheaders()}
    return response.status, response.reason, headers, body


def request_once(
    *,
    target_ip: str,
    scheme: str,
    host_header: str,
    sni_name: str | None,
    path: str,
    method: str,
    timeout: float,
    insecure: bool,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str, dict[str, str], bytes, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if scheme == "https":
        if sni_name is None:
            raise ValueError("HTTPS requests require an SNI name")
        sock, metadata = open_https_socket(target_ip, 443, timeout, sni_name, insecure)
    else:
        sock = open_http_socket(target_ip, 80, timeout)

    try:
        sock.sendall(build_raw_request(method, path, host_header, body=body, extra_headers=extra_headers))
        status, reason, headers, response_body = read_http_response(sock, method)
        return status, reason, headers, response_body, metadata
    finally:
        sock.close()


def derive_login_password(args: argparse.Namespace) -> str | None:
    if args.login_password:
        return args.login_password
    if args.gateway_password:
        return args.gateway_password[-5:]
    if args.serial:
        return args.serial[-5:]
    return None


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def build_target_endpoints(args: argparse.Namespace) -> list[str]:
    if args.mode == "discovery":
        base = DISCOVERY_ENDPOINTS
    else:
        base = [*DISCOVERY_ENDPOINTS, *EXTENDED_ENDPOINTS, *WIRED_AUTH_ENDPOINTS]
    extras = [item for item in args.extra_endpoint if item]
    return dedupe_preserve_order([*base, *extras])


def build_request_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"
    if args.cookie:
        headers["Cookie"] = args.cookie
    return headers


def redact_args(args: argparse.Namespace) -> dict[str, Any]:
    payload = vars(args).copy()
    for key in SENSITIVE_ARG_KEYS:
        if payload.get(key):
            payload[key] = "<redacted>"
    return payload


def preview_bytes(data: bytes, limit: int) -> str | None:
    if not data:
        return None
    sample = data[:limit]
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        text = sample.decode("utf-8", errors="replace")
    return text.replace("\r", " ").replace("\n", " ").strip()


def schema_summary(content_type: str | None, body: bytes) -> str | None:
    if not body:
        return None
    lower_content_type = (content_type or "").lower()
    if "json" in lower_content_type or body[:1] in {b"{", b"["}:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "invalid-json"
        if isinstance(parsed, dict):
            keys = list(parsed.keys())[:10]
            return f"json-object keys={keys}"
        if isinstance(parsed, list):
            item_type = type(parsed[0]).__name__ if parsed else "empty"
            return f"json-list len={len(parsed)} first_type={item_type}"
        return f"json-scalar type={type(parsed).__name__}"
    if is_probably_binary(body):
        return "binary-or-protobuf"
    return "text-or-html"


def is_probably_binary(body: bytes) -> bool:
    if not body:
        return False
    text_bytes = sum(1 for byte in body[:256] if 32 <= byte <= 126 or byte in {9, 10, 13})
    return text_bytes / min(len(body), 256) < 0.75


def classify_response(status: int | None, content_type: str | None, body: bytes, error: str | None) -> str:
    if error:
        return "transport_error"
    if status is None:
        return "unknown"
    if status == 429:
        return "rate_limited"
    if status in {401, 403}:
        return "exists_but_unauthorized"
    if status == 404:
        return "missing"
    if status == 405:
        return "exists_wrong_method"
    if 300 <= status <= 399:
        return "redirect"
    if 500 <= status <= 599:
        return "server_error"
    if 200 <= status <= 299:
        if is_probably_binary(body) or "octet-stream" in (content_type or "").lower():
            return "binary_or_protobuf"
        return "open_unauthenticated"
    return "unexpected"


def probe_transport(target_ip: str, host_candidates: list[str], timeout: float, insecure: bool) -> list[TransportResult]:
    results: list[TransportResult] = []

    for host_header in host_candidates:
        try:
            status, _, headers, _, _ = request_once(
                target_ip=target_ip,
                scheme="http",
                host_header=host_header,
                sni_name=None,
                path="/",
                method="GET",
                timeout=timeout,
                insecure=insecure,
            )
            results.append(
                TransportResult(
                    scheme="http",
                    port=80,
                    host_header=host_header,
                    sni_name=None,
                    success=True,
                    status=status,
                    location=headers.get("Location"),
                )
            )
        except Exception as exc:
            results.append(
                TransportResult(
                    scheme="http",
                    port=80,
                    host_header=host_header,
                    sni_name=None,
                    success=False,
                    error=format_error(exc),
                )
            )

    for host_header in host_candidates:
        try:
            status, _, headers, _, metadata = request_once(
                target_ip=target_ip,
                scheme="https",
                host_header=host_header,
                sni_name=host_header,
                path="/",
                method="GET",
                timeout=timeout,
                insecure=insecure,
            )
            results.append(
                TransportResult(
                    scheme="https",
                    port=443,
                    host_header=host_header,
                    sni_name=host_header,
                    success=True,
                    status=status,
                    location=headers.get("Location"),
                    cert_sha256=metadata.get("cert_sha256"),
                    tls_version=metadata.get("tls_version"),
                    alpn=metadata.get("alpn"),
                )
            )
        except Exception as exc:
            results.append(
                TransportResult(
                    scheme="https",
                    port=443,
                    host_header=host_header,
                    sni_name=host_header,
                    success=False,
                    error=format_error(exc),
                )
            )

    return results


def choose_best_transport(transport_results: list[TransportResult]) -> tuple[str, str, str | None] | None:
    successful_https = [item for item in transport_results if item.success and item.scheme == "https"]
    if successful_https:
        preferred = sorted(
            successful_https,
            key=lambda item: (
                item.host_header != item.sni_name,
                item.host_header != item.host_header,
                item.status not in {200, 204, 301, 302},
            ),
        )[0]
        return preferred.scheme, preferred.host_header, preferred.sni_name

    successful_http = [item for item in transport_results if item.success and item.scheme == "http"]
    if successful_http:
        preferred = successful_http[0]
        return preferred.scheme, preferred.host_header, None
    return None


def probe_endpoints(
    *,
    target_ip: str,
    scheme: str,
    host_header: str,
    sni_name: str | None,
    endpoints: list[str],
    methods: list[str],
    timeout: float,
    delay: float,
    insecure: bool,
    max_preview_bytes: int,
    request_headers: dict[str, str],
) -> list[EndpointResult]:
    results: list[EndpointResult] = []

    for path_index, path in enumerate(endpoints):
        for method_index, method in enumerate(methods):
            if path_index or method_index:
                time.sleep(delay)

            timestamp = utcnow()
            try:
                status, reason, headers, body, _ = request_once(
                    target_ip=target_ip,
                    scheme=scheme,
                    host_header=host_header,
                    sni_name=sni_name,
                    path=path,
                    method=method,
                    timeout=timeout,
                    insecure=insecure,
                    extra_headers=request_headers,
                )
                content_type = headers.get("Content-Type")
                result = EndpointResult(
                    path=path,
                    method=method,
                    scheme=scheme,
                    host_header=host_header,
                    sni_name=sni_name,
                    timestamp=timestamp,
                    status=status,
                    reason=reason,
                    content_type=content_type,
                    body_length=len(body),
                    body_sha256=hashlib.sha256(body).hexdigest() if body else None,
                    headers=headers,
                    preview=preview_bytes(body, max_preview_bytes),
                )
                result.schema_summary = schema_summary(content_type, body)
                result.classification = classify_response(status, content_type, body, None)
                results.append(result)
            except Exception as exc:
                results.append(
                    EndpointResult(
                        path=path,
                        method=method,
                        scheme=scheme,
                        host_header=host_header,
                        sni_name=sni_name,
                        timestamp=timestamp,
                        error=format_error(exc),
                        classification="transport_error",
                    )
                )
                if "429" in str(exc):
                    return results

    return results


def auth_surface_present(results: list[EndpointResult]) -> bool:
    interesting = {"open_unauthenticated", "exists_but_unauthorized", "exists_wrong_method", "unexpected"}
    for result in results:
        if not result.path.startswith("/api"):
            continue
        if result.classification in interesting:
            return True
    return False


def probe_login(
    *,
    target_ip: str,
    scheme: str,
    host_header: str,
    sni_name: str | None,
    timeout: float,
    insecure: bool,
    username: str,
    password: str,
    email: str,
    max_preview_bytes: int,
) -> EndpointResult:
    timestamp = utcnow()
    payload = json.dumps(
        {
            "username": username,
            "password": password,
            "email": email,
            "force_sm_off": False,
        }
    ).encode("utf-8")
    try:
        status, reason, headers, body, _ = request_once(
            target_ip=target_ip,
            scheme=scheme,
            host_header=host_header,
            sni_name=sni_name,
            path="/api/login/Basic",
            method="POST",
            timeout=timeout,
            insecure=insecure,
            body=payload,
        )
        content_type = headers.get("Content-Type")
        result = EndpointResult(
            path="/api/login/Basic",
            method="POST",
            scheme=scheme,
            host_header=host_header,
            sni_name=sni_name,
            timestamp=timestamp,
            status=status,
            reason=reason,
            content_type=content_type,
            body_length=len(body),
            body_sha256=hashlib.sha256(body).hexdigest() if body else None,
            headers=headers,
            preview=preview_bytes(body, max_preview_bytes),
        )
        result.schema_summary = schema_summary(content_type, body)
        result.classification = classify_response(status, content_type, body, None)
        return result
    except Exception as exc:
        return EndpointResult(
            path="/api/login/Basic",
            method="POST",
            scheme=scheme,
            host_header=host_header,
            sni_name=sni_name,
            timestamp=timestamp,
            error=format_error(exc),
            classification="transport_error",
        )


def build_decision_summary(transport_results: list[TransportResult], endpoint_results: list[EndpointResult]) -> list[str]:
    decisions: list[str] = []

    if any(item.success and item.scheme == "https" for item in transport_results):
        decisions.append("HTTPS is reachable on the home-LAN IP with at least one SNI/Host combination.")
    else:
        decisions.append("HTTPS did not complete successfully on the home-LAN IP; verify routing, SNI, or whether this interface exposes the API at all.")

    open_core = {
        "/api/status",
        "/api/meters/aggregates",
        "/api/system_status/soe",
        "/api/system_status/grid_status",
    }
    open_paths = {item.path for item in endpoint_results if item.classification == "open_unauthenticated"}
    unauthorized_paths = {item.path for item in endpoint_results if item.classification == "exists_but_unauthorized"}
    binary_paths = {item.path for item in endpoint_results if item.classification == "binary_or_protobuf"}

    if open_core & open_paths:
        decisions.append("The home-LAN IP exposes at least part of the classic JSON monitoring surface.")
    elif unauthorized_paths:
        decisions.append("The home-LAN IP likely exposes a local auth surface, but read access appears gated by authentication.")
    else:
        decisions.append("The classic JSON surface is sparse or absent on the home-LAN IP.")

    wired_auth_hits = {
        item.path
        for item in endpoint_results
        if item.classification == "exists_but_unauthorized" and item.path in set(WIRED_AUTH_ENDPOINTS)
    }
    if wired_auth_hits:
        decisions.append(
            f"Additional wired-only auth-gated endpoints were detected: {', '.join(sorted(wired_auth_hits))}."
        )

    if "/api/devices/vitals" in binary_paths:
        decisions.append("A binary or protobuf-style vitals endpoint appears present locally.")

    if not open_core & open_paths and not unauthorized_paths:
        decisions.append("Next branch: test Powerwall Wi-Fi TEDAPI at 192.168.91.1 or the vendor subnet path used by some Powerwall 3 installations.")

    return decisions


def write_report(
    *,
    output_dir: Path,
    args: argparse.Namespace,
    transport_results: list[TransportResult],
    endpoint_results: list[EndpointResult],
    decision_summary: list[str],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"powerwall_probe_{stamp}.json"
    md_path = output_dir / f"powerwall_probe_{stamp}.md"

    payload = {
        "generated_at": utcnow(),
        "args": redact_args(args),
        "transport_results": [asdict(item) for item in transport_results],
        "endpoint_results": [asdict(item) for item in endpoint_results],
        "decision_summary": decision_summary,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Powerwall Probe Report",
        "",
        f"Generated: {payload['generated_at']}",
        f"Target IP: {args.target_ip}",
        f"Mode: {args.mode}",
        f"Methods: {', '.join(args.methods)}",
        "",
        "## Decision Summary",
        "",
    ]
    for item in decision_summary:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Transport Results",
            "",
            "| Scheme | Host | SNI | Success | Status | TLS | ALPN | Note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in transport_results:
        note = item.error or item.location or ""
        lines.append(
            f"| {item.scheme} | {item.host_header} | {item.sni_name or ''} | {item.success} | {item.status or ''} | {item.tls_version or ''} | {item.alpn or ''} | {note.replace('|', '/')} |"
        )

    lines.extend(
        [
            "",
            "## Endpoint Availability Matrix",
            "",
            "| Path | Method | Status | Classification | Content-Type | Schema | Preview |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in endpoint_results:
        preview = (item.preview or item.error or "").replace("|", "/")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        lines.append(
            f"| {item.path} | {item.method} | {item.status or ''} | {item.classification} | {item.content_type or ''} | {item.schema_summary or ''} | {preview} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    host_candidates = build_host_candidates(args.target_ip, args.hostnames)
    request_headers = build_request_headers(args)

    transport_results = probe_transport(args.target_ip, host_candidates, args.timeout, args.insecure)
    endpoint_results: list[EndpointResult] = []

    if args.mode != "transport":
        chosen = choose_best_transport(transport_results)
        if chosen is None:
            print("No successful transport path found. See the report for details.", file=sys.stderr)
        else:
            scheme, host_header, sni_name = chosen
            endpoints = build_target_endpoints(args)
            endpoint_results = probe_endpoints(
                target_ip=args.target_ip,
                scheme=scheme,
                host_header=host_header,
                sni_name=sni_name,
                endpoints=endpoints,
                methods=args.methods,
                timeout=args.timeout,
                delay=args.delay,
                insecure=args.insecure,
                max_preview_bytes=args.max_preview_bytes,
                request_headers=request_headers,
            )

            if args.allow_auth_probe and auth_surface_present(endpoint_results):
                password = derive_login_password(args)
                if password:
                    time.sleep(args.delay)
                    endpoint_results.append(
                        probe_login(
                            target_ip=args.target_ip,
                            scheme=scheme,
                            host_header=host_header,
                            sni_name=sni_name,
                            timeout=args.timeout,
                            insecure=args.insecure,
                            username=args.login_username,
                            password=password,
                            email=args.email,
                            max_preview_bytes=args.max_preview_bytes,
                        )
                    )

    decision_summary = build_decision_summary(transport_results, endpoint_results)
    json_path, md_path = write_report(
        output_dir=Path(args.output_dir),
        args=args,
        transport_results=transport_results,
        endpoint_results=endpoint_results,
        decision_summary=decision_summary,
    )

    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())