#!/usr/bin/env python3
"""Reduce a DevTools-exported HAR for LLM-assisted API e2e test writing.

Assumes the HAR was already filtered in the Network panel to the minimal
timeline / URL scope for a flow. This script only strips noise that is
useless or harmful for that use case (browser chrome headers, binary
bodies, optional secret values).
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

# Browser / transport noise — not useful for reconstructing API contracts.
DROP_HEADER_NAMES = {
    ":authority",
    ":method",
    ":path",
    ":scheme",
    "accept-encoding",
    "accept-language",
    "connection",
    "content-length",
    "cookie",
    "host",
    "origin",
    "priority",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "set-cookie",
    "upgrade-insecure-requests",
    "user-agent",
}

# Redacted by default when feeding dumps to models / tickets.
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-xsrf-token",
}

# Query / JSON / form field names redacted with the same toggle.
SENSITIVE_FIELD_NAMES = SENSITIVE_HEADER_NAMES | {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "session_token",
    "authenticity_token",
    "csrf_token",
    "xsrf_token",
}

BINARY_MIME_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "font/",
)
BINARY_MIME_TYPES = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/wasm",
}


def _is_sensitive_field(name: Any) -> bool:
    return str(name).lower() in SENSITIVE_FIELD_NAMES


def _headers_to_dict(
    headers: list[dict[str, Any]] | None,
    *,
    redact_secrets: bool,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for header in headers or []:
        name = header.get("name")
        if not name:
            continue
        key = name.lower()
        if key in DROP_HEADER_NAMES or key.startswith("sec-ch-ua"):
            continue
        value = header.get("value", "")
        if redact_secrets and key in SENSITIVE_HEADER_NAMES:
            value = "<redacted>"
        # Last-wins for duplicate names; rare for API-relevant headers.
        out[key] = value
    return out


def _query_to_dict(
    query: list[dict[str, Any]] | None,
    *,
    redact_secrets: bool,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in query or []:
        name = item.get("name")
        if name is None:
            continue
        value = str(item.get("value", ""))
        if redact_secrets and _is_sensitive_field(name):
            value = "<redacted>"
        out[str(name)] = value
    return out


def _redact_structured(value: Any, *, redact_secrets: bool) -> Any:
    if not redact_secrets:
        return value
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if _is_sensitive_field(key)
                else _redact_structured(child, redact_secrets=True)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_structured(item, redact_secrets=True) for item in value]
    return value


def _reduce_params(
    params: list[dict[str, Any]] | None,
    *,
    redact_secrets: bool,
) -> list[dict[str, Any]] | None:
    if not params:
        return None
    if not redact_secrets:
        return params
    reduced: list[dict[str, Any]] = []
    for item in params:
        name = item.get("name")
        value = item.get("value", "")
        if _is_sensitive_field(name):
            value = "<redacted>"
        reduced.append({**item, "value": value})
    return reduced


def _url_without_query(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlparse(url)
    return urlunparse(parts._replace(query="", fragment=""))


def _looks_binary(mime_type: str | None, encoding: str | None) -> bool:
    if (encoding or "").lower() == "base64":
        return True
    mime = (mime_type or "").split(";")[0].strip().lower()
    if not mime:
        return False
    if mime in BINARY_MIME_TYPES:
        return True
    return mime.startswith(BINARY_MIME_PREFIXES)


def _decode_body_text(text: str | None, encoding: str | None) -> str | None:
    if text is None:
        return None
    if (encoding or "").lower() != "base64":
        return text
    try:
        return base64.b64decode(text).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _maybe_parse_json(text: str | None, mime_type: str | None) -> Any:
    if text is None:
        return None
    mime = (mime_type or "").lower()
    looks_json = "json" in mime or text[:1] in "{["
    if not looks_json:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _truncate(value: Any, max_chars: int | None) -> Any:
    if max_chars is None or not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + f"…<truncated {len(value) - max_chars} chars>"


def _reduce_post_data(
    post_data: dict[str, Any] | None,
    *,
    redact_secrets: bool,
    max_body_chars: int | None,
) -> dict[str, Any] | None:
    if not post_data:
        return None

    mime_type = post_data.get("mimeType")
    text = post_data.get("text")
    params = _reduce_params(
        post_data.get("params"), redact_secrets=redact_secrets
    )

    reduced: dict[str, Any] = {}
    if mime_type:
        reduced["mimeType"] = mime_type
    if params:
        reduced["params"] = params
    if text is not None:
        body = _redact_structured(
            _maybe_parse_json(text, mime_type),
            redact_secrets=redact_secrets,
        )
        reduced["body"] = _truncate(body, max_body_chars)
    return reduced or None


def _reduce_response_content(
    content: dict[str, Any] | None,
    *,
    redact_secrets: bool,
    max_body_chars: int | None,
) -> dict[str, Any] | None:
    if not content:
        return None

    mime_type = content.get("mimeType")
    encoding = content.get("encoding")
    text = content.get("text")
    size = content.get("size")

    reduced: dict[str, Any] = {}
    if mime_type:
        reduced["mimeType"] = mime_type
    if size is not None:
        reduced["size"] = size

    if text is None:
        return reduced or None

    if _looks_binary(mime_type, encoding):
        # Keep shape for the LLM, drop the payload (often huge base64).
        reduced["body_omitted"] = "binary_or_base64"
        return reduced

    decoded = _decode_body_text(text, encoding)
    if decoded is None:
        reduced["body_omitted"] = "undecodable"
        return reduced

    body = _redact_structured(
        _maybe_parse_json(decoded, mime_type),
        redact_secrets=redact_secrets,
    )
    reduced["body"] = _truncate(body, max_body_chars)
    return reduced


def reduce_entry(
    entry: dict[str, Any],
    *,
    redact_secrets: bool,
    max_body_chars: int | None,
) -> dict[str, Any]:
    request = entry.get("request", {})
    response = entry.get("response", {})

    reduced_request: dict[str, Any] = {
        "method": request.get("method"),
        "url": _url_without_query(request.get("url")),
    }
    query = _query_to_dict(
        request.get("queryString"), redact_secrets=redact_secrets
    )
    if query:
        reduced_request["query"] = query

    headers = _headers_to_dict(
        request.get("headers"), redact_secrets=redact_secrets
    )
    if headers:
        reduced_request["headers"] = headers

    post_data = _reduce_post_data(
        request.get("postData"),
        redact_secrets=redact_secrets,
        max_body_chars=max_body_chars,
    )
    if post_data:
        reduced_request["postData"] = post_data

    reduced_response: dict[str, Any] = {
        "status": response.get("status"),
    }
    status_text = response.get("statusText")
    if status_text:
        reduced_response["statusText"] = status_text

    resp_headers = _headers_to_dict(
        response.get("headers"), redact_secrets=redact_secrets
    )
    if resp_headers:
        reduced_response["headers"] = resp_headers

    content = _reduce_response_content(
        response.get("content"),
        redact_secrets=redact_secrets,
        max_body_chars=max_body_chars,
    )
    if content:
        reduced_response["content"] = content

    return {
        "startedDateTime": entry.get("startedDateTime"),
        "time_ms": entry.get("time"),
        "request": reduced_request,
        "response": reduced_response,
    }


def reduce_har(
    har_path: Path,
    *,
    redact_secrets: bool = True,
    max_body_chars: int | None = 20_000,
) -> dict[str, Any]:
    with har_path.open("r", encoding="utf-8") as f:
        har = json.load(f)

    try:
        entries = har["log"]["entries"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"{har_path}: not a valid HAR (missing log.entries)"
        ) from exc

    reduced_entries = [
        reduce_entry(
            entry,
            redact_secrets=redact_secrets,
            max_body_chars=max_body_chars,
        )
        for entry in entries
    ]
    return {
        "source": har_path.name,
        "entry_count": len(reduced_entries),
        "entries": reduced_entries,
    }


def output_path_for(har_path: Path) -> Path:
    # foo.har -> foo_reduced.json; foo.har.json -> foo.har_reduced.json
    return har_path.with_name(f"{har_path.stem}_reduced.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reduce a prefiltered HAR dump for LLM-assisted API e2e "
            "test writing. Writes <input_stem>_reduced.json next to the "
            "input file."
        )
    )
    parser.add_argument(
        "har_file",
        type=Path,
        help="Path to a .har (or HAR JSON) file",
    )
    parser.add_argument(
        "--keep-secrets",
        action="store_true",
        help=(
            "Do not redact sensitive headers, query params, or "
            "JSON/form field names"
        ),
    )
    parser.add_argument(
        "--max-body-chars",
        type=int,
        default=20_000,
        help=(
            "Truncate string bodies longer than this "
            "(default: 20000; 0 = no limit)"
        ),
    )
    args = parser.parse_args()

    har_path = args.har_file.expanduser().resolve()
    if not har_path.is_file():
        raise SystemExit(f"File not found: {har_path}")

    max_body_chars = None if args.max_body_chars == 0 else args.max_body_chars
    data = reduce_har(
        har_path,
        redact_secrets=not args.keep_secrets,
        max_body_chars=max_body_chars,
    )

    out_path = output_path_for(har_path)
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out_path} ({data['entry_count']} entries)")  # noqa: T201


if __name__ == "__main__":
    main()
