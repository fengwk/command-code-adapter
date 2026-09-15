import logging

import pytest
from httpx import ASGITransport, AsyncClient
from cc_adapter.main import app
from cc_adapter.core.auth import set_password
from cc_adapter.admin.router import router as admin_router
from cc_adapter.core.runtime import init as admin_state_init
from cc_adapter.core.config import AppConfig
from cc_adapter.core.utils import api_key_id
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
async def test_get_config_reports_the_live_distribution_mode(tmp_path, monkeypatch):
    """GET returns the mode that is actually in force, not just the stored one."""
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get("/admin/api/config", headers={"Authorization": f"Bearer {my_token}"})
        client_impl.scheduler.set_distribution("fill-first")  # e.g. a runtime switch
        after = await client.get("/admin/api/config", headers={"Authorization": f"Bearer {my_token}"})

    assert before.status_code == 200
    assert before.json()["distribution"] == "round-robin"
    assert after.json()["distribution"] == "fill-first"


@pytest.mark.asyncio
async def test_update_config_switches_the_distribution_without_a_rebuild(tmp_path, monkeypatch):
    """PUT {"distribution"} takes effect on the live scheduler and survives the next GET."""
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    client_before = _init_multi_key_client(["key1111", "key2222"])
    await client_before.scheduler.select("claude:running", explicit=True)  # binds key1111
    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"distribution": "fill-first"},
            headers={"Authorization": f"Bearer {my_token}"},
        )
        after = await client.get("/admin/api/config", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json()["distribution"] == "fill-first"
    assert after.json()["distribution"] == "fill-first"
    assert get_client() is client_before  # applied in place: no client rebuild
    assert get_config().distribution == "fill-first"
    assert client_before.scheduler.distribution == "fill-first"
    assert client_before.scheduler.key_state("key1111")["sessions"] == 1  # binding survived
    assert "CC_ADAPTER_DISTRIBUTION=fill-first" in (tmp_path / ".env").read_text()


@pytest.mark.asyncio
async def test_update_config_falls_back_from_an_unknown_distribution(tmp_path, monkeypatch):
    """A bad value is corrected to the default instead of erroring the whole save."""
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path / ".env"))
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    client_impl = _init_multi_key_client(["key1111", "key2222"])
    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/admin/api/config",
            json={"distribution": "sideways"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["distribution"] == "round-robin"
    assert get_config().distribution == "round-robin"
    assert client_impl.scheduler.distribution == "round-robin"


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


def test_admin_js_config_form_exposes_the_distribution_select():
    """Static guard: both modes are offered on the config form and wired through load/save."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    # The select offers the two wire values, labelled through t()
    assert '<select id="cfg-distribution">' in src
    assert '<option value="round-robin">${t("distributionRoundRobin")}</option>' in src
    assert '<option value="fill-first">${t("distributionFillFirst")}</option>' in src
    # loadConfig restores the stored mode, saveConfig only sends a changed one
    assert 'document.getElementById("cfg-distribution").value = distribution;' in src
    assert "if (distribution !== configData.distribution) body.distribution = distribution;" in src
    # Label, both options and the hint exist in zh and en
    for key in ("distributionLabel", "distributionRoundRobin", "distributionFillFirst", "distributionHint"):
        assert src.count(f"{key}:") == 2


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
        api_keys=keys if keys else None,
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
    assert keys[0]["id"] == api_key_id("singlekey1234")
    assert keys[0]["key"] == "****1234"
    assert keys[0]["state"] == "unmanaged"
    # The manual-switch fields are always present so the panel renders one shape.
    assert keys[0]["enabled"] is True
    assert keys[0]["manual"] is False
    assert keys[0]["cooldown_seconds"] is None


@pytest.mark.asyncio
async def test_list_keys_reports_scheduler_state_and_masks_keys():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["test-key1111", "test-key2222"])
    client_impl.scheduler.report("test-key1111", ok=False, status=401)
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert [entry["id"] for entry in keys] == [api_key_id("test-key1111"), api_key_id("test-key2222")]
    assert [entry["key"] for entry in keys] == ["****1111", "****2222"]
    assert [entry["state"] for entry in keys] == ["disabled", "ok"]
    assert [entry["credits"] for entry in keys] == [100, 100]


@pytest.mark.asyncio
async def test_clear_sessions_endpoint_drops_bindings():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["test-key1111", "test-key2222"])
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

    client_impl = _init_multi_key_client(["test-key1111", "test-key2222"])
    scheduler = client_impl.scheduler
    scheduler.report("test-key1111", ok=False, status=429, reason="rate_limited")
    scheduler.disable("test-key1111")
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/keys/1111/enable", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == api_key_id("test-key1111")
    assert body["key"] == "****1111"
    assert body["state"] == "ok"
    assert body["enabled"] is True
    assert body["manual"] is False
    assert body["cooldown_seconds"] is None
    assert body["credits"] is None  # cached balance dropped, so the key is selectable right away
    assert await scheduler.select(None, explicit=False) == "test-key1111"


@pytest.mark.asyncio
async def test_disable_key_endpoint_unbinds_sessions_and_is_idempotent():
    """POST /keys/{suffix}/disable takes one key out of rotation without touching the others."""
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["test-key1111", "test-key2222"])
    scheduler = client_impl.scheduler
    await scheduler.select("claude:s1", explicit=True)  # test-key1111
    await scheduler.select("claude:s2", explicit=True)  # test-key2222
    await scheduler.select("claude:s3", explicit=True)  # test-key1111 again
    assert scheduler.key_state("test-key1111")["sessions"] == 2
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/api/keys/1111/disable", headers={"Authorization": f"Bearer {my_token}"})
        again = await client.post("/admin/api/keys/1111/disable", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == api_key_id("test-key1111")
    assert body["key"] == "****1111"
    assert body["unbound_sessions"] == 2
    assert body["enabled"] is False
    assert body["manual"] is True
    assert scheduler.key_state("test-key1111")["sessions"] == 0
    assert scheduler.key_state("test-key2222")["sessions"] == 1  # other key untouched
    assert await scheduler.select(None, explicit=False) == "test-key2222"
    assert again.json()["unbound_sessions"] == 0  # idempotent


@pytest.mark.parametrize(
    "keys,suffix",
    [
        (["test-key1111", "test-key2222"], "9999"),  # unknown suffix
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
            assert resp.json()["detail"] == "Unknown or ambiguous key identifier"


@pytest.mark.asyncio
async def test_list_keys_reports_the_manual_switch_fields():
    from cc_adapter.core.auth import generate_token

    client_impl = _init_multi_key_client(["test-key1111", "test-key2222"])
    client_impl.scheduler.disable("test-key2222")
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

    _, client_before = _init_pool_client(["pool-key1111"])  # one key in pool: has single-key scheduler
    assert client_before.scheduler is not None
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": "pool-key5678"}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    assert resp.json() == {"id": api_key_id("pool-key5678"), "key": "****5678", "count": 2}
    assert get_config().cc_api_key == ["pool-key1111", "pool-key5678"]
    rebuilt = get_client()
    assert rebuilt is not client_before  # rebuilt, so the new key is selectable right away
    assert rebuilt.scheduler._keys == ["pool-key1111", "pool-key5678"]
    assert 'CC_ADAPTER_CC_API_KEY=["pool-key1111", "pool-key5678"]' in panel_env.read_text()
    added = [r for r in caplog.records if "admin.key.added" in str(r.message)]
    assert len(added) == 1
    assert api_key_id("pool-key5678") in str(added[0].message) and "count" in str(added[0].message)


@pytest.mark.asyncio
async def test_add_key_accepts_the_512_character_boundary(panel_env):
    """Boundary: 512 characters is still accepted (513 is rejected, see the limits test)."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    _init_pool_client(["pool-key1111"])
    longest = "k" * 512
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": longest}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    assert get_config().cc_api_key == ["pool-key1111", longest]


@pytest.mark.asyncio
async def test_add_key_rejects_a_key_already_in_the_pool(panel_env):
    """A duplicate would put the same upstream account in the rotation twice (compared stripped)."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    _, client_before = _init_pool_client(["pool-key1111", "pool-key2222"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": " pool-key2222 "}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Key already configured"
    assert get_config().cc_api_key == ["pool-key1111", "pool-key2222"]
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

    _, client_before = _init_pool_client(["pool-key1111"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": value}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == detail
    assert get_config().cc_api_key == ["pool-key1111"]
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

    _, client_before = _init_pool_client(["pool-key1111", "pool-key2222"])
    await client_before.scheduler.select("claude:s1", explicit=True)  # binds pool-key1111
    await client_before.scheduler.select("claude:s2", explicit=True)  # binds pool-key2222
    assert client_before.scheduler.key_state("pool-key2222")["sessions"] == 1
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/keys/2222", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"id": api_key_id("pool-key2222"), "key": "****2222", "count": 1}
    assert get_config().cc_api_key == ["pool-key1111"]
    env_content = panel_env.read_text()
    assert 'CC_ADAPTER_CC_API_KEY=["pool-key1111"]' in env_content
    assert "pool-key2222" not in env_content
    rebuilt = get_client()
    assert rebuilt is not client_before  # rebuilt without the removed key and its bindings
    assert rebuilt.scheduler is not None  # single-key pool retains KeyScheduler
    assert rebuilt.scheduler._keys == ["pool-key1111"]
    assert rebuilt.api_key == "pool-key1111"
    removed = [r for r in caplog.records if "admin.key.removed" in str(r.message)]
    assert len(removed) == 1
    assert api_key_id("pool-key2222") in str(removed[0].message) and "count" in str(removed[0].message)


@pytest.mark.asyncio
async def test_remove_key_resolves_a_single_key_pool_without_a_scheduler(panel_env):
    """An unmanaged one-key client has no scheduler, so the config list is the resolution fallback."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config

    cfg = AppConfig()
    cfg.admin_password = "admin123"
    cfg.cc_api_key = ["only1234"]
    client_before = CommandCodeClient(base_url="https://api.example.com", api_key="only1234")
    admin_state_init(cfg, client_before)
    assert client_before.scheduler is None
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/admin/api/keys/1234", headers={"Authorization": f"Bearer {my_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"id": api_key_id("only1234"), "key": "****1234", "count": 0}
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
    assert resp.json() == {"id": api_key_id("only1234"), "key": "****1234", "count": 0}
    assert get_config().cc_api_key == []
    assert "CC_ADAPTER_CC_API_KEY=[]" in panel_env.read_text()
    empty_client = get_client()
    assert empty_client.api_key == ""
    assert empty_client.scheduler is None
    # Requests still fail with the client's own "not configured" error.
    assert "CC_ADAPTER_CC_API_KEY is not configured" in str(empty_client._no_key_error())
    assert again.status_code == 404
    assert again.json()["detail"] == "Unknown or ambiguous key identifier"


@pytest.mark.parametrize(
    "keys,suffix",
    [
        (["pool-key1111", "pool-key2222"], "9999"),  # unknown suffix, scheduler active
        (["aaa-7777", "bbb-7777"], "7777"),  # ambiguous suffix, scheduler active
        (["only1234"], "9999"),  # single-key pool: no match
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
    assert resp.json()["detail"] == "Unknown or ambiguous key identifier"
    assert get_config().cc_api_key == keys
    assert get_client() is client_before
    assert not panel_env.exists()


@pytest.mark.asyncio
async def test_manual_off_survives_the_client_rebuild(panel_env):
    """A panel save rebuilds the client; a key the operator switched off must stay off."""
    import time

    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client

    _, client_before = _init_pool_client(["pool-key1111", "pool-key2222"])
    client_before.scheduler.disable("pool-key1111")  # off, so it must not come back at the head
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/keys", json={"key": "pool-key3333"}, headers={"Authorization": f"Bearer {my_token}"}
        )

    assert resp.status_code == 200
    rebuilt = get_client()
    assert rebuilt is not client_before
    scheduler = rebuilt.scheduler
    assert scheduler.manual_disabled_keys() == {"pool-key1111"}
    assert scheduler.key_state("pool-key1111")["manual"] is True
    assert scheduler.key_state("pool-key1111")["enabled"] is False
    # Seeded instead of fetched: select() must not go to the network in tests.
    scheduler._credits = {key: 100 for key in ["pool-key1111", "pool-key2222", "pool-key3333"]}
    scheduler._last_fetch = time.monotonic()
    assert await scheduler.select(None, explicit=False) == "pool-key2222"


@pytest.mark.asyncio
async def test_short_key_never_appears_verbatim_in_admin_responses_or_logs(panel_env, caplog):
    """A configured key 'abc' appears only as '****' plus non-reversible ID; literal 'abc' is absent."""
    caplog.set_level(logging.INFO)
    from cc_adapter.core.auth import generate_token

    _init_pool_client(["key1111"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Add short key "abc"
        resp_add = await client.post(
            "/admin/api/keys", json={"key": "abc"}, headers={"Authorization": f"Bearer {my_token}"}
        )
        assert resp_add.status_code == 200
        add_data = resp_add.json()
        assert add_data["key"] == "****"
        abc_id = api_key_id("abc")
        assert add_data["id"] == abc_id
        assert "abc" not in resp_add.text

        # Verify log did not leak "abc"
        add_logs = [r for r in caplog.records if "admin.key.added" in str(r.message)]
        assert any(abc_id in str(r.message) for r in add_logs)
        assert not any("key_last4=abc" in str(r.message) or "key=abc" in str(r.message) for r in add_logs)

        # 2. GET /admin/api/keys
        resp_list = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})
        assert resp_list.status_code == 200
        list_data = resp_list.json()
        abc_entry = [k for k in list_data["keys"] if k["id"] == abc_id][0]
        assert abc_entry["key"] == "****"
        assert "abc" not in resp_list.text

        # 3. Disable short key by ID
        resp_dis = await client.post(
            f"/admin/api/keys/{abc_id}/disable", headers={"Authorization": f"Bearer {my_token}"}
        )
        assert resp_dis.status_code == 200
        assert resp_dis.json()["key"] == "****"
        assert resp_dis.json()["id"] == abc_id
        assert "abc" not in resp_dis.text

        # 4. Enable short key by ID
        resp_en = await client.post(f"/admin/api/keys/{abc_id}/enable", headers={"Authorization": f"Bearer {my_token}"})
        assert resp_en.status_code == 200
        assert resp_en.json()["key"] == "****"
        assert resp_en.json()["id"] == abc_id
        assert "abc" not in resp_en.text

        # 5. Remove short key by ID
        resp_del = await client.delete(f"/admin/api/keys/{abc_id}", headers={"Authorization": f"Bearer {my_token}"})
        assert resp_del.status_code == 200
        assert resp_del.json()["key"] == "****"
        assert resp_del.json()["id"] == abc_id
        assert "abc" not in resp_del.text


@pytest.mark.asyncio
async def test_two_keys_with_same_suffix_can_be_operated_by_id_while_suffix_is_ambiguous(panel_env):
    """Two keys sharing the same last 4 chars can each be operated by ID; legacy suffix is 404."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_config

    k1, k2 = "alpha-1111", "beta-1111"
    _init_pool_client([k1, k2])
    my_token = generate_token()
    id1 = api_key_id(k1)
    id2 = api_key_id(k2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Legacy suffix 1111 is ambiguous for both actions -> 404
        r_en_ambig = await client.post("/admin/api/keys/1111/enable", headers={"Authorization": f"Bearer {my_token}"})
        assert r_en_ambig.status_code == 404
        assert r_en_ambig.json()["detail"] == "Unknown or ambiguous key identifier"

        r_dis_ambig = await client.post("/admin/api/keys/1111/disable", headers={"Authorization": f"Bearer {my_token}"})
        assert r_dis_ambig.status_code == 404
        assert r_dis_ambig.json()["detail"] == "Unknown or ambiguous key identifier"

        r_del_ambig = await client.delete("/admin/api/keys/1111", headers={"Authorization": f"Bearer {my_token}"})
        assert r_del_ambig.status_code == 404
        assert r_del_ambig.json()["detail"] == "Unknown or ambiguous key identifier"

        # Safe ID operates on each key independently
        r_dis1 = await client.post(f"/admin/api/keys/{id1}/disable", headers={"Authorization": f"Bearer {my_token}"})
        assert r_dis1.status_code == 200
        assert r_dis1.json()["id"] == id1
        assert r_dis1.json()["enabled"] is False

        r_en1 = await client.post(f"/admin/api/keys/{id1}/enable", headers={"Authorization": f"Bearer {my_token}"})
        assert r_en1.status_code == 200
        assert r_en1.json()["id"] == id1
        assert r_en1.json()["enabled"] is True

        # Delete key1 by ID leaves key2
        r_del1 = await client.delete(f"/admin/api/keys/{id1}", headers={"Authorization": f"Bearer {my_token}"})
        assert r_del1.status_code == 200
        assert r_del1.json()["id"] == id1
        assert get_config().cc_api_key == [k2]


@pytest.mark.asyncio
async def test_long_key_display_follows_mask_api_key_contract():
    """Existing long key displays follow mask_api_key() (first10…last6)."""
    from cc_adapter.core.auth import generate_token

    long_k = "sk-123456789012345678901"  # 23 chars
    _init_pool_client([long_k, "key2222"])
    my_token = generate_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/api/keys", headers={"Authorization": f"Bearer {my_token}"})
    assert resp.status_code == 200
    entries = resp.json()["keys"]
    long_entry = [e for e in entries if e["id"] == api_key_id(long_k)][0]
    assert long_entry["key"] == "sk-1234567…678901"


@pytest.mark.asyncio
async def test_update_config_zdr_live_headers_persists_and_preserves_client(panel_env):
    """PUT false changes live headers (no x-cmd-zdr) and persists lowercase, PUT true restores."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import get_client, get_config, init as state_init
    from cc_adapter.command_code.headers import make_cc_headers

    prev_cfg, prev_client = get_config(), get_client()
    cfg = AppConfig(cc_api_key="sk-test-key", zdr=True)
    client_inst = CommandCodeClient(base_url="https://api.example.com", api_key="sk-test-key")
    state_init(cfg, client_inst)
    my_token = generate_token()

    try:
        # Default is zdr=True
        headers = make_cc_headers(api_key="sk-test-key")
        assert headers.get("x-cmd-zdr") == "1"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. GET /config returns effective zdr=True
            get_resp = await client.get("/admin/api/config", headers={"Authorization": f"Bearer {my_token}"})
            assert get_resp.status_code == 200
            assert get_resp.json()["zdr"] is True

            # 2. PUT /config with zdr=False
            put_resp = await client.put(
                "/admin/api/config", json={"zdr": False}, headers={"Authorization": f"Bearer {my_token}"}
            )
            assert put_resp.status_code == 200
            assert put_resp.json()["zdr"] is False

            # Client identity unchanged (no rebuild)
            assert get_client() is client_inst
            # Live headers immediately reflect disabled ZDR
            headers_disabled = make_cc_headers(api_key="sk-test-key")
            assert "x-cmd-zdr" not in headers_disabled

            # Persisted in lowercase
            env_content = panel_env.read_text()
            assert "CC_ADAPTER_ZDR=false" in env_content

            # Reloaded AppConfig respects it
            reloaded_cfg = AppConfig(_env_file=str(panel_env))
            assert reloaded_cfg.zdr is False

            # 3. PUT /config with zdr=True restores header and lowercase persistence
            put_resp2 = await client.put(
                "/admin/api/config", json={"zdr": True}, headers={"Authorization": f"Bearer {my_token}"}
            )
            assert put_resp2.status_code == 200
            assert put_resp2.json()["zdr"] is True

            assert get_client() is client_inst
            headers_restored = make_cc_headers(api_key="sk-test-key")
            assert headers_restored.get("x-cmd-zdr") == "1"
            assert "CC_ADAPTER_ZDR=true" in panel_env.read_text()
    finally:
        state_init(prev_cfg, prev_client)
        await client_inst.aclose()


def test_admin_js_config_form_exposes_the_zdr_select():
    """Static guard: ZDR toggle is offered on config form and wired through load/save."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    assert '<select id="cfg-zdr">' in src
    assert '<option value="true">${t("zdrEnabled")}</option>' in src
    assert '<option value="false">${t("zdrDisabled")}</option>' in src
    assert 'document.getElementById("cfg-zdr").value = (zdr !== false) ? "true" : "false";' in src
    assert 'const zdrVal = document.getElementById("cfg-zdr").value === "true";' in src
    assert "if (zdrVal !== curZdr) body.zdr = zdrVal;" in src
    for key in ("zdrLabel", "zdrEnabled", "zdrDisabled", "zdrHint"):
        assert src.count(f"{key}:") == 2


def test_admin_js_keys_tab_uses_safe_id_with_suffix_fallback():
    """Static guard: Keys tab uses item.id for actions and dataset, with suffix fallback only for older servers."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    assert "function keyIdentifier(item)" in src
    assert "if (item && item.id) return item.id;" in src
    assert "row.dataset.id = id;" in src
    assert "toggleKey(id, !on, row)" in src
    assert 'deleteKey(id, item.key || "", row)' in src
    assert "keyIdentifier(k) === id" in src


def test_admin_js_build_key_row_state_and_badge_matrix():
    """Execute the actual pure helper to verify switch state and badge priority."""
    import re
    import shutil
    import subprocess
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "cc_adapter" / "admin" / "static" / "admin.js").read_text()
    helper = re.search(r"^function keyVisualState\(item\) \{.*?^\}", src, flags=re.MULTILINE | re.DOTALL)
    assert helper is not None
    helper_src = helper.group(0)
    assert 'const on = unmanaged ? enabled : (!manualOff && state === "ok");' in helper_src
    assert "item.manual === true || !enabled" in helper_src
    assert "} else if (manualOff) {" in helper_src
    assert '} else if (state === "cooling") {' in helper_src
    assert '} else if (state === "disabled") {' in helper_src

    if shutil.which("node"):
        js_code = (
            helper_src
            + """
        const stateMatrix = [
          // [item, expectedOn, expectedBadgeKey]
          [{ state: "unmanaged", enabled: true, manual: false }, true, "keyStateUnmanaged"],
          [{ state: "unmanaged", enabled: false, manual: false }, false, "keyStateUnmanaged"],
          [{ state: "ok", manual: true, enabled: false }, false, "keyStateOff"],
          [{ state: "cooling", manual: true, enabled: false }, false, "keyStateOff"],
          [{ state: "disabled", manual: true, enabled: false }, false, "keyStateOff"],
          [{ state: "cooling", manual: false, enabled: true }, false, "keyStateCooling"],
          [{ state: "disabled", manual: false, enabled: true }, false, "keyStateDisabled"],
          [{ state: "ok", manual: false, enabled: true }, true, "keyStateOk"],
          [{ state: "ok", manual: false, enabled: false }, false, "keyStateOff"],
        ];

        for (const [item, expOn, expBadge] of stateMatrix) {
          const res = keyVisualState(item);
          if (res.on !== expOn || res.badgeKey !== expBadge) {
            console.error(JSON.stringify({ item, res, expOn, expBadge }));
            process.exit(1);
          }
        }
        console.log("OK");
        """
        )
        proc = subprocess.run(["node", "-e", js_code], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node matrix check failed: {proc.stderr}"
        assert proc.stdout.strip() == "OK"

    assert 'if (reason === "invalid_key" || reason === "http_401") return t("keyReasonInvalidKey");' in src
    assert 'if (reason === "http_403") return t("keyReasonForbidden");' in src
    assert src.count("keyReasonForbidden:") == 2


@pytest.mark.asyncio
async def test_admin_daily_usage_endpoint_aggregates_all_keys(monkeypatch):
    """POST /admin/api/usage/daily aggregates multiple keys and uses local token stats."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import init as admin_state_init
    from cc_adapter.command_code.client import CommandCodeClient

    cfg = AppConfig()
    cfg.admin_password = "admin"
    cfg.cc_api_key = ["key-alpha-1111", "key-beta-2222"]
    client_inst = CommandCodeClient(base_url=cfg.cc_base_url, api_key="key-alpha-1111", api_keys=cfg.cc_api_key)
    admin_state_init(cfg, client_inst)

    async def fake_query_all(b_url, keys, start, end):
        assert keys == ["key-alpha-1111", "key-beta-2222"]
        return [
            {"date": "2026-03-01", "total_cost": 4.0, "total_count": 20},
            {"date": "2026-03-02", "total_cost": 6.0, "total_count": 30},
        ]

    monkeypatch.setattr("cc_adapter.admin.router.query_all_daily_usage", fake_query_all)
    # mock local tokens
    monkeypatch.setattr(
        "cc_adapter.admin.router.query_daily_tokens",
        lambda days: {
            "2026-03-01": {
                "tokens": 100,
                "models": {
                    "deepseek/v3": {"tokens": 60, "requests": 12},
                    "claude/sonnet": {"tokens": 40, "requests": 8},
                },
            },
            "2026-03-02": {
                "tokens": 200,
                "models": {
                    "deepseek/v3": {"tokens": 200, "requests": 30},
                },
            },
        },
    )

    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/admin/api/usage/daily",
            json={"start_date": "2026-03-01", "end_date": "2026-03-02"},
            headers={"Authorization": f"Bearer {my_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["daily"]) == 2
    day1 = data["daily"][0]
    assert day1["date"] == "2026-03-01"
    assert day1["total_cost"] == 4.0
    assert day1["total_count"] == 20
    # Day 1 models split: 60% of 4.0 = 2.4, 40% of 4.0 = 1.6
    assert len(day1["models"]) == 2
    assert day1["models"][0]["model_id"] == "deepseek/v3"
    assert day1["models"][0]["cost"] == 2.4
    assert day1["models"][1]["model_id"] == "claude/sonnet"
    assert day1["models"][1]["cost"] == 1.6

    day2 = data["daily"][1]
    assert day2["date"] == "2026-03-02"
    assert day2["total_cost"] == 6.0
    assert day2["models"][0]["cost"] == 6.0

    assert data["totals"]["total_cost"] == 10.0
    assert data["totals"]["total_count"] == 50


@pytest.mark.asyncio
async def test_put_config_invalid_cc_api_key_returns_400_without_side_effects(tmp_path, monkeypatch):
    """PUT /admin/api/config rejects invalid cc_api_key (400) without writing to disk or runtime."""
    from cc_adapter.core.auth import generate_token
    from cc_adapter.core.runtime import init as admin_state_init
    from cc_adapter.command_code.client import CommandCodeClient

    test_env = tmp_path / ".env"
    initial_content = 'CC_ADAPTER_CC_API_KEY=["valid-key-1111"]\nCC_ADAPTER_PORT=8080\n'
    test_env.write_text(initial_content)

    cfg = AppConfig()
    cfg.admin_password = "admin"
    cfg.cc_api_key = ["valid-key-1111"]
    client_inst = CommandCodeClient(base_url=cfg.cc_base_url, api_key="valid-key-1111", api_keys=cfg.cc_api_key)
    admin_state_init(cfg, client_inst)

    monkeypatch.setattr("cc_adapter.core.config.env_file_path", lambda: str(test_env))
    monkeypatch.setattr("cc_adapter.admin.config_manager.env_file_path", lambda: str(test_env))

    my_token = generate_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Invalid key with whitespace in list
        resp = await client.put(
            "/admin/api/config",
            json={"cc_api_key": ["valid-key-1111", "bad key with space"]},
            headers={"Authorization": f"Bearer {my_token}"},
        )
        assert resp.status_code == 400
        assert "Invalid cc_api_key" in resp.json()["detail"]

        # 2. Invalid empty string entry in list
        resp2 = await client.put(
            "/admin/api/config",
            json={"cc_api_key": [""]},
            headers={"Authorization": f"Bearer {my_token}"},
        )
        assert resp2.status_code == 400

    # Ensure disk file content was NOT changed
    assert test_env.read_text() == initial_content
    # Ensure runtime config was NOT modified
    assert cfg.cc_api_key == ["valid-key-1111"]


def test_docker_and_compose_configuration_static_guard():
    """Static guard for Dockerfile launcher & dynamic healthcheck, and docker-compose.yml grace period."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert 'CMD ["python", "-m", "cc_adapter"]' in dockerfile
    assert "port = c.AppConfig().port" in dockerfile
    assert "http://localhost:{port}/health" in dockerfile

    assert "stop_grace_period: 10m30s" in compose
    assert '"${CC_ADAPTER_PORT:-8080}:${CC_ADAPTER_PORT:-8080}"' in compose
    assert "CC_ADAPTER_PORT=${CC_ADAPTER_PORT:-8080}" in compose
