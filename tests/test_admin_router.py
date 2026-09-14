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
    assert "cc_api_key_count" in data
    assert "cc_base_url" in data
    assert "host" in data
    assert "port" in data
    assert "log_level" in data


@pytest.mark.asyncio
async def test_update_config_uses_first_configured_key_for_client(tmp_path, monkeypatch):
    # Pin the panel config file into the temp dir (runtime data lives next to it).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
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
    # Pin the panel config file into the temp dir (runtime data lives next to it).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
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
    # Pin the panel config file into the temp dir (runtime data lives next to it).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
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
    # Pin the panel config file into the temp dir (runtime data lives next to it).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
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
    # Pin the panel config file into the temp dir (runtime data lives next to it).
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
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


def test_admin_js_config_page_defers_keys_to_keys_tab():
    """Static guard: the config form no longer edits the key pool (the Keys tab owns it)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    # No key input on the config form, and the save payload never carries cc_api_key
    assert 'id="cfg-key"' not in src
    assert "body.cc_api_key =" not in src
    assert '"cfg-key-count"' in src
    assert 'document.getElementById("cfg-manage-keys").onclick = () => switchTab("keys")' in src
    # The masked summary is never rendered as a value anywhere
    assert "cc_api_key_count" in src


def test_admin_js_token_manager_adds_without_rewriting_the_pool():
    """Static guard: the token dialog adds keys one by one; it must not overwrite the pool."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    assert 'api("POST", "/admin/api/keys", { key: token })' in src
    assert "tokenManagerEmpty" in src
    # Nothing in the panel rewrites cc_api_key through PUT /config any more
    assert 'api("PUT", "/admin/api/config", { cc_api_key' not in src


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


def _init_multi_key_client(keys: list[str]):
    """Install a client with an active KeyScheduler and pre-filled credits (no HTTP)."""
    return _init_pool_client(keys)[1]


def _init_pool_client(keys: list[str]):
    """Install a live config + client for any pool size, credits pre-filled (no HTTP)."""
    import time

    cfg = AppConfig()
    cfg.admin_password = "admin123"
    cfg.cc_api_key = list(keys)
    cfg.cc_base_url = "https://api.example.com"
    client = CommandCodeClient(
        base_url=cfg.cc_base_url,
        api_key=keys[0] if keys else "",
        api_keys=keys if len(keys) > 1 else None,
    )
    if client.scheduler is not None:
        client.scheduler._credits = {key: 100 for key in keys}
        client.scheduler._last_fetch = time.monotonic()
    admin_state_init(cfg, client)
    return cfg, client


def _stub_refresh(monkeypatch):
    """Keep /enable's background credits refresh off the network."""
    from cc_adapter.core.key_scheduler import KeyScheduler

    async def fake_refresh(self):
        return None

    monkeypatch.setattr(KeyScheduler, "_refresh", fake_refresh)


@pytest.mark.asyncio
async def test_list_keys_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_keys_without_scheduler_reports_unmanaged():
    from cc_adapter.core.auth import generate_token

    cfg = AppConfig()
    cfg.admin_password = "admin123"
    cfg.cc_api_key = ["singlekey1234"]
    admin_state_init(cfg, CommandCodeClient(base_url="https://api.example.com", api_key="singlekey1234"))
    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["key"] == "****1234"
    assert keys[0]["state"] == "unmanaged"
    # The manual-switch fields are always present so the panel renders one shape.
    assert keys[0]["enabled"] is True
    assert keys[0]["manual"] is False
    assert keys[0]["cooldown_seconds"] is None


@pytest.mark.asyncio
async def test_list_keys_reports_scheduler_state_and_masks_keys():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    client_impl.scheduler.report("key1111", ok=False, status=401)
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert [entry["key"] for entry in keys] == ["****1111", "****2222"]
    assert [entry["state"] for entry in keys] == ["disabled", "ok"]
    assert [entry["credits"] for entry in keys] == [100, 100]


@pytest.mark.asyncio
async def test_clear_sessions_endpoint_drops_bindings():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    await client_impl.scheduler.select("claude:s1", explicit=True)
    await client_impl.scheduler.select("claude:s2", explicit=True)
    assert client_impl.scheduler._affinity.stats()["entries"] == 2
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/sessions", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"cleared": 2}
    assert client_impl.scheduler._affinity.stats()["entries"] == 0


@pytest.mark.asyncio
async def test_enable_key_endpoint_clears_manual_off_and_health(monkeypatch):
    """POST /keys/{suffix}/enable turns a key back on: manual off, health and balance cleared."""
    _stub_refresh(monkeypatch)
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    scheduler = client_impl.scheduler
    scheduler.report("key1111", ok=False, status=429, reason="rate_limited")
    scheduler.disable("key1111")
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/keys/1111/enable", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "****1111"
    assert body["state"] == "ok"
    assert body["enabled"] is True
    assert body["manual"] is False
    assert body["cooldown_seconds"] is None
    assert body["credits"] is None  # cached balance dropped, so the key is selectable right away
    assert await scheduler.select(None, explicit=False) == "key1111"


