from __future__ import annotations

import asyncio
import structlog
from datetime import date as date_type, timedelta
from typing import Any

import httpx

from cc_adapter.command_code.headers import make_cc_headers
from cc_adapter.core.utils import mask_api_key, normalize_api_keys
from cc_adapter.providers.shared.session_extractor import process_identity

logger = structlog.get_logger(__name__)

CC_BASE_PATH = "/alpha"

PLAN_NAMES = {
    "individual-go": "Go",
    "individual-pro": "Pro",
    "individual-max": "Max",
    "individual-ultra": "Ultra",
    "teams-pro": "Teams Pro",
}


async def query_token_usage(base_url: str, api_key: str, timeout: float = 15.0) -> dict:
    # The real CLI signs whoami/usage/billing with the same per-process session id as
    # its generate calls, so these carry x-session-id and x-project-slug too.
    headers = make_cc_headers(api_key, identity=process_identity(api_key), base_url=base_url)

    result: dict = {"token": mask_api_key(api_key), "label": "", "ok": False, "error": None}

    async with httpx.AsyncClient(timeout=timeout, base_url=base_url) as client:
        try:
            whoami_task = client.get(f"{CC_BASE_PATH}/whoami", headers=headers)
            usage_task = client.get(
                f"{CC_BASE_PATH}/usage/summary",
                headers=headers,
                params={"since": "1970-01-01T00:00:00Z"},
            )
            who_resp, usage_resp = await asyncio.gather(whoami_task, usage_task, return_exceptions=True)

            if isinstance(who_resp, Exception):
                result["error"] = f"Network error: {who_resp}"
                return result

            if who_resp.status_code == 401:
                result["error"] = "Invalid API key"
                return result
            who_resp.raise_for_status()
            who_data = who_resp.json()
            result["user"] = {
                "name": who_data.get("name", ""),
                "email": who_data.get("email", ""),
            }
            org_id = (who_data.get("org") or {}).get("id")

            params: dict[str, str] = {}
            if org_id:
                params["orgId"] = org_id

            async def get_json(path: str, p: dict | None = None) -> dict | None:
                try:
                    r = await client.get(path, headers=headers, params=p or params)
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    logger.warning("Usage query failed for %s: %s", path, e)
                    return None

            credits_data, sub_data = await asyncio.gather(
                get_json(f"{CC_BASE_PATH}/billing/credits"),
                get_json(f"{CC_BASE_PATH}/billing/subscriptions"),
            )

            if credits_data and "credits" in credits_data:
                c = credits_data["credits"]
                result["credits"] = {
                    "monthly": c.get("monthlyCredits", 0),
                    "purchased": c.get("purchasedCredits", 0),
                    "free": c.get("freeCredits", 0),
                    "total": c.get("monthlyCredits", 0) + c.get("purchasedCredits", 0) + c.get("freeCredits", 0),
                }

            if sub_data and sub_data.get("success") and sub_data.get("data"):
                s = sub_data["data"]
                plan_id = s.get("planId", "")
                result["subscription"] = {
                    "plan_id": plan_id,
                    "plan_name": PLAN_NAMES.get(plan_id, plan_id),
                    "status": s.get("status", ""),
                    "period_start": s.get("currentPeriodStart", ""),
                    "period_end": s.get("currentPeriodEnd", ""),
                }

            if not isinstance(usage_resp, Exception) and usage_resp is not None and usage_resp.status_code < 400:
                window_limits = (credits_data or {}).get("windowLimits") or {}
                usage_data = usage_resp.json()
                five_hour = window_limits.get("fiveHour") or {}
                weekly = window_limits.get("weekly") or {}
                # ponytail: compute limited locally from individual windows;
                # upstream may report limited=true even when no window is at cap.
                five_hour_limited = (five_hour.get("cap") or 0) > 0 and (five_hour.get("used") or 0) >= (
                    five_hour.get("cap") or 0
                )
                weekly_limited = (weekly.get("cap") or 0) > 0 and (weekly.get("used") or 0) >= (weekly.get("cap") or 0)
                result["usage"] = {
                    "total_cost": usage_data.get("totalCost", 0),
                    "total_count": usage_data.get("totalCount", 0),
                    "limited": five_hour_limited or weekly_limited,
                    "fiveHour": (
                        {
                            "used": five_hour.get("used", 0),
                            "cap": five_hour.get("cap", 0),
                            "resetAt": five_hour.get("resetAt", 0),
                        }
                        if five_hour
                        else None
                    ),
                    "weekly": (
                        {
                            "used": weekly.get("used", 0),
                            "cap": weekly.get("cap", 0),
                            "resetAt": weekly.get("resetAt", 0),
                        }
                        if weekly
                        else None
                    ),
                    "models": [
                        {
                            "model_id": m.get("model", ""),
                            "total_cost": m.get("totalCost", 0),
                            "total_count": m.get("count", 0),
                        }
                        for m in usage_data.get("models", [])
                    ],
                }

            result["ok"] = True
            return result

        except httpx.RequestError as e:
            result["error"] = f"Network error: {e}"
            return result


