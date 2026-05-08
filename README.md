# DingWatch

告警分发中台，统一接收多源监控告警，按规则匹配后精准分发到钉钉群机器人。

## 功能特性

- **多源接入**：支持 Prometheus Alertmanager、Grafana、自定义文本等多种告警格式
- **规则引擎**：按优先级匹配告警标签（namespace、deployment 等），支持 AND/OR 逻辑组合
- **精准分发**：每条告警独立匹配规则，独立推送到对应钉钉群，各自 @ 对应人员
- **渠道管理**：支持多个钉钉机器人渠道，可自定义消息模板（Jinja2）
- **静默规则**：按条件屏蔽告警，避免不必要的通知
- **流量日志**：完整记录每次告警请求及处理结果，支持回放调试
- **统计面板**：今日告警数、成功率、7 日趋势图

## 快速开始

### Docker 部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 ADMIN_PASSWORD 和 DINGWATCH_JWT_SECRET

# 2. 启动
docker-compose up -d
```

访问 `http://localhost:8000`，使用 `.env` 中配置的管理员账号登录。

### Webhook 接入

将监控系统的 Webhook 地址指向：

```
POST http://<your-host>:8000/api/v1/webhook/send
```

Prometheus Alertmanager 配置示例：

```yaml
receivers:
  - name: 'dingwatch'
    webhook_configs:
      - url: 'http://dingwatch:8000/api/v1/webhook/send'
```

## 配置说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ADMIN_USERNAME` | `admin` | 默认管理员账号 |
| `ADMIN_PASSWORD` | — | 默认管理员密码（首次启动创建） |
| `DINGWATCH_JWT_SECRET` | — | JWT 签名密钥（生产环境务必修改） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 技术栈

- **后端**：Python 3.11 / FastAPI / SQLAlchemy / SQLite
- **前端**：Jinja2 模板 + 原生 JavaScript
- **部署**：Docker / Docker Compose

## 许可证

MIT License
