"""Credits-aware key scheduler with sticky session affinity.

Adds four behaviours on top of the previous plain ``KeyPool`` precedence list:

* per-key health (``ok`` / ``cooling`` / ``disabled``): rate limits escalate
  ``KEY_COOLDOWN_BASE`` → ``KEY_COOLDOWN_MAX``, an out-of-credits key is parked
  for a flat ``KEY_CREDIT_COOLDOWN`` (30 min) with its cached balance zeroed;
* credits-aware usability (a key with known zero credits is not usable);
* round-robin bindings for explicit session identities, sticky for as long as
  the session keeps talking (sliding TTL), so every turn of one conversation
  stays on the same upstream account;
* fill-first selection (first usable key) for requests without an explicit
  session identity;
* a manual per-key on/off switch for the admin panel (``disable()`` /
  ``enable()``): an off key is never selected regardless of its credits or
  health, and turning it back on clears the automatic health/credit marks so the
  key is usable immediately. Automatic cooldowns keep running independently of
  the manual switch.

``select()`` blocks only on the very first credits fetch; later calls use the
currently known state and refresh the credits cache in the background.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import structlog

from cc_adapter.command_code.headers import make_cc_headers
from cc_adapter.core.constants import (
    KEY_COOLDOWN_BASE,
    KEY_COOLDOWN_MAX,
    KEY_CREDIT_COOLDOWN,
    KEY_CREDITS_CACHE_TTL,
    KEY_CREDITS_ERROR_BACKOFF,
    SESSION_AFFINITY_MAX_ENTRIES,
    SESSION_AFFINITY_TTL,
)

logger = structlog.get_logger(__name__)

STATE_OK = "ok"
STATE_COOLING = "cooling"
STATE_DISABLED = "disabled"


def _reason_text(reason: str | None, status: int | None) -> str | None:
    if reason:
        return reason
    return f"http_{status}" if status is not None else None


def _format_remaining(seconds: float) -> str:
    """Compact remaining-cooldown text for logs and error messages."""
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


class SessionAffinityCache:
    """``session_flag -> key`` bindings with sliding TTL and LRU eviction."""

    def __init__(self, ttl: float, max_entries: int):
        self._ttl = float(ttl)
        self._max_entries = int(max_entries)
        self._entries: dict[str, tuple[str, float]] = {}

    def get_and_refresh(self, sid: str) -> str | None:
        """Return the bound key, renewing the sliding TTL, or None if unbound/expired."""
        entry = self._entries.get(sid)
        if entry is None:
            return None
        key, last_seen = entry
        now = time.monotonic()
        if now - last_seen > self._ttl:
            self._entries.pop(sid, None)
            return None
        # Re-insert last so a hit also counts as the most recently used entry.
        self._entries.pop(sid, None)
        self._entries[sid] = (key, now)
        return key

    def set(self, sid: str, key: str) -> None:
        self._entries.pop(sid, None)
        self._entries[sid] = (key, time.monotonic())
        while len(self._entries) > self._max_entries:
            self._entries.pop(next(iter(self._entries)), None)

    def compare_and_delete(self, sid: str | None, expected_key: str) -> bool:
        """Unbind sid only while it still points at expected_key."""
        if sid is None:
            return False
        entry = self._entries.get(sid)
        if entry is None or entry[0] != expected_key:
            return False
        self._entries.pop(sid, None)
        return True

    def delete_by_key(self, key: str) -> int:
        """Unbind every session pointing at key; returns the number of sessions."""
        sids = [sid for sid, (bound, _) in self._entries.items() if bound == key]
        for sid in sids:
            self._entries.pop(sid, None)
        return len(sids)

    def clear(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        return count

    def stats(self) -> dict:
        bound_by_key: dict[str, int] = {}
        for bound_key, _ in self._entries.values():
            bound_by_key[bound_key] = bound_by_key.get(bound_key, 0) + 1
        return {"entries": len(self._entries), "bound_by_key": bound_by_key}


class KeyScheduler:
    def __init__(
        self,
        keys: list[str],
        base_url: str,
        *,
        cooldown_base: float = KEY_COOLDOWN_BASE,
        cooldown_max: float = KEY_COOLDOWN_MAX,
        credit_cooldown: float = KEY_CREDIT_COOLDOWN,
    ):
        self._keys = list(keys)
        self._base_url = base_url.rstrip("/")
        self._cooldown_base = float(cooldown_base)
        self._cooldown_max = float(cooldown_max)
        self._credit_cooldown = float(credit_cooldown)
        self._credits: dict[str, int] = {}
        self._last_fetch: float | None = None
        self._last_error: str | None = None
        self._last_failure: dict[str, Any] | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._fetch_lock = asyncio.Lock()

        self._state: dict[str, str] = {}
        self._until: dict[str, float] = {}
        self._reason: dict[str, str | None] = {}
        self._failures: dict[str, int] = {}
        self._manual_off: set[str] = set()
        self._cursor_key: str | None = None
        self._affinity = SessionAffinityCache(SESSION_AFFINITY_TTL, SESSION_AFFINITY_MAX_ENTRIES)

    # ------------------------------------------------------------------ select

    async def select(self, session_flag: str | None, *, explicit: bool, exclude: set[str] | None = None) -> str | None:
        await self._ensure_credits()
        skip = exclude or set()

        usable = [key for key in self._keys if key not in skip and self._usable(key)]
        if not usable:
            # Nothing can serve the request (every key is cooling, disabled or out of
            # credits). Fail fast: the caller reports `last_failure()` instead of
            # burning another upstream call on a key known to be unusable.
            return None

        if explicit and session_flag:
            bound = self._affinity.get_and_refresh(session_flag)
            if bound is not None and bound in usable:
                logger.info("key.select", session=session_flag[:8], key=bound[-4:], reason="sticky")
                return bound
            chosen = self._next_round_robin(usable)
            self._affinity.set(session_flag, chosen)
            logger.info("key.bind", session=session_flag[:8], key=chosen[-4:])
            return chosen

        chosen = usable[0]
        logger.info("key.select", key=chosen[-4:], reason="no-session")
        return chosen

    def _next_round_robin(self, candidates: list[str]) -> str:
        """First candidate after the cursor in configured order (ring semantics).

        Walking the configured ring instead of the filtered candidate list keeps
        the rotation stable no matter how the candidate set is filtered, so
        filtering never skews selection towards the head of the list.
        """
        allowed = set(candidates)
        start = 0
        if self._cursor_key in self._keys:
            start = self._keys.index(self._cursor_key) + 1
        for offset in range(len(self._keys)):
            key = self._keys[(start + offset) % len(self._keys)]
            if key in allowed:
                self._cursor_key = key
                return key
        self._cursor_key = candidates[0]
        return candidates[0]

    # ------------------------------------------------------------------ report

    def report(
        self,
        key: str,
        *,
        ok: bool,
        status: int | None = None,
        reason: str | None = None,
        session_flag: str | None = None,
        detail: str | None = None,
    ) -> None:
        if ok:
            self._clear_health(key)
            return

        self._last_failure = {
            "key": key,
            "status": status,
            "reason": _reason_text(reason, status),
            "detail": (detail or "")[:300] or None,
            "at": time.monotonic(),
        }

        if status in (401, 403) or reason == "invalid_key":
            self._state[key] = STATE_DISABLED
            self._until.pop(key, None)
            self._reason[key] = _reason_text(reason, status)
            unbound = self._affinity.delete_by_key(key)
            logger.info("key.disabled", key=key[-4:], status=status, reason=self._reason[key], sessions=unbound)
            return

        if status in (402, 429) or reason == "insufficient_credits":
            failures = self._failures.get(key, 0) + 1
            self._failures[key] = failures
            if reason == "insufficient_credits" or status == 402:
                # Out of credits: no request can succeed until the account is topped up,
                # so park the key for a fixed window instead of probing it every minute.
                # The credits refresh (30 min TTL) replaces the zero mark once the
                # balance recovers; POST /admin/api/keys/{suffix}/enable clears it early.
                self._credits[key] = 0
                cooldown = self._credit_cooldown
            else:
                cooldown = min(self._cooldown_base * 2 ** (failures - 1), self._cooldown_max)
            self._state[key] = STATE_COOLING
            self._until[key] = time.monotonic() + cooldown
            self._reason[key] = _reason_text(reason, status)
            unbound = self._affinity.compare_and_delete(session_flag, key)
            logger.info(
                "key.cooldown",
                key=key[-4:],
                status=status,
                reason=self._reason[key],
                failures=failures,
                cooldown=cooldown,
                unbound=unbound,
            )
            return

        # Transient failure (5xx, timeout, cancellation): keep the key in rotation.

    # ------------------------------------------------------------- health state

    def _health(self, key: str) -> str:
        """Effective state; an expired cooling window puts the key back to ok."""
        if self._state.get(key) == STATE_COOLING:
            until = self._until.get(key)
            if until is not None and until <= time.monotonic():
                self._state[key] = STATE_OK
                self._until.pop(key, None)
                self._reason.pop(key, None)
        return self._state.get(key, STATE_OK)

    def _usable(self, key: str) -> bool:
        if key in self._manual_off:
            return False
        if self._health(key) != STATE_OK:
            return False
        credits = self._credits.get(key)
        return credits is None or credits > 0

    def _clear_health(self, key: str) -> None:
        self._state[key] = STATE_OK
        self._until.pop(key, None)
        self._reason.pop(key, None)
        self._failures.pop(key, None)

    def key_state(self, key: str) -> dict:
        state = self._health(key)
        until = self._until.get(key)
        manual_off = key in self._manual_off
        return {
            "state": state,
            "until": until,
            "cooldown_seconds": max(0.0, until - time.monotonic()) if until is not None else None,
            "reason": self._reason.get(key),
            "credits": self._credits.get(key),
            "failures": self._failures.get(key, 0),
            "sessions": self._affinity.stats()["bound_by_key"].get(key, 0),
            "enabled": not manual_off,
            "manual": manual_off,
        }

    def states(self) -> list[dict]:
        return [self.key_state(key) for key in self._keys]

    def key_labels(self) -> list[str]:
        """Masked key suffixes in configured order (admin display)."""
        return [f"****{key[-4:]}" for key in self._keys]

    def last_failure(self) -> dict[str, Any] | None:
        """Most recent key-level upstream failure, for error reporting."""
        return dict(self._last_failure) if self._last_failure else None

    def unavailable_summary(self) -> str:
        """One-line per-key state describing why no key can serve a request."""
        now = time.monotonic()
        parts: list[str] = []
        for key in self._keys:
            state = self.key_state(key)
            if state["manual"]:
                parts.append(f"****{key[-4:]} disabled by admin")
                continue
            detail = state["state"]
            if state["state"] == STATE_COOLING and state["until"] is not None:
                detail += f" {_format_remaining(state['until'] - now)} left"
            if state["reason"]:
                detail += f" ({state['reason']})"
            elif state["credits"] == 0:
                detail += " (out of credits)"
            parts.append(f"****{key[-4:]} {detail}")
        return f"no usable CC key: {len(self._keys)} configured [{'; '.join(parts)}]"

    def key_by_suffix(self, suffix: str) -> str | None:
        """Resolve a configured key from its last characters, None when ambiguous."""
        suffix = suffix.lstrip("*")
        matches = [key for key in self._keys if key.endswith(suffix)]
        return matches[0] if len(matches) == 1 else None

    def clear_sessions(self) -> int:
        return self._affinity.clear()

    def disable(self, key: str) -> int:
        """Take a key out of rotation until it is enabled again (admin switch).

        A manually disabled key is skipped by ``select()`` no matter how healthy
        it looks or how many credits it has, and its sessions are unbound so the
        next turn of every conversation moves to another key. Idempotent: a
        second call for the same key unbinds nothing and returns 0.
        """
        self._manual_off.add(key)
        unbound = self._affinity.delete_by_key(key)
        logger.info("key.admin_disabled", key=key[-4:], sessions=unbound)
        return unbound

    def enable(self, key: str) -> None:
        """Clear the manual off mark and the automatic health/credit marks."""
        self._manual_off.discard(key)
        self.reset_key(key)
        logger.info("key.admin_enabled", key=key[-4:])

    def reset_key(self, key: str) -> None:
        """Clear cooling/disabled health and the cached zero-credit mark.

        This is the ops escape hatch after topping an account up: dropping the
        cached credits makes the key selectable immediately, and the background
        refresh replaces it with the real balance.
        """
        self._clear_health(key)
        self._credits.pop(key, None)
        self._trigger_refresh()

    # ----------------------------------------------------------------- credits

    def get_credits(self, key: str) -> int | None:
        return self._credits.get(key)

    async def _ensure_credits(self) -> None:
        """Block on the first fetch only; afterwards refresh in the background."""
        if not self._keys or not self._is_stale():
            return
        if self._last_fetch is None:
            try:
                await self.refresh()
            except Exception:
                logger.warning("initial_credits_fetch_failed", exc_info=True)
        else:
            self._trigger_refresh()

    def _is_stale(self) -> bool:
        if self._last_fetch is None:
            return True
        ttl = KEY_CREDITS_ERROR_BACKOFF if self._last_error else KEY_CREDITS_CACHE_TTL
        return time.monotonic() - self._last_fetch > ttl

    def _trigger_refresh(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            if not self._fetch_task or self._fetch_task.done():
                self._fetch_task = loop.create_task(self.refresh())
        except RuntimeError:
            pass

    async def refresh(self) -> None:
        async with self._fetch_lock:
            await self._refresh()

    async def _refresh(self) -> None:
        self._last_error = None
        try:
            tasks = [self._fetch_credits(key) for key in self._keys]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = 0
            for key, result in zip(self._keys, results):
                if isinstance(result, Exception):
                    logger.warning("credits_fetch_failed", key=key[-4:], error=str(result))
                elif isinstance(result, int):
                    self._credits[key] = result
                    success_count += 1
            if success_count == 0 and self._keys:
                self._last_error = "All credit fetches failed"
            self._last_fetch = time.monotonic()
        except Exception as e:
            self._last_error = str(e)
            self._last_fetch = time.monotonic()
            logger.warning("credits_refresh_failed", error=str(e))

    async def _fetch_credits(self, api_key: str) -> int | None:
        headers = make_cc_headers(api_key)
        async with httpx.AsyncClient(timeout=10.0, base_url=self._base_url) as client:
            r = await client.get("/alpha/billing/credits", headers=headers)
            r.raise_for_status()
            data = r.json()
            if "credits" in data:
                c = data["credits"]
                return c.get("monthlyCredits", 0) + c.get("purchasedCredits", 0) + c.get("freeCredits", 0)
            return 0

    @property
    def last_fetch_time(self) -> float | None:
        return self._last_fetch

    @property
    def last_error(self) -> str | None:
        return self._last_error
