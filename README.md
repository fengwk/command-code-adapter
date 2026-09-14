# Command Code Adapter

**中文** | [English](#english)

---

## 中文

将 [Command Code API](https://api.commandcode.ai) 暴露为兼容 OpenAI Chat Completions、Anthropic Messages 和 OpenAI Responses 格式的适配器。

支持**流式（SSE）**和**非流式**响应，附带 Web 管理面板。

> **兼容性说明：** `OpenAI Chat Completions`（`/v1/chat/completions`）适配效果最好，功能覆盖最完整，推荐优先使用。`Anthropic Messages` 和 `OpenAI Responses` 为基础适配，部分高级特性未覆盖。

### 快速开始

```bash
# 安装依赖
poetry install

# 配置 API Key
export CC_ADAPTER_CC_API_KEY=user_your_key_here

# 启动服务
poetry run python -m cc_adapter
```

服务启动后访问 `http://localhost:8080`，管理面板在 `http://localhost:8080/admin`。

### Docker

```bash
# 构建并运行
docker build -t cc-adapter .
docker run -p 8080:8080 -e CC_ADAPTER_CC_API_KEY=user_your_key_here cc-adapter

# 或使用 docker-compose（推荐）
# 编辑 .env 文件配置 CC_ADAPTER_CC_API_KEY，然后：
docker compose up -d
```

### 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CC_ADAPTER_CC_API_KEY` | — | Command Code API Key（必填） |
| `CC_ADAPTER_CC_BASE_URL` | `https://api.commandcode.ai` | CC API 地址 |
| `CC_ADAPTER_HOST` | `0.0.0.0` | 监听地址 |
| `CC_ADAPTER_PORT` | `8080` | 监听端口 |
| `CC_ADAPTER_LOG_LEVEL` | `INFO` | 日志级别 |
| `CC_ADAPTER_LOG_FORMAT` | `console` | 日志格式：`console` 或 `json` |
| `CC_ADAPTER_ADMIN_PASSWORD` | — | 管理面板密码（留空则无需认证） |
| `CC_ADAPTER_ACCESS_KEY` | — | API 访问密钥（留空则无需认证） |
| `CC_ADAPTER_DEFAULT_MODEL` | `deepseek/deepseek-v4-flash` | 管理面板 Playground 默认模型 |
| `CC_ADAPTER_HTTP_MAX_CONNECTIONS` | `200` | HTTP 连接池最大连接数 |
| `CC_ADAPTER_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `50` | HTTP 连接池最大 Keepalive 连接数 |
| `CC_ADAPTER_HTTP2` | `false` | 启用 HTTP/2 |
| `CC_ADAPTER_KEY_COOLDOWN_BASE` | `60` | 限流（429）冷却起始秒数，每次失败翻倍 |
| `CC_ADAPTER_KEY_COOLDOWN_MAX` | `1800` | 限流冷却上限（秒） |
| `CC_ADAPTER_KEY_CREDIT_COOLDOWN` | `1800` | 额度用尽的 Key 冷却时长（秒，固定值） |
| `CC_ADAPTER_ZDR` | `true` | 发送 `x-cmd-zdr: 1` 请求头（零数据留存） |
| `CC_ADAPTER_OSS_PRIMARY_PROVIDER` | — | 可选的 OSS 提供商名称，作为 `x-oss-primary-provider` 请求头发送 |
| `CC_ADAPTER_ENV_FILE` | `.env` | 配置文件路径（管理面板读写此文件，见下） |

也可通过 `.env` 文件配置（参考 `.env.example`）。

管理面板保存的配置会写回 `CC_ADAPTER_ENV_FILE` 指向的文件（默认工作目录下的 `.env`）。容器里想持久化面板改动，把它指向挂载卷内的路径即可，例如：

```yaml
environment:
  CC_ADAPTER_ENV_FILE: /app/data/.env
volumes:
  - ./data:/app/data
```

两点注意：① 不要用单文件挂载 `/app/.env`——面板的原子写入（临时文件 + `rename`）在单文件挂载上会报 `EBUSY`；② 环境变量优先级高于该文件，想让某个字段"由面板管理"，就不要再用环境变量注入它（否则重启后被环境变量覆盖）。

### 多 Key 路由

配置多个 Key（`CC_ADAPTER_CC_API_KEY=["k1","k2"]`）时，适配器按"会话粘性 + 首可用优先"分配上游 Key：

- 客户端带会话标识时（Claude Code 的 `x-claude-code-session-id` / `metadata.user_id`、Codex 的 `session-id`、`x-session-id`、`prompt_cache_key` 等），同一会话固定使用同一个 Key；新会话按配置顺序轮询分配 —— 目的是最大化上游 prompt cache 命中率。
- 识别不到会话标识的请求固定使用第一个可用 Key（fill-first），保证行为可预期。
- Key 故障自动切换：401/403 直接禁用该 Key；限流（429）进入指数冷却（默认 60s → 上限 1800s）；**额度用尽**（上游返回 insufficient credits）会把该 Key 固定冷却一段时间（默认 30 分钟，可用 `CC_ADAPTER_KEY_CREDIT_COOLDOWN` 调整）并清掉其已知余额；冷却/禁用会解除受影响会话的绑定，重试时自动绑定到健康 Key。
- 所有 Key 都不可用时**不再消耗上游调用**，直接返回最后一个 Key 的失败信息（附各 Key 状态摘要）。
- 手动开关：面板可单独把某个 Key 关掉/打开。关掉后该 Key **永不被选中**（无视其额度与健康状态），其绑定的会话立即解绑并在下次请求切到其他 Key；打开后**立即可用**（清除手动标记与冷却/禁用状态、丢弃已缓存的余额并后台刷新），充值后用它恢复即可。自动冷却逻辑与手动开关互不影响。
- 运维接口（需管理员认证）：`GET /admin/api/keys` 查看各 Key 状态/额度/绑定会话数（含 `enabled`/`manual`/`cooldown_seconds`），`DELETE /admin/api/sessions` 清空绑定，`POST /admin/api/keys/{后四位}/disable` 关闭某个 Key，`POST /admin/api/keys/{后四位}/enable` 打开（解除冷却/禁用并清除余额缓存）。

### 日志

日志格式通过 `CC_ADAPTER_LOG_FORMAT` 控制（默认 `console`）。

**Console 格式**（默认）— 人眼可读的结构化单行日志：

```
07:42:18 INFO  app.start        base=https://api.commandcode.ai port=8080
07:42:31 INFO  openai.request   model=deepseek-v4-flash stream=true message_count=3 tools=true req=8f3a91c2
07:42:33 WARNING  upstream.retry   reason=empty_response attempt=1 max_attempts=2 req=8f3a91c2
07:42:34 INFO  upstream.usage   model=deepseek-v4-flash input=120 output=834 total=954 elapsed=2.1s req=8f3a91c2
07:42:34 INFO  http.done        method=POST path=/v1/chat/completions status_code=200 elapsed=2.48s req=8f3a91c2
```

**JSON 格式** — 机器解析用结构化格式：

```json
{"event": "http.done", "level": "info", "logger": "cc_adapter.main", "method": "POST", "path": "/v1/chat/completions", "status_code": 200, "elapsed": "2.480s", "request_id": "8f3a91c2", "timestamp": "2026-05-13T07:42:34Z"}
```

**事件列表：** `app.start`、`http.done`、`openai.request`、`anthropic.request`、`responses.request`、`upstream.error`、`upstream.retry`、`upstream.usage`、`tool.call`、`auth.failed`、`admin.login.failed`、`admin.config.updated`、`admin.verify_key`

每个请求日志会输出 `reasoning_effort`（客户端请求值）和 `cc_reasoning_effort`（clamp 后实际发送值），以及 `thinking_budget`（Anthropic 模式）。

**脱敏：** 敏感字段（authorization、API key、messages、tool 编辑参数、路径信息等）自动替换为 `***`。

### 使用

**OpenAI Chat Completions：**

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

**Anthropic Messages：**

```bash
curl http://localhost:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: sk-your-key" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

兼容任意 OpenAI SDK：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)
```

### Reasoning Effort

适配器支持 `reasoning_effort` 参数，用于控制模型的思考推理强度。

| 值 | 说明 |
|---|---|
| `"off"` | 关闭推理输出（响应端过滤 `reasoning-delta`） |
| `"low"` | 最小推理 |
| `"medium"` | 中等推理 |
| `"high"` | 较高推理 |
| `"xhigh"` | 高推理 |
| `"max"` | 最大推理 |
| `null` / 不传 | 不设推理 |

支持的取值因模型而异。适配器内置了 `MODEL_REASONING_EFFORTS_MAP`（来源：CC v0.26.7 客户端数据），当传入的强度值超出模型支持范围时，自动向上最近值（nearest-higher）映射。模型不在映射表中时不设该参数。

| 模型 | 支持的值 |
|---|---|---|
| deepseek/deepseek-v4-* | high, max |
| claude-sonnet-4-6, claude-opus-4-6/7, claude-opus-5 | low, medium, high, xhigh, max |
| gpt-5.5, gpt-5.4, gpt-5.3-codex | low, medium, high, xhigh |
| gpt-5.4-mini, claude-haiku-4-5, qwen-3-7-*, mimo-v2.5, inkling-small | low, medium, high |

实现：对 `reasoning_effort` 按模型支持范围进行 clamp（nearest-higher）后透传给 CC API，不注入任何 system prompt。响应端保留 `reasoning-delta` 的过滤逻辑（`"off"` 模式下剥离 `reasoning_content`）。

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Solve 2x+5=13"}],
    "reasoning_effort": "high",
    "stream": true
  }'
```

### 运行测试

```bash
poetry run pytest
```

### 目录结构

```
cc_adapter/
├── main.py                # FastAPI 应用入口与路由
├── core/                  # 基础设施
│   ├── config.py          #   配置管理（pydantic-settings）
│   ├── errors.py          #   错误处理与状态码映射
│   ├── logging.py         #   日志配置与中间件
│   ├── auth.py            #   认证逻辑（HMAC token）
│   ├── runtime.py         #   运行时单例（config/client/translator）
│   └── utils.py           #   工具函数
├── command_code/          # CC API 客户端
│   ├── client.py          #   HTTP 客户端
│   ├── headers.py         #   请求头构造
│   └── body.py            #   请求体构造
├── providers/             # 协议翻译
│   ├── openai/            #   OpenAI 兼容
│   │   ├── router.py      #   POST /v1/chat/completions
│   │   ├── models.py      #   数据模型
│   │   ├── request.py     #   OpenAI → CC
│   │   └── response.py    #   CC → OpenAI
│   ├── anthropic/         #   Anthropic 兼容
│   │   ├── router.py      #   POST /v1/messages
│   │   ├── models.py      #   数据模型
│   │   ├── request.py     #   Anthropic → CC
│   │   └── response.py    #   CC → Anthropic
│   └── shared/            #   共享工具
│       ├── model_mapping.py  # 模型名映射
│       └── tool_mapping.py   # 工具参数名映射
├── catalog/               # 数据目录
│   └── models_data.py     #   模型列表
└── admin/                 # Web 管理面板
    └── ...                #   管理界面
```

---

## English

Exposes the [Command Code API](https://api.commandcode.ai) as OpenAI Chat Completions, Anthropic Messages, and OpenAI Responses compatible adapters.

Supports **streaming (SSE)** and **non-streaming** responses, with a built-in web admin panel.

> **Compatibility note:** `OpenAI Chat Completions` (`/v1/chat/completions`) has the best adaptation with full feature coverage and is recommended for primary use. `Anthropic Messages` and `OpenAI Responses` provide basic adaptation with limited advanced feature support.

### Quick Start

```bash
# Install dependencies
poetry install

# Configure API Key
export CC_ADAPTER_CC_API_KEY=user_your_key_here

# Start server
poetry run python -m cc_adapter
```

Once started, visit `http://localhost:8080`. The admin panel is at `http://localhost:8080/admin`.

### Docker

```bash
# Build and run
docker build -t cc-adapter .
docker run -p 8080:8080 -e CC_ADAPTER_CC_API_KEY=user_your_key_here cc-adapter

# Or use docker-compose (recommended)
# Edit the .env file to set CC_ADAPTER_CC_API_KEY, then:
docker compose up -d
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CC_ADAPTER_CC_API_KEY` | — | Command Code API Key (required) |
| `CC_ADAPTER_CC_BASE_URL` | `https://api.commandcode.ai` | CC API base URL |
| `CC_ADAPTER_HOST` | `0.0.0.0` | Listen address |
| `CC_ADAPTER_PORT` | `8080` | Listen port |
| `CC_ADAPTER_LOG_LEVEL` | `INFO` | Log level |
| `CC_ADAPTER_LOG_FORMAT` | `console` | Log format: `console` or `json` |
| `CC_ADAPTER_ADMIN_PASSWORD` | — | Admin panel password (leave blank for no auth) |
| `CC_ADAPTER_ACCESS_KEY` | — | API access key (leave blank for no auth) |
| `CC_ADAPTER_DEFAULT_MODEL` | `deepseek/deepseek-v4-flash` | Admin Playground default model |
| `CC_ADAPTER_HTTP_MAX_CONNECTIONS` | `200` | HTTP connection pool max connections |
| `CC_ADAPTER_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `50` | HTTP connection pool max keepalive connections |
| `CC_ADAPTER_HTTP2` | `false` | Enable HTTP/2 |
| `CC_ADAPTER_KEY_COOLDOWN_BASE` | `60` | Rate-limit (429) cooldown start in seconds, doubles per failure |
| `CC_ADAPTER_KEY_COOLDOWN_MAX` | `1800` | Rate-limit cooldown cap in seconds |
| `CC_ADAPTER_KEY_CREDIT_COOLDOWN` | `1800` | Flat cooldown for an out-of-credits key, in seconds |
| `CC_ADAPTER_ZDR` | `true` | Send `x-cmd-zdr: 1` header (zero data retention) |
| `CC_ADAPTER_OSS_PRIMARY_PROVIDER` | — | Optional OSS provider name, sent as `x-oss-primary-provider` header |
| `CC_ADAPTER_ENV_FILE` | `.env` | Config file path (the admin panel reads and rewrites this file) |

You can also configure via a `.env` file (see `.env.example`).

Config saved in the admin panel is written back to the file referenced by `CC_ADAPTER_ENV_FILE` (`.env` in the working directory by default). To persist panel changes in a container, point it at a mounted volume:

```yaml
environment:
  CC_ADAPTER_ENV_FILE: /app/data/.env
volumes:
  - ./data:/app/data
```

Two caveats: (1) do not bind-mount a single file over `/app/.env` — the panel's atomic rewrite (temp file + `rename`) fails with `EBUSY` on a single-file mount; (2) environment variables outrank that file, so a field you want the panel to manage must not be injected as an environment variable.

### Multi-key routing

With more than one key configured (`CC_ADAPTER_CC_API_KEY=["k1","k2"]`) the adapter assigns upstream keys by session stickiness plus first-usable fallback:

- Requests carrying a session identity (Claude Code `x-claude-code-session-id` / `metadata.user_id`, Codex `session-id`, `x-session-id`, `prompt_cache_key`, …) stick to one key per conversation; new sessions are bound round-robin in configured order — this maximizes upstream prompt-cache hits.
- Requests without a session identity always use the first usable key (fill-first).
- Failures fail over automatically: 401/403 disables a key, a rate limit (429) puts it in escalating cooling backoff (60s → 1800s cap), and an out-of-credits response parks it for a flat window (`CC_ADAPTER_KEY_CREDIT_COOLDOWN`, default 30 min) while zeroing its cached balance; parked keys unbind the affected sessions, which rebind to a healthy key on retry.
- When every key is unusable the adapter makes **no further upstream call** and returns the last key's failure together with a per-key state summary.
- Manual switch: the panel can turn an individual key off/on. Off means the key is **never selected** (regardless of its credits or health) and its bound sessions are unbound immediately, so the next turn moves to another key; on makes it **immediately selectable** (manual mark plus cooling/disabled state cleared, cached balance dropped and refreshed in the background), which is the way to restore a key right after a top-up. Automatic cooldowns keep working independently of the switch.
- Ops endpoints (admin auth required): `GET /admin/api/keys` (state/credits/bound sessions per key, plus `enabled`/`manual`/`cooldown_seconds`), `DELETE /admin/api/sessions` (drop all bindings), `POST /admin/api/keys/{last4}/disable` (take a key out of rotation), `POST /admin/api/keys/{last4}/enable` (clear manual off + cooling/disabled + cached balance).

### Logging

The log format is controlled by `CC_ADAPTER_LOG_FORMAT` (default: `console`).

**Console format** (default) — human-readable single-line logs:

```
07:42:18 INFO  app.start        base=https://api.commandcode.ai port=8080
07:42:31 INFO  openai.request   model=deepseek-v4-flash stream=true message_count=3 tools=true req=8f3a91c2
07:42:33 WARNING  upstream.retry   reason=empty_response attempt=1 max_attempts=2 req=8f3a91c2
07:42:34 INFO  upstream.usage   model=deepseek-v4-flash input=120 output=834 total=954 elapsed=2.1s req=8f3a91c2
07:42:34 INFO  http.done        method=POST path=/v1/chat/completions status_code=200 elapsed=2.48s req=8f3a91c2
```

**JSON format** — structured for machine parsing:

```json
{"event": "http.done", "level": "info", "logger": "cc_adapter.main", "method": "POST", "path": "/v1/chat/completions", "status_code": 200, "elapsed": "2.480s", "request_id": "8f3a91c2", "timestamp": "2026-05-13T07:42:34Z"}
```

**Event names:** `app.start`, `http.done`, `openai.request`, `anthropic.request`, `responses.request`, `upstream.error`, `upstream.retry`, `upstream.usage`, `tool.call`, `auth.failed`, `admin.login.failed`, `admin.config.updated`, `admin.verify_key`

Each request log includes `reasoning_effort` (client-requested) and `cc_reasoning_effort` (clamped value sent to CC), plus `thinking_budget` for Anthropic mode.

**Redaction:** Sensitive fields (authorization, API keys, messages, tool edit parameters, paths) are automatically replaced with `***`.

### Usage

**OpenAI Chat Completions:**

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

**Anthropic Messages:**

```bash
curl http://localhost:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: sk-your-key" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Compatible with any OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)
```

### Reasoning Effort

The adapter supports the `reasoning_effort` parameter to control the model's reasoning/thinking intensity.

| Value | Description |
|---|---|
| `"off"` | Suppress reasoning output (response-side `reasoning-delta` filtering) |
| `"low"` | Minimal reasoning |
| `"medium"` | Moderate reasoning |
| `"high"` | High reasoning |
| `"xhigh"` | Extra high reasoning |
| `"max"` | Maximum reasoning |
| `null` / not set | No reasoning effort set |

Supported values vary per model. The adapter uses `MODEL_REASONING_EFFORTS_MAP` (sourced from CC v0.26.7 client data). When a value exceeds a model's supported range, it is clamped to the nearest higher supported value. Models not in the map get no `reasoning_effort` param.

| Model | Supported Values |
|---|---|---|
| deepseek/deepseek-v4-* | high, max |
| claude-sonnet-4-6, claude-opus-4-6/7, claude-opus-5 | low, medium, high, xhigh, max |
| gpt-5.5, gpt-5.4, gpt-5.3-codex | low, medium, high, xhigh |
| gpt-5.4-mini, claude-haiku-4-5, qwen-3-7-*, mimo-v2.5, inkling-small | low, medium, high |

Implementation: clamps `reasoning_effort` to the model's supported range (nearest-higher), then forwards to CC API. **No system prompt injection**. Response-side filtering strips `reasoning-delta` events when set to `"off"`.

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Solve 2x+5=13"}],
    "reasoning_effort": "high",
    "stream": true
  }'
```

### Running Tests

```bash
poetry run pytest
```

### Directory Structure

```
cc_adapter/
├── main.py                # FastAPI app entry & routes
├── core/                  # Infrastructure
│   ├── config.py          #   Configuration (pydantic-settings)
│   ├── errors.py          #   Error handling & status code mapping
│   ├── logging.py         #   Logging & middleware
│   ├── auth.py            #   Auth (HMAC token)
│   ├── runtime.py         #   Runtime singletons
│   └── utils.py           #   Utility functions
├── command_code/          # CC API client
│   ├── client.py          #   HTTP client
│   ├── headers.py         #   Request headers
│   └── body.py            #   Request body builder
├── providers/             # Protocol translators
│   ├── openai/            #   OpenAI-compatible
│   │   ├── router.py      #   POST /v1/chat/completions
│   │   ├── models.py      #   Data models
│   │   ├── request.py     #   OpenAI → CC
│   │   └── response.py    #   CC → OpenAI
│   ├── anthropic/         #   Anthropic-compatible
│   │   ├── router.py      #   POST /v1/messages
│   │   ├── models.py      #   Data models
│   │   ├── request.py     #   Anthropic → CC
│   │   └── response.py    #   CC → Anthropic
│   └── shared/            #   Shared utilities
│       ├── model_mapping.py  # Model name mapping
│       └── tool_mapping.py   # Tool param name mapping
├── catalog/               # Data directory
│   └── models_data.py     #   Model listings
└── admin/                 # Web admin panel
    └── ...                #   Admin interface
```

### License

MIT
