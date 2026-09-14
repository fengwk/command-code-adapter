"""Unit tests for cc_adapter.core.key_scheduler.

Credits fetching is always stubbed (`_fetch_credits` monkeypatched or the
`_credits`/`_last_fetch` snapshot seeded directly) so no HTTP happens.

Time-dependent behaviour (cooldown windows, affinity TTL) is driven by
rewriting the stored deadline/timestamp instead of patching `time.monotonic`,
which keeps the tests deterministic and free of arbitrary sleeps.
"""

import asyncio
import time

import pytest

from cc_adapter.core import key_scheduler as ks
from cc_adapter.core.constants import (
    KEY_COOLDOWN_BASE,
    KEY_COOLDOWN_MAX,
    KEY_CREDIT_COOLDOWN,
    KEY_CREDITS_CACHE_TTL,
    KEY_CREDITS_ERROR_BACKOFF,
    SESSION_AFFINITY_TTL,
)
from cc_adapter.core.key_scheduler import KeyScheduler, SessionAffinityCache

BASE_URL = "https://api.example.com"
K1, K2, K3 = "cc-key-alpha-1111", "cc-key-beta-2222", "cc-key-gamma-3333"


def make_scheduler(keys: list[str], credits: dict[str, int] | None = None) -> KeyScheduler:
    """Scheduler with a fresh credits snapshot, so select() never blocks on a fetch."""
    sched = KeyScheduler(keys=keys, base_url=BASE_URL)
    if credits is not None:
        sched._credits.update(credits)
    sched._last_fetch = time.monotonic()
    return sched


