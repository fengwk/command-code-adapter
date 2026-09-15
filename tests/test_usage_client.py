import json
from datetime import date, timedelta

import httpx
import pytest
import respx

from cc_adapter.admin.usage_client import (
    query_token_usage,
    query_all_tokens,
    query_daily_usage,
    query_all_daily_usage,
)
from cc_adapter.providers.shared.session_extractor import process_identity


@pytest.fixture
def base_url():
    return "https://api.commandcode.ai"


@pytest.fixture
def api_key():
    return "test-api-key"


class TestQueryTokenUsage:
    @pytest.mark.asyncio
    async def test_success_with_all_data(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "name": "Test User",
                        "email": "test@example.com",
                        "org": {"id": "org_123"},
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 12.50,
                        "totalCount": 500,
                        "models": [
                            {"model": "deepseek-v4", "totalCost": 10.0, "count": 400},
                            {"model": "step-3.5", "totalCost": 2.5, "count": 100},
                        ],
                    },
                )
            )
            mock.get("/alpha/billing/credits", params={"orgId": "org_123"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "credits": {
                            "monthlyCredits": 1000,
                            "purchasedCredits": 500,
                            "freeCredits": 50,
                        }
                    },
                )
            )
            mock.get("/alpha/billing/subscriptions", params={"orgId": "org_123"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "planId": "individual-pro",
                            "status": "active",
                            "currentPeriodStart": "2025-01-01T00:00:00Z",
                            "currentPeriodEnd": "2025-02-01T00:00:00Z",
                        },
                    },
                )
            )

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is True
        assert result["user"]["email"] == "test@example.com"
        assert result["user"]["name"] == "Test User"
        assert result["usage"]["total_cost"] == 12.50
        assert result["usage"]["total_count"] == 500
        assert len(result["usage"]["models"]) == 2
        assert result["credits"]["monthly"] == 1000
        assert result["credits"]["purchased"] == 500
        assert result["credits"]["free"] == 50
        assert result["credits"]["total"] == 1550
        assert result["subscription"]["plan_id"] == "individual-pro"
        assert result["subscription"]["plan_name"] == "Pro"
        assert result["subscription"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_unauthorized_key(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is False
        assert result["error"] == "Invalid API key"

    @pytest.mark.asyncio
    async def test_result_masks_the_api_key(self, base_url):
        """The panel must never receive the full upstream key."""
        long_key = "user_abcdefghij0123456789ABCDEFGHIJ"
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

            result = await query_token_usage(base_url, long_key)

        assert result["token"] == long_key[:10] + "…" + long_key[-6:]
        assert long_key not in json.dumps(result)

    @pytest.mark.asyncio
    async def test_short_key_is_fully_hidden(self, base_url):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

            result = await query_token_usage(base_url, "test-api-key")

        assert result["token"] == "****-key"
        assert "test-api-key" not in json.dumps(result)

    @pytest.mark.asyncio
    async def test_whoami_network_error(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(side_effect=httpx.ConnectError("connection refused"))

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is False
        assert "Network error" in result["error"]
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_ok_without_org(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(200, json={"name": "User", "email": "u@e.com"}))
            mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(200, json={"totalCost": 0, "totalCount": 0})
            )
            mock.get("/alpha/billing/credits").mock(return_value=httpx.Response(200, json={"credits": {}}))
            mock.get("/alpha/billing/subscriptions").mock(
                return_value=httpx.Response(
                    200,
                    json={"success": False, "data": None},
                )
            )

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is True
        assert "subscription" not in result

    @pytest.mark.asyncio
    async def test_credits_and_subs_fail_gracefully(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(
                return_value=httpx.Response(
                    200,
                    json={"name": "U", "email": "u@e.com", "org": {"id": "o1"}},
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(200, json={"totalCost": 0, "totalCount": 0})
            )
            mock.get("/alpha/billing/credits", params={"orgId": "o1"}).mock(return_value=httpx.Response(500))
            mock.get("/alpha/billing/subscriptions", params={"orgId": "o1"}).mock(
                side_effect=httpx.ConnectError("down")
            )

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is True
        assert "credits" not in result
        assert "subscription" not in result

    @pytest.mark.asyncio
    async def test_usage_response_error(self, base_url, api_key):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(200, json={"name": "U", "email": "u@e.com"}))
            mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(500)
            )
            mock.get("/alpha/billing/credits").mock(return_value=httpx.Response(200, json={}))
            mock.get("/alpha/billing/subscriptions").mock(return_value=httpx.Response(200, json={}))

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is True
        assert "usage" not in result


class TestProcessIdentityHeaders:
    """Every authed call is signed like the real CLI signs it: same session id, same project."""

    @pytest.mark.asyncio
    async def test_whoami_usage_and_billing_carry_the_process_identity(self, base_url, api_key):
        identity = process_identity(api_key)
        with respx.mock(base_url=base_url) as mock:
            whoami = mock.get("/alpha/whoami").mock(
                return_value=httpx.Response(200, json={"name": "U", "email": "u@e.com", "org": {"id": "o1"}})
            )
            usage = mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(200, json={"totalCost": 1.0, "totalCount": 2})
            )
            credits = mock.get("/alpha/billing/credits", params={"orgId": "o1"}).mock(
                return_value=httpx.Response(200, json={"credits": {"monthlyCredits": 3}})
            )
            subscriptions = mock.get("/alpha/billing/subscriptions", params={"orgId": "o1"}).mock(
                return_value=httpx.Response(200, json={"success": True, "data": {"planId": "individual-go"}})
            )

            result = await query_token_usage(base_url, api_key)

        assert result["ok"] is True
        for route in (whoami, usage, credits, subscriptions):
            assert route.called, "every authed call of the CLI sends the session headers"
            headers = route.calls.last.request.headers
            assert headers["x-session-id"] == identity.session_id
            assert headers["x-project-slug"] == identity.project_slug
            assert headers["Authorization"] == f"Bearer {api_key}"
            # the CC header set replaces httpx's own defaults (no library fingerprint)
            assert headers["user-agent"] == "cli"
            assert headers["host"] == "api.commandcode.ai"

    @pytest.mark.asyncio
    async def test_every_key_gets_its_own_process_identity(self, base_url):
        keys = ["key-one", "key-two"]
        with respx.mock(base_url=base_url) as mock:
            whoami = mock.get("/alpha/whoami").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

            await query_all_tokens(base_url, keys)

        sent = {call.request.headers["x-session-id"] for call in whoami.calls}
        assert sent == {process_identity("key-one").session_id, process_identity("key-two").session_id}
        assert process_identity("key-one").session_id != process_identity("key-two").session_id

    @pytest.mark.asyncio
    async def test_daily_usage_queries_reuse_one_process_identity(self, base_url, api_key):
        """All snapshots of one report come from the same forged process, not one per call."""
        identity = process_identity(api_key)
        with respx.mock(base_url=base_url) as mock:
            route = mock.get("/alpha/usage/summary").mock(
                return_value=httpx.Response(200, json={"totalCost": 1.0, "totalCount": 2, "models": []})
            )

            await query_daily_usage(base_url, api_key, date(2025, 1, 1), date(2025, 1, 2))

        assert len(route.calls) > 1
        assert {call.request.headers["x-session-id"] for call in route.calls} == {identity.session_id}
        assert {call.request.headers["x-project-slug"] for call in route.calls} == {identity.project_slug}


class TestQueryAllTokens:
    @pytest.mark.asyncio
    async def test_multiple_keys(self, base_url):
        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/whoami").mock(return_value=httpx.Response(200, json={"name": "User", "email": "a@b.com"}))
            mock.get("/alpha/usage/summary").mock(
                return_value=httpx.Response(200, json={"totalCost": 0, "totalCount": 0})
            )
            mock.get("/alpha/billing/credits").mock(return_value=httpx.Response(200, json={}))
            mock.get("/alpha/billing/subscriptions").mock(return_value=httpx.Response(200, json={}))

            results = await query_all_tokens(base_url, ["key1", "key2", "key3"])

        assert len(results) == 3
        for r in results:
            assert r["ok"] is True


class TestQueryDailyUsage:
    @pytest.mark.asyncio
    async def test_daily_usage_two_days(self, base_url, api_key):
        start = date(2025, 1, 1)
        end = date(2025, 1, 2)

        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/usage/summary", params={"since": "2025-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 10.0,
                        "totalCount": 100,
                        "models": [{"model": "m1", "totalCost": 10.0, "count": 100}],
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "2025-01-02T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 18.0,
                        "totalCount": 180,
                        "models": [{"model": "m1", "totalCost": 18.0, "count": 180}],
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "2025-01-03T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 18.0,
                        "totalCount": 180,
                        "models": [{"model": "m1", "totalCost": 18.0, "count": 180}],
                    },
                )
            )

            results = await query_daily_usage(base_url, api_key, start, end)

        assert len(results) == 2
        assert results[0]["date"] == "2025-01-01"
        assert results[1]["date"] == "2025-01-02"

    @pytest.mark.asyncio
    async def test_daily_usage_handles_none_snapshots(self, base_url, api_key):
        start = date(2025, 1, 1)
        end = date(2025, 1, 1)

        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/usage/summary", params={"since": "2025-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(500)
            )
            mock.get("/alpha/usage/summary", params={"since": "2025-01-02T00:00:00Z"}).mock(
                return_value=httpx.Response(200, json={"totalCost": 5, "totalCount": 50})
            )

            results = await query_daily_usage(base_url, api_key, start, end)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_daily_usage_skips_day_when_next_snapshot_fails(self, base_url, api_key):
        start = date(2025, 1, 1)

        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/usage/summary", params={"since": "2025-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 10,
                        "totalCount": 100,
                        "models": [{"model": "m1", "totalCost": 10, "count": 100}],
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "2025-01-02T00:00:00Z"}).mock(
                return_value=httpx.Response(500)
            )

            results = await query_daily_usage(base_url, api_key, start, start)

        assert results == []

    @pytest.mark.asyncio
    async def test_daily_usage_uses_current_snapshot_when_tomorrow_is_unavailable(self, base_url, api_key):
        today = date.today()
        tomorrow = today + timedelta(days=1)

        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/usage/summary", params={"since": f"{today.isoformat()}T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 3,
                        "totalCount": 30,
                        "models": [{"model": "m1", "totalCost": 3, "count": 30}],
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": f"{tomorrow.isoformat()}T00:00:00Z"}).mock(
                return_value=httpx.Response(500)
            )

            results = await query_daily_usage(base_url, api_key, today, today)

        assert results[0]["total_cost"] == 3
        assert results[0]["total_count"] == 30

    @pytest.mark.asyncio
    async def test_daily_usage_zero_consumption(self, base_url, api_key):
        start = date(2025, 1, 1)
        end = date(2025, 1, 1)

        with respx.mock(base_url=base_url) as mock:
            mock.get("/alpha/usage/summary", params={"since": "2025-01-01T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 10,
                        "totalCount": 100,
                        "models": [{"model": "m1", "totalCost": 10, "count": 100}],
                    },
                )
            )
            mock.get("/alpha/usage/summary", params={"since": "2025-01-02T00:00:00Z"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "totalCost": 10,
                        "totalCount": 100,
                        "models": [{"model": "m1", "totalCost": 10, "count": 100}],
                    },
                )
            )

            results = await query_daily_usage(base_url, api_key, start, end)

        assert len(results) == 1
        assert results[0]["total_cost"] == 0
        assert results[0]["total_count"] == 0


