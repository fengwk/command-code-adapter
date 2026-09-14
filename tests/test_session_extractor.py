"""Tests for cc_adapter.providers.shared.session_extractor."""

import dataclasses
import hashlib
import re

import pytest

from cc_adapter.command_code.body import make_cc_body, make_config
from cc_adapter.core.constants import PROJECT_SLUGS_PER_ACCOUNT_MAX, PROJECT_SLUGS_PER_ACCOUNT_MIN
from cc_adapter.providers.anthropic.models import AnthropicRequest
from cc_adapter.providers.openai.models import ChatCompletionRequest
from cc_adapter.providers.openai.responses_models import ResponseCreateRequest
from cc_adapter.providers.shared.session_extractor import (
    _HOME_LOGIN_POOL,
    _PROJECT_SLUG_POOL,
    SessionExtractor,
    SessionIdentity,
    SessionSignal,
    get_session_extractor,
    is_valid_cmd_session_id,
)

# Claude Code sends `user_<hash>_account_<uuid>_session_<uuid>` in metadata.
CLAUDE_USER_ID = "user_3f221fe6b5c1_account_2f8f0b68_session_ac980658-63bd-4fb3-97ba-8da64cb1e344"
CLAUDE_SESSION_ID = "ac980658-63bd-4fb3-97ba-8da64cb1e344"


def _cc_body(**params):
    """Return a CC body as produced by request translators (system + messages
    live inside params, not at the top level)."""
    return make_cc_body(config=make_config(), params=params)


def _chat_request(**overrides) -> ChatCompletionRequest:
    payload = {"model": "deepseek/deepseek-v4-pro", "messages": [{"role": "user", "content": "hi"}]}
    payload.update(overrides)
    return ChatCompletionRequest(**payload)


def _anthropic_request(**overrides) -> AnthropicRequest:
    payload = {
        "model": "deepseek/deepseek-v4-pro",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }
    payload.update(overrides)
    return AnthropicRequest(**payload)


def _responses_request(**overrides) -> ResponseCreateRequest:
    payload = {"model": "deepseek/deepseek-v4-pro", "input": "hi"}
    payload.update(overrides)
    return ResponseCreateRequest(**payload)