def stub_credits(monkeypatch, values: dict[str, object], calls: list[str] | None = None) -> None:
    """Replace the HTTP fetch with an in-memory table ({key: credits | Exception})."""

    async def fake_fetch(self, api_key):
        if calls is not None:
            calls.append(api_key)
        value = values.get(api_key, 0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(KeyScheduler, "_fetch_credits", fake_fetch)


def age_affinity(sched: KeyScheduler, sid: str, seconds: float) -> None:
    """Move a binding's last-seen timestamp `seconds` into the past."""
    key, last_seen = sched._affinity._entries[sid]
    sched._affinity._entries[sid] = (key, last_seen - seconds)


def expire_cooldown(sched: KeyScheduler, key: str) -> None:
    """Move a cooling window's deadline into the past."""
    sched._until[key] = time.monotonic() - 0.001


class TestSessionAffinityCache:
    def test_get_and_refresh_returns_none_when_unbound(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        assert cache.get_and_refresh("s1") is None

    def test_set_then_get_returns_bound_key(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K1)
        assert cache.get_and_refresh("s1") == K1
        assert cache.stats() == {"entries": 1, "bound_by_key": {K1: 1}}

    def test_sliding_ttl_renews_on_every_hit(self):
        """Two hits win over the TTL clock: each hit restarts the window."""
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K1)
        key, last_seen = cache._entries["s1"]
        cache._entries["s1"] = (key, last_seen - 90)
        assert cache.get_and_refresh("s1") == K1
        # 180s elapsed since binding, but only 90s since the last hit -> still bound
        key, last_seen = cache._entries["s1"]
        cache._entries["s1"] = (key, last_seen - 90)
        assert cache.get_and_refresh("s1") == K1

    def test_expired_binding_is_dropped(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K1)
        key, last_seen = cache._entries["s1"]
        cache._entries["s1"] = (key, last_seen - 101)
        assert cache.get_and_refresh("s1") is None
        assert cache.stats()["entries"] == 0

    def test_compare_and_delete_only_matches_expected_key(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K2)
        assert cache.compare_and_delete("s1", K1) is False
        assert cache.compare_and_delete(None, K1) is False
        assert cache.get_and_refresh("s1") == K2
        assert cache.compare_and_delete("s1", K2) is True
        assert cache.get_and_refresh("s1") is None

    def test_delete_by_key_unbinds_every_session_of_that_key(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K1)
        cache.set("s2", K1)
        cache.set("s3", K2)
        assert cache.delete_by_key(K1) == 2
        assert cache.stats() == {"entries": 1, "bound_by_key": {K2: 1}}
        assert cache.delete_by_key(K1) == 0

    def test_clear_returns_previous_entry_count(self):
        cache = SessionAffinityCache(ttl=100, max_entries=10)
        cache.set("s1", K1)
        cache.set("s2", K2)
        assert cache.clear() == 2
        assert cache.stats() == {"entries": 0, "bound_by_key": {}}

    def test_evicts_least_recently_used_entry_over_capacity(self):
        cache = SessionAffinityCache(ttl=1000, max_entries=2)
        cache.set("s1", K1)
        cache.set("s2", K2)
        cache.get_and_refresh("s1")  # s1 becomes most recently used, s2 is now LRU
        cache.set("s3", K3)
        assert cache.stats() == {"entries": 2, "bound_by_key": {K1: 1, K3: 1}}
        assert cache.get_and_refresh("s2") is None
        assert cache.get_and_refresh("s1") == K1


class TestFillFirstSelection:
    @pytest.mark.asyncio
    async def test_repeated_select_without_session_identity_keeps_first_usable_key(self):
        """Non-explicit traffic is fill-first: it must not rotate away from the head."""
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        assert [await sched.select(None, explicit=False) for _ in range(3)] == [K1, K1, K1]

    @pytest.mark.asyncio
    async def test_implicit_session_flag_is_never_bound(self):
        """Only explicit session identities get affinity bindings."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert await sched.select("header:implicit", explicit=False) == K1
        assert sched._affinity.stats()["entries"] == 0

    @pytest.mark.asyncio
    async def test_zero_credit_head_key_is_skipped_until_credits_recover(self):
        sched = make_scheduler([K1, K2, K3], {K1: 0, K2: 0, K3: 500})
        assert await sched.select(None, explicit=False) == K3
        sched._credits[K1] = 500
        assert await sched.select(None, explicit=False) == K1

    @pytest.mark.asyncio
    async def test_cooling_head_key_is_skipped_until_the_window_expires(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=429)
        assert await sched.select(None, explicit=False) == K2
        expire_cooldown(sched, K1)
        assert await sched.select(None, explicit=False) == K1


class TestRoundRobinBindings:
    @pytest.mark.asyncio
    async def test_unbound_explicit_sessions_rotate_in_configured_order(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        picked = [await sched.select(f"header:s{i}", explicit=True) for i in range(4)]
        assert picked == [K1, K2, K3, K1]  # wraps around the configured ring
        assert sched._affinity.get_and_refresh("header:s0") == K1
        assert sched._affinity.get_and_refresh("header:s1") == K2
        assert sched._affinity.get_and_refresh("header:s3") == K1  # re-bound after wrapping

    @pytest.mark.asyncio
    async def test_rotation_does_not_restart_at_the_head_when_candidates_are_filtered(self):
        """Excluding the bound key must continue the ring, not re-pick the filtered head."""
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        assert await sched.select("header:s1", explicit=True) == K1
        assert await sched.select("header:s2", explicit=True, exclude={K1}) == K2
        assert await sched.select("header:s3", explicit=True, exclude={K1}) == K3

    @pytest.mark.asyncio
    async def test_rotation_skips_a_cooling_middle_key(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        sched.report(K2, ok=False, status=402)
        picked = [await sched.select(f"header:s{i}", explicit=True) for i in range(3)]
        assert picked == [K1, K3, K1]


class TestSessionAffinity:
    @pytest.mark.asyncio
    async def test_bound_session_keeps_its_key_when_a_priority_key_recovers(self):
        """Stickiness beats fill-first: a recovered head key must not steal the session."""
        sched = make_scheduler([K1, K2], {K1: 0, K2: 100})
        flag = "header:sticky-session-1"
        assert await sched.select(flag, explicit=True) == K2
        sched._credits[K1] = 100  # head key recovers
        assert await sched.select(flag, explicit=True) == K2
        assert await sched.select("header:other-session", explicit=True) == K1

    @pytest.mark.asyncio
    async def test_binding_slides_its_ttl_on_every_use(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:sliding-session"
        assert await sched.select(flag, explicit=True) == K1
        age_affinity(sched, flag, SESSION_AFFINITY_TTL - 60)
        assert await sched.select(flag, explicit=True) == K1
        age_affinity(sched, flag, SESSION_AFFINITY_TTL - 60)  # > TTL since binding, < TTL since last use
        assert await sched.select(flag, explicit=True) == K1

    @pytest.mark.asyncio
    async def test_expired_binding_becomes_cold_and_is_rebound(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:expiring-session"
        assert await sched.select(flag, explicit=True) == K1
        age_affinity(sched, flag, SESSION_AFFINITY_TTL + 1)
        assert await sched.select(flag, explicit=True) == K2  # cold binding -> round robin continues
        assert sched._affinity.get_and_refresh(flag) == K2

    @pytest.mark.asyncio
    async def test_excluding_the_bound_key_rebinds_the_session(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:retry-session"
        assert await sched.select(flag, explicit=True) == K1
        assert await sched.select(flag, explicit=True, exclude={K1}) == K2
        assert sched._affinity.get_and_refresh(flag) == K2

    @pytest.mark.asyncio
    async def test_binding_for_a_disabled_key_is_replaced(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=401)
        sched._affinity.set("header:stale-binding", K1)
        assert await sched.select("header:stale-binding", explicit=True) == K2
        assert sched._affinity.get_and_refresh("header:stale-binding") == K2

    def test_key_state_counts_sessions_per_key(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K1)
        assert sched.key_state(K1)["sessions"] == 2
        assert sched.key_state(K2)["sessions"] == 0
        assert sched.clear_sessions() == 2
        assert sched.key_state(K1)["sessions"] == 0


class TestReport:
    def test_out_of_credits_parks_key_for_flat_window(self):
        sched = make_scheduler([K1], {K1: 100})
        for attempt in (1, 2, 3):
            sched.report(K1, ok=False, status=400, reason="insufficient_credits")
            state = sched.key_state(K1)
            assert state["state"] == "cooling"
            assert state["failures"] == attempt
            assert state["reason"] == "insufficient_credits"
            assert state["credits"] == 0  # cached balance is zeroed
            # flat window, no exponential ramp
            assert state["until"] - time.monotonic() == pytest.approx(KEY_CREDIT_COOLDOWN, abs=1.0)

    def test_payment_required_also_parks_key(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=402)
        state = sched.key_state(K1)
        assert state["credits"] == 0
        assert state["until"] - time.monotonic() == pytest.approx(KEY_CREDIT_COOLDOWN, abs=1.0)

    def test_parked_key_is_second_choice_for_the_next_request(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=400, reason="insufficient_credits")
        assert asyncio.run(sched.select("header:s1", explicit=True)) == K2

    def test_rate_limit_cools_down_with_escalating_backoff(self):
        sched = make_scheduler([K1], {K1: 100})
        for attempt in (1, 2, 3):
            sched.report(K1, ok=False, status=429, reason="rate_limited")
            state = sched.key_state(K1)
            assert state["state"] == "cooling"
            assert state["failures"] == attempt
            assert state["reason"] == "rate_limited"
            assert state["until"] - time.monotonic() == pytest.approx(KEY_COOLDOWN_BASE * 2 ** (attempt - 1), abs=1.0)

    def test_cooldown_escalation_caps_at_max(self):
        sched = make_scheduler([K1], {K1: 100})
        for _ in range(10):
            sched.report(K1, ok=False, status=429, reason="rate_limited")
        assert sched.key_state(K1)["failures"] == 10
        assert sched.key_state(K1)["until"] - time.monotonic() == pytest.approx(KEY_COOLDOWN_MAX, abs=1.0)

    def test_scheduler_cooldowns_are_injectable(self):
        sched = KeyScheduler([K1], BASE_URL, cooldown_base=5, cooldown_max=7, credit_cooldown=42)
        sched._credits[K1] = 100
        sched._last_fetch = time.monotonic()
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        assert sched.key_state(K1)["until"] - time.monotonic() == pytest.approx(5, abs=1.0)
        sched.report(K1, ok=False, status=400, reason="insufficient_credits")
        assert sched.key_state(K1)["until"] - time.monotonic() == pytest.approx(42, abs=1.0)

    def test_reset_clears_the_zero_credit_mark(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=400, reason="insufficient_credits")
        assert sched.key_state(K1)["credits"] == 0
        sched.reset_key(K1)
        state = sched.key_state(K1)
        assert state["state"] == "ok"
        assert state["credits"] is None
        assert state["until"] is None

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_status_disables_key_and_unbinds_sessions(self, status):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K1)
        sched._affinity.set("header:s3", K2)
        sched.report(K1, ok=False, status=status)
        state = sched.key_state(K1)
        assert state["state"] == "disabled"
        assert state["reason"] == f"http_{status}"
        assert state["until"] is None
        assert sched._affinity.stats() == {"entries": 1, "bound_by_key": {K2: 1}}

    def test_invalid_key_reason_disables_key(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, reason="invalid_key")
        assert sched.key_state(K1)["state"] == "disabled"
        assert sched.key_state(K1)["reason"] == "invalid_key"

    @pytest.mark.parametrize("status", [500, 502, 504, None])
    def test_transient_failures_leave_state_untouched(self, status):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=status, reason="upstream_error")
        state = sched.key_state(K1)
        assert state == {
            "state": "ok",
            "until": None,
            "reason": None,
            "credits": 100,
            "failures": 0,
            "sessions": 0,
        }

    def test_report_ok_resets_health(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        sched.report(K1, ok=True)
        assert sched.key_state(K1) == {
            "state": "ok",
            "until": None,
            "reason": None,
            "credits": 100,
            "failures": 0,
            "sessions": 0,
        }

    def test_success_does_not_clear_a_zero_credit_mark(self):
        """A key parked for credits only recovers via the credits refresh or /reset."""
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=400, reason="insufficient_credits")
        sched.report(K1, ok=True)
        assert sched.key_state(K1)["credits"] == 0
        assert sched.key_state(K1)["state"] == "ok"

    def test_cooling_window_expiry_keeps_failures_so_backoff_keeps_escalating(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        expire_cooldown(sched, K1)
        expired = sched.key_state(K1)
        assert expired["state"] == "ok"
        assert expired["until"] is None
        assert expired["reason"] is None
        assert expired["failures"] == 2  # counter survives the window
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        assert sched.key_state(K1)["until"] - time.monotonic() == pytest.approx(KEY_COOLDOWN_BASE * 4, abs=1.0)

    def test_reset_key_clears_cooling_and_disabled_health(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=401)
        sched.report(K2, ok=False, status=429, reason="rate_limited")
        sched.reset_key(K1)
        sched.reset_key(K2)
        assert sched.key_state(K1)["state"] == "ok"
        assert sched.key_state(K2) == {
            "state": "ok",
            "until": None,
            "reason": None,
            "credits": None,  # reset drops the cached balance so the key is selectable now
            "failures": 0,
            "sessions": 0,
        }

    def test_cooldown_unbinds_only_the_session_that_used_the_key(self):
        """compare-and-delete must not steal a session that already moved elsewhere."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K2)
        sched.report(K1, ok=False, status=402, session_flag="header:s2")
        assert sched._affinity.get_and_refresh("header:s2") == K2  # untouched
        assert sched._affinity.get_and_refresh("header:s1") == K1
        sched.report(K1, ok=False, status=402, session_flag="header:s1")
        assert sched._affinity.get_and_refresh("header:s1") is None
        assert sched._affinity.get_and_refresh("header:s2") == K2

    def test_cooldown_without_session_flag_keeps_binding(self):
        sched = make_scheduler([K1], {K1: 100})
        sched._affinity.set("header:s1", K1)
        sched.report(K1, ok=False, status=429)
        assert sched._affinity.get_and_refresh("header:s1") == K1

    @pytest.mark.asyncio
    async def test_cooldown_then_retry_rebinds_the_session_to_the_next_key(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:retry-flow"
        assert await sched.select(flag, explicit=True) == K1
        sched.report(K1, ok=False, status=402, session_flag=flag)
        assert await sched.select(flag, explicit=True) == K2


class TestSelectExcludeAndFailFast:
    @pytest.mark.asyncio
    async def test_exclude_removes_key_from_selection(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        assert await sched.select(None, explicit=False, exclude={K1}) == K2

    @pytest.mark.asyncio
    async def test_no_selection_when_every_key_is_cooling_or_out_of_credits(self):
        sched = make_scheduler([K1, K2], {K1: 0, K2: 0})
        sched.report(K1, ok=False, status=402)
        assert await sched.select(None, explicit=False) is None
        assert await sched.select("header:s1", explicit=True) is None

    @pytest.mark.asyncio
    async def test_no_selection_skips_disabled_keys(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 0})
        sched.report(K1, ok=False, status=401)
        sched.report(K2, ok=False, status=402)
        assert await sched.select(None, explicit=False) is None

    @pytest.mark.asyncio
    async def test_cooled_key_recovers_after_the_window_and_keeps_its_binding(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:parked-session"
        assert await sched.select(flag, explicit=True) == K1
        sched.report(K1, ok=False, status=429, reason="rate_limited", session_flag=flag)
        # Other keys are busy-free, so the session rebinds instead of failing.
        assert await sched.select(flag, explicit=True) == K2
        sched.report(K2, ok=False, status=429, reason="rate_limited", session_flag=flag)
        assert await sched.select(flag, explicit=True) is None
        expire_cooldown(sched, K1)
        assert await sched.select(flag, explicit=True) == K1

    @pytest.mark.asyncio
    async def test_returns_none_when_every_key_is_disabled(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=401)
        sched.report(K2, ok=False, status=403)
        assert await sched.select(None, explicit=False) is None
        assert await sched.select("header:s1", explicit=True) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_every_key_is_excluded(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert await sched.select(None, explicit=False, exclude={K1, K2}) is None

    @pytest.mark.asyncio
    async def test_returns_none_without_configured_keys(self):
        sched = KeyScheduler(keys=[], base_url=BASE_URL)
        assert await sched.select(None, explicit=False) is None
        assert sched.last_fetch_time is None  # nothing to fetch, no blocking call


class TestCreditsPlumbing:
    @pytest.mark.asyncio
    async def test_first_select_blocks_on_a_single_fetch(self, monkeypatch):
        calls: list[str] = []
        stub_credits(monkeypatch, {K1: 100, K2: 0}, calls)
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        assert sched.last_fetch_time is None
        assert await sched.select(None, explicit=False) == K1
        assert calls == [K1, K2]
        assert sched.get_credits(K1) == 100
        assert sched.get_credits(K2) == 0
        assert sched.last_fetch_time is not None
        assert sched.last_error is None

    @pytest.mark.asyncio
    async def test_second_select_does_not_fetch_while_the_snapshot_is_fresh(self, monkeypatch):
        calls: list[str] = []
        stub_credits(monkeypatch, {K1: 100}, calls)
        sched = KeyScheduler(keys=[K1], base_url=BASE_URL)
        await sched.select(None, explicit=False)
        await sched.select(None, explicit=False)
        assert calls.count(K1) == 1

    @pytest.mark.asyncio
    async def test_stale_snapshot_refreshes_in_the_background(self, monkeypatch):
        """select() must never block once a snapshot exists, even when it is stale."""
        refreshed = asyncio.Event()

        async def fake_refresh(self):
            refreshed.set()

        monkeypatch.setattr(KeyScheduler, "_refresh", fake_refresh)
        sched = make_scheduler([K1, K2], {K1: 100, K2: 0})
        sched._last_fetch = time.monotonic() - (KEY_CREDITS_CACHE_TTL + 1)
        assert await sched.select(None, explicit=False) == K1  # returns from cached state
        assert sched._fetch_task is not None
        await sched._fetch_task
        assert refreshed.is_set()

    @pytest.mark.asyncio
    async def test_initial_fetch_failure_is_swallowed(self, monkeypatch):
        async def boom(self):
            raise RuntimeError("network down")

        monkeypatch.setattr(KeyScheduler, "_refresh", boom)
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        assert await sched.select(None, explicit=False) == K1
        assert sched.last_fetch_time is None
        assert sched.get_credits(K1) is None

    @pytest.mark.asyncio
    async def test_refresh_records_partial_failures(self, monkeypatch):
        stub_credits(monkeypatch, {K1: 160, K2: RuntimeError("boom")})
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        await sched.refresh()
        assert sched.get_credits(K1) == 160
        assert sched.get_credits(K2) is None
        assert sched.last_error is None  # one success is enough to keep the snapshot valid
        assert sched.last_fetch_time is not None

    @pytest.mark.asyncio
    async def test_refresh_with_every_fetch_failing_sets_last_error(self, monkeypatch):
        stub_credits(monkeypatch, {K1: RuntimeError("down"), K2: RuntimeError("down")})
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        await sched.refresh()
        assert sched.last_error == "All credit fetches failed"
        assert sched.get_credits(K1) is None
        assert sched.last_fetch_time is not None

    def test_staleness_uses_cache_ttl_and_error_backoff(self):
        sched = KeyScheduler(keys=[K1], base_url=BASE_URL)
        assert sched._is_stale()  # never fetched
        sched._last_fetch = time.monotonic() - (KEY_CREDITS_CACHE_TTL + 1)
        assert sched._is_stale()
        sched._last_fetch = time.monotonic() - 5
        assert not sched._is_stale()
        sched._last_error = "All credit fetches failed"
        sched._last_fetch = time.monotonic() - (KEY_CREDITS_ERROR_BACKOFF + 1)
        assert sched._is_stale()  # retry after the shorter error backoff
        sched._last_fetch = time.monotonic() - 5
        assert not sched._is_stale()

    @pytest.mark.asyncio
    async def test_disabled_and_cooling_keys_still_block_the_first_fetch(self, monkeypatch):
        """Health filters do not short-circuit the credits snapshot lifecycle."""
        calls: list[str] = []
        stub_credits(monkeypatch, {K1: 100, K2: 100}, calls)
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        sched.report(K1, ok=False, status=401)
        assert await sched.select(None, explicit=False) == K2
        assert calls == [K1, K2]


class TestKeyStates:
    def test_states_follow_configuration_order_and_report_fields(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 50, K3: 0})
        sched.report(K2, ok=False, status=429)
        states = sched.states()
        assert [s["state"] for s in states] == ["ok", "cooling", "ok"]
        assert [s["credits"] for s in states] == [100, 50, 0]
        assert [s["reason"] for s in states] == [None, "http_429", None]
        assert states[0]["until"] is None
        assert states[1]["until"] > time.monotonic()

    def test_key_state_for_unknown_key_reports_ok(self):
        sched = make_scheduler([K1], {K1: 100})
        assert sched.key_state(K2)["state"] == "ok"
        assert sched.key_state(K2)["credits"] is None


class _RecordingLogger:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def info(self, event, **kwargs):
        self.events.append((event, kwargs))

    def warning(self, event, **kwargs):  # pragma: no cover - only used if a fetch is stubbed out
        self.events.append((event, kwargs))


class TestLogging:
    @pytest.mark.asyncio
    async def test_logs_never_leak_full_session_or_key_values(self, monkeypatch):
        """Privacy: only the session prefix and the key suffix may be logged."""
        recorder = _RecordingLogger()
        monkeypatch.setattr(ks, "logger", recorder)
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:secret-session-identity"
        await sched.select(flag, explicit=True)
        sched.report(K1, ok=False, status=402, session_flag=flag)
        sched.report(K1, ok=False, status=401)
        await sched.select(None, explicit=False)

        events = recorder.events
        assert [event for event, _ in events] == ["key.bind", "key.cooldown", "key.disabled", "key.select"]
        assert events[0][1] == {"session": flag[:8], "key": K1[-4:]}
        assert events[3][1] == {"key": K2[-4:], "reason": "no-session"}  # K1 is disabled, fill-first moves on
        for _, kwargs in events:
            assert flag not in str(kwargs)
            assert K1 not in str(kwargs)
