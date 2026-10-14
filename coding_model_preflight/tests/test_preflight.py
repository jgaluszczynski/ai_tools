"""Tests for coding model preflight."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import preflight  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


@pytest.fixture
def config():
    return preflight.load_config(CONFIG_PATH)


@pytest.fixture
def openrouter_payload():
    return json.loads((FIXTURES / "openrouter_coding.json").read_text())


@pytest.fixture
def aistupidlevel_payload():
    return json.loads((FIXTURES / "aistupidlevel.json").read_text())


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(preflight, "cache_dir", lambda: cache_root)
    monkeypatch.setattr(
        preflight, "cache_path", lambda: cache_root / "snapshot.json"
    )
    return cache_root


def test_load_config_valid(config):
    assert config["fallback_model"] == "claude-opus-5-thinking-high"
    assert len(config["models"]) == 12


def test_load_config_missing_key(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"models": []}))
    with pytest.raises(preflight.ConfigError):
        preflight.load_config(bad)


def test_load_config_duplicate_slug(tmp_path):
    bad = tmp_path / "dup.json"
    bad.write_text(
        json.dumps(
            {
                "fallback_model": "a",
                "near_tie_margin": 2.0,
                "cost_quality_margin": 5.0,
                "soft_ttl_hours": 12,
                "hard_ttl_hours": 72,
                "timeout_seconds": 10,
                "max_body_bytes": 1000,
                "models": [
                    {"slug": "a", "enabled": True},
                    {"slug": "a", "enabled": True},
                ],
            }
        )
    )
    with pytest.raises(preflight.ConfigError, match="Duplicate"):
        preflight.load_config(bad)


def test_fetch_openrouter_parses_fixture(openrouter_payload, monkeypatch):
    def fake_get(url, timeout, max_bytes, headers=None):
        return json.dumps(openrouter_payload).encode()

    monkeypatch.setattr(preflight, "http_get", fake_get)
    records, as_of = preflight.fetch_openrouter("key", 10, 100000)
    assert len(records) == 4
    assert records[0].external_id == "anthropic/claude-opus-5"
    assert records[0].coding_score == 69.4
    assert records[0].intelligence_score == 70.0
    assert records[0].output_price_per_million == pytest.approx(75.0)
    assert as_of == "2026-09-11T09:00:00.000Z"


def test_fetch_openrouter_not_configured():
    with pytest.raises(preflight.SourceError) as exc:
        preflight.fetch_openrouter(None, 10, 1000)
    assert exc.value.kind == "not_configured"


def test_fetch_aistupidlevel_parses_fixture(aistupidlevel_payload, monkeypatch):
    def fake_get(url, timeout, max_bytes, headers=None):
        return json.dumps(aistupidlevel_payload).encode()

    monkeypatch.setattr(preflight, "http_get", fake_get)
    records, cached_at = preflight.fetch_aistupidlevel(10, 100000)
    assert len(records) == 5
    assert all(r.source == "aistupidlevel" for r in records)


def test_exact_mapping_and_exclusion(config):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="anthropic/claude-opus-5-20260723",
                            display_name="Claude Opus 5",
                            coding_score=69.4,
                        )
                    ]
                ),
            },
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }
    candidates, exclusions, has_primary = preflight.build_candidates(
        config, snapshot
    )
    slugs = {c.slug for c in candidates}
    assert "claude-opus-5-thinking-high" in slugs
    assert "composer-2.5-fast" not in slugs
    assert any(e["slug"] == "composer-2.5-fast" for e in exclusions)


def test_ranking_prefers_higher_score_and_asl_breaks_exact_ties():
    candidates = [
        preflight.Candidate("b-model", 68.0, 70, None, ["openrouter"]),
        preflight.Candidate("a-model", 68.5, 65, None, ["openrouter"]),
        preflight.Candidate("c-model", 60.0, 80, None, ["openrouter"]),
        preflight.Candidate("tie-low-asl", 68.0, 10, None, ["openrouter"]),
    ]
    ranked = preflight.rank_candidates(candidates, "coding")
    assert [c.slug for c in ranked] == [
        "a-model",
        "b-model",
        "tie-low-asl",
        "c-model",
    ]

    picks = preflight.build_picks(
        ranked, "coding", near_tie_margin=2.0, cost_quality_margin=5.0
    )
    assert picks[0]["slug"] == "a-model"
    assert picks[0]["reason"] == "highest coding score"
    assert picks[1]["slug"] == "b-model"
    assert picks[1]["role"] == "similarly_strong"
    assert picks[1]["reason"] == "0.5 points below strong"


def test_fallback_source_only_medium_confidence(config, tmp_cache):
    now = datetime.now(timezone.utc)
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "sources": {
            "openrouter": {"status": "not_configured", "records": []},
            "aistupidlevel": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="aistupidlevel",
                            external_id="claude-opus-5",
                            display_name="claude-opus-5",
                            coding_score=65.0,
                        )
                    ]
                ),
            },
        },
    }
    rec = preflight.recommend(config, snapshot)
    assert rec.selected_model == "claude-opus-5-thinking-high"
    assert rec.confidence == "medium"
    planning = rec.tasks["planning"]
    assert planning["confidence"] == "low"
    assert "coding-heavy" in planning["note"]
    assert planning["picks"][0]["slug"] == "claude-opus-5-thinking-high"


def test_no_data_uses_fallback(config, tmp_cache):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {"status": "not_configured", "records": []},
            "aistupidlevel": {"status": "http", "records": []},
        },
    }
    rec = preflight.recommend(config, snapshot)
    assert rec.selected_model == config["fallback_model"]
    assert rec.confidence == "low"
    assert rec.used_fallback is True
    assert rec.tasks["coding"]["picks"] == []
    assert rec.tasks["planning"]["picks"] == []


def test_fresh_cache_skips_refresh(config, tmp_cache, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": now,
        "sources": {
            "openrouter": {"status": "ok", "records": []},
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }
    preflight.write_cache(snapshot)

    called = {"refresh": False}

    def fake_refresh(cfg, snap, *, force=False):
        called["refresh"] = True
        return snap

    monkeypatch.setattr(preflight, "refresh_cache", fake_refresh)
    preflight.ensure_snapshot(config, force_refresh=False)
    assert called["refresh"] is False


def test_stale_cache_triggers_refresh(config, tmp_cache, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": old,
        "sources": {
            "openrouter": {"status": "ok", "records": []},
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }
    preflight.write_cache(snapshot)

    called = {"refresh": False}

    def fake_refresh(cfg, snap, *, force=False):
        called["refresh"] = True
        snap = dict(snap or snapshot)
        snap["generated_at"] = datetime.now(timezone.utc).isoformat()
        return snap

    monkeypatch.setattr(preflight, "refresh_cache", fake_refresh)
    preflight.ensure_snapshot(config, force_refresh=False)
    assert called["refresh"] is True


def test_refresh_keeps_prior_records_on_source_failure(
    config, tmp_cache, monkeypatch
):
    prior = preflight.records_to_json(
        [
            preflight.Record(
                source="openrouter_artificial_analysis",
                external_id="anthropic/claude-opus-5-20260723",
                display_name="Claude Opus 5",
                coding_score=69.0,
            )
        ]
    )
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {"status": "ok", "records": prior},
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }

    def fail_openrouter(*args, **kwargs):
        raise preflight.SourceError("timeout", "timed out")

    monkeypatch.setattr(preflight, "fetch_openrouter", fail_openrouter)
    monkeypatch.setattr(
        preflight,
        "fetch_aistupidlevel",
        lambda *a, **k: (
            [
                preflight.Record(
                    source="aistupidlevel",
                    external_id="gpt-5.5",
                    display_name="gpt-5.5",
                    coding_score=68.0,
                )
            ],
            "2026-09-11T00:00:00Z",
        ),
    )

    updated = preflight.refresh_cache(config, snapshot, force=True)
    or_records = updated["sources"]["openrouter"]["records"]
    assert len(or_records) == 1
    assert updated["sources"]["openrouter"]["status"] == "timeout"
    assert updated["sources"]["aistupidlevel"]["status"] == "ok"


def test_failed_refresh_preserves_freshness_and_confidence(
    config, tmp_cache, monkeypatch
):
    old = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    prior = preflight.records_to_json(
        [
            preflight.Record(
                source="openrouter_artificial_analysis",
                external_id="anthropic/claude-opus-5-20260723",
                display_name="Claude Opus 5",
                coding_score=69.0,
            )
        ]
    )
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": old,
        "sources": {
            "openrouter": {"status": "ok", "records": prior},
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }

    def fail_all(*args, **kwargs):
        raise preflight.SourceError("timeout", "timed out")

    monkeypatch.setattr(preflight, "fetch_openrouter", fail_all)
    monkeypatch.setattr(preflight, "fetch_aistupidlevel", fail_all)
    updated = preflight.refresh_cache(config, snapshot, force=True)
    assert updated["generated_at"] == old
    rec = preflight.recommend(config, updated)
    assert rec.cache["used_stale_data"] is True
    assert rec.confidence in ("medium", "low")


def test_per_slug_asl_fallback_when_openrouter_unmatched(config):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="anthropic/claude-opus-5-20260723",
                            display_name="Claude Opus 5",
                            coding_score=69.4,
                            intelligence_score=70.0,
                        )
                    ]
                ),
            },
            "aistupidlevel": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="aistupidlevel",
                            external_id="gpt-5.5",
                            display_name="gpt-5.5",
                            coding_score=68.5,
                        )
                    ]
                ),
            },
        },
    }
    candidates, exclusions, _ = preflight.build_candidates(config, snapshot)
    slugs = {c.slug for c in candidates}
    assert "gpt-5.5-medium" in slugs
    gpt = next(c for c in candidates if c.slug == "gpt-5.5-medium")
    assert gpt.sources == ["aistupidlevel"]
    assert gpt.coding_index == pytest.approx(68.5)
    assert gpt.intelligence_index is None

    rec = preflight.recommend(config, snapshot)
    planning_slugs = [p["slug"] for p in rec.tasks["planning"]["picks"]]
    assert planning_slugs == ["claude-opus-5-thinking-high"]


def test_asl_coding_backfill_does_not_inherit_openrouter_confidence(config):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="openai/gpt-5.5-20260423",
                            display_name="GPT-5.5",
                            coding_score=None,
                            intelligence_score=80.0,
                            output_price_per_million=10.0,
                        ),
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="anthropic/claude-opus-5-20260723",
                            display_name="Claude Opus 5",
                            coding_score=40.0,
                            intelligence_score=40.0,
                            output_price_per_million=20.0,
                        ),
                    ]
                ),
            },
            "aistupidlevel": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="aistupidlevel",
                            external_id="gpt-5.5",
                            display_name="gpt-5.5",
                            coding_score=70.0,
                        )
                    ]
                ),
            },
        },
    }
    rec = preflight.recommend(config, snapshot)
    assert rec.selected is not None
    assert rec.selected_model == "gpt-5.5-medium"
    assert rec.selected.coding_from_openrouter is False
    assert rec.selected.coding_index == pytest.approx(70.0)
    assert rec.confidence == "medium"
    assert rec.tasks["coding"]["confidence"] == "medium"
    assert "aistupidlevel" in rec.selected.sources
    assert "openrouter_artificial_analysis" in rec.selected.sources

    planning = rec.tasks["planning"]
    assert planning["confidence"] == "high"
    assert planning["picks"][0]["slug"] == "gpt-5.5-medium"
    assert planning["picks"][0]["reason"] == "highest planning score"


def _or_record(external_id, coding, intelligence, price):
    return preflight.Record(
        source="openrouter_artificial_analysis",
        external_id=external_id,
        display_name=external_id,
        coding_score=coding,
        output_price_per_million=price,
        intelligence_score=intelligence,
    )


def _task_snapshot():
    return {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        _or_record(
                            "anthropic/claude-opus-5-20260723",
                            69.4,
                            70.0,
                            75.0,
                        ),
                        _or_record("openai/gpt-5.5-20260423", 68.5, 70.5, 50.0),
                        _or_record(
                            "openai/gpt-5.6-sol-20260709", 66.0, 73.0, 40.0
                        ),
                        _or_record(
                            "anthropic/claude-4.6-sonnet-20260217",
                            60.0,
                            60.0,
                            15.0,
                        ),
                    ]
                ),
            },
            "aistupidlevel": {"status": "ok", "records": []},
        },
    }


def _roles(rec, task):
    return {p["role"]: p["slug"] for p in rec.tasks[task]["picks"]}


def test_task_picks_diverge_between_coding_and_planning(config):
    rec = preflight.recommend(config, _task_snapshot())

    coding = _roles(rec, "coding")
    assert coding["strong"] == "claude-opus-5-thinking-high"
    assert coding["similarly_strong"] == "gpt-5.5-medium"
    assert rec.selected_model == coding["strong"]

    planning = _roles(rec, "planning")
    assert planning["strong"] == "gpt-5.6-sol-medium"
    assert planning["next_best"] == "gpt-5.5-medium"
    assert "similarly_strong" not in planning
    assert rec.tasks["planning"]["confidence"] == "high"


def test_cost_pick_stays_inside_quality_floor_and_cheaper(config):
    rec = preflight.recommend(config, _task_snapshot())

    coding = _roles(rec, "coding")
    assert coding["cost_efficient"] == "gpt-5.6-sol-medium"
    assert "claude-4.6-sonnet-medium-thinking" not in coding.values()
    cost_pick = next(
        p for p in rec.tasks["coding"]["picks"] if p["role"] == "cost_efficient"
    )
    strong_pick = next(
        p for p in rec.tasks["coding"]["picks"] if p["role"] == "strong"
    )
    assert cost_pick["output_price_per_million"] < (
        strong_pick["output_price_per_million"]
    )
    assert strong_pick["score"] - cost_pick["score"] <= (
        config["cost_quality_margin"]
    )

    # Planning: opus is pricier than the strong pick, sonnet is outside the
    # floor, so no cost slot.
    assert "cost_efficient" not in _roles(rec, "planning")


def test_load_dotenv_sets_key_when_unset(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('OPENROUTER_API_KEY="from-dotenv"\n')
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    preflight.load_dotenv(env_file)
    assert os.environ.get("OPENROUTER_API_KEY") == "from-dotenv"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=from-dotenv\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "already-set")
    preflight.load_dotenv(env_file)
    assert os.environ.get("OPENROUTER_API_KEY") == "already-set"


def test_atomic_write_leaves_no_partial_file(config, tmp_cache):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {},
    }
    preflight.write_cache(snapshot)
    cache_file = preflight.cache_path()
    assert cache_file.exists()
    leftovers = list(tmp_cache.glob("*.tmp"))
    assert leftovers == []


def test_corrupt_cache_treated_as_missing(tmp_cache, monkeypatch):
    cache_file = preflight.cache_path()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not json")
    assert preflight.load_cache() is None


def test_collect_unmapped(config):
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "openrouter": {
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="vendor/new-model",
                            display_name="New Model",
                            coding_score=99.0,
                        )
                    ]
                )
            },
            "aistupidlevel": {"records": []},
        },
    }
    unmapped = preflight.collect_unmapped(config, snapshot)
    assert unmapped[0]["external_id"] == "vendor/new-model"


def test_main_invalid_config_exit_code(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert preflight.main(["--config", str(bad), "select"]) == 1


def test_main_select_json(config, tmp_cache, monkeypatch, capsys):
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "schema_version": preflight.SCHEMA_VERSION,
        "generated_at": now,
        "sources": {
            "openrouter": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="openrouter_artificial_analysis",
                            external_id="anthropic/claude-opus-5-20260723",
                            display_name="Claude Opus 5",
                            coding_score=69.4,
                        )
                    ]
                ),
            },
            "aistupidlevel": {
                "status": "ok",
                "records": preflight.records_to_json(
                    [
                        preflight.Record(
                            source="aistupidlevel",
                            external_id="claude-opus-5",
                            display_name="claude-opus-5",
                            coding_score=65,
                        )
                    ]
                ),
            },
        },
    }
    preflight.write_cache(snapshot)
    monkeypatch.setattr(
        preflight,
        "DEFAULT_CONFIG_PATH",
        CONFIG_PATH,
    )
    code = preflight.main(["--config", str(CONFIG_PATH), "select", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["selected_model"] == "claude-opus-5-thinking-high"
    assert payload["confidence"] in ("high", "medium")
    assert set(payload["tasks"]) == {"coding", "planning"}
    assert payload["tasks"]["coding"]["picks"][0]["role"] == "strong"
