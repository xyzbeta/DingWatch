# 系统设计文档 (v1.4.3)

本文档描述 DingWatch 的技术架构、核心业务逻辑及数据模型。

---

## 1. 架构概览

DingWatch 是基于 Python FastAPI 的轻量级告警中台，连接监控系统（Prometheus、Grafana、Alertmanager 等）与钉钉。采用前后端同体部署的单体架构。

### 核心组件

1.  **Webhook Receiver (接收器)**:
    *   统一入口，接收 JSON 或 Text 格式告警。
    *   异步队列：请求入队即返回 `{"status": "queued"}`，后台处理。

2.  **Alert Normalizer (归一化器) — v1.3 新增**:
    *   自动识别告警源格式（Prometheus、Grafana、自定义文本、通用 JSON）。
    *   将各平台字段映射为统一的标准键名（`namespace`、`workload`、`instance` 等）。
    *   支持中文键名自动翻译（`命名空间` → `namespace` 等）。

3.  **Rule Matcher (规则匹配器)**:
    *   对原始告警数据进行递归查找、正则匹配、多条件 AND/OR 运算。
    *   支持优先级排序和独占模式。

4.  **Message Renderer (消息渲染器) — v1.3 新增**:
    *   基于 Jinja2 模板引擎渲染钉钉消息。
    *   支持通道级自定义模板，留空使用格式默认模板。
    *   内置 `format_time` 过滤器（ISO 8601 → 北京时间）。

5.  **DingTalk Notifier (通知器)**:
    *   将渲染后的文本消息发送到钉钉 Webhook（v1.4.3 起统一使用 text 类型）。
    *   处理 `@手机号` 和 `@所有人` 逻辑。

6.  **Scheduler (调度器)**:
    *   APScheduler 每日凌晨 3 点清理过期日志。

---

## 2. 告警处理流程

```
HTTP POST /api/v1/webhook/send?env=生产环境  ← query params 注入 params
         │
         ▼
  读取 Body + Query Params ──→ JSON? ──是──→ JSON 解析
         │                      │
        否                      ▼
         │               detect_format()
         ▼                      │
  parse_text_to_alerts()        ▼
  (strip <br />)        normalize_alert()
         │                      │
         └──────→ 入队 ←────────┘
                      │
              webhook_worker (后台)
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
    Phase 1: DB 读取        extract_raw_alerts()
    (规则/通道/屏蔽)               │
          │                       ▼
          ▼               match_single_alert() × N
    db.close()            _resolve_channel_mem()
          │                       │
          ▼                       ▼
    Phase 2: 无 DB        render_message()
    (匹配/渲染/HTTP)              │
          │                       ▼
          ▼              dingtalk_client.send_text()
    等待钉钉响应                   │
          │                       ▼
          ▼              收集结果 (Phase 2 结束)
    Phase 3: 新 session
    (写 RequestLog 结果)
```

### 关键设计决策

*   **规则匹配使用原始数据**：保证用户规则配置不受归一化影响，向后兼容。
*   **逐条告警独立匹配 (v1.4.1)**：规则匹配粒度从 payload 级拆分为逐条 alert 级。多告警 payload 中每条告警独立评估规则，匹配到的走对应通道，未匹配的走默认通道。独占模式仅在当前告警层面生效，不影响同 payload 中其他告警。
*   **模板渲染使用归一化数据**：模板访问的是 `alert.details.namespace` 等标准键，跨格式统一。
*   **DB session 三阶段拆分 (v1.4.3)**：Phase 1 完成所有 DB 读取后立即关闭 session，Phase 2（匹配、渲染、钉钉 HTTP 调用）无 session 占用，Phase 3 用新 session 写入结果。避免 HTTP 调用期间持有数据库锁。
*   **URL 查询参数注入 (v1.4.3)**：请求 URL 中的 query string 自动解析为 `params` 字典注入模板上下文，用于传递告警 JSON 中缺失的环境标识等附加信息。
*   **消息类型统一为 text (v1.4.3)**：告警、公告、屏蔽通知、通道测试全部使用钉钉 text 消息类型，移除 markdown 依赖。
*   **时间归一化 (v1.4.1)**：`startsAt` 等时间字段在归一化阶段自动转为北京时间（Asia/Shanghai），模板中 `format_time` 过滤器保持幂等兼容。

---

## 3. 告警格式归一化

### 3.1 格式识别 (detect_format)

按优先级检测：

| 优先级 | 格式 | 识别特征 |
|--------|------|---------|
| 1 | custom_text | 含 `raw_message` 键（文本解析器设定） |
| 2 | prometheus | `alerts[].labels` 或 `alerts[].annotations` 存在 |
| 3 | grafana | `evalMatches` 存在，或 `ruleName` + `state` 存在 |
| 4 | generic_json | 以上均不匹配 |

