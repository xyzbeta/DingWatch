# OpenAPI 接口文档 (v1.4.1)

DingWatch 提供 RESTful API 用于与外部系统集成。本文档说明核心接口的调用方式。

---

## 1. 访问在线文档

*   **Swagger UI**: `http://<server-ip>:8000/api/docs`
*   **OpenAPI JSON**: `http://<server-ip>:8000/api/openapi.json`

---

## 2. 认证方式

### Webhook 接口

默认开放。若在系统设置中开启「Webhook 接口认证」：

*   **Header**: `X-API-Token`
*   **值**: 在「系统设置 → API 访问令牌」中生成的 Token。

### 管理接口

管理接口（`/api/v1/settings/*`、`/api/v1/users` 等）需要 Cookie 认证（通过 Web UI 登录获取）。

---

## 3. 核心接口

### 3.1 发送告警 (Webhook) — `POST /api/v1/webhook/send`

系统唯一入口，接收外部监控系统的告警。

*   **Content-Type**: `application/json` 或 `text/plain`
*   **响应**: `{"status": "queued", "log_id": 123}` — 告警入队即返回，后台异步处理。

#### 格式示例

**Prometheus Alertmanager：**
```json
{
  "receiver": "monitor_webhook",
  "status": "firing",
  "alerts": [{
    "status": "firing",
    "labels": {
      "alertname": "ReplicaMismatch",
      "namespace": "dx-insight",
      "deployment": "dx-insight",
      "instance": "10.162.63.254:8080",
      "severity": "critical"
    },
    "annotations": {
      "code": "K810",
      "description": "Deployment 期望副本数和可用副本数不匹配。"
    },
    "startsAt": "2026-04-28T09:23:09.987Z"
  }],
  "commonLabels": {"severity": "critical"},
  "commonAnnotations": {"description": "Deployment 期望副本数和可用副本数不匹配。"},
  "externalURL": "http://alertmanager:9093"
}
```

**Grafana：**
```json
{
  "dashboardId": 1,
  "evalMatches": [{"value": 95, "metric": "disk_usage", "tags": {"host": "db-01", "namespace": "prod"}}],
  "message": "磁盘使用率超过95%阈值",
  "ruleName": "磁盘监控",
  "state": "alerting",
  "title": "[Alerting] 磁盘监控"
}
```

**自定义文本：**
```
规则名称: cpu
告警级别: critical
集群: kpanda-global-cluster
命名空间: mcamel-system
资源名称: rfr-mcamel-common-redis-cluster
发生时间: 2026-01-19T03:48:00Z
描述: cpu使用率大于0
```

**通用 JSON：**
```json
{
  "title": "服务异常",
  "severity": "critical",
  "message": "payment-api 响应超时",
  "namespace": "prod",
  "service": "payment-api"
}
```

系统会自动识别以上四种格式，归一化后进行规则匹配和消息推送。

---

### 3.2 通道管理 — `GET/POST /api/v1/settings/channels`

v1.3 新增 `message_template` 字段：

```json
{
  "id": 1,
  "name": "运维告警群",
  "type": "dingtalk",
  "config": "{\"webhook_url\":\"...\",\"secret\":\"...\",\"access_token\":\"...\"}",
  "is_enabled": true,
  "message_template": null,
  "created_at": "2026-01-01T00:00:00"
}
```

`message_template` 为 `null` 时使用格式对应的系统默认模板。支持 Jinja2 语法。

#### 模板可用变量

| 变量 | 说明 |
|------|------|
| `title` | 告警标题 |
| `severity` | 归一化严重级别 (critical/warning/info) |
| `message` | 告警消息正文 |
| `alerts` | 告警条目列表，每项含 `name`/`level`/`description`/`time`/`details` |
| `source` | 格式来源 (prometheus/grafana/custom_text/generic_json) |
| `raw_data` | 原始请求数据 |

#### 模板可用过滤器

| 过滤器 | 说明 | 示例 |
|--------|------|------|
| `format_time` | ISO 8601 → `YYYY-MM-DD HH:MM:SS`（北京时间） | `{{ alert.time \| format_time }}` |

---

### 3.3 调试接口 — `GET /api/v1/debug/logs`

查询历史请求日志，支持分页和搜索。

*   **参数**: `skip`, `limit`, `q`（搜索关键词）
*   **响应**: `{"items": [...], "total": N}`

### 3.4 日志重放 — `POST /api/v1/debug/replay/{log_id}`

用当前最新配置重新处理指定日志。调试规则和模板时使用。

---

### 3.5 系统公告 — `POST /api/v1/settings/announcement`

```json
{
  "title": "系统维护通知",
  "content": "将于今晚 22:00 进行停机维护。",
  "target_type": "all",
  "target_ids": [],
  "channel_id": 1
}
```

*   `target_type`: `all` / `team` / `user`
*   `channel_id`: 可选，不传使用默认通道

---

### 3.6 统计信息 — `GET /api/v1/stats/`

```json
{
  "today_count": 125,
  "success_count": 120,
  "active_rules_count": 8,
  "active_teams_count": 5,
  "daily_stats": [{"date": "04-23", "count": 45}, ...]
}
```

---

### 3.7 告警屏蔽 — `GET/POST/DELETE /api/v1/settings/silences` (v1.4)

管理告警屏蔽规则。

**创建屏蔽 — POST**:
```json
{
  "name": "发版: dx-insight v2.3",
  "reason": "预计2小时窗口",
  "ends_at": "2026-04-30T14:00:00.000Z",
  "match_mode": "AND",
  "conditions": [
    {"key": "namespace", "operator": "equals", "value": "dx-insight"}
  ]
}
```

**获取列表 — GET**: 返回所有屏蔽，可选 `include_expired=false` 仅返回活跃的。

**提前取消 — DELETE** `/api/v1/settings/silences/{id}`: 立即取消，记录 `cancelled_at`。

### 3.8 健康检查 — `GET /api/health`

```json
{
  "status": "ok",
  "version": "1.3",
  "db_size_bytes": 2744320,
  "db_wal_enabled": true
}
```
