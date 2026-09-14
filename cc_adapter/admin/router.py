from __future__ import annotations

import re
import structlog
import time
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from cc_adapter.core.auth import generate_token, validate_token
from cc_adapter.core.runtime import (
    get_config,
    get_provider_map,
    get_reasoning_efforts,
    get_model_fetcher,
    force_refresh_models,
)
from cc_adapter.core.token_recorder import query_daily_tokens
from cc_adapter.core.config import DEFAULT_MODEL
from cc_adapter.core.constants import DEFAULT_DISTRIBUTION, VERSION
from cc_adapter.command_code.body import make_cc_body, make_config
from cc_adapter.admin.config_manager import ConfigManager
from cc_adapter.admin.usage_client import query_all_tokens, query_daily_usage
from cc_adapter.core.utils import api_key_id, mask_api_key, normalize_api_keys
from cc_adapter.core import log_buffer

router = APIRouter(prefix="/admin/api")
logger = structlog.get_logger(__name__)
_start_time = time.time()


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


class ConfigUpdate(BaseModel):
    cc_api_key: str | None = None
    cc_base_url: str | None = None
    host: str | None = None
    port: int | None = None
    log_level: str | None = None
    log_format: str | None = None
    default_model: str | None = None
    distribution: str | None = None
    zdr: bool | None = None


async def verify_auth(authorization: str | None = Header(None)):
    cfg = get_config()
    if not cfg or not cfg.admin_password:
        # No admin password configured: the panel runs unauthenticated
        # (intranet-only deployments). Matches README "leave blank for no auth".
        return True
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("auth.failed", reason="missing_or_malformed_auth_header")
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization[7:]
    if not validate_token(token):
        logger.warning("auth.failed", reason="invalid_admin_token")
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@router.post("/login")
async def login(req: LoginRequest):
    cfg = get_config()
    if not cfg or not cfg.admin_password:
        raise HTTPException(status_code=503, detail="Admin password is not configured")
    if req.password != cfg.admin_password:
        logger.warning("admin.login.failed", reason="invalid_password")
        raise HTTPException(status_code=401, detail="Invalid password")
    token = generate_token()
    return LoginResponse(token=token)


def _effective_distribution(cfg) -> str:
    """The mode that is actually in force: the live scheduler's, else the stored config.

    The scheduler owns the value once it exists (the panel switches it in place), and a
    single-key pool has no scheduler, so there the config file is the source of truth.
    """
    from cc_adapter.core.runtime import get_client

    scheduler = getattr(get_client(), "scheduler", None)
    if scheduler is not None:
        return scheduler.distribution
    return cfg.distribution if cfg else DEFAULT_DISTRIBUTION


@router.get("/config")
async def get_config_endpoint(_=Depends(verify_auth)):
    cfg = get_config()
    return {
        # The key pool is managed by the Keys tab; this stays a masked summary (never a real key)
        # and the count is exposed separately so the UI does not have to parse it.
        "cc_api_key": f"{len(cfg.cc_api_key)} key(s) configured" if cfg and cfg.cc_api_key else "",
        "cc_api_key_count": len(cfg.cc_api_key) if cfg else 0,
        "cc_base_url": cfg.cc_base_url if cfg else "",
        "host": cfg.host if cfg else "",
        "port": cfg.port if cfg else 8080,
        "log_level": cfg.log_level if cfg else "INFO",
        "log_format": cfg.log_format if cfg else "console",
        "admin_password_configured": bool(cfg and cfg.admin_password),
        "default_model": cfg.default_model if cfg else DEFAULT_MODEL,
        "distribution": _effective_distribution(cfg),
        "zdr": cfg.zdr if cfg is not None else True,
    }


@router.get("/ui-config")
async def ui_config():
    cfg = get_config()
    return {
        "default_model": cfg.default_model if cfg else DEFAULT_MODEL,
    }


_MODEL_DISPLAY_PREFIXES: dict[str, str] = {
    "deepseek-v4-": "DeepSeek V4 ",
    "kimi-k2-": "Kimi K2 ",
    "glm-": "GLM ",
    "minimax-m2-": "Minimax M2 ",
    "qwen-3-6-": "Qwen 3-6 ",
    "step-3-5-": "Step 3-5 ",
    "mimo-": "MiMo ",
}