@pytest.mark.asyncio
async def test_disable_key_endpoint_unbinds_sessions_and_is_idempotent():
    """POST /keys/{suffix}/disable takes one key out of rotation without touching the others."""
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    scheduler = client_impl.scheduler
    await scheduler.select("claude:s1", explicit=True)  # key1111
    await scheduler.select("claude:s2", explicit=True)  # key2222
    await scheduler.select("claude:s3", explicit=True)  # key1111 again
    assert scheduler.key_state("key1111")["sessions"] == 2
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/keys/1111/disable", headers={"Authorization": f"Bearer {my_token}"})
        again = await client.post("/admin/api/keys/1111/disable", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "****1111"
    assert body["unbound_sessions"] == 2
    assert body["enabled"] is False
    assert body["manual"] is True
    assert scheduler.key_state("key1111")["sessions"] == 0
    assert scheduler.key_state("key2222")["sessions"] == 1  # other key untouched
    assert await scheduler.select(None, explicit=False) == "key2222"
    assert again.json()["unbound_sessions"] == 0  # idempotent


@pytest.mark.parametrize(
    "keys,suffix",
    [
        (["key1111", "key2222"], "9999"),  # unknown suffix
        (["aaa-7777", "bbb-7777"], "7777"),  # ambiguous suffix
    ],
)
@pytest.mark.asyncio
async def test_key_switch_endpoints_reject_unresolvable_suffixes(keys, suffix):
    from cc_adapter.core.auth import generate_token

    _init_multi_key_client(keys)
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for verb in ("enable", "disable"):
            resp = await client.post(
                f"/admin/api/keys/{suffix}/{verb}", headers={"Authorization": f"Bearer {my_token}"}
            )
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Unknown or ambiguous key suffix"


@pytest.mark.asyncio
async def test_list_keys_reports_the_manual_switch_fields():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    client_impl.scheduler.disable("key2222")
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert [entry["key"] for entry in keys] == ["****1111", "****2222"]
    assert [entry["enabled"] for entry in keys] == [True, False]
    assert [entry["manual"] for entry in keys] == [False, True]
    assert [entry["cooldown_seconds"] for entry in keys] == [None, None]


@pytest.fixture
def panel_env(tmp_path, monkeypatch):
    """Panel config file inside a temp dir: key management must never touch the repo's real .env."""
    target = tmp_path / "panel.env"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(target))
    return target


@pytest.mark.asyncio
async def test_add_key_appends_persists_and_applies_to_the_running_client(panel_env, caplog):
    """POST /keys: the key lands in the live pool, in the rebuilt client and in the config file."""
    caplog.set_level(logging.INFO)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["key1111"])  # one key: no scheduler yet
    assert client_before.scheduler is None
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": "key5678"}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    assert resp.json() == {"key": "****5678", "count": 2}
    assert get_config().cc_api_key == ["key1111", "key5678"]
    rebuilt = get_client()
    assert rebuilt is not client_before  # rebuilt, so the new key is selectable right away
    assert rebuilt.scheduler._keys == ["key1111", "key5678"]
    assert 'CC_ADAPTER_CC_API_KEY=["key1111", "key5678"]' in panel_env.read_text()
    added = [r for r in caplog.records if "admin.key.added" in str(r.message)]
    assert len(added) == 1
    assert "5678" in str(added[0].message) and "count" in str(added[0].message)


@pytest.mark.asyncio
async def test_add_key_accepts_the_512_character_boundary(panel_env):
    """Boundary: 512 characters is still accepted (513 is rejected, see the limits test)."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    _init_pool_client(["key1111"])
    longest = "k" * 512
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": longest}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    assert get_config().cc_api_key == ["key1111", longest]


@pytest.mark.asyncio
async def test_add_key_rejects_a_key_already_in_the_pool(panel_env):
    """A duplicate would put the same upstream account in the rotation twice (compared stripped)."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["key1111", "key2222"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": " key2222 "}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Key already configured"
    assert get_config().cc_api_key == ["key1111", "key2222"]
    assert get_client() is client_before  # nothing rebuilt
    assert not panel_env.exists()  # nothing persisted


