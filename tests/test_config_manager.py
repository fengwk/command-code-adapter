import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cc_adapter.admin.config_manager import ConfigManager, FIELD_MAP, _apply_config_fields
from cc_adapter.core.config import AppConfig, env_file_path
from cc_adapter.core.constants import DISTRIBUTION_FILL_FIRST, DISTRIBUTION_ROUND_ROBIN


class TestApplyConfigFields:
    def test_simple_field_update(self):
        cfg = AppConfig(default_model="old-model")
        changed = _apply_config_fields(cfg, {"default_model": "new-model"})
        assert cfg.default_model == "new-model"
        assert not changed  # default_model is not a client field

    def test_client_field_update(self):
        cfg = AppConfig(cc_base_url="https://old.example.com")
        changed = _apply_config_fields(cfg, {"cc_base_url": "https://new.example.com"})
        assert cfg.cc_base_url == "https://new.example.com"
        assert changed  # cc_base_url is a client field

    def test_distribution_update_is_normalized_and_keeps_the_client(self):
        """The mode is applied in place, so the stored value must be canonical and unremarkable."""
        cfg = AppConfig()
        changed = _apply_config_fields(cfg, {"distribution": "Fill_First"})
        assert cfg.distribution == DISTRIBUTION_FILL_FIRST
        assert not changed  # switching the distribution must not rebuild the client

    def test_an_unknown_distribution_update_stores_the_default(self):
        cfg = AppConfig(distribution="fill-first")
        _apply_config_fields(cfg, {"distribution": "sideways"})
        assert cfg.distribution == DISTRIBUTION_ROUND_ROBIN

    def test_zdr_update_keeps_the_client_and_handles_types(self):
        cfg = AppConfig(zdr=True)
        # 1. Setting bool False
        changed = _apply_config_fields(cfg, {"zdr": False})
        assert cfg.zdr is False
        assert not changed  # zdr is not a client field

        # 2. String "false" must not evaluate truthy (as bool("false") would)
        _apply_config_fields(cfg, {"zdr": "false"})
        assert cfg.zdr is False

        # 3. String "true"
        _apply_config_fields(cfg, {"zdr": "true"})
        assert cfg.zdr is True

        # 4. Unknown strings are rejected instead of making memory and dotenv disagree.
        with pytest.raises(ValueError, match="invalid boolean value"):
            _apply_config_fields(cfg, {"zdr": "invalid"})
        assert cfg.zdr is True

    def test_api_key_normalization_single_string(self):
        cfg = AppConfig(cc_api_key="single-key")
        changed = _apply_config_fields(cfg, {"cc_api_key": "single-key"})
        # normalize_api_keys always returns a list
        assert cfg.cc_api_key == ["single-key"]
        assert changed  # cc_api_key is a client field

    def test_api_key_normalization_json_list(self):
        cfg = AppConfig(cc_api_key=["k1"])
        changed = _apply_config_fields(cfg, {"cc_api_key": json.dumps(["key1", "key2"])})
        # normalize_api_keys parses the JSON string into a list
        assert cfg.cc_api_key == ["key1", "key2"]
        assert changed


