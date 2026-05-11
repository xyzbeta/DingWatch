# 部署文档 (v1.4.3)

本文档将指导您如何在各种环境中部署 DingWatch 告警分发中台。

---

## 目录
1. [环境要求](#1-环境要求)
2. [Docker 部署 (推荐)](#2-docker-部署-推荐)
3. [手动部署](#3-手动部署)
4. [离线部署](#4-离线部署)
5. [配置说明](#5-配置说明)
6. [数据备份与迁移](#6-数据备份与迁移)
7. [健康检查](#7-健康检查)

---

## 1. 环境要求
*   **操作系统**: Linux (推荐 Ubuntu/CentOS), macOS, Windows
*   **Python**: 3.9 或更高版本
*   **数据库**: SQLite (默认，无需配置), 开启 WAL 模式以支持高并发。
*   **容器引擎**: Docker & Docker Compose (若选择 Docker 部署)

---

## 2. Docker 部署 (推荐)

这是最简单快捷的部署方式，适合生产环境和快速体验。

### 步骤
1.  **克隆代码**:
    ```bash
    git clone https://github.com/your-repo/DingWatch.git
    cd DingWatch
    ```

2.  **配置环境变量**:
    复制示例配置文件并修改。
    ```bash
    cp .env.example .env
    vi .env
    ```
    请参考 [配置说明](#5-配置说明) 章节填写必要的参数。

3.  **启动服务**:
    使用 Docker Compose 构建并启动容器。
    ```bash
    docker-compose up -d --build
    ```

4.  **验证**:
    访问 `http://<服务器IP>:8000`，应能看到登录页面。

### 更新与重启
```bash
# 拉取最新代码
git pull
# 重建镜像并重启 (只会重建变更的部分)
docker-compose up -d --build
```

---

## 3. 手动部署

适合开发调试或不支持 Docker 的环境。

### 步骤
1.  **准备 Python 环境**:
    建议使用虚拟环境。
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

2.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **配置环境变量**:
    同样需要 `.env` 文件，参考上文。

4.  **初始化数据库**:
    系统在首次启动时会自动创建 SQLite 数据库表结构，无需手动执行 SQL。
    > 注意：数据文件默认存储在 `app/data/dingwatch.db`。请确保该目录有写入权限。

5.  **启动服务**:
    使用 `uvicorn` 启动 ASGI 服务。
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    *   `--reload`: 仅在开发模式下使用，代码变更后自动重启。

---

## 4. 离线部署

针对内网隔离环境（无法访问 PyPI 或 CDN），DingWatch v1.2 已做全量本地化处理。

### 前端资源
所有前端依赖（Vue.js, TailwindCSS, Chart.js, RemixIcon）均已内置在 `static/` 目录下，**无需**访问互联网即可加载 UI。

### 后端依赖
1.  在有网机器上下载依赖包：
    ```bash
    pip download -r requirements.txt -d ./packages
    ```
2.  将 `packages` 目录和源码打包传输至内网服务器。
3.  在内网服务器安装：
    ```bash
    pip install --no-index --find-links=./packages -r requirements.txt
    ```

---

## 5. 配置说明

请在项目根目录创建 `.env` 文件。

| 变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `LOG_LEVEL` | `INFO` | 日志级别 (DEBUG, INFO, WARNING, ERROR) |
| `ADMIN_USERNAME` | `admin` | 默认系统管理员用户名 |
| `ADMIN_PASSWORD` | (必填) | 默认系统管理员密码 |
| `SECRET_KEY` | (随机) | Flask/FastAPI Session 加密密钥，建议修改 |

**注意**: 旧版本中的 `DINGTALK_WEBHOOK_URL` 等配置项在 v1.1 中已废弃，改为在系统 UI 的“系统设置”页面中动态配置。

---

## 6. 数据备份与迁移

### 备份
DingWatch 默认使用 SQLite 数据库，数据文件位于 `app/data/dingwatch.db`。
备份只需拷贝该文件即可：
```bash
cp app/data/dingwatch.db /backup/dingwatch_$(date +%Y%m%d).db
```

### 迁移
将备份的 `.db` 文件覆盖到新部署环境的相同位置即可恢复所有数据（规则、用户、日志、系统配置）。

v1.2 支持在 UI 界面通过 JSON 文件导入/导出所有配置，建议优先使用该功能进行环境迁移。

---

## 7. 健康检查

系统提供标准的健康检查接口，可用于 K8s Liveness Probe 或负载均衡器检测。

*   **Endpoint**: `GET /api/health`
*   **Response**:
    ```json
    {
      "status": "ok",
      "version": "1.4.3",
      "db_size_bytes": 1048576,
      "db_wal_enabled": true
    }
    ```
