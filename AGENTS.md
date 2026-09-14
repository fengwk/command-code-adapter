# CC-Adapter — Agent Guide

## Commands

```bash
poetry install                        # install deps
poetry run pytest                     # run full test suite
poetry run pytest tests/test_tool_mapping.py -v  # single test file
poetry run black .                    # format (line-length 120)
poetry run python -m cc_adapter       # dev server (port 8080, or $CC_ADAPTER_PORT)
poetry run cc-adapter                 # same, via pyproject.toml scripts
bash run.sh                           # alternative: sources .env, runs uvicorn directly
docker build -t ${DOCKERHUB_NAMESPACE:-yourname}/command-code-proxy:latest .
docker compose up -d                  # docker-compose.yml + optional docker-compose.override.yml
```

**Version**: `pyproject.toml` `[tool.poetry].version` is the single source of truth. `core/constants.py` reads it at import via `_load_version()`. Both `main.py` and `admin/router.py` import `VERSION` from constants. Bump in pyproject.toml when releasing — do not edit constants.py.

**After each feature/fix**: bump the version in `pyproject.toml` before committing. Push the `docker` branch to trigger `docker-publish.yml`, which builds a multi-arch (`linux/amd64` + `linux/arm64`) image and pushes `docker` + `latest` + `sha-*` tags to `<DOCKERHUB_NAMESPACE>/command-code-proxy` on Docker Hub.

## Routes

| Path | Handler | Auth |
|---|---|---|
| `GET /` | `main.py` | none (redirects to /admin/) |
| `GET /health` | `main.py` | none |
| `POST /v1/chat/completions` | `providers/openai/router.py` | access_key |
| `POST /v1/messages` | `providers/anthropic/router.py` | access_key (or x-api-key) |
| `POST /v1/responses` | `providers/openai/responses_router.py` | access_key |
| `GET /v1/models` | `main.py` (dynamic via `get_models_data()`) | none |
| `GET /admin/api/models` | `admin/router.py` (public listing, no auth) | none |
| `GET /admin/api/ui-config` | `admin/router.py` (playground defaults) | none — intentionally public, exposes no secrets |
| `GET /admin/api/reasoning-effort` | `admin/router.py` (model → reasoning-effort map) | none — intentionally public, exposes no secrets |
| `GET /admin/api/models/status` | `admin/router.py` (model-fetch status) | none — intentionally public, exposes no secrets |
| `POST /admin/api/models/refresh` | `admin/router.py` | admin auth |
| `GET /admin/api/keys` | `admin/router.py` (per-key scheduler state + manual switch) | admin auth |
| `POST /admin/api/keys` | `admin/router.py` (add one upstream key) | admin auth |
| `DELETE /admin/api/keys/{suffix}` | `admin/router.py` (remove one upstream key) | admin auth |
| `DELETE /admin/api/sessions` | `admin/router.py` (drop session→key bindings) | admin auth |
| `POST /admin/api/keys/{suffix}/enable` | `admin/router.py` (switch key on: clears manual off + cooling/disabled + cached balance) | admin auth |
| `POST /admin/api/keys/{suffix}/disable` | `admin/router.py` (switch key off: never selected, unbinds its sessions) | admin auth |

Entry: `cc_adapter/__main__.py` → `main.py:run()` → uvicorn. Import: `from cc_adapter.main import app`.

**Module-level side effect**: `main.py:58` calls `cfg = AppConfig()` and `runtime_init(cfg, create_client(cfg))` at import time. Tests and any code that imports `cc_adapter.main` must be aware of this — it creates a real client with `.env` defaults.

**`docs/` is gitignored**: Documentation lives outside the repo. Do not create files under `docs/`.

## Config (prefix `CC_ADAPTER_`)

Fields in `core/config.py:AppConfig` (loaded eagerly from `.env` at import).