@pytest.mark.asyncio
async def test_query_usage_extracts_limits():
    with respx.mock(base_url="https://api.commandcode.ai") as mock:
        mock.get("/alpha/whoami").mock(return_value=httpx.Response(200, json={"name": "U", "email": "u@e.com"}))
        mock.get("/alpha/usage/summary", params={"since": "1970-01-01T00:00:00Z"}).mock(
            return_value=httpx.Response(200, json={"totalCost": 5.0, "totalCount": 10, "models": []})
        )
        mock.get("/alpha/billing/credits").mock(
            return_value=httpx.Response(
                200,
                json={
                    "windowLimits": {
                        "limited": True,
                        "fiveHour": {"used": 42, "cap": 100, "resetAt": 1720000000000},
                        "weekly": {"used": 150, "cap": 500, "resetAt": 1720600000000},
                    }
                },
            )
        )
        mock.get("/alpha/billing/subscriptions").mock(return_value=httpx.Response(200, json={}))

        result = await query_token_usage("https://api.commandcode.ai", "test-key")

    assert result["ok"] is True
    assert result["usage"]["limited"] is False  # neither window at cap
    assert result["usage"]["fiveHour"]["used"] == 42
    assert result["usage"]["fiveHour"]["cap"] == 100
    assert result["usage"]["weekly"]["used"] == 150
    assert result["usage"]["weekly"]["cap"] == 500