class TestUpdateEnvFile:
    def test_update_existing_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_DEFAULT_MODEL=old-model\n")
            ConfigManager.update_env_file({"default_model": "new-model"}, env_path)
            content = env_path.read_text()
            assert "CC_ADAPTER_DEFAULT_MODEL=new-model" in content

    def test_add_new_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_PORT=8080\n")
            ConfigManager.update_env_file({"default_model": "my-model"}, env_path)
            content = env_path.read_text()
            assert "CC_ADAPTER_DEFAULT_MODEL=my-model" in content

    def test_update_api_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_CC_API_KEY=" + json.dumps("old-key") + "\n")
            ConfigManager.update_env_file({"cc_api_key": "new-key"}, env_path)
            content = env_path.read_text()
            assert "new-key" in content

    def test_update_distribution_writes_the_canonical_mode(self):
        """The config file must not keep the raw panel spelling (it is what operators read)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_DISTRIBUTION=round-robin\n")
            ConfigManager.update_env_file({"distribution": "Fill_First"}, env_path)
            assert env_path.read_text() == f"CC_ADAPTER_DISTRIBUTION={DISTRIBUTION_FILL_FIRST}\n"

    def test_add_distribution_writes_the_canonical_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_PORT=8080\n")
            ConfigManager.update_env_file({"distribution": "sideways"}, env_path)
            content = env_path.read_text()
            assert f"CC_ADAPTER_DISTRIBUTION={DISTRIBUTION_ROUND_ROBIN}\n" in content
            assert "sideways" not in content

    def test_update_zdr_writes_canonical_lowercase_bool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_ZDR=true\n")
            ConfigManager.update_env_file({"zdr": False}, env_path)
            assert env_path.read_text() == "CC_ADAPTER_ZDR=false\n"
            ConfigManager.update_env_file({"zdr": True}, env_path)
            assert env_path.read_text() == "CC_ADAPTER_ZDR=true\n"

    def test_add_zdr_writes_canonical_lowercase_bool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_PORT=8080\n")
            ConfigManager.update_env_file({"zdr": False}, env_path)
            assert "CC_ADAPTER_ZDR=false\n" in env_path.read_text()

    def test_invalid_zdr_does_not_rewrite_the_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            original = "CC_ADAPTER_ZDR=true\n"
            env_path.write_text(original)
            with pytest.raises(ValueError, match="invalid boolean value"):
                ConfigManager.update_env_file({"zdr": "invalid"}, env_path)
            assert env_path.read_text() == original

    def test_update_api_key_json_list_to_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("CC_ADAPTER_CC_API_KEY=" + json.dumps(["k1", "k2"]) + "\n")
            ConfigManager.update_env_file({"cc_api_key": json.dumps(["k3", "k4"])}, env_path)
            content = env_path.read_text()
            parsed_line = [l for l in content.splitlines() if "CC_ADAPTER_CC_API_KEY" in l][0]
            assert "k3" in parsed_line
            assert "k4" in parsed_line

    def test_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            ConfigManager.update_env_file({"default_model": "test"}, env_path)
            assert env_path.exists()
            content = env_path.read_text()
            assert "CC_ADAPTER_DEFAULT_MODEL=test" in content

    def test_multiple_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            ConfigManager.update_env_file(
                {"host": "1.2.3.4", "port": 9090, "log_level": "DEBUG"},
                env_path,
            )
            content = env_path.read_text()
            assert "CC_ADAPTER_HOST=1.2.3.4" in content
            assert "CC_ADAPTER_PORT=9090" in content
            assert "CC_ADAPTER_LOG_LEVEL=DEBUG" in content


class TestRecreateClient:
    """The panel rebuilds the client on every client-field change; the manual switch is operator intent."""

    def test_manual_off_carries_over_for_keys_still_configured(self):
        from cc_adapter.admin.config_manager import _recreate_client
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, init as state_init

        keys = ["cc-key-alpha-1111", "cc-key-beta-2222", "cc-key-gamma-3333"]
        cfg = AppConfig(cc_api_key=keys)
        old = CommandCodeClient(base_url=cfg.cc_base_url, api_key=keys[0], api_keys=keys)
        old.scheduler.disable(keys[1])
        old.scheduler.disable(keys[2])
        state_init(cfg, old)
        previous = (cfg, old)
        try:
            cfg.cc_api_key = [keys[0], keys[1]]  # the panel dropped the third key
            assert _recreate_client(cfg) is old
            new = get_client()
            assert new is not old
            # Only keys still configured come back off; the dropped one is simply gone.
            assert new.scheduler.manual_disabled_keys() == {keys[1]}
            assert new.scheduler.key_state(keys[1])["enabled"] is False
            assert new.scheduler.key_state(keys[0])["enabled"] is True
        finally:
            state_init(*previous)  # do not leave this fixture client in the runtime singleton

    @pytest.mark.asyncio
    async def test_session_bindings_carry_over_to_the_rebuilt_client(self):
        """A panel save must not drag running conversations to another upstream account."""
        from cc_adapter.admin.config_manager import _recreate_client
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, init as state_init

        keys = ["cc-key-alpha-1111", "cc-key-beta-2222"]
        cfg = AppConfig(cc_api_key=keys)
        old = CommandCodeClient(base_url=cfg.cc_base_url, api_key=keys[0], api_keys=keys)
        old.scheduler._credits = {key: 100 for key in keys}
        old.scheduler._last_fetch = time.monotonic()
        sticky = "header:running-conversation"
        assert await old.scheduler.select(sticky, explicit=True) == keys[0]
        assert await old.scheduler.select("header:second", explicit=True) == keys[1]
        state_init(cfg, old)
        previous = (cfg, old)
        try:
            _recreate_client(cfg)  # same key list, fresh client
            new = get_client()
            assert new is not old
            new.scheduler._credits = {key: 100 for key in keys}  # no balance fetch in this test
            new.scheduler._last_fetch = time.monotonic()
            # Both bindings survived, so the round-robin head does not steal them
            assert await new.scheduler.select(sticky, explicit=True) == keys[0]
            assert await new.scheduler.select("header:second", explicit=True) == keys[1]
            assert new.scheduler.key_state(keys[0])["sessions"] == 1
        finally:
            state_init(*previous)

    @pytest.mark.asyncio
    async def test_bindings_of_a_removed_key_are_dropped(self):
        from cc_adapter.admin.config_manager import _recreate_client
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, init as state_init

        keys = ["cc-key-alpha-1111", "cc-key-beta-2222", "cc-key-gamma-3333"]
        cfg = AppConfig(cc_api_key=keys)
        old = CommandCodeClient(base_url=cfg.cc_base_url, api_key=keys[0], api_keys=keys)
        old.scheduler._credits = {key: 100 for key in keys}
        old.scheduler._last_fetch = time.monotonic()
        moved = "header:on-the-dropped-key"
        assert await old.scheduler.select(moved, explicit=True) == keys[0]
        assert await old.scheduler.select("header:stays", explicit=True) == keys[1]
        state_init(cfg, old)
        previous = (cfg, old)
        try:
            cfg.cc_api_key = [keys[1], keys[2]]  # the panel removed the key the session was bound to
            _recreate_client(cfg)
            new = get_client()
            new.scheduler._credits = {key: 100 for key in cfg.cc_api_key}
            new.scheduler._last_fetch = time.monotonic()
            assert new.scheduler._affinity.get_and_refresh(moved) is None
            assert new.scheduler._affinity.get_and_refresh("header:stays") == keys[1]
            assert await new.scheduler.select(moved, explicit=True) == keys[1]
        finally:
            state_init(*previous)

    @pytest.mark.asyncio
    async def test_disabled_key_remains_disabled_across_rebuild_when_adding_key(self):
        """Reproduction: disabled -> add another key -> disabled (previously became ok)."""
        from cc_adapter.admin.config_manager import _recreate_client
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, get_config, init as state_init

        keys = ["cc-key-alpha-1111", "cc-key-beta-2222"]
        cfg = AppConfig(cc_api_key=keys)
        old = CommandCodeClient(base_url=cfg.cc_base_url, api_key=keys[0], api_keys=keys)
        old.scheduler._credits = {key: 100 for key in keys}
        old.scheduler._last_fetch = time.monotonic()
        # Mark alpha as 401 disabled
        old.scheduler.report(keys[0], ok=False, status=401)
        assert old.scheduler.key_state(keys[0])["state"] == "disabled"
        assert old.scheduler._usable(keys[0]) is False

        previous = (get_config(), get_client())
        state_init(cfg, old)
        new = None
        try:
            # Operator adds a third key in the panel
            new_keys = ["cc-key-alpha-1111", "cc-key-beta-2222", "cc-key-gamma-3333"]
            cfg.cc_api_key = new_keys
            _recreate_client(cfg)
            new = get_client()
            assert new is not old
            assert new.scheduler is not None

            # Alpha must remain disabled, not restored to ok
            assert new.scheduler.key_state(keys[0])["state"] == "disabled"
            assert new.scheduler.key_state(keys[0])["reason"] == "http_401"
            assert new.scheduler._usable(keys[0]) is False

            # Beta remains usable
            assert new.scheduler.key_state(keys[1])["state"] == "ok"
            assert new.scheduler._usable(keys[1]) is True

            # Newly added key causes last_fetch_time to be None (forcing fresh snapshot on next select)
            assert new.scheduler.last_fetch_time is None
        finally:
            state_init(*previous)
            await old.aclose()
            if new is not None:
                await new.aclose()

    @pytest.mark.asyncio
    async def test_scheduler_state_survives_2_to_3_and_3_to_2_rebuild(self):
        """Automatic health, cooling deadline, failures, zero-credits and affinity survive rebuild."""
        from cc_adapter.admin.config_manager import _recreate_client
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, get_config, init as state_init

        k1, k2, k3 = "key-alpha-1111", "key-beta-2222", "key-gamma-3333"
        keys = [k1, k2, k3]
        cfg = AppConfig(cc_api_key=keys)
        old = CommandCodeClient(base_url=cfg.cc_base_url, api_key=k1, api_keys=keys)
        sched = old.scheduler
        assert sched is not None

        # k1: 401 disabled
        sched.report(k1, ok=False, status=401)
        # k2: 429 cooling with failure count = 2
        sched.report(k2, ok=False, status=429, reason="rate_limited")
        sched.report(k2, ok=False, status=429, reason="rate_limited")
        k2_until = sched._until[k2]
        sched._credits[k2] = 0  # zero-credit mark
        # k3: manual off + sticky session
        sched.disable(k3)
        sched._affinity.set("sess:surviving", k2)
        sched._affinity.set("sess:on-dropped", k3)

        previous = (get_config(), get_client())
        state_init(cfg, old)
        new = None
        try:
            # 3 -> 2 keys rebuild: drop k3
            cfg.cc_api_key = [k1, k2]
            _recreate_client(cfg)
            new = get_client()
            new_sched = new.scheduler
            assert new_sched is not None

            # k1 survived as disabled
            assert new_sched.key_state(k1)["state"] == "disabled"
            assert new_sched.key_state(k1)["reason"] == "http_401"

            # k2 survived with cooling deadline, failure count and zero credits
            assert new_sched.key_state(k2)["state"] == "cooling"
            assert new_sched.key_state(k2)["failures"] == 2
            assert new_sched.key_state(k2)["reason"] == "rate_limited"
            assert new_sched.key_state(k2)["credits"] == 0
            assert new_sched._until.get(k2) == k2_until

            # k3 (dropped) has no state in new scheduler
            assert k3 not in new_sched._keys
            assert k3 not in new_sched._state
            assert k3 not in new_sched._until
            assert k3 not in new_sched._failures
            assert k3 not in new_sched._manual_off

            # Affinity: binding on k2 survived, binding on dropped k3 was discarded
            assert new_sched._affinity.get_and_refresh("sess:surviving") == k2
            assert new_sched._affinity.get_and_refresh("sess:on-dropped") is None

            # Objects are deep copies, not shared
            assert new_sched._state is not sched._state
            assert new_sched._until is not sched._until
            assert new_sched._failures is not sched._failures
            assert new_sched._credits is not sched._credits
        finally:
            state_init(*previous)
            await old.aclose()
            if new is not None:
                await new.aclose()


class TestDistributionUpdate:
    """A mode switch is applied to the live scheduler in place; nothing is rebuilt.

    Each test installs a client into the runtime singleton, so it restores whatever was
    there before and closes its own pools: a client left behind keeps serving later test
    files, and its httpx pools belong to this test's (closed) event loop.
    """

    @pytest.mark.asyncio
    async def test_update_switches_the_live_scheduler_without_a_rebuild(self):
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, get_config, init as state_init

        keys = ["cc-key-alpha-1111", "cc-key-beta-2222"]
        cfg = AppConfig(cc_api_key=keys)
        client = CommandCodeClient(base_url=cfg.cc_base_url, api_key=keys[0], api_keys=keys)
        client.scheduler._credits = {key: 100 for key in keys}
        client.scheduler._last_fetch = time.monotonic()
        sticky = "header:running-conversation"
        assert await client.scheduler.select(sticky, explicit=True) == keys[0]
        assert await client.scheduler.select("header:second", explicit=True) == keys[1]
        previous = (get_config(), get_client())
        state_init(cfg, client)
        try:
            await ConfigManager.apply_config_update({"distribution": "fill-first"})

            assert get_client() is client  # same object: no rebuild, so no re-dealt bindings
            assert client.scheduler.distribution == DISTRIBUTION_FILL_FIRST
            assert cfg.distribution == DISTRIBUTION_FILL_FIRST
            # Both running conversations keep their account ...
            assert await client.scheduler.select(sticky, explicit=True) == keys[0]
            assert await client.scheduler.select("header:second", explicit=True) == keys[1]
            # ... while a new one follows the new mode
            assert await client.scheduler.select("header:third", explicit=True) == keys[0]
        finally:
            state_init(*previous)
            await client.aclose()

    @pytest.mark.asyncio
    async def test_update_without_a_scheduler_only_stores_the_mode(self):
        """A single-key pool has no scheduler; the mode applies to the next rebuild."""
        from cc_adapter.command_code.client import CommandCodeClient
        from cc_adapter.core.runtime import get_client, get_config, init as state_init

        cfg = AppConfig(cc_api_key=["only-key-1234"])
        client = CommandCodeClient(base_url=cfg.cc_base_url, api_key="only-key-1234")
        assert client.scheduler is None
        previous = (get_config(), get_client())
        state_init(cfg, client)
        try:
            await ConfigManager.apply_config_update({"distribution": DISTRIBUTION_FILL_FIRST})
            assert cfg.distribution == DISTRIBUTION_FILL_FIRST
            assert get_client() is client
        finally:
            state_init(*previous)
            await client.aclose()

    @pytest.mark.asyncio
    async def test_update_survives_a_runtime_without_a_client(self, monkeypatch):
        """Nothing has been initialised yet: the mode is stored, not crashed on."""
        from cc_adapter.core import runtime

        cfg = AppConfig(cc_api_key=["only-key-1234"])
        monkeypatch.setattr(runtime, "_config", cfg)
        monkeypatch.setattr(runtime, "_cc_client", None)
        await ConfigManager.apply_config_update({"distribution": DISTRIBUTION_FILL_FIRST})
        assert cfg.distribution == DISTRIBUTION_FILL_FIRST


class TestFieldMap:
    def test_field_map_covers_key_fields(self):
        for field in [
            "cc_api_key",
            "cc_base_url",
            "host",
            "port",
            "log_level",
            "log_format",
            "default_model",
            "distribution",
            "zdr",
        ]:
            assert field in FIELD_MAP

    def test_field_map_env_prefix(self):
        for env_key in FIELD_MAP.values():
            assert env_key.startswith("CC_ADAPTER_")


class TestDistributionConfig:
    """`CC_ADAPTER_DISTRIBUTION` chooses the first-sight distribution of new sessions."""

    def test_default_is_round_robin(self, monkeypatch):
        monkeypatch.delenv("CC_ADAPTER_DISTRIBUTION", raising=False)
        assert AppConfig().distribution == DISTRIBUTION_ROUND_ROBIN

    def test_env_var_is_honoured(self, monkeypatch):
        monkeypatch.setenv("CC_ADAPTER_DISTRIBUTION", "fill-first")
        assert AppConfig().distribution == DISTRIBUTION_FILL_FIRST

    def test_an_unknown_env_value_normalizes_to_the_default(self, monkeypatch):
        """A typo must not leave the deployment without a working mode."""
        monkeypatch.setenv("CC_ADAPTER_DISTRIBUTION", "sideways")
        assert AppConfig().distribution == DISTRIBUTION_ROUND_ROBIN

    def test_config_file_value_is_honoured_and_normalized(self, tmp_path):
        """The dotenv file is a settings source too (fresh process, own env file)."""
        custom = tmp_path / "cc-adapter.env"
        custom.write_text("CC_ADAPTER_DISTRIBUTION=FillFirst\n")  # sloppy spelling on purpose
        env = {k: v for k, v in os.environ.items() if not k.startswith("CC_ADAPTER_")}
        env["CC_ADAPTER_ENV_FILE"] = str(custom)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        proc = subprocess.run(
            [sys.executable, "-c", "from cc_adapter.core.config import AppConfig; print(AppConfig().distribution)"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == DISTRIBUTION_FILL_FIRST


class TestEnvFilePath:
    def test_defaults_to_working_directory_env(self, monkeypatch):
        monkeypatch.delenv("CC_ADAPTER_ENV_FILE", raising=False)
        assert env_file_path() == ".env"

    def test_defaults_to_env_var_when_empty(self, monkeypatch):
        monkeypatch.setenv("CC_ADAPTER_ENV_FILE", "")
        assert env_file_path() == ".env"

    def test_honors_cc_adapter_env_file(self, monkeypatch):
        monkeypatch.setenv("CC_ADAPTER_ENV_FILE", "/app/data/.env")
        assert env_file_path() == "/app/data/.env"

    def test_update_env_file_defaults_to_resolved_path(self, monkeypatch, tmp_path):
        target = tmp_path / "cc-adapter.env"
        monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(target))
        ConfigManager.update_env_file({"default_model": "from-panel"})
        assert "CC_ADAPTER_DEFAULT_MODEL=from-panel" in target.read_text()

    def test_update_env_file_creates_missing_parent_dir(self, monkeypatch, tmp_path):
        target = tmp_path / "data" / ".env"
        monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(target))
        ConfigManager.update_env_file({"default_model": "panel-model"})
        assert target.exists()
        assert "CC_ADAPTER_DEFAULT_MODEL=panel-model" in target.read_text()

    def test_update_env_file_new_file_is_private(self, tmp_path):
        target = tmp_path / ".env"
        ConfigManager.update_env_file({"default_model": "x"}, target)
        assert target.stat().st_mode & 0o777 == 0o600

    def test_update_env_file_preserves_existing_mode(self, tmp_path):
        target = tmp_path / ".env"
        target.write_text("CC_ADAPTER_PORT=8080\n")
        os.chmod(target, 0o640)
        ConfigManager.update_env_file({"default_model": "x"}, target)
        assert target.stat().st_mode & 0o777 == 0o640

    def test_update_env_file_writes_temp_file_next_to_target(self, monkeypatch, tmp_path):
        """Atomic rename must stay on one filesystem (mounted config volume)."""
        from cc_adapter.admin import config_manager

        target = tmp_path / "data" / ".env"
        seen: list[str] = []
        real_mkstemp = tempfile.mkstemp

        def spy(*args, **kwargs):
            seen.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(config_manager.tempfile, "mkstemp", spy)
        ConfigManager.update_env_file({"default_model": "x"}, target)
        assert seen == [str(tmp_path / "data")]

    def test_appconfig_reads_the_configured_file(self, tmp_path):
        """CC_ADAPTER_ENV_FILE actually repoints the settings source (fresh process)."""
        custom = tmp_path / "cc-adapter.env"
        custom.write_text("CC_ADAPTER_DEFAULT_MODEL=custom/model-v1\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("CC_ADAPTER_")}
        env["CC_ADAPTER_ENV_FILE"] = str(custom)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        proc = subprocess.run(
            [sys.executable, "-c", "from cc_adapter.core.config import AppConfig; print(AppConfig().default_model)"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "custom/model-v1"

    def test_appconfig_falls_back_when_configured_file_missing(self, tmp_path):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CC_ADAPTER_")}
        env["CC_ADAPTER_ENV_FILE"] = str(tmp_path / "not-there" / ".env")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        proc = subprocess.run(
            [sys.executable, "-c", "from cc_adapter.core.config import AppConfig; print(AppConfig().default_model)"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "deepseek/deepseek-v4-flash"
