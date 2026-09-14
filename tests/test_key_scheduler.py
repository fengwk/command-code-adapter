"""Unit tests for cc_adapter.core.key_scheduler.

Credits fetching is always stubbed (`_fetch_credits` monkeypatched or the
`_credits`/`_last_fetch` snapshot seeded directly) so no HTTP happens.

Time-dependent behaviour (cooldown windows, affinity TTL) is driven by
rewriting the stored deadline/timestamp instead of patching `time.monotonic`,
which keeps the tests deterministic and free of arbitrary sleeps.
"""

import asyncio
import time

import httpx
import pytest

from cc_adapter.core import key_scheduler as ks
from cc_adapter.core.constants import (
    KEY_COOLDOWN_BASE,
    KEY_COOLDOWN_MAX,
    KEY_CREDIT_COOLDOWN,
    KEY_CREDITS_CACHE_TTL,
    KEY_CREDITS_ERROR_BACKOFF,
    KEY_CREDITS_PROBE_SPREAD,
    KEY_FORBIDDEN_COOLDOWN,
    KEY_MAX_CONCURRENT_STREAMS,
    SESSION_AFFINITY_TTL,
)
from cc_adapter.core.key_scheduler import KeyScheduler, SessionAffinityCache
from cc_adapter.providers.shared.session_extractor import process_identity

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


class _FakeClock:
    """Stand-in for the `time` module: only `monotonic()` is used by the scheduler."""

    def __init__(self, now: float):
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
    async def test_implicit_session_flag_binds_the_fill_first_head(self):
        """A content-anchored conversation is bound too, but still starts at the head."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert await sched.select("msg:implicit", explicit=False) == K1
        assert sched._affinity.get_and_refresh("msg:implicit") == K1
        assert sched._affinity.stats()["entries"] == 1
        assert await sched.select("msg:implicit-2", explicit=False) == K1  # still fill-first

    @pytest.mark.asyncio
    async def test_bound_conversation_does_not_bounce_back_to_a_recovered_head(self):
        """The binding is what keeps one conversation out of two accounts.

        Fill-first alone drags every conversation to the head key as soon as its
        cooldown expires, so the same content would reappear under two accounts
        every time the head key cools and recovers.
        """
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "msg:conversation"
        assert await sched.select(flag, explicit=False) == K1
        sched.report(K1, ok=False, status=429, session_flag=flag)  # K1 cools: migrate once
        assert await sched.select(flag, explicit=False) == K2
        expire_cooldown(sched, K1)  # head key is healthy again ...
        assert await sched.select(flag, explicit=False) == K2  # ... and the conversation stays put
        assert await sched.select("msg:another", explicit=False) == K1  # new one still fill-first

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


class TestConcurrencyCap:
    """`KEY_MAX_CONCURRENT_STREAMS` spreads load over the keys; it never fails a request."""

    @pytest.mark.asyncio
    async def test_saturated_keys_are_skipped_while_another_key_has_room(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        load = {K1: KEY_MAX_CONCURRENT_STREAMS, K2: 0, K3: 0}
        assert await sched.select(None, explicit=False, load=load.get) == K2
        load[K2] = KEY_MAX_CONCURRENT_STREAMS
        assert await sched.select(None, explicit=False, load=load.get) == K3

    @pytest.mark.asyncio
    async def test_saturated_keys_are_skipped_for_an_explicit_session_too(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        load = {K1: KEY_MAX_CONCURRENT_STREAMS, K2: 1}
        assert await sched.select("header:s1", explicit=True, load=load.get) == K2

    @pytest.mark.asyncio
    async def test_all_keys_saturated_picks_the_least_loaded(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        load = {K1: 9, K2: 5, K3: 7}
        assert await sched.select(None, explicit=False, load=load.get) == K2
        assert await sched.select("header:s1", explicit=True, load=load.get) == K2

    @pytest.mark.asyncio
    async def test_all_saturated_ties_keep_configuration_order(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})

        def load(key: str) -> int:
            return KEY_MAX_CONCURRENT_STREAMS

        assert await sched.select(None, explicit=False, load=load) == K1
        assert await sched.select("header:s1", explicit=True, load=load) == K1

    @pytest.mark.asyncio
    async def test_a_single_saturated_key_is_still_used(self):
        """The cap can never turn into "no key": the last resort is the loaded key itself."""
        sched = make_scheduler([K1], {K1: 100})
        assert await sched.select(None, explicit=False, load=lambda _: 99) == K1

    @pytest.mark.asyncio
    async def test_unusable_keys_are_filtered_before_the_load_is_considered(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=401)  # disabled: not a candidate, loaded or not
        assert await sched.select(None, explicit=False, load=lambda _: KEY_MAX_CONCURRENT_STREAMS) == K2

    @pytest.mark.asyncio
    async def test_without_a_load_source_the_cap_is_not_applied(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert await sched.select(None, explicit=False) == K1
        assert await sched.select("header:s1", explicit=True) == K1

    @pytest.mark.asyncio
    async def test_bound_session_stays_on_its_key_while_it_has_room(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:busy-session"
        assert await sched.select(flag, explicit=True) == K1
        load = {K1: KEY_MAX_CONCURRENT_STREAMS - 1, K2: 0}
        assert await sched.select(flag, explicit=True, load=load.get) == K1
        assert sched._affinity.get_and_refresh(flag) == K1

    @pytest.mark.asyncio
    async def test_saturated_bound_key_is_handled_like_an_unusable_one(self):
        """The session is rebound, and stays there for its next turn."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:blocked-session"
        assert await sched.select(flag, explicit=True) == K1
        load = {K1: KEY_MAX_CONCURRENT_STREAMS, K2: 0}
        assert await sched.select(flag, explicit=True, load=load.get) == K2
        assert sched._affinity.get_and_refresh(flag) == K2
        load[K1] = 0
        assert await sched.select(flag, explicit=True, load=load.get) == K2  # rebind is sticky