def _format_model_display_name(bare_name: str) -> str:
    for prefix, replacement in _MODEL_DISPLAY_PREFIXES.items():
        if bare_name.startswith(prefix):
            suffix = bare_name[len(prefix) :]
            suffix = " ".join(word.capitalize() for word in suffix.split("-"))
            return replacement + suffix
    return bare_name.replace("-", " ").title()


@router.get("/models")
async def list_models():
    models = []
    for bare_name, canonical_id in get_provider_map().items():
        display_name = _format_model_display_name(bare_name)
        provider = canonical_id.split("/")[0]
        models.append(
            {
                "id": canonical_id,
                "name": display_name,
                "provider": provider,
            }
        )
    return {"models": models}


@router.get("/reasoning-effort")
async def get_reasoning_effort_config():
    return {
        "model_reasoning_efforts": get_reasoning_efforts(),
        "description": (
            "Per-model supported reasoning_effort levels. "
            "Values not in the list are clamped to the nearest higher level."
        ),
    }


@router.get("/models/status")
async def models_status():
    return get_model_fetcher().get_status()


@router.post("/models/refresh")
async def models_refresh(_=Depends(verify_auth)):
    try:
        await force_refresh_models()
        status = get_model_fetcher().get_status()
        return {"message": "Models refreshed", "status": status}
    except Exception as e:
        logger.error("admin.models_refresh.failed", error=str(e))
        raise HTTPException(status_code=500, detail="Model refresh failed, check server logs")


# GET /admin/api/config masks the pool as "<N> key(s) configured"; echoing it back would
# replace the whole key pool with that bogus value, so reject it before persisting anything.
_MASKED_KEY_SUMMARY_RE = re.compile(r"^\s*\d+\s+key\(s\)\s+configured\s*$", re.IGNORECASE)


@router.put("/config")
async def update_config(update: ConfigUpdate, _=Depends(verify_auth)):
    update_dict = update.model_dump(exclude_none=True)
    cc_api_key = update_dict.get("cc_api_key")
    if isinstance(cc_api_key, str) and _MASKED_KEY_SUMMARY_RE.match(cc_api_key):
        logger.warning("admin.config.rejected", reason="masked_summary")
        raise HTTPException(status_code=400, detail="cc_api_key must be a real key or omitted")
    ConfigManager.update_env_file(update_dict)
    await ConfigManager.apply_config_update(update_dict)
    return await get_config_endpoint()


def _key_scheduler():
    """Scheduler of the active client, or None when fewer than two keys are configured."""
    from cc_adapter.core.runtime import get_client

    return getattr(get_client(), "scheduler", None)


@router.get("/keys")
async def list_keys(_=Depends(verify_auth)):
    """Per-key scheduler state (credits, health, manual switch, bound sessions) for ops."""
    scheduler = _key_scheduler()
    if scheduler is None:
        cfg = get_config()
        keys = normalize_api_keys(cfg.cc_api_key) if cfg else []
        return {
            "keys": [
                {
                    "id": api_key_id(key),
                    "key": mask_api_key(key),
                    "state": "unmanaged",
                    "until": None,
                    "cooldown_seconds": None,
                    "reason": None,
                    "credits": None,
                    "failures": 0,
                    "sessions": 0,
                    "enabled": True,
                    "manual": False,
                }
                for key in keys
            ]
        }
    return {
        "keys": [
            {
                "id": api_key_id(key),
                "key": mask_api_key(key),
                **scheduler.key_state(key),
            }
            for key in scheduler.keys
        ]
    }


@router.delete("/sessions")
async def clear_sessions(_=Depends(verify_auth)):
    """Drop every session-to-key binding (forces fresh routing)."""
    scheduler = _key_scheduler()
    cleared = scheduler.clear_sessions() if scheduler is not None else 0
    logger.info("admin.sessions.cleared", cleared=cleared)
    return {"cleared": cleared}


def _scheduler_and_key(identifier: str):
    """Resolve the active scheduler and one of its keys by ID or unique suffix (404 otherwise)."""
    scheduler = _key_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=404, detail="No key scheduler is active")
    key = scheduler.key_by_identifier(identifier)
    if key is None:
        raise HTTPException(status_code=404, detail="Unknown or ambiguous key identifier")
    return scheduler, key