### 3.2 字段归一化映射

归一化器将各平台字段映射到标准键，存储在 `alerts[].details` 中：

| 标准键 | Prometheus | Grafana | 自定义文本 | 通用 JSON |
|--------|-----------|---------|-----------|----------|
| `namespace` | `labels.namespace` | `tags.namespace` | `命名空间` / `所属空间` / `集群` | `namespace` |
| `workload` | `labels.deployment` / `statefulset` / `daemonset` | — | `资源名称` / `工作负载` | `deployment` |
| `instance` | `labels.instance` | `tags.host` | `实例` / `实例地址` | `instance` |
| `code` | `annotations.code` | — | `错误码` | `code` |
| `description` | `annotations.description` | — | `描述` | `description` |

### 3.3 状态映射

| 原始值 | 归一化 severity | 中文显示 |
|--------|----------------|---------|
| `critical` / `firing` / `alerting` | `critical` | 告警触发 |
| `warning` | `warning` | 告警触发 |
| `resolved` / `ok` / `info` | `info` | 告警恢复 |

---

## 4. 消息模板系统

### 4.1 模板引擎

基于 Jinja2，支持变量插值、条件判断、循环和自定义过滤器。

### 4.2 模板层级

1.  **通道自定义模板** (`NotificationChannel.message_template`)：优先级最高。
2.  **格式默认模板** (`DEFAULT_TEMPLATES`)：按 `prometheus` / `grafana` / `custom_text` / `generic_json` 各有一套，均为纯文本格式。
3.  **硬编码降级**：模板渲染异常时的最终兜底。

### 4.3 模板变量

| 变量 | 说明 |
|------|------|
| `title` | 告警标题 |
| `severity` | 告警级别（critical/warning/info） |
| `message` | 告警描述 |
| `source` | 告警来源格式（prometheus/grafana/custom_text/generic_json） |
| `alerts` | 告警条目列表，每条含 `name`、`level`、`description`、`time`、`details` |
| `raw_data` | 原始告警 JSON |
| `params` | **v1.4.3 新增** — URL 查询参数字典，键名为 query string key |

### 4.4 自定义过滤器

| 过滤器 | 输入 | 输出 |
|--------|------|------|
| `format_time` | `2026-04-28T09:23:09.987Z` | `2026-04-28 17:23:09` |

自动识别 ISO 8601 格式并转换为 Asia/Shanghai 时区。`0001-01-01T00:00:00Z`（Prometheus 未恢复告警占位值）返回空字符串。v1.4.1 起，归一化阶段已预先调用此转换，过滤器保持幂等（已格式化时间原样返回）。

---

## 5. 数据模型

### 5.1 NotificationChannel (v1.3 更新)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `name` | String | 通道名称 |
| `type` | String | 类型（dingtalk） |
| `config` | Text (JSON) | Webhook URL / Secret / Access Token |
| `is_enabled` | Boolean | 启用状态 |
| `message_template` | Text | **v1.3 新增** — Jinja2 模板，null=使用默认 |
| `created_at` | DateTime | 创建时间 |

### 5.2 Rule / RuleCondition

规则引擎核心。支持 AND/OR 多条件、优先级、独占模式。条件操作符支持 equals / contains / startswith / regex / exists。规则匹配针对原始 JSON 数据进行递归查找。

### 5.3 RequestLog

审计日志。记录每条 webhook 请求的 headers、body、最终状态、匹配规则、发送通道和钉钉响应。

### 5.4 Silence / SilenceCondition (v1.4 新增)

告警屏蔽规则。在规则匹配之后、钉钉发送之前拦截告警。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String | 屏蔽名称 |
| `reason` | String | 备注原因 |
| `starts_at` | DateTime | 开始时间 |
| `ends_at` | DateTime | 截止时间（过后自动失效） |
| `is_active` | Boolean | 可手动提前取消；取消时发送钉钉通知 |
| `match_mode` | String | AND / OR |
| `conditions` | [SilenceCondition] | 匹配条件列表 |

创建/取消屏蔽时，系统通过默认通道自动推送钉钉通知，包含名称、起止时间（北京时间）、匹配条件等信息。

### 5.5 其他实体

*   **User / Team** — 多对多关系，User 含 `phone_number` 用于钉钉 @。
*   **SystemSetting** — Key-Value 全局配置。
*   **ApiToken** — 外部调用鉴权 Token。
*   **Admin** — 管理员账号，密码 bcrypt 加密存储。

---

## 6. 性能优化

*   **SQLite WAL 模式**: 允许读写并发。
*   **异步队列**: 告警处理与 HTTP 响应解耦，避免阻塞。
*   **静态资源缓存**: `/static` 7 天强缓存。
*   **日志自动清理**: 定时删除过期 RequestLog，防止 DB 膨胀。
