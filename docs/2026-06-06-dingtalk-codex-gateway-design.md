# DingTalk Codex Gateway Design

Date: 2026-06-06
Status: Draft for user review
Project directory: `/root/dingtalk-codex-gateway`

## Goal

Build a local-first DingTalk single-chat bot gateway that can receive operator commands, route them through a safe whitelist, run CutiClub analysis tasks across Shopline, Shoplazza, and Meta Ads, and return Markdown results. The gateway must stay separate from `/root/cuticlubads` so it can later support multiple workspaces.

## Scope

### In scope for MVP

- Local HTTP test service, reachable on localhost only.
- `curl`-based message simulation before connecting real DingTalk callbacks.
- DingTalk single-chat bot architecture support for the later production phase.
- Whitelisted read/low-risk commands.
- Hybrid execution:
  - Fixed scripts for stable recurring workflows.
  - `codex exec` for complex analysis commands.
- Local command audit log.
- Markdown response output.
- Workspace-based routing, starting with CutiClub.
- Store-source routing for both Shopline and Shoplazza.

### Out of scope for MVP

- Public HTTPS callback deployment.
- Real DingTalk callback signature verification.
- Starting, pausing, creating, or editing Meta ads.
- Editing Shopline or Shoplazza products, discounts, theme, navigation, or orders.
- Arbitrary shell execution from DingTalk messages.
- Multi-user admin UI.

## Directory Layout

```text
/root/dingtalk-codex-gateway/
  README.md
  config/
    commands.yaml
    workspaces.yaml
  src/
    server.py
    router.py
    security.py
    dingtalk.py
    executors/
      script_executor.py
      codex_executor.py
  logs/
    commands.jsonl
  reports/
  docs/
    2026-06-06-dingtalk-codex-gateway-design.md
```

## Workspaces

The gateway treats business projects as external workspaces. CutiClub is the first workspace. A workspace can have multiple store data sources.

```yaml
workspaces:
  cuticlub:
    path: /root/cuticlubads
    allowed_write_paths:
      - /root/cuticlubads/ad_tests
      - /root/cuticlubads/MEETING_NOTES.md
      - /root/cuticlubads/TASKS.md
      - /root/cuticlubads/WEEKLY_LOG.md
```

The gateway code lives outside the CutiClub project. It may read from `/root/cuticlubads` and may write only to explicitly allowed reporting/memory paths.


## Store Sources

CutiClub currently needs two store integrations:

```yaml
stores:
  shopline:
    type: shopline
    mode: read_only_by_default
    allowed_actions:
      - list_orders
      - count_orders
      - get_order
      - list_products
      - get_product
  shoplazza:
    type: shoplazza
    mode: read_only_by_default
    allowed_actions:
      - list_orders
      - count_orders
      - get_order
      - list_products
      - get_product
```

MVP store behavior:

- Order and revenue reports should support `store=shopline`, `store=shoplazza`, and `store=all`.
- `store=all` aggregates both stores and keeps per-store subtotals.
- Revenue should use the store-native order total that includes shipping when available.
- Reports must label the data source clearly so Shopline and Shoplazza orders are not mixed without attribution.
- Store write operations remain blocked in DingTalk-triggered MVP commands.

## Command Model

### Allowed MVP commands

```text
广告日报 今天
广告日报 昨天
订单日报 今天
订单日报 今天 store=shopline
订单日报 今天 store=shoplazza
订单日报 今天 store=all
检查漏单 今天
广告状态
复杂分析 <自然语言任务>
```

### Command routing

- `广告日报` routes to a fixed reporting workflow when available.
- `订单日报` routes to a fixed store order summary workflow and supports Shopline, Shoplazza, or both stores.
- `检查漏单` routes to the existing CutiClub reconciliation workflow. First version may use Shopline-only reconciliation if Shoplazza ad attribution fields are not yet mapped; the report must say which stores are included.
- `广告状态` routes to a read-only Meta status workflow.
- `复杂分析` routes to `codex exec` with a strict safety prompt.

## Execution Strategy

### Fixed script executor

Used for recurring tasks with known inputs and outputs. This is the preferred executor for daily operations.

Expected behavior:

