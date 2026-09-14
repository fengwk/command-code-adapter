import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cc_adapter.admin.config_manager import ConfigManager, FIELD_MAP, _apply_config_fields
from cc_adapter.core.config import AppConfig, env_file_path


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
            "zdr",
        ]:
            assert field in FIELD_MAP

    def test_field_map_env_prefix(self):
        for env_key in FIELD_MAP.values():
            assert env_key.startswith("CC_ADAPTER_")


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