class TestPriorityChainLevels:
    """One test per level of the documented CLIProxyAPI-style chain."""

    def setup_method(self):
        self.ex = SessionExtractor()

    # level 1 ----------------------------------------------------------
    def test_level1_claude_code_header(self):
        signal = self.ex.extract({"x-claude-code-session-id": "cli-abc"})
        assert signal == SessionSignal("claude:cli-abc", True)

    def test_level1_header_lookup_is_case_insensitive(self):
        # Routers lowercase inbound headers, but the extractor must not rely on it.
        signal = self.ex.extract({"X-Claude-Code-Session-Id": "cli-abc"})
        assert signal == SessionSignal("claude:cli-abc", True)

    # level 2 ----------------------------------------------------------
    def test_level2_anthropic_metadata_user_id_carrying_session(self):
        req = _anthropic_request(metadata={"user_id": CLAUDE_USER_ID})
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal(f"claude:session_{CLAUDE_SESSION_ID}", True)

    def test_level2_responses_metadata_user_id_carrying_session(self):
        req = _responses_request(metadata={"user_id": CLAUDE_USER_ID})
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal(f"claude:session_{CLAUDE_SESSION_ID}", True)

    def test_level2_metadata_user_id_without_session_is_hashed(self):
        user_id = "user_abc123"
        expected = "user:" + hashlib.sha256(user_id.encode()).hexdigest()[:16]
        req = _anthropic_request(metadata={"user_id": user_id})
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal(expected, True)

    def test_level2_metadata_without_user_id_falls_through(self):
        req = _anthropic_request(metadata={"other": "value"})
        body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])
        signal = self.ex.extract({}, req, body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    # level 3 ----------------------------------------------------------
    def test_level3_codex_session_headers(self):
        assert self.ex.extract({"session-id": "cx-1"}) == SessionSignal("codex:cx-1", True)
        assert self.ex.extract({"session_id": "cx-2"}) == SessionSignal("codex:cx-2", True)

    # level 4 ----------------------------------------------------------
    def test_level4_http_session_header(self):
        assert self.ex.extract({"x-http-session-id": "http-1"}) == SessionSignal("http:http-1", True)

    # level 5 ----------------------------------------------------------
    def test_level5_affinity_headers(self):
        assert self.ex.extract({"x-session-id": "s"}) == SessionSignal("header:s", True)
        assert self.ex.extract({"x-session-affinity": "a"}) == SessionSignal("affinity:a", True)
        assert self.ex.extract({"x-slot-session-id": "sl"}) == SessionSignal("slot:sl", True)

    def test_level5_header_order_within_level(self):
        signal = self.ex.extract({"x-slot-session-id": "sl", "x-session-affinity": "a", "x-session-id": "s"})
        assert signal == SessionSignal("header:s", True)

    # level 6 ----------------------------------------------------------
    def test_level6_conversation_and_thread_headers(self):
        assert self.ex.extract({"x-conversation-id": "c"}) == SessionSignal("conv:c", True)
        assert self.ex.extract({"x-thread-id": "t"}) == SessionSignal("thread:t", True)

    def test_level6_conversation_header_beats_thread_header(self):
        signal = self.ex.extract({"x-thread-id": "t", "x-conversation-id": "c"})
        assert signal == SessionSignal("conv:c", True)

    # level 7 ----------------------------------------------------------
    def test_level7_prompt_cache_key_on_chat_request(self):
        req = _chat_request(prompt_cache_key="pck-1")
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal("pck:pck-1", True)

    def test_level7_prompt_cache_key_on_responses_request(self):
        req = _responses_request(prompt_cache_key="pck-1")
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal("pck:pck-1", True)

    def test_level7_prompt_cache_key_on_body(self):
        # CommandCodeClient.generate() only has the CC body to work with.
        signal = self.ex.extract({}, None, {"params": {"model": "m"}, "prompt_cache_key": "pck-2"})
        assert signal == SessionSignal("pck:pck-2", True)

    # level 8 ----------------------------------------------------------
    def test_level8_conversation_string(self):
        req = _responses_request(conversation="conv-1")
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal("conv:conv-1", True)

    def test_level8_conversation_object_id(self):
        req = _responses_request(conversation={"id": "conv-2"})
        signal = self.ex.extract({}, req, _cc_body(model="m", system="sys", messages=[]))
        assert signal == SessionSignal("conv:conv-2", True)

    def test_level8_conversation_without_id_falls_through(self):
        req = _responses_request(conversation={"unrelated": "value"})
        body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])
        signal = self.ex.extract({}, req, body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    # level 9 ----------------------------------------------------------
    def test_level9_body_session_ids(self):
        assert self.ex.extract({}, {"session_id": "s1"}) == SessionSignal("session:s1", True)
        assert self.ex.extract({}, {"sessionId": "s2"}) == SessionSignal("session:s2", True)

    def test_level9_body_conversation_ids(self):
        assert self.ex.extract({}, {"conversation_id": "c1"}) == SessionSignal("conv:c1", True)
        assert self.ex.extract({}, {"chat_id": "c2"}) == SessionSignal("conv:c2", True)

    # level 10 ---------------------------------------------------------
    def test_level10_content_hash_fallback(self):
        body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])
        signal = self.ex.extract({}, None, body)
        assert signal.flag.startswith("msg:")
        assert len(signal.flag) == len("msg:") + 16
        assert signal.explicit is False