@pytest.mark.asyncio
class TestQueryAllDailyUsage:
    async def test_empty_keys_returns_empty(self, base_url):
        res = await query_all_daily_usage(base_url, [], date(2026, 3, 1), date(2026, 3, 2))
        assert res == []

    async def test_aggregates_multiple_keys_by_date(self, monkeypatch, base_url):
        k1 = "key-alpha-1111"
        k2 = "key-beta-2222"

        async def fake_query_daily_usage(b_url, key, s_date, e_date, timeout=30.0):
            if key == k1:
                return [
                    {"date": "2026-03-01", "total_cost": 1.25, "total_count": 10},
                    {"date": "2026-03-02", "total_cost": 2.0, "total_count": 20},
                ]
            elif key == k2:
                return [
                    {"date": "2026-03-01", "total_cost": 0.75, "total_count": 5},
                    {"date": "2026-03-02", "total_cost": 1.5, "total_count": 10},
                ]
            return []

        monkeypatch.setattr("cc_adapter.admin.usage_client.query_daily_usage", fake_query_daily_usage)

        res = await query_all_daily_usage(base_url, [k1, k2], date(2026, 3, 1), date(2026, 3, 2))
        assert len(res) == 2
        assert res[0] == {"date": "2026-03-01", "total_cost": 2.0, "total_count": 15}
        assert res[1] == {"date": "2026-03-02", "total_cost": 3.5, "total_count": 30}

    async def test_deduplicates_keys_without_double_querying(self, monkeypatch, base_url):
        k1 = "key-alpha-1111"
        queried = []

        async def fake_query_daily_usage(b_url, key, s_date, e_date, timeout=30.0):
            queried.append(key)
            return [{"date": "2026-03-01", "total_cost": 1.0, "total_count": 10}]

        monkeypatch.setattr("cc_adapter.admin.usage_client.query_daily_usage", fake_query_daily_usage)

        res = await query_all_daily_usage(base_url, [k1, k1, k1], date(2026, 3, 1), date(2026, 3, 1))
        assert queried == [k1]
        assert len(res) == 1
        assert res[0]["total_cost"] == 1.0

    async def test_partial_failure_preserves_successful_keys(self, monkeypatch, base_url):
        k1 = "key-alpha-1111"
        k2 = "key-beta-2222"

        async def fake_query_daily_usage(b_url, key, s_date, e_date, timeout=30.0):
            if key == k1:
                return [{"date": "2026-03-01", "total_cost": 1.5, "total_count": 10}]
            raise RuntimeError("upstream timeout")

        monkeypatch.setattr("cc_adapter.admin.usage_client.query_daily_usage", fake_query_daily_usage)

        res = await query_all_daily_usage(base_url, [k1, k2], date(2026, 3, 1), date(2026, 3, 1))
        assert len(res) == 1
        assert res[0] == {"date": "2026-03-01", "total_cost": 1.5, "total_count": 10}