class TestAffinityCarryOver:
    """The panel rebuilds the client on every save; running conversations must not move."""

    def test_export_returns_the_bindings_in_lru_order(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K2)
        assert sched.export_affinity() == [("header:s1", K1), ("header:s2", K2)]

    def test_import_rebinds_sessions_to_configured_keys(self):
        source = make_scheduler([K1, K2], {K1: 100, K2: 100})
        source._affinity.set("header:s1", K2)
        target = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert target.import_affinity(source.export_affinity()) == 1
        assert target._affinity.stats() == {"entries": 1, "bound_by_key": {K2: 1}}

    def test_import_drops_bindings_of_keys_that_are_gone(self):
        source = make_scheduler([K1, K2], {K1: 100, K2: 100})
        source._affinity.set("header:kept", K1)
        source._affinity.set("header:dropped", K2)
        target = make_scheduler([K1], {K1: 100})
        assert target.import_affinity(source.export_affinity()) == 1
        assert target._affinity.get_and_refresh("header:kept") == K1
        assert target._affinity.get_and_refresh("header:dropped") is None

    def test_imported_bindings_keep_the_sliding_ttl(self):
        source = make_scheduler([K1], {K1: 100})
        source._affinity.set("header:s1", K1)
        target = make_scheduler([K1], {K1: 100})
        target.import_affinity(source.export_affinity())
        age_affinity(target, "header:s1", SESSION_AFFINITY_TTL + 1)
        assert target._affinity.get_and_refresh("header:s1") is None

    @pytest.mark.asyncio
    async def test_a_session_stays_on_its_key_across_a_rebuild(self):
        """Assignment survives: without the carry-over the session would move to the head key."""
        source = make_scheduler([K1, K2], {K1: 100, K2: 100})
        flag = "header:running-conversation"
        assert await source.select(flag, explicit=True) == K1
        assert await source.select("header:other", explicit=True) == K2
        assert source._affinity.get_and_refresh(flag) == K1
        source.disable(K2)  # panel switched a key off: its session is unbound

        target = make_scheduler([K1, K2], {K1: 100, K2: 100})
        target.import_affinity(source.export_affinity())

        assert await target.select(flag, explicit=True) == K1  # sticky, not round-robin
        target.clear_sessions()
        assert await target.select(flag, explicit=True) == K1  # cold: the head key again