class TestPriorityPrecedence:
    """A higher level always wins, regardless of which other source is set."""

    def setup_method(self):
        self.ex = SessionExtractor()
        self.body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])

    def test_claude_header_beats_metadata_user_id(self):
        req = _anthropic_request(metadata={"user_id": CLAUDE_USER_ID})
        headers = {"x-claude-code-session-id": "cli-abc"}
        assert self.ex.extract(headers, req, self.body) == SessionSignal("claude:cli-abc", True)

    def test_metadata_user_id_beats_codex_session_header(self):
        req = _anthropic_request(metadata={"user_id": CLAUDE_USER_ID})
        headers = {"session-id": "cx-1"}
        signal = self.ex.extract(headers, req, self.body)
        assert signal == SessionSignal(f"claude:session_{CLAUDE_SESSION_ID}", True)

    def test_codex_header_beats_http_session_header(self):
        signal = self.ex.extract({"x-http-session-id": "http-1", "session-id": "cx-1"})
        assert signal == SessionSignal("codex:cx-1", True)

    def test_http_header_beats_session_headers(self):
        signal = self.ex.extract({"x-session-id": "s", "x-http-session-id": "http-1"})
        assert signal == SessionSignal("http:http-1", True)

    def test_headers_beat_body_fields(self):
        req = _chat_request(prompt_cache_key="pck-1")
        signal = self.ex.extract({"x-session-id": "hdr"}, req, self.body)
        assert signal == SessionSignal("header:hdr", True)

    def test_prompt_cache_key_precedes_body_session_ids(self):
        # Documented order: prompt_cache_key (7) is checked before session_id (9).
        signal = self.ex.extract({}, {"session_id": "s1", "prompt_cache_key": "pck-1"})
        assert signal == SessionSignal("pck:pck-1", True)


class TestExplicitSemantics:
    """explicit is True for levels 1-9 and False for the content-hash fallback."""

    @pytest.mark.parametrize(
        ("headers", "original", "body", "expected_flag"),
        [
            ({"x-claude-code-session-id": "v"}, None, None, "claude:v"),
            ({}, {"metadata": {"user_id": CLAUDE_USER_ID}}, None, f"claude:session_{CLAUDE_SESSION_ID}"),
            ({"session-id": "v"}, None, None, "codex:v"),
            ({"x-http-session-id": "v"}, None, None, "http:v"),
            ({"x-session-id": "v"}, None, None, "header:v"),
            ({"x-conversation-id": "v"}, None, None, "conv:v"),
            ({}, {"prompt_cache_key": "v"}, None, "pck:v"),
            ({}, {"conversation": "v"}, None, "conv:v"),
            ({}, {"session_id": "v"}, None, "session:v"),
        ],
    )
    def test_client_identities_are_explicit(self, headers, original, body, expected_flag):
        signal = SessionExtractor().extract(headers, original, body)
        assert signal.explicit is True
        assert not signal.flag.startswith("msg:")
        assert signal.flag == expected_flag

    def test_content_hash_fallback_is_not_explicit(self):
        body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])
        assert SessionExtractor().extract({}, None, body).explicit is False


class TestFallbackStability:
    """The fallback flag groups every turn of one conversation on one key."""

    def setup_method(self):
        self.ex = SessionExtractor()

    def test_appending_turns_keeps_the_same_flag(self):
        base = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "first ask"}])
        extended = _cc_body(
            model="m",
            system="sys",
            messages=[
                {"role": "user", "content": "first ask"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "follow up question"},
            ],
        )
        assert self.ex.extract({}, None, base).flag == self.ex.extract({}, None, extended).flag

    def test_different_first_user_message_changes_the_flag(self):
        a = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "ask A"}])
        b = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "ask B"}])
        assert self.ex.extract({}, None, a).flag != self.ex.extract({}, None, b).flag

    def test_different_system_changes_the_flag(self):
        a = _cc_body(model="m", system="A", messages=[{"role": "user", "content": "x"}])
        b = _cc_body(model="m", system="B", messages=[{"role": "user", "content": "x"}])
        assert self.ex.extract({}, None, a).flag != self.ex.extract({}, None, b).flag

    def test_model_name_does_not_change_the_flag(self):
        # Only system + first user message anchor the hash, so a model bump on a
        # later turn (or a different route) keeps one conversation together.
        a = _cc_body(model="m1", system="sys", messages=[{"role": "user", "content": "x"}])
        b = _cc_body(model="m2", system="sys", messages=[{"role": "user", "content": "x"}])
        assert self.ex.extract({}, None, a).flag == self.ex.extract({}, None, b).flag


