import json
from pathlib import Path

import httpx
import pytest

from cc_adapter.core import version_checker as version_checker_module
from cc_adapter.core.config import data_dir
from cc_adapter.core.runtime import get_version_checker, reset_version_checker
from cc_adapter.core.version_checker import DEFAULT_VERSION_FILE, VersionChecker

NPM_VERSION_URL = "https://registry.npmjs.org/command-code/latest"


@pytest.fixture(autouse=True)
def isolate_version_data_dir(monkeypatch, tmp_path: Path):
    """Point the data dir at tmp_path: a successful fetch persists cli_version.json and
    the suite must never write that file into the repository working tree."""
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / "data" / ".env"))


class TestRuntimeVersionChecker:
    def test_get_version_checker_returns_singleton(self):
        reset_version_checker()
        c1 = get_version_checker()
        c2 = get_version_checker()
        assert c1 is c2


class TestVersionChecker:
    @pytest.mark.asyncio
    async def test_get_version_returns_default_on_first_call(self):
        checker = VersionChecker()
        version = checker.get_version()
        assert version == "1.54.0"

    @pytest.mark.asyncio
    async def test_get_version_returns_cached_value_without_fetch(self):
        checker = VersionChecker()
        v1 = checker.get_version()
        checker._cached_version = "0.99.0"
        v2 = checker.get_version()
        assert v2 == "0.99.0"

    @pytest.mark.asyncio
    async def test_refresh_updates_version(self, respx_mock):
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.26.3"}))
        checker = VersionChecker()
        await checker.refresh()
        assert checker.get_version() == "0.26.3"
        assert checker.last_fetch_time is not None

    @pytest.mark.asyncio
    async def test_refresh_preserves_old_on_network_failure(self, respx_mock):
        respx_mock.get(NPM_VERSION_URL).mock(side_effect=httpx.RequestError("connection failed"))
        checker = VersionChecker()
        checker._cached_version = "1.54.0"
        await checker.refresh()
        assert checker.get_version() == "1.54.0"
        assert checker.last_error is not None
        assert checker.last_fetch_time is not None  # backoff enforced
        assert not checker._path.exists()  # a failure writes nothing

    @pytest.mark.asyncio
    async def test_refresh_preserves_old_on_bad_json(self, respx_mock):
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, text="not json"))
        checker = VersionChecker()
        await checker.refresh()
        assert checker.get_version() == "1.54.0"

    @pytest.mark.asyncio
    async def test_refresh_sets_fetch_time_even_when_version_missing(self, respx_mock):
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"other": "data"}))
        checker = VersionChecker()
        await checker.refresh()
        assert checker.last_fetch_time is not None
        assert checker.get_version() == "1.54.0"

    @pytest.mark.asyncio
    async def test_failure_clears_old_error_before_attempt(self, respx_mock):
        """last_error should be cleared at start of fetch, not just set on failure."""
        checker = VersionChecker()
        checker._last_error = "stale error"
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.27.0"}))
        assert checker.last_error == "stale error"
        await checker.refresh()
        assert checker.get_version() == "0.27.0"
        assert checker.last_error is None  # success clears it

    @pytest.mark.asyncio
    async def test_failure_sets_fetch_time_for_error_backoff(self, respx_mock):
        """After failure, _last_fetch_time is set so _is_stale uses ERROR_BACKOFF."""
        respx_mock.get(NPM_VERSION_URL).mock(side_effect=httpx.RequestError("down"))
        checker = VersionChecker()
        await checker.refresh()
        assert checker.last_fetch_time is not None
        assert checker.last_error is not None

    @pytest.mark.asyncio
    async def test_background_fetch_updates_version(self, respx_mock):
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.28.0"}))
        checker = VersionChecker()
        checker._last_fetch_time = None
        checker.get_version()
        assert checker.get_version() == "1.54.0"
        if checker._fetch_task is not None:
            await checker._fetch_task
        assert checker.get_version() == "0.28.0"

    @pytest.mark.asyncio
    async def test_get_version_does_not_trigger_duplicate_fetches(self, respx_mock):
        route = respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.26.3"}))
        checker = VersionChecker()
        checker._last_fetch_time = None

        checker.get_version()
        checker.get_version()

        if checker._fetch_task is not None:
            await checker._fetch_task
        assert route.call_count == 1