class TestCreditsRequestHeaders:
    """Billing calls are signed like generate calls: process identity + the CLI header set."""

    @pytest.mark.asyncio
    async def test_credits_call_carries_the_process_identity(self, respx_mock):
        route = respx_mock.get(f"{BASE_URL}/alpha/billing/credits").mock(
            return_value=httpx.Response(
                200, json={"credits": {"monthlyCredits": 5, "purchasedCredits": 2, "freeCredits": 0}}
            )
        )
        sched = KeyScheduler(keys=[K1], base_url=BASE_URL)
        assert await sched._fetch_credits(K1) == 7

        headers = route.calls.last.request.headers
        identity = process_identity(K1)
        assert headers["x-session-id"] == identity.session_id
        assert headers["x-project-slug"] == identity.project_slug
        assert headers["Authorization"] == f"Bearer {K1}"
        # the header set replaces httpx's defaults instead of stacking on top of them
        assert headers["user-agent"] == "cli"
        assert headers["accept-encoding"] == "gzip, deflate"
        assert headers["host"] == "api.example.com"


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

    def test_401_disables_key_and_unbinds_sessions(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K1)
        sched._affinity.set("header:s3", K2)
        sched.report(K1, ok=False, status=401)
        state = sched.key_state(K1)
        assert state["state"] == "disabled"
        assert state["reason"] == "http_401"
        assert state["until"] is None
        assert sched._affinity.stats() == {"entries": 1, "bound_by_key": {K2: 1}}

    def test_bare_403_cools_the_key_down_for_two_hours(self):
        """A policy denial is not a revoked key: park it instead of disabling it forever."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K2)
        sched.report(K1, ok=False, status=403, session_flag="header:s1")

        state = sched.key_state(K1)
        assert state["state"] == "cooling"
        assert state["reason"] == "http_403"
        assert state["cooldown_seconds"] == pytest.approx(KEY_FORBIDDEN_COOLDOWN, abs=1.0)
        # the session that hit the denial is unbound (like every other cooldown path),
        # sessions on other keys stay untouched
        assert sched._affinity.get_and_refresh("header:s1") is None
        assert sched._affinity.get_and_refresh("header:s2") == K2
        # next request moves to the healthy key ...
        assert asyncio.run(sched.select(None, explicit=False)) == K2
        # ... and comes back to the cooled key once the window is over
        expire_cooldown(sched, K1)
        assert asyncio.run(sched.select(None, explicit=False)) == K1

    def test_bare_403_cooldown_expires_with_the_clock(self, monkeypatch):
        """Same as above, driven by a fake clock instead of rewriting the deadline."""
        clock = _FakeClock(time.monotonic())
        monkeypatch.setattr(ks, "time", clock)
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=403)
        assert asyncio.run(sched.select(None, explicit=False)) == K2
        clock.advance(KEY_FORBIDDEN_COOLDOWN - 1)
        assert asyncio.run(sched.select(None, explicit=False)) == K2  # still cooling
        clock.advance(2)
        assert asyncio.run(sched.select(None, explicit=False)) == K1  # window passed

    def test_403_with_invalid_key_reason_still_disables(self):
        """Only an explicit invalid-key report is permanent for a 403."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched.report(K1, ok=False, status=403, reason="invalid_key")
        state = sched.key_state(K1)
        assert state["state"] == "disabled"
        assert state["reason"] == "invalid_key"
        assert state["until"] is None
        assert sched._affinity.get_and_refresh("header:s1") is None

    def test_forbidden_cooldown_does_not_touch_the_failure_counter(self):
        """The 403 window is flat: it neither escalates nor resets a rate-limit counter."""
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        sched.report(K1, ok=False, status=403)
        assert sched.key_state(K1)["failures"] == 1
        assert sched.key_state(K1)["cooldown_seconds"] == pytest.approx(KEY_FORBIDDEN_COOLDOWN, abs=1.0)

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
            "cooldown_seconds": None,
            "reason": None,
            "credits": 100,
            "failures": 0,
            "sessions": 0,
            "enabled": True,
            "manual": False,
        }

    def test_report_ok_resets_health(self):
        sched = make_scheduler([K1], {K1: 100})
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        sched.report(K1, ok=True)
        assert sched.key_state(K1) == {
            "state": "ok",
            "until": None,
            "cooldown_seconds": None,
            "reason": None,
            "credits": 100,
            "failures": 0,
            "sessions": 0,
            "enabled": True,
            "manual": False,
        }

    def test_success_does_not_clear_a_zero_credit_mark(self):
        """A key parked for credits only recovers via the credits refresh or /enable."""
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
            "cooldown_seconds": None,
            "reason": None,
            "credits": None,  # reset drops the cached balance so the key is selectable now
            "failures": 0,
            "sessions": 0,
            "enabled": True,
            "manual": False,
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
        sched.report(K2, ok=False, status=403, reason="invalid_key")
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


