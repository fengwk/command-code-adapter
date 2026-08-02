from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path

import pytest

from cc_adapter.core.model_fetcher import ModelFetcher


class TestModelFetcher:
    def test_fallback_to_hardcoded(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        mf = ModelFetcher(cache_path=str(cache))
        models = mf.get_models_data()
        assert len(models) >= 19
        ids = {m["id"] for m in models}
        assert "deepseek/deepseek-v4-flash" in ids
        assert "stepfun/Step-3.5-Flash" in ids
        assert {
            "claude-opus-5",
            "xiaomi/mimo-v2.5-pro",
            "xiaomi/mimo-v2.5",
            "thinkingmachines/inkling-small",
        } <= ids
        assert mf.get_reasoning_efforts()["xiaomi/mimo-v2.5"] == ["low", "medium", "high"]

    def test_load_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        cache.write_text(
            json.dumps(
                {
                    "version": "0.99.0",
                    "fetched_at": time.time(),
                    "models": [
                        {
                            "id": "test-org/test-model",
                            "context_window": 500000,
                            "reasoning_efforts": ["low", "high"],
                        }
                    ],
                }
            )
        )
        mf = ModelFetcher(cache_path=str(cache))
        assert mf.get_status()["cached_version"] == "0.99.0"
        assert mf.get_status()["model_count"] == 1
        assert "test-org/test-model" in mf.get_reasoning_efforts()

    def test_old_monotonic_cache_is_loaded_but_marked_stale(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"version": "1.5.0", "fetched_at": 12345, "models": []}))
        mf = ModelFetcher(cache_path=cache)
        assert mf.get_status()["cached_version"] == "1.5.0"
        assert mf.get_status()["fetched_at"] is None
        assert mf._is_stale()

    def test_build_maps(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        mf = ModelFetcher(cache_path=str(cache))
        entries = [
            {"id": "org/A", "context_window": 100000, "reasoning_efforts": ["high"]},
            {"id": "no-slash-model", "context_window": 50000, "reasoning_efforts": None},
        ]
        mf._build_maps(entries)

        models = mf.get_models_data()
        assert len(models) == 2
        assert models[0]["id"] == "org/A"
        assert models[0]["owned_by"] == "org"
        assert models[0]["context_length"] == 100000

        assert "A" in mf.get_provider_map()
        assert mf.get_provider_map()["A"] == "org/A"

        assert "org/A" in mf.get_reasoning_efforts()
        assert "no-slash-model" not in mf.get_reasoning_efforts()

    def test_build_maps_no_slash(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        mf = ModelFetcher(cache_path=str(cache))
        entries = [
            {"id": "gpt-5.5", "context_window": 400000, "reasoning_efforts": ["low", "high"]},
        ]
        mf._build_maps(entries)
        assert mf.get_provider_map()["gpt-5.5"] == "gpt-5.5"
        assert mf.get_models_data()[0]["owned_by"] == "unknown"

    def test_atomic_write_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        mf = ModelFetcher(cache_path=str(cache))
        data = {"version": "0.99.0", "fetched_at": time.time(), "models": []}
        mf._atomic_write_cache(data)
        assert cache.exists()
        loaded = json.loads(cache.read_text())
        assert loaded["version"] == "0.99.0"

    def test_is_stale_initially(self, tmp_path: Path) -> None:
        mf = ModelFetcher(cache_path=str(tmp_path / "nonexistent.json"))
        assert mf._is_stale()

    def test_not_stale_after_fetch(self, tmp_path: Path) -> None:
        mf = ModelFetcher(cache_path=str(tmp_path / "nonexistent.json"))
        mf._fetched_at = time.time()
        assert not mf._is_stale()

    def test_get_status(self, tmp_path: Path) -> None:
        mf = ModelFetcher(cache_path=str(tmp_path / "models_cache.json"))
        status = mf.get_status()
        assert "cached_version" in status
        assert "fetched_at" in status
        assert "model_count" in status
        assert "last_error" in status

    def test_extract_models_js_numeric_literals(self, tmp_path: Path) -> None:
        mjs = """
export const models = {
  flash: { id: "deepseek/deepseek-v4-flash", contextWindow: 1e6, reasoningEfforts: ["high","max"] },
  pro: { id: "deepseek/deepseek-v4-pro", contextWindow: 2e5, reasoningEfforts: ["high","max"] },
  mini: { id: "gpt-5.4-mini", contextWindow: 256e3 },
};
"""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="package/dist/index.mjs")
            info.size = len(mjs.encode())
            tar.addfile(info, io.BytesIO(mjs.encode()))
        mf = ModelFetcher(cache_path=str(tmp_path / "models_cache.json"))
        entries = mf._extract_models(buf.getvalue())
        ids = {e["id"] for e in entries}
        assert "deepseek/deepseek-v4-flash" in ids
        for e in entries:
            if e["id"] == "deepseek/deepseek-v4-flash":
                assert e["context_window"] == 1000000
            elif e["id"] == "deepseek/deepseek-v4-pro":
                assert e["context_window"] == 200000
            elif e["id"] == "gpt-5.4-mini":
                assert e["context_window"] == 256000
        assert len(entries) == 3

    def test_extract_models_prefers_package_main_and_reads_command_code_1_6_catalog(self, tmp_path: Path) -> None:
        package = '{"main":"dist/cli.mjs"}'
        cli = """
        export const models = {
          opus: { id: "claude-opus-5", contextWindow: 1e6, reasoningEfforts: ["low","medium","high","xhigh","max"] },
          mimo: { id: "xiaomi/mimo-v2.5", contextWindow: 1e6, reasoningEfforts: ["low","medium","high"] },
          inkling: { id: "thinkingmachines/inkling-small", contextWindow: 1e6, reasoningEfforts: ["low","medium","high"] },
          qwen: { id: "Qwen/Qwen3.7-Flash", contextWindow: 1e6, reasoningEfforts: ["low","medium","high"] },
        };
        """
        legacy = 'export const models = { old: { id: "deepseek/deepseek-v4-flash" } };'
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, content in (
                ("package/package.json", package),
                ("package/dist/cli.mjs", cli),
                ("package/dist/index.mjs", legacy),
            ):
                info = tarfile.TarInfo(name=name)
                info.size = len(content.encode())
                tar.addfile(info, io.BytesIO(content.encode()))

        mf = ModelFetcher(cache_path=tmp_path / "models_cache.json")
        entries = mf._extract_models(buf.getvalue())
        ids = {entry["id"] for entry in entries}
        assert {"claude-opus-5", "xiaomi/mimo-v2.5", "thinkingmachines/inkling-small", "Qwen/Qwen3.7-Flash"} <= ids
        assert "deepseek/deepseek-v4-flash" not in ids

    def test_build_maps_preserves_static_aliases(self, tmp_path: Path) -> None:
        cache = tmp_path / "models_cache.json"
        mf = ModelFetcher(cache_path=str(cache))
        entries = [
            {"id": "stepfun/Step-3.5-Flash", "context_window": 100000, "reasoning_efforts": ["high"]},
            {"id": "moonshotai/Kimi-K2.6", "context_window": 200000, "reasoning_efforts": None},
        ]
        mf._build_maps(entries)
        pm = mf.get_provider_map()
        assert "step-3-5-flash" in pm
        assert pm["step-3-5-flash"] == "stepfun/Step-3.5-Flash"
        assert "kimi-k2-6" in pm
        assert pm["kimi-k2-6"] == "moonshotai/Kimi-K2.6"

    def test_sync_maps_updates_global(self, tmp_path: Path) -> None:
        from cc_adapter.providers.shared.model_mapping import (
            MODEL_PROVIDER_MAP,
            MODEL_REASONING_EFFORTS_MAP,
            refresh_maps,
        )

        original_provider = dict(MODEL_PROVIDER_MAP)
        original_re = dict(MODEL_REASONING_EFFORTS_MAP)
        try:
            mf = ModelFetcher(cache_path=str(tmp_path / "models_cache.json"))
            entries = [
                {"id": "synced-org/synced-model", "context_window": 500000, "reasoning_efforts": ["high"]},
            ]
            mf._build_maps(entries)
            mf._sync_maps()
            assert "synced-model" in MODEL_PROVIDER_MAP
            assert MODEL_PROVIDER_MAP["synced-model"] == "synced-org/synced-model"
            assert "synced-org/synced-model" in MODEL_REASONING_EFFORTS_MAP
            assert MODEL_REASONING_EFFORTS_MAP["synced-org/synced-model"] == ["high"]
        finally:
            refresh_maps(provider_map=original_provider, reasoning_efforts=original_re)