class TestFallbackAnchorQuality:
    """The content anchor must be specific enough not to merge conversations and
    stable enough not to split one: both mistakes show up upstream as a wrong
    session identity (a merged or a fresh conversation)."""

    def setup_method(self):
        self.ex = SessionExtractor()

    def test_shared_boilerplate_head_does_not_merge_two_conversations(self):
        # >100 characters of identical opening used to be enough to collide, which
        # merged two unrelated conversations onto one upstream session identity.
        boilerplate = "You are a helpful coding assistant working on a repository. " * 3
        first = _cc_body(
            model="m", system=boilerplate + "project alpha", messages=[{"role": "user", "content": "start"}]
        )
        second = _cc_body(
            model="m", system=boilerplate + "project beta", messages=[{"role": "user", "content": "start"}]
        )
        assert self.ex.extract({}, None, first).flag != self.ex.extract({}, None, second).flag

    def test_full_first_user_message_not_just_its_head(self):
        head = "please review this diff " * 10  # shared opening well past 100 characters
        a = _cc_body(model="m", system="s", messages=[{"role": "user", "content": head + "option A"}])
        b = _cc_body(model="m", system="s", messages=[{"role": "user", "content": head + "option B"}])
        assert self.ex.extract({}, None, a).flag != self.ex.extract({}, None, b).flag

    def test_masked_system_dynamics_keep_the_anchor_stable(self):
        def flag(system: str) -> str:
            body = _cc_body(model="m", system=system, messages=[{"role": "user", "content": "hi"}])
            return self.ex.extract({}, None, body).flag

        assert flag("Today is 2026-09-15T00:00:00Z.") == flag("Today is 2026-09-16T11:22:33.500+08:00.")
        assert flag("Today's date: 2026-09-15") == flag("Today's date: 2026-10-01")
        assert flag("request 3f2504e0-4f89-11d3-9a0c-0305e82c3301") == flag(
            "request 6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        )
        # Stable content still separates conversations.
        assert flag("Today is 2026-09-15. Project alpha.") != flag("Today is 2026-09-15. Project beta.")


class TestContentHashFallbackShape:
    """Body-shape edge cases of the content hash (defensive, must not raise)."""

    def setup_method(self):
        self.ex = SessionExtractor()

    def _flag(self, body):
        return self.ex.extract({}, None, body).flag

    def test_non_dict_body_is_stable(self):
        assert self._flag(None) == "msg:empty"
        assert self._flag("not-a-body") == "msg:empty"

    def test_body_without_params_is_stable(self):
        assert self._flag({"config": {}}) == "msg:empty"

    def test_string_system(self):
        flag = self._flag(_cc_body(model="m", system="system prompt", messages=[{"role": "user", "content": "hi"}]))
        assert flag.startswith("msg:")
        assert flag != "msg:empty"

    def test_list_system(self):
        flag = self._flag(_cc_body(model="m", system=[{"type": "text", "text": "p"}], messages=[]))
        assert flag.startswith("msg:")

    def test_string_content(self):
        flag = self._flag(_cc_body(model="m", system="s", messages=[{"role": "user", "content": "plain text"}]))
        assert flag.startswith("msg:")

    def test_list_content(self):
        flag = self._flag(
            _cc_body(model="m", system="s", messages=[{"role": "user", "content": [{"type": "text", "text": "part"}]}])
        )
        assert flag.startswith("msg:")

    def test_non_string_system_coerces(self):
        flag = self._flag(_cc_body(model="m", system=42, messages=[]))
        assert flag.startswith("msg:")

    def test_non_list_messages(self):
        flag = self._flag({"params": {"system": "s", "messages": "not-a-list"}})
        assert flag.startswith("msg:")

    def test_non_user_roles_do_not_contribute(self):
        a = self._flag(_cc_body(model="m", system="sys", messages=[{"role": "system", "content": "sys"}]))
        b = self._flag(_cc_body(model="m", system="sys", messages=[{"role": "tool", "content": "tool"}]))
        assert a == b


class TestValueHygiene:
    """Blank / over-long / control-character values are skipped."""

    def setup_method(self):
        self.ex = SessionExtractor()
        self.body = _cc_body(model="m", system="sys", messages=[{"role": "user", "content": "hi"}])

    def test_blank_value_falls_through(self):
        signal = self.ex.extract({"x-session-id": "   "}, None, self.body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    def test_value_is_trimmed(self):
        assert self.ex.extract({"x-session-id": "  abc  "}) == SessionSignal("header:abc", True)

    def test_value_at_max_length_is_kept(self):
        value = "a" * 200
        assert self.ex.extract({"x-session-id": value}) == SessionSignal(f"header:{value}", True)

    def test_over_long_value_falls_through(self):
        signal = self.ex.extract({"x-session-id": "a" * 201}, None, self.body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    @pytest.mark.parametrize("value", ["bad\nvalue", "bad\x00value", "bad\tvalue", "bad\x7fvalue"])
    def test_control_characters_fall_through(self, value):
        signal = self.ex.extract({"x-session-id": value}, None, self.body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    def test_invalid_value_continues_down_the_chain(self):
        # Same level: x-session-id is unusable, so x-session-affinity is next.
        signal = self.ex.extract({"x-session-id": "a" * 201, "x-session-affinity": "aff"}, None, self.body)
        assert signal == SessionSignal("affinity:aff", True)

    def test_hygiene_applies_to_metadata_user_id(self):
        req = _anthropic_request(metadata={"user_id": "user_abc\ndef"})
        signal = self.ex.extract({}, req, self.body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    def test_hygiene_applies_to_body_fields(self):
        signal = self.ex.extract({}, {"prompt_cache_key": "a" * 201}, self.body)
        assert signal.flag.startswith("msg:")
        assert signal.explicit is False

    def test_non_string_values_are_ignored(self):
        signal = self.ex.extract({"x-session-id": 12345}, None, self.body)
        assert signal.flag.startswith("msg:")


class TestSessionExtractorDerive:
    def setup_method(self):
        self.ex = SessionExtractor()

    def test_derive_returns_cmd_compatible_session_id(self):
        identity = self.ex.derive("msg:abc123", "key1")
        assert is_valid_cmd_session_id(identity.session_id)
        assert identity.session_id.startswith("sess_")
        assert len(identity.session_id) == 21

    def test_derive_returns_frozen_identity(self):
        identity = self.ex.derive("msg:abc123", "key1")
        assert isinstance(identity, SessionIdentity)
        with pytest.raises(dataclasses.FrozenInstanceError):
            identity.session_id = "sess_0000000000000000"

    def test_derive_returns_valid_slug_and_login(self):
        identity = self.ex.derive("msg:abc123", "key1")
        assert identity.project_slug
        assert identity.project_slug.islower()
        assert identity.project_slug in _PROJECT_SLUG_POOL
        assert identity.home_login in _HOME_LOGIN_POOL

    def test_derive_is_deterministic(self):
        assert self.ex.derive("msg:abc", "key1") == self.ex.derive("msg:abc", "key1")

    def test_derive_session_changes_per_key(self):
        assert self.ex.derive("msg:same", "key1").session_id != self.ex.derive("msg:same", "key2").session_id

    def test_home_login_is_stable_per_key_across_sessions(self):
        # One upstream key is one forged machine: every session it serves reports
        # the same home login, while session ids stay per session and projects are
        # drawn from that machine's own small palette.
        identities = [self.ex.derive(f"msg:session{i}", "key1") for i in range(32)]
        assert len({identity.home_login for identity in identities}) == 1

        slugs = {identity.project_slug for identity in identities}
        assert PROJECT_SLUGS_PER_ACCOUNT_MIN <= len(slugs) <= PROJECT_SLUGS_PER_ACCOUNT_MAX
        assert identities[0].session_id != identities[1].session_id
        assert identities[0].project_slug in slugs

    def test_same_session_on_another_key_changes_all_three_values(self):
        first = self.ex.derive("msg:same", "key1")
        second = self.ex.derive("msg:same", "key2")
        assert first.session_id != second.session_id
        assert first.project_slug != second.project_slug
        assert first.home_login != second.home_login

    def test_machine_works_in_a_small_palette_of_projects(self):
        # A real dev machine works in a handful of repositories, so one key must not
        # report a brand-new project for every session. Repeated projects are the
        # normal case, and every slug still comes from the shared pool.
        slugs = [self.ex.derive(f"msg:flag{i}", "key1").project_slug for i in range(200)]
        distinct = set(slugs)
        assert PROJECT_SLUGS_PER_ACCOUNT_MIN <= len(distinct) <= PROJECT_SLUGS_PER_ACCOUNT_MAX
        assert distinct <= set(_PROJECT_SLUG_POOL)
        assert len(slugs) > len(distinct) * 10

    def test_project_palette_is_a_pure_function_of_the_key(self):
        # No state and no memory: repeated calls and a fresh extractor derive the same
        # palette, so restarts, client rebuilds and rejoins can not move a session to
        # a different project.
        first = {SessionExtractor().derive(f"msg:flag{i}", "key1").project_slug for i in range(200)}
        second = {SessionExtractor().derive(f"msg:flag{i}", "key1").project_slug for i in range(200)}
        assert first == second
        assert self.ex.derive("msg:flag0", "key1").project_slug in first

    def test_palettes_vary_across_keys(self):
        # Every account samples its own subset: palettes differ, and no account is
        # restricted to the same handful of names as the others. An occasional shared
        # name is acceptable (two people on similarly named repos).
        palettes = {
            key: frozenset(self.ex.derive(f"msg:flag{i}", key).project_slug for i in range(200))
            for key in ("key1", "key2", "key3", "key4", "key5")
        }
        assert all(
            PROJECT_SLUGS_PER_ACCOUNT_MIN <= len(palette) <= PROJECT_SLUGS_PER_ACCOUNT_MAX
            for palette in palettes.values()
        )
        assert len(set(palettes.values())) == len(palettes)
        assert len(set().union(*palettes.values())) > PROJECT_SLUGS_PER_ACCOUNT_MAX

    def test_derive_validates_empty_inputs(self):
        with pytest.raises(ValueError):
            self.ex.derive("", "key1")
        with pytest.raises(ValueError):
            self.ex.derive("msg:abc", "")

    @pytest.mark.parametrize("bad", [123, None, []])
    def test_derive_validates_non_string_inputs(self, bad):
        with pytest.raises(ValueError):
            self.ex.derive(bad, "key1")
        with pytest.raises(ValueError):
            self.ex.derive("msg:abc", bad)


class TestIdentityPools:
    def test_project_slug_pool_is_expanded_and_unique(self):
        assert len(_PROJECT_SLUG_POOL) >= 64
        assert len(set(_PROJECT_SLUG_POOL)) == len(_PROJECT_SLUG_POOL)
        for slug in _PROJECT_SLUG_POOL:
            assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", slug)

    def test_home_login_pool_looks_like_real_logins(self):
        assert len(_HOME_LOGIN_POOL) == 64
        assert len(set(_HOME_LOGIN_POOL)) == len(_HOME_LOGIN_POOL)
        for login in _HOME_LOGIN_POOL:
            assert re.fullmatch(r"[a-z]{3,10}", login)
        # No generic service-account names: those would identify the adapter.
        assert not {"dev", "user", "root", "admin"} & set(_HOME_LOGIN_POOL)

    def test_digest_segments_do_not_overlap(self):
        # session_id reads digest[:8], the slug digest[8:12] and the login comes
        # from a separate key-only digest, so the 64-entry slug pool and the
        # 64-entry login pool stay independent of the session id.
        flags = [f"msg:flag{i}" for i in range(64)]
        identities = [SessionExtractor().derive(flag, "key1") for flag in flags]
        assert len({identity.session_id for identity in identities}) == 64
        assert len({identity.home_login for identity in identities}) == 1


class TestSessionExtractorSingleton:
    def test_get_session_extractor_returns_same_instance(self):
        a = get_session_extractor()
        b = get_session_extractor()
        assert a is b


class TestIsValidCmdSessionId:
    def test_valid_session_id(self):
        assert is_valid_cmd_session_id("sess_a1b2c3d4e5f60718") is True

    def test_wrong_length(self):
        assert is_valid_cmd_session_id("sess_abc") is False

    def test_no_prefix(self):
        assert is_valid_cmd_session_id("a1b2c3d4e5f60718xxxx") is False

    def test_uppercase_rejected(self):
        assert is_valid_cmd_session_id("sess_A1B2C3D4E5F60718") is False

    def test_empty(self):
        assert is_valid_cmd_session_id("") is False

    def test_non_string(self):
        assert is_valid_cmd_session_id(123) is False