- Runs a predefined script or command.
- Uses a configured workspace path.
- Captures stdout/stderr.
- Writes a result summary into `reports/`.
- Returns Markdown.

### Codex executor

Used only for flexible analysis tasks that do not fit a fixed script.

Constraints:

- Working directory must be the configured workspace path.
- Prompt must include a mandatory safety preamble.
- Must not perform external write operations through MCP.
- Must not modify Meta ads, Shopline or Shoplazza products, discounts, theme, navigation, or orders.
- May write local reports or project memory only inside allowed paths.

Mandatory preamble:

```text
You are running from DingTalk Codex Gateway. This task is read-only for external systems. Do not create, pause, activate, edit, or delete ads. Do not edit Shopline or Shoplazza products, discounts, theme, navigation, or orders. You may read data and write local analysis reports only to allowed project paths.
```

## Security Rules

### Dangerous command rejection

Reject any command containing high-risk intent, including:

```text
启动广告
暂停广告
改预算
提高预算
降低预算
新建广告
创建广告
删除广告
改折扣
改产品
改主题
改导航
发真实订单
补发purchase
```

The rejection response should explain that the command is outside the DingTalk MVP permission scope and must be run manually in Codex with explicit confirmation.

### Localhost-only MVP

The first version binds to `127.0.0.1`, not `0.0.0.0`. This prevents external access until the callback phase is designed.

### Audit log

Every request writes one JSONL record:

```json
{
  "timestamp": "2026-06-06T10:00:00-04:00",
  "source": "local_test",
  "workspace": "cuticlub",
  "raw_text": "广告日报 今天",
  "normalized_command": "ad_daily_today",
  "executor": "script",
  "status": "success",
  "report_path": "reports/2026-06-06-ad-daily.md"
}
```

Logs must not include API tokens, DingTalk secrets, Meta tokens, Shopline tokens, Shoplazza tokens, order PII, or full customer details.

## Local API Shape

### Health check

```http
GET /health
```

Response:

```json
{"ok": true}
```

### Local message simulation

```http
POST /local/message
Content-Type: application/json

{
  "workspace": "cuticlub",
  "sender": "local-user",
  "text": "订单日报 今天 store=all"
}
```

Response:

```json
{
  "ok": true,
  "command": "order_daily_today_all_stores",
  "markdown": "...",
  "report_path": "reports/...md"
}
```

## DingTalk Production Phase

After local MVP works, add real DingTalk single-chat integration:

- DingTalk callback endpoint.
- Signature verification.
- Sender identity extraction.
- Authorized sender allowlist.
- Reply API or webhook response handling.
- Optional DingTalk markdown/card formatting.

This phase requires DingTalk app credentials and a public HTTPS callback URL or tunnel.

## Testing Plan

### Unit-level checks

- Command parser maps supported Chinese commands correctly.
- Dangerous commands are rejected.
- Unknown commands return help text.
- Workspace config refuses unknown workspace names.

### Local integration checks

- `GET /health` returns ok.
- `POST /local/message` with `订单日报 今天 store=all` returns Markdown with Shopline and Shoplazza subtotals.
- `POST /local/message` with `暂停广告` is rejected.
- Audit log receives one line per command.

### CutiClub-specific checks

- Reconciliation command can call existing scripts in `/root/cuticlubads`.
- Store reporting can read both Shopline and Shoplazza MCP/API data sources.
- Generated reports stay outside tokens/PII.
- No Meta, Shopline, or Shoplazza write tools are called from DingTalk-triggered tasks.

## Store Attribution Notes

Shopline and Shoplazza may expose different order fields for source, UTM, shipping, discounts, and total revenue. The MVP should normalize only the minimum needed fields for reporting:

```text
store, order_id, order_name, created_at, financial_status, fulfillment_status, total_price_including_shipping, currency, source_name, landing_site, note_attributes/raw_attribution
```

If a field is unavailable from one store, the report should show `unknown` rather than guessing.

## Open Questions Deferred Until Production

- Public callback hosting: domain, Cloudflare Tunnel, or other tunnel.
- DingTalk app credential storage path.
- Exact DingTalk reply mode: immediate response, async message, or both.
- Whether to support approval cards for high-risk actions in a later version.
