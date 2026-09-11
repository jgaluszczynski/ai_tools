#!/usr/bin/env python3
"""Recommend a Cursor model slug from public coding benchmark data."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/benchmarks"
    "?source=artificial-analysis&task_type=coding"
)
AISTUPIDLEVEL_URL = (
    "https://aistupidlevel.info/dashboard/cached"
    "?period=latest&sortBy=combined&analyticsPeriod=latest"
)

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"
ENV_FILE = SKILL_DIR / ".env"


class ConfigError(Exception):
    pass


class SourceError(Exception):
    def __init__(self, kind: str, message: str = "") -> None:
        self.kind = kind
        self.message = message
        super().__init__(message or kind)


@dataclass
class Record:
    source: str
    external_id: str
    display_name: str
    coding_score: float
    output_price_per_million: float | None = None
    source_updated_at: str | None = None


@dataclass
class Candidate:
    slug: str
    coding_index: float | None
    aistupidlevel_score: int | None
    output_price_per_million: float | None
    sources: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    selected_model: str
    confidence: str
    selected: Candidate | None
    alternatives: list[dict[str, Any]]
    cache: dict[str, Any]
    sources: dict[str, Any]
    exclusions: list[dict[str, str]]
    used_fallback: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "coding-model-preflight"
    return Path.home() / ".cache" / "coding-model-preflight"


def cache_path() -> Path:
    return cache_dir() / "snapshot.json"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing env."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Invalid config at {path}: {exc}") from exc

    required = [
        "fallback_model",
        "near_tie_margin",
        "soft_ttl_hours",
        "hard_ttl_hours",
        "timeout_seconds",
        "max_body_bytes",
        "models",
    ]
    for key in required:
        if key not in raw:
            raise ConfigError(f"Missing config key: {key}")

    if not isinstance(raw["models"], list) or not raw["models"]:
        raise ConfigError("config.models must be a non-empty list")

    slugs: set[str] = set()
    for model in raw["models"]:
        if not isinstance(model, dict):
            raise ConfigError("Each model entry must be an object")
        slug = model.get("slug")
        if not slug or not isinstance(slug, str):
            raise ConfigError("Each model needs a string slug")
        if slug in slugs:
            raise ConfigError(f"Duplicate slug: {slug}")
        slugs.add(slug)

    fallback = raw["fallback_model"]
    if fallback not in slugs:
        raise ConfigError(
            f"fallback_model {fallback!r} is not in configured models"
        )

    return raw


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for path in (
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if os.path.isfile(path):
            try:
                ctx.load_verify_locations(path)
                break
            except ssl.SSLError:
                continue
    return ctx


def http_get(
    url: str, timeout: int, max_bytes: int, headers: dict | None = None
) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(
            req, timeout=timeout, context=ssl_context()
        ) as resp:
            data = resp.read(max_bytes + 1)
    except TimeoutError as exc:
        raise SourceError("timeout", "request timed out") from exc
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SourceError("auth", f"HTTP {exc.code}") from exc
        raise SourceError("http", f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SourceError("http", str(exc.reason)) from exc

    if len(data) > max_bytes:
        raise SourceError("schema", "response too large")
    return data


def fetch_openrouter(
    api_key: str | None, timeout: int, max_bytes: int
) -> tuple[list[Record], str | None]:
    if not api_key:
        raise SourceError("not_configured", "OPENROUTER_API_KEY not set")

    body = http_get(
        OPENROUTER_URL,
        timeout,
        max_bytes,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceError("schema", "invalid JSON") from exc

    if not isinstance(payload, dict):
        raise SourceError("schema", "root must be object")

    data = payload.get("data")
    if not isinstance(data, list):
        raise SourceError("schema", "missing data array")

    meta = payload.get("meta")
    as_of = None
    if isinstance(meta, dict):
        raw_as_of = meta.get("as_of")
        if isinstance(raw_as_of, str):
            as_of = raw_as_of

    records: list[Record] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        permaslug = item.get("model_permaslug")
        display_name = item.get("display_name")
        coding_index = item.get("coding_index")
        if not isinstance(permaslug, str) or not permaslug:
            continue
        if not isinstance(display_name, str):
            display_name = permaslug
        if not isinstance(coding_index, (int, float)):
            continue

        output_price = None
        pricing = item.get("pricing")
        if isinstance(pricing, dict):
            completion = pricing.get("completion")
            if completion is not None:
                try:
                    output_price = float(completion) * 1_000_000
                except (TypeError, ValueError):
                    output_price = None

        records.append(
            Record(
                source="openrouter_artificial_analysis",
                external_id=permaslug,
                display_name=display_name,
                coding_score=float(coding_index),
                output_price_per_million=output_price,
                source_updated_at=as_of,
            )
        )

    if not records:
        raise SourceError("schema", "no usable benchmark rows")

    return records, as_of


def fetch_aistupidlevel(
    timeout: int, max_bytes: int
) -> tuple[list[Record], str | None]:
    body = http_get(AISTUPIDLEVEL_URL, timeout, max_bytes)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceError("schema", "invalid JSON") from exc

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SourceError("schema", "success=false or invalid root")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise SourceError("schema", "missing data object")

    model_scores = data.get("modelScores")
    if not isinstance(model_scores, list):
        raise SourceError("schema", "missing modelScores")

    meta = payload.get("meta")
    cached_at = None
    if isinstance(meta, dict):
        raw_cached = meta.get("cachedAt")
        if isinstance(raw_cached, str):
            cached_at = raw_cached

    records: list[Record] = []
    for item in model_scores:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        score = item.get("score")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(score, (int, float)):
            continue
        records.append(
            Record(
                source="aistupidlevel",
                external_id=name,
                display_name=name,
                coding_score=float(score),
                source_updated_at=cached_at,
            )
        )

    if not records:
        raise SourceError("schema", "no usable modelScores")

    return records, cached_at


def records_to_json(records: list[Record]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]


def records_from_json(items: list[Any]) -> list[Record]:
    records: list[Record] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                Record(
                    source=str(item["source"]),
                    external_id=str(item["external_id"]),
                    display_name=str(item["display_name"]),
                    coding_score=float(item["coding_score"]),
                    output_price_per_million=(
                        float(item["output_price_per_million"])
                        if item.get("output_price_per_million") is not None
                        else None
                    ),
                    source_updated_at=item.get("source_updated_at"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


def load_cache() -> dict[str, Any] | None:
    path = cache_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"warning: corrupt cache at {path}", file=sys.stderr)
        return None

    if not isinstance(raw, dict):
        print(f"warning: invalid cache root at {path}", file=sys.stderr)
        return None
    if raw.get("schema_version") != SCHEMA_VERSION:
        print(f"warning: cache schema mismatch at {path}", file=sys.stderr)
        return None
    return raw


def write_cache(snapshot: dict[str, Any]) -> None:
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = cache_path()
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def cache_age_hours(snapshot: dict[str, Any]) -> float:
    generated_at = snapshot.get("generated_at")
    if not isinstance(generated_at, str):
        return float("inf")
    delta = utc_now() - parse_iso(generated_at)
    return delta.total_seconds() / 3600.0


def needs_refresh(
    snapshot: dict[str, Any] | None, config: dict[str, Any]
) -> bool:
    if snapshot is None:
        return True
    age = cache_age_hours(snapshot)
    return age >= float(config["soft_ttl_hours"])


def source_status_from_error(exc: SourceError) -> dict[str, Any]:
    status = {
        "status": exc.kind,
        "error": exc.message or exc.kind,
    }
    return status


def refresh_cache(
    config: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    if snapshot is None:
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now().isoformat(),
            "sources": {},
        }

    timeout = int(config["timeout_seconds"])
    max_bytes = int(config["max_body_bytes"])
    api_key = os.environ.get("OPENROUTER_API_KEY")
    sources = snapshot.setdefault("sources", {})
    prior_generated_at = snapshot.get("generated_at")
    any_fetch_succeeded = False

    # OpenRouter
    or_source = sources.setdefault("openrouter", {})
    try:
        records, as_of = fetch_openrouter(api_key, timeout, max_bytes)
        or_source["records"] = records_to_json(records)
        or_source["status"] = "ok"
        or_source["fetched_at"] = utc_now().isoformat()
        or_source["as_of"] = as_of
        or_source.pop("error", None)
        any_fetch_succeeded = True
    except SourceError as exc:
        or_source.update(source_status_from_error(exc))
        if not or_source.get("records") and exc.kind != "not_configured":
            or_source["records"] = []

    # aistupidlevel
    asl_source = sources.setdefault("aistupidlevel", {})
    try:
        records, cached_at = fetch_aistupidlevel(timeout, max_bytes)
        asl_source["records"] = records_to_json(records)
        asl_source["status"] = "ok"
        asl_source["fetched_at"] = utc_now().isoformat()
        asl_source["cached_at"] = cached_at
        asl_source.pop("error", None)
        any_fetch_succeeded = True
    except SourceError as exc:
        asl_source.update(source_status_from_error(exc))
        if not asl_source.get("records"):
            asl_source["records"] = []

    if any_fetch_succeeded:
        snapshot["generated_at"] = utc_now().isoformat()
    elif prior_generated_at is not None:
        snapshot["generated_at"] = prior_generated_at
    else:
        snapshot["generated_at"] = utc_now().isoformat()

    write_cache(snapshot)
    return snapshot


def index_records(records: list[Record]) -> dict[str, Record]:
    return {record.external_id: record for record in records}


def match_openrouter(
    model_cfg: dict[str, Any], index: dict[str, Record]
) -> Record | None:
    for external_id in model_cfg.get("openrouter_ids", []):
        if external_id in index:
            return index[external_id]
    return None


def match_aistupidlevel(
    model_cfg: dict[str, Any], index: dict[str, Record]
) -> Record | None:
    for name in model_cfg.get("aistupidlevel_names", []):
        if name in index:
            return index[name]
    return None


def build_candidates(
    config: dict[str, Any], snapshot: dict[str, Any]
) -> tuple[list[Candidate], list[dict[str, str]], bool]:
    sources = snapshot.get("sources", {})
    or_records = records_from_json(
        sources.get("openrouter", {}).get("records", [])
    )
    asl_records = records_from_json(
        sources.get("aistupidlevel", {}).get("records", [])
    )
    or_index = index_records(or_records)
    asl_index = index_records(asl_records)
    has_primary_source = bool(or_records)

    candidates: list[Candidate] = []
    exclusions: list[dict[str, str]] = []

    for model_cfg in config["models"]:
        if not model_cfg.get("enabled", True):
            exclusions.append(
                {"slug": model_cfg["slug"], "reason": "disabled in config"}
            )
            continue

        slug = model_cfg["slug"]
        or_match = match_openrouter(model_cfg, or_index)
        asl_match = match_aistupidlevel(model_cfg, asl_index)

        coding_index = or_match.coding_score if or_match else None
        asl_score = int(asl_match.coding_score) if asl_match else None
        output_price = or_match.output_price_per_million if or_match else None
        source_names: list[str] = []

        if or_match:
            source_names.append("openrouter_artificial_analysis")
        if asl_match:
            source_names.append("aistupidlevel")

        if coding_index is None and asl_match:
            coding_index = float(asl_match.coding_score)
            source_names = ["aistupidlevel"]

        if coding_index is None:
            exclusions.append(
                {"slug": slug, "reason": "no external coding score"}
            )
            continue

        candidates.append(
            Candidate(
                slug=slug,
                coding_index=coding_index,
                aistupidlevel_score=asl_score,
                output_price_per_million=output_price,
                sources=source_names,
            )
        )

    return candidates, exclusions, has_primary_source


def rank_candidates(
    candidates: list[Candidate], near_tie_margin: float
) -> list[Candidate]:
    if not candidates:
        return []

    by_score = sorted(
        candidates,
        key=lambda c: (
            -c.coding_index if c.coding_index is not None else 0.0,
            c.slug,
        ),
    )
    top_score = by_score[0].coding_index or 0.0
    near_top = [
        c
        for c in by_score
        if top_score - (c.coding_index or 0.0) <= near_tie_margin
    ]
    near_top_sorted = sorted(
        near_top,
        key=lambda c: (
            -(c.aistupidlevel_score or -1),
            -(c.coding_index or 0.0),
            c.slug,
        ),
    )
    rest = [c for c in by_score if c not in near_top_sorted]
    return near_top_sorted + rest


def confidence_for(
    snapshot: dict[str, Any],
    config: dict[str, Any],
    selected: Candidate | None,
    has_primary_source: bool,
    used_fallback: bool,
) -> tuple[str, bool]:
    age = cache_age_hours(snapshot)
    soft = float(config["soft_ttl_hours"])
    hard = float(config["hard_ttl_hours"])
    used_stale = age >= soft

    if used_fallback:
        return "low", used_stale

    if selected is None:
        return "low", used_stale

    if age > hard:
        return "low", True

    if (
        not has_primary_source
        or (
            "aistupidlevel" in selected.sources
            and "openrouter_artificial_analysis" not in selected.sources
        )
    ):
        return "medium", used_stale

    if used_stale:
        return "medium", True

    return "high", False


def alternative_reason(top: Candidate, alt: Candidate, margin: float) -> str:
    diff = (top.coding_index or 0.0) - (alt.coding_index or 0.0)
    parts = [f"within {margin:.1f} of top"]
    if (
        alt.aistupidlevel_score is not None
        and top.aistupidlevel_score is not None
        and alt.aistupidlevel_score < top.aistupidlevel_score
    ):
        parts.append("lower aistupidlevel score")
    elif diff > 0:
        parts.append(f"{diff:.1f} coding_index points lower")
    return "; ".join(parts)


def recommend(
    config: dict[str, Any], snapshot: dict[str, Any]
) -> Recommendation:
    candidates, exclusions, has_primary_source = build_candidates(
        config, snapshot
    )
    ranked = rank_candidates(candidates, float(config["near_tie_margin"]))
    used_fallback = False
    selected: Candidate | None = ranked[0] if ranked else None

    if selected is None:
        selected = Candidate(
            slug=config["fallback_model"],
            coding_index=None,
            aistupidlevel_score=None,
            output_price_per_million=None,
            sources=[],
        )
        used_fallback = True

    confidence, used_stale = confidence_for(
        snapshot,
        config,
        selected if not used_fallback else None,
        has_primary_source,
        used_fallback,
    )

    margin = float(config["near_tie_margin"])
    alternatives: list[dict[str, Any]] = []
    if ranked and not used_fallback:
        top = ranked[0]
        top_score = top.coding_index or 0.0
        for alt in ranked[1:]:
            if top_score - (alt.coding_index or 0.0) > margin:
                break
            alternatives.append(
                {
                    "slug": alt.slug,
                    "coding_index": alt.coding_index,
                    "reason": alternative_reason(top, alt, margin),
                }
            )
            if len(alternatives) >= 2:
                break

    sources_meta: dict[str, Any] = {}
    for name in ("openrouter", "aistupidlevel"):
        src = snapshot.get("sources", {}).get(name, {})
        entry: dict[str, Any] = {"status": src.get("status", "missing")}
        if src.get("as_of"):
            entry["as_of"] = src["as_of"]
        if src.get("cached_at"):
            entry["cached_at"] = src["cached_at"]
        if src.get("error"):
            entry["error"] = src["error"]
        sources_meta[name] = entry

    return Recommendation(
        selected_model=selected.slug,
        confidence=confidence,
        selected=selected,
        alternatives=alternatives,
        cache={
            "generated_at": snapshot.get("generated_at"),
            "age_hours": round(cache_age_hours(snapshot), 1),
            "used_stale_data": used_stale,
        },
        sources=sources_meta,
        exclusions=exclusions,
        used_fallback=used_fallback,
    )


def recommendation_to_json(rec: Recommendation) -> dict[str, Any]:
    selected = None
    if rec.selected:
        selected = {
            "slug": rec.selected.slug,
            "coding_index": rec.selected.coding_index,
            "aistupidlevel_score": rec.selected.aistupidlevel_score,
            "output_price_per_million": rec.selected.output_price_per_million,
            "sources": rec.selected.sources,
        }
    return {
        "selected_model": rec.selected_model,
        "confidence": rec.confidence,
        "selected": selected,
        "alternatives": rec.alternatives,
        "cache": rec.cache,
        "sources": rec.sources,
        "exclusions": rec.exclusions,
        "used_fallback": rec.used_fallback,
    }


def format_human(rec: Recommendation) -> str:
    lines = [
        f"Recommended: {rec.selected_model} ({rec.confidence} confidence)",
    ]
    if rec.selected and rec.selected.coding_index is not None:
        lines.append(
            "Highest externally reported coding score among eligible "
            "Cursor models."
        )
    elif rec.used_fallback:
        lines.append(
            "No mapped external coding scores available; using configured "
            "fallback."
        )

    age = rec.cache.get("age_hours")
    if age is not None:
        lines.append(f"Snapshot: {age:.1f}h old.")
    if rec.cache.get("used_stale_data"):
        lines.append("Warning: stale benchmark snapshot.")

    or_status = rec.sources.get("openrouter", {}).get("status")
    if or_status == "ok":
        lines.append("Primary source: OpenRouter / Artificial Analysis.")
    elif or_status == "not_configured":
        lines.append("Primary source: not configured (OPENROUTER_API_KEY).")

    for alt in rec.alternatives[:1]:
        lines.append(f"Alternative: {alt['slug']} — {alt['reason']}.")

    for exc in rec.exclusions[:2]:
        lines.append(f"Excluded: {exc['slug']} — {exc['reason']}.")

    return "\n".join(lines)


def collect_unmapped(
    config: dict[str, Any], snapshot: dict[str, Any], limit: int = 20
) -> list[dict[str, Any]]:
    mapped_or: set[str] = set()
    mapped_asl: set[str] = set()
    for model in config["models"]:
        mapped_or.update(model.get("openrouter_ids", []))
        mapped_asl.update(model.get("aistupidlevel_names", []))

    sources = snapshot.get("sources", {})
    unmapped: list[dict[str, Any]] = []

    for record in records_from_json(
        sources.get("openrouter", {}).get("records", [])
    ):
        if record.external_id in mapped_or:
            continue
        unmapped.append(
            {
                "source": "openrouter",
                "external_id": record.external_id,
                "display_name": record.display_name,
                "coding_index": record.coding_score,
            }
        )

    for record in records_from_json(
        sources.get("aistupidlevel", {}).get("records", [])
    ):
        if record.external_id in mapped_asl:
            continue
        unmapped.append(
            {
                "source": "aistupidlevel",
                "external_id": record.external_id,
                "display_name": record.display_name,
                "score": int(record.coding_score),
            }
        )

    unmapped.sort(
        key=lambda item: (
            0 if item["source"] == "openrouter" else 1,
            -(item.get("coding_index") or item.get("score") or 0),
            item["external_id"],
        )
    )
    return unmapped[:limit]


def ensure_snapshot(
    config: dict[str, Any], *, force_refresh: bool = False
) -> dict[str, Any]:
    snapshot = load_cache()
    if force_refresh or needs_refresh(snapshot, config):
        snapshot = refresh_cache(config, snapshot, force=force_refresh)
    if snapshot is None:
        snapshot = refresh_cache(config, None, force=True)
    return snapshot


def cmd_select(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    snapshot = ensure_snapshot(config, force_refresh=args.refresh)
    rec = recommend(config, snapshot)
    if args.json:
        print(json.dumps(recommendation_to_json(rec), indent=2))
    else:
        print(format_human(rec))
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    snapshot = load_cache()
    snapshot = refresh_cache(config, snapshot, force=True)
    if args.json:
        print(json.dumps({"generated_at": snapshot["generated_at"]}, indent=2))
    else:
        print(f"Cache refreshed at {snapshot['generated_at']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    snapshot = load_cache()
    if snapshot is None:
        print("No cache present.", file=sys.stderr)
        return 1

    payload: dict[str, Any] = {
        "generated_at": snapshot.get("generated_at"),
        "age_hours": round(cache_age_hours(snapshot), 1),
        "sources": {},
    }
    for name in ("openrouter", "aistupidlevel"):
        src = snapshot.get("sources", {}).get(name, {})
        payload["sources"][name] = {
            "status": src.get("status", "missing"),
            "record_count": len(src.get("records", [])),
            "fetched_at": src.get("fetched_at"),
        }

    if args.unmapped:
        payload["unmapped"] = collect_unmapped(config, snapshot)

    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    select = sub.add_parser("select", help="Recommend a Cursor model slug")
    select.add_argument("--json", action="store_true", help="JSON output")
    select.add_argument(
        "--refresh", action="store_true", help="Force refresh before select"
    )
    select.set_defaults(func=cmd_select)

    refresh = sub.add_parser("refresh", help="Refresh benchmark cache")
    refresh.add_argument("--json", action="store_true", help="JSON output")
    refresh.set_defaults(func=cmd_refresh)

    status = sub.add_parser("status", help="Show cache and source status")
    status.add_argument(
        "--unmapped",
        action="store_true",
        help="List top external models with no config mapping",
    )
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"configuration_error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
