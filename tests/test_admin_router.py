import logging

import pytest
from httpx import ASGITransport, AsyncClient
from cc_adapter.main import app
from cc_adapter.core.auth import set_password
from cc_adapter.admin.router import router as admin_router
from cc_adapter.core.runtime import init as admin_state_init
from cc_adapter.core.config import AppConfig
from cc_adapter.command_code.client import CommandCodeClient

app.include_router(admin_router)


@pytest.fixture(autouse=True)
def setup_auth():
    cfg = AppConfig()
    cfg.admin_password = "admin123"
    client = CommandCodeClient(base_url=cfg.cc_base_url, api_key=cfg.cc_api_key[0] if cfg.cc_api_key else "")
    admin_state_init(cfg, client)
    set_password("admin123")


@pytest.mark.asyncio
async def test_login_success():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/login", json={"password": "admin123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data


@pytest.mark.asyncio
async def test_login_failure():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/login", json={"password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_config_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_config_returns_fields():
    set_password("admin123")
    from cc_adapter.core.auth import generate_token

    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/config", headers={"Authorization": f"Bearer {my_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "cc_api_key" in data
    assert "cc_base_url" in data
    assert "host" in data
    assert "port" in data
    assert "log_level" in data


@pytest.mark.asyncio
async def test_update_config_uses_first_configured_key_for_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"cc_api_key": '["user_one","user_two"]'},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    assert get_config().cc_api_key == ["user_one", "user_two"]
    assert get_client().api_key == "user_one"


@pytest.mark.asyncio
async def test_update_config_persists_prefixed_env_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cc_adapter.core.auth import generate_token

    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"cc_api_key": "user_one", "cc_base_url": "https://example.test"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    env_content = (tmp_path / ".env").read_text()
    env_lines = set(env_content.splitlines())
    assert 'CC_ADAPTER_CC_API_KEY=["user_one"]' in env_content
    assert "CC_ADAPTER_CC_BASE_URL=https://example.test" in env_content
    assert not any(line.startswith("CC_API_KEY=") for line in env_lines)
    assert not any(line.startswith("CC_BASE_URL=") for line in env_lines)


@pytest.mark.asyncio
async def test_usage_query_returns_empty_when_no_keys():
    from cc_adapter.core.runtime import init as admin_state_init, get_config
    from cc_adapter.core.auth import generate_token

    cfg = get_config()
    cfg.cc_api_key = []
    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/usage/query", headers={"Authorization": f"Bearer {my_token}"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_update_config_rejects_masked_key_summary(tmp_path, monkeypatch, caplog):
    """The masked summary returned by GET /admin/api/config must never be persisted as a key."""
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.WARNING)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    env_content = 'CC_ADAPTER_CC_API_KEY=["real_one","real_two"]\n'
    env_path = tmp_path / ".env"
    env_path.write_text(env_content)
    get_config().cc_api_key = ["real_one", "real_two"]
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"cc_api_key": "2 key(s) configured"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "cc_api_key must be a real key or omitted"
    assert any("admin.config.rejected" in str(r.message) for r in caplog.records)
    # Nothing was persisted: .env and the in-memory key pool are unchanged
    assert env_path.read_text() == env_content
    assert get_config().cc_api_key == ["real_one", "real_two"]


@pytest.mark.asyncio
async def test_update_config_accepts_real_key_and_normalizes_pool(tmp_path, monkeypatch):
    """Guard must stay narrow: a genuine key still saves and is normalized into the pool."""
    monkeypatch.chdir(tmp_path)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    get_config().cc_api_key = []
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"cc_api_key": "real_key_001"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    assert get_config().cc_api_key == ["real_key_001"]
    assert 'CC_ADAPTER_CC_API_KEY=["real_key_001"]' in (tmp_path / ".env").read_text()


@pytest.mark.asyncio
async def test_update_config_without_key_keeps_existing_pool(tmp_path, monkeypatch):
    """A blank key input is omitted by the frontend, so saving other fields must keep the pool."""
    monkeypatch.chdir(tmp_path)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    get_config().cc_api_key = ["real_one", "real_two"]
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"cc_base_url": "https://example.test"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    assert get_config().cc_api_key == ["real_one", "real_two"]
    env_content = (tmp_path / ".env").read_text()
    assert "CC_ADAPTER_CC_BASE_URL=https://example.test" in env_content
    assert "configured" not in env_content


def test_admin_js_shows_key_summary_only_as_placeholder():
    """Static guard: the masked summary is rendered as a placeholder, never as the input value."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    assert 'getElementById("cfg-key").value = configData.cc_api_key' not in src
    assert "keyInput.placeholder = configData.cc_api_key" in src
    # loadConfig and saveConfig both leave the input empty
    assert src.count('keyInput.value = ""') >= 2


def test_admin_js_token_manager_saves_full_keys():
    """Static guard: the token dialog must save the stored full keys, never the masked row text."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    # The row carries the full key; only the masked form is rendered (escaped, and only here)
    assert "row.dataset.key = keyVal" in src
    assert "escapeHtml(keyVal.slice(0, 12)" in src
    assert src.count("keyVal.slice(0, 12)") == 1
    # tm-save rebuilds the token list from the stored value, not from the truncated DOM text
    assert "const keyVal = row.dataset.key;" in src
    assert 'codeEl.textContent.replace("...", "")' not in src
    assert 'querySelector("code")' not in src