| Env var | Default | Notes |
|---|---|---|
| `CC_ADAPTER_CC_API_KEY` | — | `str \| list[str]` — JSON array: `["k1","k2"]`. Optional: the panel's key management (`POST /admin/api/keys`, `DELETE /admin/api/keys/{suffix}`) writes the pool into `CC_ADAPTER_ENV_FILE`, and the service starts without any key (requests then fail with `AuthenticationError`). |
| `CC_ADAPTER_ACCESS_KEY` | — | Bearer token auth (all endpoints) |
| `CC_ADAPTER_CC_BASE_URL` | `https://api.commandcode.ai` | |
| `CC_ADAPTER_DEFAULT_MODEL` | `deepseek/deepseek-v4-flash` | |
| `CC_ADAPTER_HOST` | `0.0.0.0` | |
| `CC_ADAPTER_PORT` | `8080` | |
| `CC_ADAPTER_LOG_LEVEL` | `INFO` | |
| `CC_ADAPTER_LOG_FORMAT` | `console` | or `json` |
| `CC_ADAPTER_ADMIN_PASSWORD` | — | Admin panel password |
| `CC_ADAPTER_HTTP_MAX_CONNECTIONS` | `200` | |
| `CC_ADAPTER_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `50` | |
| `CC_ADAPTER_HTTP2` | `false` | Per-key HTTP/2 (each key keeps its own pool and multiplexes only its own streams) |
| `CC_ADAPTER_KEY_COOLDOWN_BASE` | `60` | Rate-limit (429) cooldown start, seconds — doubles per failure |
| `CC_ADAPTER_KEY_COOLDOWN_MAX` | `1800` | Rate-limit cooldown cap, seconds |
| `CC_ADAPTER_KEY_CREDIT_COOLDOWN` | `1800` | Flat park window for an out-of-credits key, seconds |
| `CC_ADAPTER_ZDR` | `true` | Sends `x-cmd-zdr: 1` header (zero data retention) |
| `CC_ADAPTER_OSS_PRIMARY_PROVIDER` | — | Optional OSS provider name, sent as `x-oss-primary-provider` header |
| `CC_ADAPTER_ENV_FILE` | `.env` | Dotenv file read at startup **and rewritten by the admin panel** (`core/config.py:env_file_path()`). Point it at a mounted path (e.g. `/app/data/.env`) to persist panel changes — a single-file bind mount over `/app/.env` breaks the atomic rewrite (rename → EBUSY). Real environment variables still outrank this file, so anything the panel must own has to be absent from the container environment. Its directory is also the data directory (`core/config.py:data_dir()`): `token_usage.json`, `models_cache.json` and `cli_version.json` live there. |

- **The panel never receives a full key**: `GET /admin/api/keys` and `GET /admin/api/config` return masked forms, and `POST /admin/api/usage/query` masks each upstream key with `core/utils.py:mask_api_key()` (first 10 + last 6, `****` + last 4 for short keys) - the admin UI mirrors the rule in `admin/static/admin.js:maskToken()` and escapes every upstream-derived string at its `innerHTML` sink.
- **Keys are managed from the panel**: add/remove an upstream key at runtime (persisted into `CC_ADAPTER_ENV_FILE`, client rebuilt in-process, no restart) — nothing has to be injected as `CC_ADAPTER_CC_API_KEY`, and a zero-key startup is valid (requests fail with the client's own `AuthenticationError`). The Keys tab is the only key editor: the Configuration tab just reports `cc_api_key_count` and links there, and the Usage tab's token dialog adds keys through `POST /admin/api/keys` (it never rewrites the pool). A rebuild retires the old client with `schedule_close_when_idle()` instead of closing it outright, so a stream that is still being read keeps its pool until it ends (at most `CLIENT_CLOSE_GRACE_SECONDS`).

## Architecture

```
POST /v1/messages → providers/anthropic/request.py → command_code/client.py
POST /v1/chat/completions → providers/openai/request.py → command_code/client.py
Both translate to CC /alpha/generate body, stream SSE back.
```

- **Two translator pairs** in `providers/anthropic/` and `providers/openai/` (request→CC, response←CC); shared code in `providers/shared/`, `command_code/`, `core/`.
- **Singletons** owned by `core/runtime.py`: `_config`, `_cc_client`, translator instances (lazy init via `get_*()`). Also `_version_checker` and `_model_fetcher`.
- - **Balance probes are staggered**: the scheduler refreshes every key's credits on one cadence, so
  the background refresh delays each key by a deterministic per-key offset (`KEY_CREDITS_PROBE_SPREAD`, 4 min)
  instead of firing all probes in the same instant from one IP - a synchronized multi-key burst is a
  multi-account signature. The first (cold) fetch and explicit refreshes stay immediate.
**`get_or_create_client()`** at `runtime.py:41` — auto-creates a client with `AppConfig()` defaults if `init()` hasn't been called, logging a warning. Used by all routers when no client is available.
- **Auth headers**: `core/headers.py` — `extract_token()` (Bearer/x-api-key), `auth_error_response(message, protocol)` (401). Branches on `protocol: "openai" | "anthropic"` for correct error shape; `message` parameter allows custom error text.
- **Retry**: `core/retry.py` — `stream_with_retry()` drives a streaming request (`generate_fn` → `translate_fn`) for all three routers and retries once on an empty upstream response; the optional `_BufferDetector` (OpenAI chat with tools) spots that empty response before any visible delta, and `error_fn` turns a final failure into an SSE error event. Non-streaming requests go through the providers' own `collect_and_translate_*_nonstream()` helpers — there is no non-streaming retry helper. Inside `client.py:generate()` a retryable upstream error (402/429/400-insufficient-credits) or a key error (401/403) feeds `KeyScheduler.report()` and moves to the next key.
- **Admin auth**: HMAC-signed token in `core/auth.py` (not JWT); embeds `exp` (24h) + password hash prefix. API access validation at `core/auth.py:check_api_access()`. When `CC_ADAPTER_ADMIN_PASSWORD` is empty the admin API is **unauthenticated** (`verify_auth` short-circuits it; `main.py` logs a startup warning) — intranet-only deployments rely on this, do not reintroduce a 503 gate.
- **ID generation**: `generate_id(prefix, length)` in `core/utils.py`.
- **Constants**: `core/constants.py` — `STREAMING_HEADERS`, `NPM_URL`, `NPM_CACHE_TTL`, `NPM_ERROR_BACKOFF`, `NPM_FETCH_HEADERS`, `KEY_CREDITS_CACHE_TTL`, `KEY_CREDITS_ERROR_BACKOFF`, `KEY_CREDITS_PROBE_SPREAD`, `KEY_COOLDOWN_BASE`, `KEY_COOLDOWN_MAX`, `KEY_CREDIT_COOLDOWN`, `KEY_FORBIDDEN_COOLDOWN`, `KEY_MAX_CONCURRENT_STREAMS`, `SESSION_AFFINITY_TTL`, `SESSION_AFFINITY_MAX_ENTRIES`, `PROJECT_SLUGS_PER_ACCOUNT_MIN/MAX`, `CLIENT_CLOSE_GRACE_SECONDS`, `VERSION`. The three key cooldowns are also config fields (`CC_ADAPTER_KEY_COOLDOWN_BASE|MAX`, `CC_ADAPTER_KEY_CREDIT_COOLDOWN`) so deployments can tune them from the environment; `KEY_FORBIDDEN_COOLDOWN` and `KEY_MAX_CONCURRENT_STREAMS` are hardcoded disguise knobs.
- **Version checker**: Background npm polling, cached 30min, fallback `1.54.0` (env `CC_ADAPTER_DEFAULT_VERSION`). The last successfully fetched version is persisted to `cli_version.json` next to the other runtime data (`data_dir()`, i.e. beside `CC_ADAPTER_ENV_FILE`) and read back on construction, so a restart after a successful fetch never falls back to the constant; a failed fetch or a 200 without a `version` field leaves the file and the in-memory value untouched. See `core/version_checker.py`. Tests must set `_last_fetch_time = None` (not `0.0`) to guarantee cache invalidation.
- **Model fetcher**: `core/model_fetcher.py` — downloads the cmd CLI npm tarball (`registry.npmjs.org`, 30min TTL), extracts model ids/context windows/reasoning efforts and rebuilds the model list plus `MODEL_PROVIDER_MAP` / `MODEL_REASONING_EFFORTS_MAP` via `refresh_maps()`. Unknown model ids pass through unchanged, so new upstream models need no code change; the static tables in `catalog/models_data.py` / `providers/shared/model_mapping.py` are only the pre-fetch fallback. Both npm fetchers (this one and the version checker) pass `NPM_FETCH_HEADERS` so no `python-httpx/...` user agent ever reaches any socket.
- **Key scheduler**: `core/key_scheduler.py` — `KeyScheduler` replaces the old `KeyPool` (deleted). Owns per-key health (ok/cooling/disabled), credits, per-session sticky bindings and the first-sight distribution (round-robin for client identities, fill-first for content anchors). Bindings are carried across the panel's client rebuild via `export_affinity()` / `import_affinity()`, and `select(..., load=client.key_load)` applies the per-key concurrency cap.

### CC Request Headers

`make_cc_headers(api_key=None, *, identity=None, base_url=None)` in `headers.py` builds the headers for **every** CC API call and mimics real cmd CLI v1.54.0 traffic (verified against the CLI bundle and measured on the wire against a Node v24 `fetch`/undici request).

The dict is built in the exact byte order undici emits, and `tests/test_headers.py` locks it (a raw-socket capture re-measures what really leaves the process):

```
host, connection, Content-Type, User-Agent, x-command-code-version, x-cli-environment,
x-project-slug, x-taste-learning, [traceparent], x-session-id, Authorization,
[x-oss-primary-provider], x-cmd-zdr, accept, accept-language, sec-fetch-mode,
accept-encoding, Content-Length
```

- `connection: keep-alive`, `accept: */*`, `accept-language: *`, `sec-fetch-mode: cors`, `accept-encoding: gzip, deflate` are the undici defaults the CLI sends. Setting all four explicitly *replaces* the httpx defaults (`python-httpx/...`, `gzip, deflate, br, zstd`) instead of stacking on top of them, so no request ever advertises the HTTP library. The npm fetchers get the same treatment through `NPM_FETCH_HEADERS`.
- `host` is written first when `base_url` is passed (`httpx.URL(base_url).netloc`, the same value httpx would auto-generate); without it the transport prepends its own `Host`. `Content-Length` is the one header httpx appends itself (after our set, i.e. last, as undici does) and keeps httpx's capitalization.
- `x-command-code-version` (dynamic), `x-cli-environment: production`, `x-taste-learning: false` (the CLI always sends this header; the value is the real toggle state)
- `Authorization: Bearer <key>` when a key is given, `x-cmd-zdr: 1` when ZDR is on, `x-oss-primary-provider` when configured (before `x-cmd-zdr`)
- `traceparent` sits with the explicit CLI headers, right after `x-taste-learning`
- `x-co-flag` is **NOT** sent — the CLI never sends it, do not re-add it

`x-session-id` / `x-project-slug` are filled from `identity=` (a `SessionIdentity`); without one they are absent. They are derived per (session flag, chosen key) via `SessionExtractor.derive()`:

- `derive(flag, key)` returns a frozen `SessionIdentity(session_id, project_slug, home_login)`, each value read from a disjoint digest segment: `sess_<16 hex>` (from the session digest) + a slug from the key's own 4-8 entry palette (`PROJECT_SLUGS_PER_ACCOUNT_MIN/MAX`, drawn from a 64-entry pool) + a home login from a 64-entry pool (derived from the key **only**, so every session of one key reports the same forged machine)
- the same conversation on the same key always yields the same triple (mirrors the CLI's per-process id); another key yields a different session id, slug and — for a different login — home directory, which is intentional: each key is a different upstream account
- everything is a **pure function** of `(flag, key)`: no state, no cache, so a restart or a client rebuild never moves a session to another project. A key reports only its own handful of projects (a real machine works in a few repos); two keys may share a name, which is acceptable — session id and home always stay per key
- **Non-generate calls carry them too**: the real CLI signs *every* authed call with the session id of its process, so `key_scheduler._fetch_credits()` (billing/credits) and `admin/usage_client.py` (whoami, usage summary, billing credits/subscriptions, daily usage) pass `identity=process_identity(key)`. That identity is `derive(f"process:{_PROCESS_GENERATION}", key)`, where `_PROCESS_GENERATION` is a module-level `secrets.token_hex(8)` drawn once per process: stable for the process lifetime, different after a restart, and still a `sess_<16hex>` id plus a slug from that key's palette. `/alpha/generate` keeps its per-conversation identity.

### Per-key connection pools

`CommandCodeClient._client(key)` (client.py) keeps **one `httpx.AsyncClient` per upstream key** in `self._pools`, created lazily on that key's first attempt, so a keep-alive connection never carries a second key's `Authorization` header — the upstream cannot link two keys through TCP/TLS connection reuse. `aclose()` (and therefore `schedule_close_when_idle()`) closes and clears every pool. `CC_ADAPTER_HTTP_MAX_CONNECTIONS` / `_MAX_KEEPALIVE_CONNECTIONS` / `CC_ADAPTER_HTTP2` apply **per pool**; HTTP/2 stays off by default, and with `http2=True` each key multiplexes only its own streams. A caller-injected `http_client=` is shared by every key and bypasses that isolation (tests only), and is never closed by the client.

### CC Request Body

`body.py` constructs the body for `POST /alpha/generate` in the CLI's shape: `memory: null`, `taste: null`, `skills: null`, `permissionMode: "standard"`, and a `config` with

- `date: "YYYY-MM-DD"` (UTC), `environment` = node platform name (`linux` inside Docker)
- git/workspace metadata derived per project slug by `workspace_metadata(slug)` (`currentBranch`/`mainBranch`, `gitStatus`, `structure`) plus `recentCommits`: three commits derived deterministically from the slug. About 70% of slugs get the plain identity (`main`/`main`, `Working tree clean`, `["src/", "tests/", "docs/"]`); the rest spread over `develop` / `feature/<verb>-<slug word>`, a short dirty status (`M src/app.ts`, `?? notes.md`, …) and a variant layout (`["app/", "tests/", "scripts/"]`, …). All values are pure functions of the slug (sha256 digest bytes) and always single-line — they are interpolated into the upstream JSON body only, never into shell/HTML
- `workingDir` rewritten by `bind_workspace(config, slug, home_login)` (called from `client.py:generate()`) to `/home/<home_login>/proj/<slug>` so its basename equals the `x-project-slug` header, like the real CLI; the same call applies that slug's branch/status/layout variation. `make_config()` keeps the legacy default identity (`_DEFAULT_HOME_LOGIN = "dev"` → `/home/dev/proj/cc-adapter`) and the plain static metadata, so it is untouched by the per-slug derivation

Do **not** re-add `additionalDirectories` or an `env` field — the CLI sends neither. `_STATIC_CONFIG` deliberately does **NOT** contain an `"env"` field.

### Key routing & session affinity

`core/key_scheduler.py` (`KeyScheduler`, created for clients with 2+ keys) decides which upstream key serves a request:

- **Sticky**: an explicit client session identity (see the `SessionExtractor.extract()` chain: `x-claude-code-session-id`, `metadata.user_id`, `session-id`, `x-session-id`, `x-conversation-id`, `prompt_cache_key`, …) is bound to a key; a new session is bound round-robin in configured key order.
- An established binding outranks key order — a recovered key does not steal a session back.
- **First-sight distribution then stickiness**: an unbound conversation starts on the first usable key when the adapter only knows
  its content anchor (`explicit=False`) and on the next ring slot when the client provided an identity (`explicit=True`); either way the
  choice is bound to that session. Without the binding a content-anchored conversation would follow the head key's cooldown and back, so
  one conversation would keep showing up under two accounts.
- **Content anchor**: the fallback identity hashes the *full* system prompt and the *full* first user message (never truncated), with
  timestamps, dates and UUIDs in the system prompt masked - a truncated head merged unrelated conversations, and an unmasked clock split one
  conversation into a new identity every day.
- **Per-key isolation**: each key keeps its own httpx pool (no shared TCP/TLS connection) and its own forged machine — `workingDir` is `/home/<login>/proj/<slug>` with the login derived from the key alone. A conversation that moves to another key switches session id + slug, which is intended.
- Bindings slide: 1h TTL, 4096 entries, LRU eviction (`constants.py`). `export_affinity()` / `import_affinity()` carry them across a panel-driven client rebuild (`admin/config_manager.py:_recreate_client()`): a session bound to a key that is still configured keeps its key, a binding to a removed key is dropped. Without the carry-over every running conversation would be re-dealt by the fresh scheduler's round-robin.
- **Concurrency cap**: `KEY_MAX_CONCURRENT_STREAMS` (4) bounds how many streams one account serves at once. `select(..., load=client.key_load)` skips keys at the cap while any usable key is below it, and when *every* usable key is saturated it returns the least loaded one (ties keep configured order) — the cap spreads load, it never fails a request. A bound session keeps its key while that key has room; a saturated bound key is treated like an unusable one, so the session is rebound (documented in `select()`'s docstring). `CommandCodeClient` tracks the count per key (`key_load()`, `_key_inflight`) around each upstream attempt, so a retry only charges the key it moved to.
- Health: a 401 or an explicit `invalid_key` reason disables a key permanently and unbinds its sessions; a bare 403 (policy denial, not a revoked key) cools it down for the flat `KEY_FORBIDDEN_COOLDOWN` (2 h) and unbinds the session that hit it; 429 cools it down with escalating backoff (`KEY_COOLDOWN_BASE` → `KEY_COOLDOWN_MAX`); an out-of-credits failure (400 + "insufficient credits", or 402) parks the key for a flat `KEY_CREDIT_COOLDOWN` (30 min), zeroes its cached balance (the 30-min credits refresh, or `POST /admin/api/keys/{suffix}/enable`, clears it) and unbinds the affected session; 5xx changes nothing. `client.py:generate()` calls `report()` after every attempt.
- **Manual switch**: `POST /admin/api/keys/{suffix}/disable` marks a key off in `KeyScheduler._manual_off` — `_usable()` rejects it no matter its health or credits, and its bindings are dropped (the response reports `unbound_sessions`). `POST .../enable` clears the mark and runs `reset_key()` (health + cached balance + background credits refresh), so the key is selectable immediately; automatic cooldowns keep working while a key is on. `key_state()` exposes `enabled` / `manual` plus `cooldown_seconds` (remaining cooling seconds, `None` when not cooling), and `unavailable_summary()` renders an off key as `****abcd disabled by admin`.
- **Fail-fast**: when no key is usable, `select()` returns `None` and `client.py:_no_key_error()` raises the remembered `last_failure()` (status + upstream text) plus a per-key state summary — no extra upstream call is made. Tune the windows with `CC_ADAPTER_KEY_COOLDOWN_BASE` / `CC_ADAPTER_KEY_COOLDOWN_MAX` / `CC_ADAPTER_KEY_CREDIT_COOLDOWN`.
- Ops endpoints: `GET /admin/api/keys`, `DELETE /admin/api/sessions`, `POST /admin/api/keys/{suffix}/enable`, `POST /admin/api/keys/{suffix}/disable`.

## Translation quirks

**Shared (`providers/shared/`):**
- `session_extractor.py`: `extract(headers, original, body)` returns `SessionSignal(flag, explicit)` using the CLIProxyAPI-style priority chain (Claude Code header → `metadata.user_id` → `session-id` → `x-http-session-id` → `x-session-id`/affinity/slot → conversation/thread headers → `prompt_cache_key` → `conversation.id` → body session ids → content-hash fallback). `x-client-request-id` is deliberately excluded (per-request UUID). `derive(flag, key)` returns a frozen `SessionIdentity(session_id, project_slug, home_login)`; the login and the project palette are key-scoped, the session id and the slug chosen inside the palette are (flag, key)-scoped.
- `model_mapping.py`: `MODEL_PROVIDER_MAP` — bare names → canonical CC IDs. `clamp_reasoning_effort()` — nearest-higher clamping per model's supported range (from `MODEL_REASONING_EFFORTS_MAP`); unknown models drop the effort. Maps are mutable at runtime via `refresh_maps()`.
- `tool_mapping.py`: `normalize_schema()` (filePath↔path), `normalize_args()` (path/old_str/new_str→filePath/oldString/newString for file tools), `translate_tool_choice()` (auto/none/required↔type), `make_tool_call_block()`/`make_tool_result_block()`.

**OpenAI:**
- Model mapping: bare names → canonical CC IDs (e.g. `step-3-5-flash` → `stepfun/Step-3.5-Flash`). Unknown pass through.
- Silently drops: `top_p`, `stop`, `n`, `presence_penalty`, `frequency_penalty`, `user`, `response_format`.
- System prompt → top-level `system` field. `tool` role → `tool-call`/`tool-result` content blocks.
- `reasoning_effort`: clamped per model via `clamp_reasoning_effort()`. No prompt injection.

**Anthropic:**
- `thinking.budget_tokens` → `reasoning_effort`: `<4K=low, <8K=medium, <16K=high, >=16K=xhigh` (then clamped per model). Returns `None` when `thinking.enabled` without `budget_tokens`.
- Content blocks: `tool_use`→`tool-call`, `tool_result`→`tool-result`; `image`→warn+skip; `thinking`→pass.
- Auth: `x-api-key` or `Authorization: Bearer`.
- Unsupported: `top_p`, `top_k`, `stop_sequences`, `metadata`.

**Responses API (`providers/openai/responses_*.py`):**
- Converts `input` + `instructions` to CC `messages` format. `previous_response_id` unsupported (returns error).
- `reasoning.effort` clamped same as chat completions.

## Testing

- **Unit tests**: `pytest` + `pytest-asyncio`. Async tests need `@pytest.mark.asyncio`. Uses `ASGITransport(app=app)` + `respx` for HTTP mocking — no real HTTP or CC API key.
- **e2e tests**: `tests/e2e_test.sh` (7 scenarios via Docker). Run: `CC_ADAPTER_KEY=<key> bash tests/e2e_test.sh`. Note: `CC_ADAPTER_KEY` is the access_key (not the CC API key).
- **Known flaky**: `tests/test_main_auth.py:38 test_chat_completions_with_invalid_access_key` (cross-test singleton contamination in `runtime.py`).
- **Formatter**: black (line-length 120). No linter/typechecker.
- **Conftest**: `tests/conftest.py` has three autouse fixtures — `isolate_auth_env` (clears auth env vars), `isolate_runtime_data_dir` (points `CC_ADAPTER_ENV_FILE` at a session temp dir, so no test ever writes `cli_version.json`/`token_usage.json`/`models_cache.json` into the repository; tests that assert the default location override the variable themselves, e.g. `tests/test_data_dir.py`) and `configure_structlog_for_tests` (stdlib logging bridge). Structlog must be stdlib-configured for `caplog`/`capsys` to capture log output in tests.
- **Wire-level header test**: `tests/test_headers.py` sends a real POST to a loopback socket server and asserts the raw request line, because `respx` never serialises headers — it locks Host-first/Content-Length-last, the full ordered set and the absence of `python-httpx`.

## Docker

```bash
docker build -t ${DOCKERHUB_NAMESPACE:-yourname}/command-code-proxy:latest .
# Port conflict? Create docker-compose.override.yml mapping 8081:8080
docker compose up -d
```

**Container user**: the image runs as `appuser` (uid/gid pinned to 999 in `Dockerfile`). A deployment that mounts a
data directory for the panel-managed config either runs as that uid or overrides `user:` (the nas-aiproxy compose runs
as the host uid and sets `PYTHONDONTWRITEBYTECODE=1`, since nothing is written inside `/app` once configuration,
`token_usage.json`, `models_cache.json` and `cli_version.json` live next to `CC_ADAPTER_ENV_FILE`).

**Publishing to Docker Hub**: `.github/workflows/docker-publish.yml` runs on every push to the `docker` branch (and via `workflow_dispatch`). It logs in with `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets and pushes the image to `<DOCKERHUB_NAMESPACE>/command-code-proxy`. Set the `DOCKERHUB_NAMESPACE` repository variable to override the namespace; otherwise the workflow falls back to `DOCKERHUB_USERNAME`.

## End-of-work checklist

1. `poetry run pytest tests/` — all pass
2. `docker build` — image builds
3. `docker compose up -d` — container starts
4. `CC_ADAPTER_KEY=<key> bash tests/e2e_test.sh` — 7/7 scenarios pass (重点测试容器)