@pytest.mark.parametrize(
    "value,detail",
    [
        ("   ", "Key must not be empty"),
        ("key 1111", "Key must not contain whitespace"),
        ('["key1", "key2"]', "Key must not contain whitespace"),  # pasted JSON array
        ("key\n1111", "Key must not contain whitespace"),  # pasted line break
        ("k" * 513, "Key must not exceed 512 characters"),
    ],
)
@pytest.mark.asyncio
async def test_add_key_rejects_blank_whitespace_and_oversized_values(panel_env, value, detail):
    """Malformed input is refused before anything is applied or persisted."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["key1111"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": value}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == detail
    assert get_config().cc_api_key == ["key1111"]
    assert get_client() is client_before
    assert not panel_env.exists()


@pytest.mark.asyncio
async def test_add_key_reports_missing_config(monkeypatch):
    """Without a live config there is nothing to update, so report it instead of half-applying."""
    import cc_adapter.admin.router as admin_router_module
    from cc_adapter.core.auth import generate_token

    monkeypatch.setattr(admin_router_module, "get_config", lambda: None)
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": "key1111"}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Configuration is not available"


@pytest.mark.asyncio
async def test_remove_key_drops_it_from_pool_client_and_config_file(panel_env, caplog):
    """DELETE /keys/{suffix}: the key leaves the pool and the config file, bindings included."""
    caplog.set_level(logging.INFO)
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["key1111", "key2222"])
    await client_before.scheduler.select("claude:s1", explicit=True)  # binds key1111
    await client_before.scheduler.select("claude:s2", explicit=True)  # binds key2222
    assert client_before.scheduler.key_state("key2222")["sessions"] == 1
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/keys/2222", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"key": "****2222", "count": 1}
    assert get_config().cc_api_key == ["key1111"]
    env_content = panel_env.read_text()
    assert 'CC_ADAPTER_CC_API_KEY=["key1111"]' in env_content
    assert "key2222" not in env_content
    rebuilt = get_client()
    assert rebuilt is not client_before  # rebuilt without the removed key and its bindings
    assert rebuilt.scheduler is None
    assert rebuilt.api_key == "key1111"
    removed = [r for r in caplog.records if "admin.key.removed" in str(r.message)]
    assert len(removed) == 1
    assert "2222" in str(removed[0].message) and "count" in str(removed[0].message)


@pytest.mark.asyncio
async def test_remove_key_resolves_a_single_key_pool_without_a_scheduler(panel_env):
    """A one-key pool has no scheduler, so the config list is the resolution fallback."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["only1234"])
    assert client_before.scheduler is None
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/keys/1234", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"key": "****1234", "count": 0}
    assert get_config().cc_api_key == []


@pytest.mark.asyncio
async def test_removing_the_last_key_leaves_a_supported_empty_pool(panel_env):
    """Zero keys stays valid: the adapter keeps running and reports the CC error path itself."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _init_pool_client(["only1234"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/keys/1234", headers={"Authorization": f"Bearer {my_token}"})
        again = await client.delete("/admin/api/keys/1234", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"key": "****1234", "count": 0}
    assert get_config().cc_api_key == []
    assert "CC_ADAPTER_CC_API_KEY=[]" in panel_env.read_text()
    empty_client = get_client()
    assert empty_client.api_key == ""
    assert empty_client.scheduler is None
    # Requests still fail with the client's own "not configured" error.
    assert "CC_ADAPTER_CC_API_KEY is not configured" in str(empty_client._no_key_error())
    assert again.status_code == 404
    assert again.json()["detail"] == "Unknown or ambiguous key suffix"


@pytest.mark.parametrize(
    "keys,suffix",
    [
        (["key1111", "key2222"], "9999"),  # unknown suffix, scheduler active
        (["aaa-7777", "bbb-7777"], "7777"),  # ambiguous suffix, scheduler active
        (["only1234"], "9999"),  # single-key pool: no scheduler, config-list fallback
    ],
)
@pytest.mark.asyncio
async def test_remove_key_rejects_unresolvable_suffixes(panel_env, keys, suffix):
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(keys)
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/admin/api/keys/{suffix}", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown or ambiguous key suffix"
    assert get_config().cc_api_key == keys
    assert get_client() is client_before
    assert not panel_env.exists()


@pytest.mark.asyncio
async def test_manual_off_survives_the_client_rebuild(panel_env):
    """A panel save rebuilds the client; a key the operator switched off must stay off."""
    import time

    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client

    _, client_before = _init_pool_client(["key1111", "key2222"])
    client_before.scheduler.disable("key1111")  # off, so it must not come back at the head
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": "key3333"}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    rebuilt = get_client()
    assert rebuilt is not client_before
    scheduler = rebuilt.scheduler
    assert scheduler.manual_disabled_keys() == {"key1111"}
    assert scheduler.key_state("key1111")["manual"] is True
    assert scheduler.key_state("key1111")["enabled"] is False
    # Seeded instead of fetched: select() must not go to the network in tests.
    scheduler._credits = {key: 100 for key in ["key1111", "key2222", "key3333"]}
    scheduler._last_fetch = time.monotonic()
    assert await scheduler.select(None, explicit=False) == "key2222"