async def query_all_tokens(base_url: str, api_keys: list[str]) -> list[dict]:
    tasks = [query_token_usage(base_url, key) for key in api_keys]
    return list(await asyncio.gather(*tasks))


def _fmt_since(d: date_type) -> str:
    return f"{d.isoformat()}T00:00:00Z"


async def _query_usage_since(client: httpx.AsyncClient, headers: dict[str, str], since: str) -> dict[str, Any] | None:
    params: dict[str, str] = {"since": since}
    try:
        r = await client.get(f"{CC_BASE_PATH}/usage/summary", headers=headers, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("Daily usage query failed for %s: %s", since, e)
        return None


def _sub_models(a: list[dict], b: list[dict]) -> list[dict]:
    b_map = {m["model_id"]: m for m in b}
    result = []
    for ma in a:
        mid = ma["model_id"]
        mb = b_map.get(mid, {"cost": 0, "count": 0})
        cost = round(max(0, ma["cost"] - mb["cost"]), 4)
        if cost < 0.005:
            continue
        result.append(
            {
                "model_id": mid,
                "cost": cost,
                "count": max(0, ma["count"] - mb["count"]),
            }
        )
    return result


async def query_daily_usage(
    base_url: str, api_key: str, start_date: date_type, end_date: date_type, timeout: float = 30.0
) -> list[dict[str, Any]]:
    headers = make_cc_headers(api_key, identity=process_identity(api_key), base_url=base_url)
    boundaries: list[date_type] = []
    current = start_date
    while current <= end_date:
        boundaries.append(current)
        current += timedelta(days=1)
    boundaries.append(current)

    async with httpx.AsyncClient(timeout=timeout, base_url=base_url) as client:
        snapshots = await asyncio.gather(*(_query_usage_since(client, headers, _fmt_since(b)) for b in boundaries))

    daily_results: list[dict[str, Any]] = []
    for i in range(len(boundaries) - 1):
        cur = snapshots[i]
        nxt = snapshots[i + 1]
        if cur is None or (nxt is None and boundaries[i] != date_type.today()):
            continue

        # ponytail: nxt can be None when boundary is a future date (e.g. end_date=today,
        # end_date+1=tomorrow). Use cur directly without subtraction.
        if nxt is not None:
            day_cost = round(max(0, cur.get("totalCost", 0) - nxt.get("totalCost", 0)), 4)
            day_count = max(0, cur.get("totalCount", 0) - nxt.get("totalCount", 0))
            cur_models = [
                {"model_id": m.get("model", ""), "cost": m.get("totalCost", 0), "count": m.get("count", 0)}
                for m in cur.get("models", [])
            ]
            nxt_models = [
                {"model_id": m.get("model", ""), "cost": m.get("totalCost", 0), "count": m.get("count", 0)}
                for m in nxt.get("models", [])
            ]
            models = _sub_models(cur_models, nxt_models)
        else:
            day_cost = cur.get("totalCost", 0)
            day_count = cur.get("totalCount", 0)
            models = [
                {"model_id": m.get("model", ""), "cost": m.get("totalCost", 0), "count": m.get("count", 0)}
                for m in cur.get("models", [])
            ]

        daily_results.append(
            {
                "date": boundaries[i].isoformat(),
                "total_cost": day_cost,
                "total_count": day_count,
                "models": models,
            }
        )

    return daily_results


async def query_all_daily_usage(
    base_url: str,
    api_keys: list[str],
    start_date: date_type,
    end_date: date_type,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Query daily usage for all unique keys concurrently and aggregate by date.

    Results are aggregated across all keys per date with costs rounded to 4 decimal places,
    sorted stably by date. If any key query fails, other keys' results are preserved.
    """
    keys = normalize_api_keys(api_keys)
    if not keys:
        return []

    results = await asyncio.gather(
        *(query_daily_usage(base_url, key, start_date, end_date, timeout=timeout) for key in keys),
        return_exceptions=True,
    )

    by_date: dict[str, dict[str, Any]] = {}
    for res in results:
        if isinstance(res, Exception):
            logger.warning("query_all_daily_usage.key_failed", error=str(res))
            continue
        for entry in res:
            date_key = entry["date"]
            if date_key not in by_date:
                by_date[date_key] = {"date": date_key, "total_cost": 0.0, "total_count": 0}
            by_date[date_key]["total_cost"] += float(entry.get("total_cost", 0.0))
            by_date[date_key]["total_count"] += int(entry.get("total_count", 0))

    aggregated = [
        {
            "date": d_str,
            "total_cost": round(data["total_cost"], 4),
            "total_count": data["total_count"],
        }
        for d_str, data in sorted(by_date.items(), key=lambda x: x[0])
    ]
    return aggregated