def _resolve_key_identifier(identifier: str) -> str:
    """Resolve one configured key from its ID or unique suffix (404 when unknown or ambiguous).

    The scheduler owns identifier resolution whenever it exists; a pool of a single key
    has no scheduler, so the live config list is used as the fallback there.
    """
    scheduler = _key_scheduler()
    if scheduler is not None:
        return _scheduler_and_key(identifier)[1]
    cfg = get_config()
    keys = normalize_api_keys(cfg.cc_api_key) if cfg else []
    for key in keys:
        if api_key_id(key) == identifier:
            return key
    suffix = identifier.lstrip("*")
    matches = [key for key in keys if key.endswith(suffix)]
    if len(matches) != 1:
        raise HTTPException(status_code=404, detail="Unknown or ambiguous key identifier")
    return matches[0]


async def _update_key_pool(keys: list[str]) -> None:
    """Persist the pool to the panel config file, then hot-apply it to the running process."""
    ConfigManager.update_env_file({"cc_api_key": keys})
    await ConfigManager.apply_config_update({"cc_api_key": keys})


@router.post("/keys/{identifier}/enable")
async def enable_key(identifier: str, _=Depends(verify_auth)):
    """Make one key selectable again: manual off + cooling/disabled + cached balance cleared."""
    scheduler, key = _scheduler_and_key(identifier)
    scheduler.enable(key)
    key_id = api_key_id(key)
    logger.info("admin.key.enabled", key_id=key_id)
    return {"id": key_id, "key": mask_api_key(key), **scheduler.key_state(key)}


@router.post("/keys/{identifier}/disable")
async def disable_key(identifier: str, _=Depends(verify_auth)):
    """Take one key out of rotation until it is enabled again."""
    scheduler, key = _scheduler_and_key(identifier)
    unbound = scheduler.disable(key)
    key_id = api_key_id(key)
    logger.info("admin.key.disabled", key_id=key_id, unbound_sessions=unbound)
    return {"id": key_id, "key": mask_api_key(key), "unbound_sessions": unbound, **scheduler.key_state(key)}


class KeyAddRequest(BaseModel):
    key: str


@router.post("/keys")
async def add_key(req: KeyAddRequest, _=Depends(verify_auth)):
    """Add one upstream key: persisted to the panel config file and selectable right away.

    A local key is a single token: reject pasted JSON arrays or line breaks instead of
    storing them as a bogus pool entry; use PUT /config for bulk edits.
    """
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key must not be empty")
    if any(char.isspace() for char in key):
        raise HTTPException(status_code=400, detail="Key must not contain whitespace")
    if len(key) > 512:
        raise HTTPException(status_code=400, detail="Key must not exceed 512 characters")
    cfg = get_config()
    if cfg is None:
        raise HTTPException(status_code=503, detail="Configuration is not available")
    keys = list(normalize_api_keys(cfg.cc_api_key))
    if key in keys:
        raise HTTPException(status_code=409, detail="Key already configured")
    keys.append(key)
    await _update_key_pool(keys)
    key_id = api_key_id(key)
    logger.info("admin.key.added", key_id=key_id, count=len(keys))
    return {"id": key_id, "key": mask_api_key(key), "count": len(keys)}


@router.delete("/keys/{identifier}")
async def remove_key(identifier: str, _=Depends(verify_auth)):
    """Remove one upstream key: its session bindings go away with it. The last key may go too."""
    cfg = get_config()
    if cfg is None:
        raise HTTPException(status_code=503, detail="Configuration is not available")
    key = _resolve_key_identifier(identifier)
    keys = [existing for existing in normalize_api_keys(cfg.cc_api_key) if existing != key]
    await _update_key_pool(keys)
    key_id = api_key_id(key)
    logger.info("admin.key.removed", key_id=key_id, count=len(keys))
    return {"id": key_id, "key": mask_api_key(key), "count": len(keys)}


@router.post("/verify-key")
async def verify_key(_=Depends(verify_auth)):
    cfg = get_config()
    keys = normalize_api_keys(cfg.cc_api_key) if cfg else []
    primary_key = keys[0] if keys else ""
    if not cfg or not primary_key:
        result = {"valid": False, "message": "No API Key configured"}
        logger.info("admin.verify_key", valid=result["valid"])
        return result
    from cc_adapter.core.runtime import create_client

    test_client = create_client(cfg, timeout=10.0)
    try:
        # Standard /alpha/generate shape (same config/params as a real request), so the probe
        # exercises the same body and key fingerprint as production traffic.
        test_body = make_cc_body(
            config=make_config(),
            params={
                "model": cfg.default_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 10,
                "stream": True,
            },
        )
        async for _ in test_client.generate(test_body):
            break
        result = {"valid": True, "message": "API Key is valid"}
    except Exception as e:
        msg = str(e)
        for k in keys:
            if k and k in msg:
                msg = msg.replace(k, mask_api_key(k))
        result = {"valid": False, "message": msg}
    finally:
        await test_client.aclose()
    logger.info("admin.verify_key", valid=result["valid"])
    return result