class TestPersistedVersion:
    def test_default_version_file_name(self):
        # The persisted file name is part of the module contract (mirrors DEFAULT_DATA_FILE).
        assert DEFAULT_VERSION_FILE == "cli_version.json"

    def test_default_path_follows_data_dir(self, tmp_path: Path):
        assert VersionChecker()._path == data_dir() / DEFAULT_VERSION_FILE
        assert VersionChecker()._path == tmp_path / "data" / DEFAULT_VERSION_FILE  # isolated by the fixture

    def test_explicit_version_path_wins_over_data_dir(self, tmp_path: Path):
        # Mirrors TokenRecorder(data_path=...) / ModelFetcher(cache_path=...).
        explicit = tmp_path / "custom" / "cli_version.json"
        assert VersionChecker(version_path=explicit)._path == explicit
        assert VersionChecker(version_path=str(explicit))._path == explicit

    def test_new_checker_reads_persisted_version(self, tmp_path: Path):
        # A restart must report the last successfully fetched version, not the constant,
        # and must not need a fetch for it.
        version_path = tmp_path / "cli_version.json"
        version_path.write_text(json.dumps({"version": "0.26.3"}))
        checker = VersionChecker(version_path=version_path)
        assert checker.get_version() == "0.26.3"
        assert checker.last_fetch_time is None

    def test_missing_or_broken_file_falls_back_to_default(self, tmp_path: Path):
        version_path = tmp_path / "cli_version.json"
        assert VersionChecker(version_path=version_path).get_version() == "1.54.0"  # missing
        version_path.write_text("")  # empty
        assert VersionChecker(version_path=version_path).get_version() == "1.54.0"
        version_path.write_text("not json")  # unreadable
        assert VersionChecker(version_path=version_path).get_version() == "1.54.0"
        version_path.write_text(json.dumps({"other": "data"}))  # no version field
        assert VersionChecker(version_path=version_path).get_version() == "1.54.0"

    def test_default_version_env_override_still_applies(self, monkeypatch, tmp_path: Path):
        # CC_ADAPTER_DEFAULT_VERSION is read into DEFAULT_VERSION at import time and stays
        # the fallback whenever nothing usable is persisted.
        monkeypatch.setattr(version_checker_module, "DEFAULT_VERSION", "9.99.9")
        assert VersionChecker(version_path=tmp_path / "cli_version.json").get_version() == "9.99.9"

    @pytest.mark.asyncio
    async def test_refresh_persists_fetched_version(self, respx_mock, tmp_path: Path):
        # A successful fetch must survive a restart: the fetched version lands on disk.
        version_path = tmp_path / "cli_version.json"
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "1.54.0"}))
        checker = VersionChecker(version_path=version_path)
        await checker.refresh()
        assert checker.get_version() == "1.54.0"
        assert json.loads(version_path.read_text()) == {"version": "1.54.0"}

    @pytest.mark.asyncio
    async def test_refresh_creates_parent_directory(self, respx_mock, tmp_path: Path):
        # The data dir may not exist yet on a fresh deployment.
        version_path = tmp_path / "data" / "cli_version.json"
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "1.54.0"}))
        await VersionChecker(version_path=version_path).refresh()
        assert json.loads(version_path.read_text()) == {"version": "1.54.0"}

    @pytest.mark.asyncio
    async def test_failed_fetch_keeps_persisted_version(self, respx_mock, tmp_path: Path):
        # Network failure: neither the file nor the in-memory value may change, so a fresh
        # checker after the failure still reports the last good version.
        version_path = tmp_path / "cli_version.json"
        version_path.write_text(json.dumps({"version": "0.26.3"}))
        respx_mock.get(NPM_VERSION_URL).mock(side_effect=httpx.RequestError("down"))
        checker = VersionChecker(version_path=version_path)
        await checker.refresh()
        assert checker.get_version() == "0.26.3"
        assert checker.last_error is not None
        assert VersionChecker(version_path=version_path).get_version() == "0.26.3"
        assert json.loads(version_path.read_text()) == {"version": "0.26.3"}

    @pytest.mark.asyncio
    async def test_failed_fetch_after_success_keeps_last_good_version(self, respx_mock, tmp_path: Path):
        # The in-memory value from the last success also survives the next failed refresh.
        version_path = tmp_path / "cli_version.json"
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.26.3"}))
        checker = VersionChecker(version_path=version_path)
        await checker.refresh()
        respx_mock.get(NPM_VERSION_URL).mock(side_effect=httpx.RequestError("down"))
        await checker.refresh()
        assert checker.get_version() == "0.26.3"
        assert VersionChecker(version_path=version_path).get_version() == "0.26.3"
        assert json.loads(version_path.read_text()) == {"version": "0.26.3"}

    @pytest.mark.asyncio
    async def test_empty_version_field_does_not_overwrite_persisted_value(self, respx_mock, tmp_path: Path):
        # HTTP 200 without a usable version keeps the previous value and writes nothing.
        version_path = tmp_path / "cli_version.json"
        version_path.write_text(json.dumps({"version": "0.26.3"}))
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "", "other": "data"}))
        checker = VersionChecker(version_path=version_path)
        await checker.refresh()
        assert checker.get_version() == "0.26.3"
        assert checker.last_fetch_time is not None
        assert json.loads(version_path.read_text()) == {"version": "0.26.3"}

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_break_the_fetch(self, respx_mock, tmp_path: Path):
        # A broken data directory only warns: the in-memory version is still updated.
        respx_mock.get(NPM_VERSION_URL).mock(return_value=httpx.Response(200, json={"version": "0.29.0"}))
        checker = VersionChecker(version_path=tmp_path / "cli_version.json")
        checker._path = tmp_path / "blocked" / "cli_version.json"  # parent is a file → mkdir fails
        (tmp_path / "blocked").write_text("not a directory")
        await checker.refresh()
        assert checker.get_version() == "0.29.0"
        assert checker.last_error is None
        assert checker.last_fetch_time is not None
