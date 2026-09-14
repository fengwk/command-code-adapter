from __future__ import annotations

import json
import os
from pathlib import Path

from cc_adapter.core.config import data_dir
from cc_adapter.core.model_fetcher import ModelFetcher
from cc_adapter.core.token_recorder import TokenRecorder
from cc_adapter.core.version_checker import VersionChecker


def test_data_dir_defaults_to_working_directory(monkeypatch) -> None:
    # Without CC_ADAPTER_ENV_FILE the dotenv default ".env" keeps runtime files in the CWD.
    monkeypatch.delenv("CC_ADAPTER_ENV_FILE", raising=False)
    assert data_dir() == Path(".")


def test_data_dir_follows_env_file(monkeypatch, tmp_path: Path) -> None:
    # A mounted dotenv path means runtime data must land in that same directory.
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / "data" / ".env"))
    assert data_dir() == tmp_path / "data"


def test_default_paths_live_next_to_env_file(monkeypatch, tmp_path: Path) -> None:
    # Every runtime artefact defaults under the dotenv directory; a missing cache file is tolerated
    # without touching the network (no refresh call, static catalog fallback).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / "data" / ".env"))
    recorder = TokenRecorder()
    fetcher = ModelFetcher()
    checker = VersionChecker()
    assert recorder._path == tmp_path / "data" / "token_usage.json"
    assert fetcher._cache_path == tmp_path / "data" / "models_cache.json"
    assert checker._path == tmp_path / "data" / "cli_version.json"
    assert fetcher.get_status()["cached_version"] is None


def test_explicit_paths_are_unchanged(monkeypatch, tmp_path: Path) -> None:
    # An explicit path argument must win over the configured data directory.
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / "data" / ".env"))
    assert TokenRecorder(data_path=tmp_path / "x.json")._path == tmp_path / "x.json"
    assert ModelFetcher(cache_path=tmp_path / "y.json")._cache_path == tmp_path / "y.json"
    assert VersionChecker(version_path=tmp_path / "z.json")._path == tmp_path / "z.json"


def test_model_fetcher_atomic_write_stays_next_to_target(monkeypatch, tmp_path: Path) -> None:
    # Regression for the EXDEV layout: the temp file must be created in the cache file's own
    # directory (a mounted data volume can be a different device than the system temp dir).
    target = tmp_path / "deep" / "models_cache.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        seen.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr("cc_adapter.core.model_fetcher.os.replace", spy_replace)
    ModelFetcher(cache_path=target)._atomic_write_cache({"version": "1", "models": []})

    assert len(seen) == 1
    src, dst = seen[0]
    assert Path(src).parent == Path(dst).parent == tmp_path / "deep"
    assert Path(dst) == target
    assert json.loads(target.read_text()) == {"version": "1", "models": []}


def test_token_recorder_atomic_write_stays_next_to_target(monkeypatch, tmp_path: Path) -> None:
    # Same EXDEV regression as above, for the token usage file.
    target = tmp_path / "deep" / "token_usage.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        seen.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr("cc_adapter.core.token_recorder.os.replace", spy_replace)
    recorder = TokenRecorder(data_path=target)
    recorder._data = {"2026-09-14": {"tokens": 3, "requests": 1, "models": {}}}
    recorder._atomic_write()

    assert len(seen) == 1
    src, dst = seen[0]
    assert Path(src).parent == Path(dst).parent == tmp_path / "deep"
    assert Path(dst) == target
    assert json.loads(target.read_text()) == recorder._data


def test_version_checker_atomic_write_stays_next_to_target(monkeypatch, tmp_path: Path) -> None:
    # Same EXDEV regression as above, for the persisted CLI version.
    target = tmp_path / "deep" / "cli_version.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        seen.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr("cc_adapter.core.version_checker.os.replace", spy_replace)
    VersionChecker(version_path=target)._persist_version("1.54.0")

    assert len(seen) == 1
    src, dst = seen[0]
    assert Path(src).parent == Path(dst).parent == tmp_path / "deep"
    assert Path(dst) == target
    assert json.loads(target.read_text()) == {"version": "1.54.0"}
