"""Session identity extraction and stateless session-id derivation.

Upstream session id / project slug derivation
---------------------------------------------
The upstream cmd CLI derives a per-process `sess_<16 hex>` id on startup and
keeps it stable for the process lifetime. The adapter can not imitate that
verbatim (it is a long-running server, not a short-lived CLI) without leaking
signals (one session id covering many distinct end-users).

Instead we derive both the upstream session id and the project slug from a
deterministic function of the inbound request and the chosen cmd key:

    fig          = sha256(stable_flag | cmd_key)
    session_id   = "sess_" + fig.hex()[:16]        # matches cmd CLI shape
    project_slug = POOL[fig uint32 % len(POOL)]    # looks like a real cwd slug

This makes every (stable_flag, cmd_key) pair land on a unique (session_id,
slug) tuple with no in-memory state. Switching cmd keys invalidates the
session id, which is the correct behavior: each cmd key is a different
upstream account and must not share session-scoped state.

Session identity extraction (CLIProxyAPI-style priority chain)
-------------------------------------------------------------
`SessionExtractor.extract()` walks the inbound request from the most explicit
client-provided session identity down to a content hash of the translated body:

1.  header ``x-claude-code-session-id``                -> ``claude:<value>``
2.  ``metadata.user_id`` on the inbound request        -> ``claude:session_<uuid>``
                                                          or ``user:<sha256[:16]>``
3.  header ``session-id`` / ``session_id`` (Codex)     -> ``codex:<value>``
4.  header ``x-http-session-id``                       -> ``http:<value>``
5.  header ``x-session-id``                            -> ``header:<value>``
    header ``x-session-affinity``                      -> ``affinity:<value>``
    header ``x-slot-session-id``                       -> ``slot:<value>``
6.  header ``x-conversation-id``                       -> ``conv:<value>``
    header ``x-thread-id``                             -> ``thread:<value>``
7.  ``prompt_cache_key``                               -> ``pck:<value>``
8.  ``conversation`` (string, or object with ``id``)   -> ``conv:<value>``
9.  ``session_id`` / ``sessionId``                     -> ``session:<value>``
    ``conversation_id`` / ``chat_id``                  -> ``conv:<value>``
10. content hash of the CC body (system + first user
    message, 100 chars each)                           -> ``msg:<hash16>``

Levels 1-9 carry a client-provided session identity and yield
``explicit=True``; level 10 is the derived fallback and yields
``explicit=False``. The fallback anchors on the system prompt plus the *first*
user message, so it stays identical while a conversation grows.

Sources are duck-typed: inbound headers, the inbound protocol request (dict or
pydantic model) and the translated CC body. Levels 7-9 are looked up on the
inbound request first and on the CC body second, so the chain also works when
only one of the two payloads is available (`CommandCodeClient.generate()`
passes the CC body only).

Deliberate exclusion: ``x-client-request-id`` is *not* part of the chain. It is
a per-request UUID in Claude Code traffic, so using it as a session identity
would scatter one conversation across keys; such requests intentionally fall
through to the stable content-hash level.

Value hygiene: values are trimmed, and empty / control-character / over-long
(> 200 chars) values are discarded, continuing down the chain.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


# Pool of plausible project slugs (lowercase, hyphenated, cwd-style).
# Sized so that a 16-element pool gives ~4 bits of spread per slug.
_PROJECT_SLUG_POOL: tuple[str, ...] = (
    "alpha-services",
    "analytics-pipeline",
    "auth-gateway",
    "checkout-service",
    "core-api",
    "data-platform",
    "edge-runtime",
    "frontend-app",
    "infra-automation",
    "ml-training",
    "notification-hub",
    "payment-service",
    "search-indexer",
    "storage-layer",
    "user-portal",
    "video-pipeline",
)

_CMD_SESSION_PATTERN = re.compile(r"^sess_[0-9a-f]{16}$")

# Claude Code sends `metadata.user_id` shaped like
# `user_<hash>_account_<uuid>_session_<uuid>`. Take the fragment after
# `session_` (tolerating the loose `[a-f0-9-]` token CLIProxyAPI matches, and
# hex tokens without canonical UUID dashes), ignore anything shorter than a
# realistic id, and fall back to the hashed raw value when nothing matches.
_USER_ID_SESSION_PATTERN = re.compile(r"session_([0-9a-fA-F][0-9a-fA-F-]{7,})")

_MAX_VALUE_LENGTH = 200
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def is_valid_cmd_session_id(value: str) -> bool:
    """True if value matches cmd CLI's per-process session id shape."""
    if not isinstance(value, str) or len(value) != 21:
        return False
    return bool(_CMD_SESSION_PATTERN.match(value))