@router.post("/usage/query")
async def admin_usage_query(_=Depends(verify_auth)):
    cfg = get_config()
    if not cfg or not cfg.cc_api_key:
        return []
    results = await query_all_tokens(cfg.cc_base_url, cfg.cc_api_key)
    return results


@router.get("/token-usage")
async def token_usage(days: int = 365, _=Depends(verify_auth)):
    return query_daily_tokens(days)


class DailyUsageRequest(BaseModel):
    start_date: str
    end_date: str


@router.post("/usage/daily")
async def admin_daily_usage(req: DailyUsageRequest, _=Depends(verify_auth)):
    cfg = get_config()
    if not cfg or not cfg.cc_api_key:
        return {"daily": [], "totals": {"total_cost": 0, "total_count": 0, "models": []}}
    primary_key = normalize_api_keys(cfg.cc_api_key)
    if not primary_key:
        return {"daily": [], "totals": {"total_cost": 0, "total_count": 0, "models": []}}
    start = date_type.fromisoformat(req.start_date)
    end = date_type.fromisoformat(req.end_date)

    # ponytail: CC billing API no longer returns per-model breakdown.
    # Use local per-model token stats to proportionally split daily cost.
    daily_cc = await query_daily_usage(cfg.cc_base_url, primary_key[0], start, end)
    local = query_daily_tokens(days=365)

    daily_result: list[dict[str, Any]] = []
    for d in daily_cc:
        date_key = d["date"]
        day_cost = d["total_cost"]
        local_entry = local.get(date_key, {})
        local_models = local_entry.get("models", {})
        local_total_tokens = local_entry.get("tokens", 0)

        models: list[dict[str, Any]] = []
        if local_models and local_total_tokens > 0:
            for m_name, m_data in local_models.items():
                share = m_data["tokens"] / local_total_tokens
                models.append(
                    {
                        "model_id": m_name,
                        "cost": round(day_cost * share, 4),
                        "count": m_data["requests"],
                    }
                )
            # sort by cost desc
            models.sort(key=lambda x: x["cost"], reverse=True)

        daily_result.append(
            {
                "date": date_key,
                "total_cost": day_cost,
                "total_count": d["total_count"],
                "models": models,
            }
        )

    total_cost = sum(d["total_cost"] for d in daily_result)
    total_count = sum(d["total_count"] for d in daily_result)

    model_agg: dict[str, dict[str, object]] = {}
    for d in daily_result:
        for m in d.get("models", []):
            mid = m["model_id"]
            if mid not in model_agg:
                model_agg[mid] = {"model_id": mid, "cost": 0.0, "count": 0}
            model_agg[mid]["cost"] += m["cost"]
            model_agg[mid]["count"] += m["count"]

    models_list = sorted(model_agg.values(), key=lambda x: x["cost"], reverse=True)
    for m in models_list:
        m["pct"] = round((m["cost"] / total_cost * 100), 1) if total_cost > 0 else 0

    return {
        "daily": daily_result,
        "totals": {
            "total_cost": round(total_cost, 4),
            "total_count": total_count,
            "models": models_list,
        },
    }


@router.get("/health")
async def admin_health(_=Depends(verify_auth)):
    cfg = get_config()
    return {
        "status": "ok",
        "version": VERSION,
        "uptime": int(time.time() - _start_time),
        "cc_api_key_configured": bool(cfg and cfg.cc_api_key),
    }


@router.get("/logs")
async def get_logs(level: str = "INFO", search: str = "", limit: int = 200, _=Depends(verify_auth)):
    if limit < 1:
        limit = 200
    if limit > 500:
        limit = 500
    entries = log_buffer.get_entries(level=level, search=search, limit=limit)
    entries = [e for e in entries if e.get("path") != "/admin/api/logs"]
    return {"entries": entries, "total_in_buffer": log_buffer.buffer_size()}