class TestManualSwitch:
    """The admin on/off switch: off means "never select this key"."""

    def test_disabled_key_is_never_selected_despite_health_and_credits(self):
        """The manual switch outranks both an expired cooldown and a positive balance."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.report(K1, ok=False, status=429, reason="rate_limited")
        sched.disable(K1)
        expire_cooldown(sched, K1)  # automatic window is over and the key is funded again
        assert sched.key_state(K1)["state"] == "ok"
        assert asyncio.run(sched.select(None, explicit=False)) == K2
        assert asyncio.run(sched.select("header:s1", explicit=True)) == K2

    def test_returns_none_when_every_key_is_manually_disabled(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched.disable(K1)
        sched.disable(K2)
        assert asyncio.run(sched.select(None, explicit=False)) is None
        assert asyncio.run(sched.select("header:s1", explicit=True)) is None

    def test_disable_unbinds_only_that_keys_sessions_and_returns_the_count(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        sched._affinity.set("header:s1", K1)
        sched._affinity.set("header:s2", K1)
        sched._affinity.set("header:s3", K2)
        assert sched.disable(K1) == 2
        assert sched._affinity.stats() == {"entries": 1, "bound_by_key": {K2: 1}}
        assert sched.disable(K1) == 0  # idempotent: nothing left to unbind

    def test_enable_restores_selection_and_clears_health_and_credit_marks(self):
        sched = make_scheduler([K1, K2], {K1: 0, K2: 100})
        sched.report(K1, ok=False, status=401)  # automatic disabled health
        sched.disable(K1)
        assert sched.key_state(K1)["manual"] is True
        assert asyncio.run(sched.select(None, explicit=False)) == K2

        sched.enable(K1)  # no running loop -> the background credits refresh is skipped
        state = sched.key_state(K1)
        assert state["enabled"] is True
        assert state["manual"] is False
        assert state["state"] == "ok"
        assert state["until"] is None
        assert state["cooldown_seconds"] is None
        assert state["credits"] is None  # cached zero mark dropped -> selectable right away
        assert asyncio.run(sched.select(None, explicit=False)) == K1

    def test_states_expose_the_manual_switch_and_the_remaining_cooldown(self):
        sched = make_scheduler([K1, K2, K3], {K1: 100, K2: 100, K3: 100})
        sched.report(K2, ok=False, status=429, reason="rate_limited")
        sched.disable(K1)
        states = sched.states()
        assert [s["enabled"] for s in states] == [False, True, True]
        assert [s["manual"] for s in states] == [True, False, False]
        assert states[0]["cooldown_seconds"] is None
        assert states[1]["cooldown_seconds"] == pytest.approx(KEY_COOLDOWN_BASE, abs=1.0)
        assert states[2]["cooldown_seconds"] is None
        expire_cooldown(sched, K2)
        assert sched.key_state(K2)["cooldown_seconds"] is None  # expired, never negative

    def test_unavailable_summary_marks_a_manually_disabled_key(self):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 0})
        sched.disable(K1)
        summary = sched.unavailable_summary()
        assert f"****{K1[-4:]} disabled by admin" in summary
        assert f"****{K2[-4:]} ok (out of credits)" in summary

    def test_manual_disabled_keys_reports_the_switch_read_only(self):
        """The accessor feeds the client rebuild, so callers must not be able to mutate the switch."""
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        assert sched.manual_disabled_keys() == set()
        sched.disable(K2)
        assert sched.manual_disabled_keys() == {K2}
        sched.manual_disabled_keys().add(K1)  # a copy: the scheduler is unaffected
        assert sched.manual_disabled_keys() == {K2}
        sched.enable(K2)
        assert sched.manual_disabled_keys() == set()


class TestProbeStagger:
    """The scheduled balance refresh must not fire every key in one instant.

    Firing all probes together from a single IP once per TTL is a multi-account
    signature, so the background refresh delays each key by its own offset.
    """

    def test_offset_is_stable_and_within_spread(self):
        sched = KeyScheduler(keys=[K1, K2, "key-c"], base_url=BASE_URL)
        offsets = {key: sched._probe_offset(key) for key in (K1, K2, "key-c")}
        assert all(0.0 <= value < KEY_CREDITS_PROBE_SPREAD for value in offsets.values())
        assert offsets == {key: sched._probe_offset(key) for key in (K1, K2, "key-c")}
        assert len(set(offsets.values())) > 1

    @pytest.mark.asyncio
    async def test_scheduled_refresh_staggers_every_key(self, monkeypatch):
        staggered: list[str] = []
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})

        async def record(api_key: str) -> None:
            staggered.append(api_key)

        monkeypatch.setattr(sched, "_stagger_probe", record)
        stub_credits(monkeypatch, {K1: 100, K2: 100})

        await sched.refresh(stagger=True)
        assert sorted(staggered) == sorted([K1, K2])

        staggered.clear()
        await sched.refresh()
        assert staggered == []

    @pytest.mark.asyncio
    async def test_stale_background_refresh_staggers(self, monkeypatch):
        sched = make_scheduler([K1, K2], {K1: 100, K2: 100})
        seen: list[bool] = []

        async def fake_refresh(*, stagger: bool = False) -> None:
            seen.append(stagger)

        monkeypatch.setattr(sched, "refresh", fake_refresh)
        sched._last_fetch = time.monotonic() - KEY_CREDITS_CACHE_TTL - 1
        await sched._ensure_credits()
        if sched._fetch_task is not None:
            await sched._fetch_task
        assert seen == [True]

    @pytest.mark.asyncio
    async def test_cold_fetch_is_not_staggered(self, monkeypatch):
        sched = KeyScheduler(keys=[K1, K2], base_url=BASE_URL)
        seen: list[bool] = []

        async def fake_refresh(*, stagger: bool = False) -> None:
            seen.append(stagger)

        monkeypatch.setattr(sched, "refresh", fake_refresh)
        await sched._ensure_credits()  # _last_fetch is None: the first request needs the balances
        assert seen == [False]


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

        async def fake_refresh(self, *, stagger: bool = False):
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
        assert events[0][1] == {"session": flag[:8], "key": K1[-4:], "explicit": True}
        assert events[3][1] == {"key": K2[-4:], "reason": "no-session"}  # K1 is disabled, fill-first moves on
        for _, kwargs in events:
            assert flag not in str(kwargs)
            assert K1 not in str(kwargs)

    def test_logs_the_admin_switch_with_the_key_suffix_and_unbound_count(self, monkeypatch):
        recorder = _RecordingLogger()
        monkeypatch.setattr(ks, "logger", recorder)
        sched = make_scheduler([K1], {K1: 100})
        sched._affinity.set("header:secret-session-identity", K1)
        assert sched.disable(K1) == 1
        sched.enable(K1)
        assert [event for event, _ in recorder.events] == ["key.admin_disabled", "key.admin_enabled"]
        assert recorder.events[0][1] == {"key": K1[-4:], "sessions": 1}
        assert recorder.events[1][1] == {"key": K1[-4:]}
        for _, kwargs in recorder.events:
            assert K1 not in str(kwargs)  # only the masked suffix is logged