def _field(obj: Any, name: str) -> Any:
    """Duck-typed field access: dict key, pydantic model field or attribute.

    Returns None when the object or the field is absent, so callers can keep
    walking the priority chain.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)

    value = getattr(obj, name, None)
    if value is not None:
        return value

    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
        except Exception:  # pragma: no cover - defensive: unhashable/odd models
            return None
        if isinstance(data, dict):
            return data.get(name)
    return None


@dataclass(frozen=True)
class SessionSignal:
    """Session identity carried from the inbound request to the CC upstream.

    flag: non-empty routing/disguise key, e.g. "claude:<uuid>", "pck:<value>".
    explicit: True only when the flag came from a client-provided session
        identity; the content-hash fallback sets it to False.
    """

    flag: str
    explicit: bool


class SessionExtractor:
    """Stateless extractor: request -> SessionSignal, then -> session id/slug."""

    _POOL_SIZE = len(_PROJECT_SLUG_POOL)

    def extract(
        self,
        headers: dict[str, str] | None,
        original: Any = None,
        body: Any = None,
    ) -> SessionSignal:
        """Return the session signal for an inbound request.

        `headers` are the inbound request headers, `original` is the inbound
        protocol request (dict or pydantic model) and `body` is the translated
        CC body used for the content-hash fallback. Both payloads are optional.
        """
        hdrs = self._normalize_headers(headers)

        # 1. Claude Code session header (most explicit identity available).
        if value := self._clean(hdrs.get("x-claude-code-session-id")):
            return SessionSignal(f"claude:{value}", True)

        # 2. metadata.user_id (Anthropic / Responses metadata object).
        metadata = self._lookup(original, body, "metadata")
        if value := self._clean(_field(metadata, "user_id")):
            return SessionSignal(self._user_id_flag(value), True)

        # 3. Codex-style session header.
        for name in ("session-id", "session_id"):
            if value := self._clean(hdrs.get(name)):
                return SessionSignal(f"codex:{value}", True)

        # 4. Antigravity-CLI style session header.
        if value := self._clean(hdrs.get("x-http-session-id")):
            return SessionSignal(f"http:{value}", True)

        # 5. Generic affinity headers.
        for name, prefix in (
            ("x-session-id", "header"),
            ("x-session-affinity", "affinity"),
            ("x-slot-session-id", "slot"),
        ):
            if value := self._clean(hdrs.get(name)):
                return SessionSignal(f"{prefix}:{value}", True)

        # 6. Conversation / thread headers.
        for name, prefix in (("x-conversation-id", "conv"), ("x-thread-id", "thread")):
            if value := self._clean(hdrs.get(name)):
                return SessionSignal(f"{prefix}:{value}", True)

        # 7. OpenAI prompt cache key (per-conversation, client-provided).
        if value := self._clean(self._lookup(original, body, "prompt_cache_key")):
            return SessionSignal(f"pck:{value}", True)

        # 8. Responses `conversation` (plain id or object carrying an id).
        conversation = self._lookup(original, body, "conversation")
        if conversation is not None:
            raw = conversation if isinstance(conversation, str) else _field(conversation, "id")
            if value := self._clean(raw):
                return SessionSignal(f"conv:{value}", True)

        # 9. Generic body-level session / conversation ids.
        for names, prefix in (
            (("session_id", "sessionId"), "session"),
            (("conversation_id", "chat_id"), "conv"),
        ):
            for name in names:
                if value := self._clean(self._lookup(original, body, name)):
                    return SessionSignal(f"{prefix}:{value}", True)

        # 10. Content-hash fallback: stable across the turns of a conversation.
        return SessionSignal(f"msg:{self._content_hash(body)}", False)

    def derive(self, stable_flag: str, cmd_key: str) -> tuple[str, str]:
        """Return (session_id, project_slug) for a (stable_flag, cmd_key) pair.

        Pure function: same inputs always yield the same outputs.
        """
        if not isinstance(stable_flag, str) or not stable_flag:
            raise ValueError("stable_flag must be a non-empty string")
        if not isinstance(cmd_key, str) or not cmd_key:
            raise ValueError("cmd_key must be a non-empty string")

        digest = hashlib.sha256(f"{stable_flag}|{cmd_key}".encode()).digest()
        session_id = f"sess_{digest.hex()[:16]}"
        slug = _PROJECT_SLUG_POOL[int.from_bytes(digest[:4], "big") % self._POOL_SIZE]
        return session_id, slug

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_headers(headers: dict[str, str] | None) -> dict[str, Any]:
        """Lowercase header names so lookups never depend on the caller."""
        if not headers:
            return {}
        try:
            items = headers.items()
        except AttributeError:  # pragma: no cover - defensive: non-mapping input
            return {}
        return {str(name).lower(): value for name, value in items}

    @staticmethod
    def _clean(value: Any) -> str | None:
        """Value hygiene: reject non-strings, blanks, control chars, over-long."""
        if not isinstance(value, str):
            return None
        if _CONTROL_CHARACTERS.search(value):
            return None
        text = value.strip()
        if not text or len(text) > _MAX_VALUE_LENGTH:
            return None
        return text

    @staticmethod
    def _lookup(original: Any, body: Any, name: str) -> Any:
        """Read a body-level field from the inbound request, then the CC body."""
        value = _field(original, name)
        if value is None:
            value = _field(body, name)
        return value

    @staticmethod
    def _user_id_flag(user_id: str) -> str:
        """Map `metadata.user_id` to a claude session flag or a hashed user flag."""
        match = _USER_ID_SESSION_PATTERN.search(user_id)
        if match:
            return f"claude:session_{match.group(1)}"
        return f"user:{hashlib.sha256(user_id.encode()).hexdigest()[:16]}"

    def _content_hash(self, body: Any) -> str:
        """Hash system + first user message (truncated to 100 chars each).

        The adapter sends a CC body ({..., params: {system, messages, ...}}) to
        the upstream. System and messages live inside *params*, not at the
        top level.

        Anchors are chosen so the hash is identical across every turn of one
        conversation: system prompt is stable, and only the first user message
        is taken (later user turns and assistant replies do not contribute).
        """
        params = body.get("params") if isinstance(body, dict) else {}
        if not isinstance(params, dict):
            params = {}
        if not params:
            return "empty"
        h = hashlib.sha256()
        h.update(f"sys:{self._first_text(params.get('system'))[:100]}\n".encode())
        user_text = self._first_text_from_role(params.get("messages", []), "user")
        if user_text:
            h.update(f"usr:{user_text[:100]}\n".encode())
        return h.hexdigest()[:16]

    @staticmethod
    def _first_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            return " ".join(parts)
        return str(value)

    @staticmethod
    def _first_text_from_role(messages: Any, role: str) -> str:
        if not isinstance(messages, list):
            return ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == role:
                return SessionExtractor._first_text(msg.get("content"))
        return ""


_SESSION_EXTRACTOR: SessionExtractor | None = None


def get_session_extractor() -> SessionExtractor:
    global _SESSION_EXTRACTOR
    if _SESSION_EXTRACTOR is None:
        _SESSION_EXTRACTOR = SessionExtractor()
    return _SESSION_EXTRACTOR
