# 会员空间平台 · 报备人工复核与归属争议处理接口（员工端）

工单 **S6-REF-008**。实现员工端的**人工复核**与**归属争议**处理流程，
含**双人审批**逻辑、审计日志与超时提醒任务。

> ⚠️ 本仓库使用**虚构的测试数据**，不含任何真实个人信息或企业信息；
> 交付物中不出现客户名称。

## 技术栈（对齐客户统一技术约定）

| 项 | 选型 |
|---|---|
| 语言 | Python 3.11+（开发与验证用 3.13） |
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2（`Mapped[]` 声明式） |
| 迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis（预留，未在本单使用） |
| 测试 | pytest + httpx（`TestClient` 打真实 HTTP） |

金额一律以「**分**」存整数；配置与密钥只从环境变量读取；
未引入任何向境外发送数据的第三方 SDK。

## 快速开始

### 1. 起数据库（PostgreSQL 16）

```bash
docker run -d --name refdispute-pg \
  -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app \
  -p 55432:5432 postgres:16-alpine
```

### 2. 建虚拟环境并安装

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

### 3. 配置

```bash
export APP_DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:55432/app"
export APP_REDIS_URL="redis://127.0.0.1:6379/0"
```

> ⚠️ `APP_DATABASE_URL` 等**只在环境变量里**，不写进仓库。

### 4. 迁移

```bash
.venv/bin/python -m alembic upgrade head
```

### 5. 起服务

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：`GET /healthz`、`GET /readyz`。

### 6. 跑测试

```bash
export TEST_DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:55432/app"
.venv/bin/python -m pytest tests/ -v
```

> ⚠️ 测试**必须跑在真实 PostgreSQL 16** 上（不用 SQLite）：验收标准 3 是
> 集成测试，涉及 `CheckConstraint` / `UniqueConstraint` / `pgvector` 方言 ⇒
> SQLite 下测的是**另一套东西**。

## 接口

### 复核（员工端）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/admin/ref/reports?status=&reporter_type=&owner_staff_id=` | 列出报备（分页，`limit` 上限 200） |
| `POST` | `/api/admin/ref/reports/{id}/verify` | 对 `accepted` 报备标记 `verified` |
| `POST` | `/api/admin/ref/reports/{id}/reject` | 以 `rejected_invalid` 驳回（**原因必填**） |

### 争议

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/ref/reports/{id}/disputes` | 提交争议（说明 + 证据附件，**最多 5 个**） |
| `GET` | `/api/admin/ref/disputes/{id}` | 查看争议 |
| `POST` | `/api/admin/ref/disputes/{id}/decide` | 处理：`uphold` 维持 / `overturn` 改判 |

### 身份

当前身份从请求头取（**S2-IAM 的接口桩**，真实实现时替换
`app/api/deps.py::get_actor` 即可，路由层不感知）：

```
X-Actor-Id: <uuid>     # 必填
X-Actor-Type: staff    # 可选，默认 staff
X-Org-Id: <uuid>       # 可选
```

缺少 `X-Actor-Id` ⇒ **401**（不猜、不默认成某个用户）。

## 业务规则

### 争议理由：只受理「系统判断错误」类

| 受理 | 不受理 |
|---|---|
| `normalization_false_duplicate`（归一化误判为重复） | `earlier_offline_contact`（更早在线下接触过客户） |
| `existing_customer_data_error`（存量客户信息有误） | `first_report_rule_conflict`（与首次报备规则冲突） |
| `wrong_attribution`（归属判错） | |
| `other_system_error`（其它系统错误） | |

⚠️ 白名单同时落在**应用层校验**与**数据库 `CheckConstraint`** ⇒ 换一条
SQL 也写不进非法理由。

### 改判：双人审批

改判（`overturn`）需要 `channel_manager` 与 `finance` **两个角色由两个
不同的人各审批一次**才生效。

- 只有**一个**角色审批 ⇒ 改判**不生效**（返回 `effective=false` 与
  `missing_roles`），状态仍是 `pending`。
- **维持**（`uphold`）**一次即生效**，不需要双人审批。
- ⚠️ **同一个人同时拥有两个角色时，重复审批不计为双人审批**：
  - 该人第二次审批会被**拒**（`409 same_person_already_approved`）；
  - 且即使绕过应用层直接写两条审批记录，**判定**也不认（按「审批人」而非
    「角色」做二分图配对）——**双人**这个性质由**判定**保证，不只由**写入**保证。
- ⚠️ 某人同时具备两个角色时，`decide` **必须**在请求体里用 `role` 字段
  显式指定本次用哪个角色（否则返回 `422`）——逼调用方把话说清楚。

### 改判后重算归属

改判生效后，系统按报备的**原报备时间**（`reported_at`，**不是**
`created_at`）**重新判定归属**，并把重算结果写入审计日志
（`action=attribution.recompute`），同时通知受影响各方（通知为**桩**，
落 `notification_stub` 表）。

归属策略是可替换的 `AttributionStrategy` 协议，默认实现
`FirstReportWinsStrategy`（同渠道同客户时，**原报备时间更早**的报备优先）。
真实归属规则接入时替换实现即可，调用方不感知。

### 超时提醒

争议提交后 **10 天**未处理 ⇒ 提醒负责人：

```bash
.venv/bin/python -m app.tasks remind-disputes --days 10
```

⚠️ **幂等**：已提醒过的不再重复提醒。
⚠️ 做成**独立 CLI**（由外部 cron / K8s CronJob 触发），不在进程内起后台
线程——进程内定时器在容器重启/多副本时会重复触发或漏触发。

## 数据模型

| 表 | 用途 |
|---|---|
| `ref_report` | 报备（含 `reported_at` 原报备时间、`owner_staff_id` 归属） |
| `ref_dispute` | 争议 |
| `dispute_approval` | 审批记录（`approver_id` 是**人**，`approver_role` 是角色） |
| `audit_log` | 审计日志（操作人、前后状态、理由**均为必填**） |
| `staff_role` | 员工角色（**S2-IAM 的桩**） |
| `notification_stub` | 通知桩 |

统一约定：业务表均含 `id`(UUID) / `org_id` / `site_id` / `created_at` /
`created_by` / `updated_at` / `deleted_at`（**软删除**）。

⚠️ `dispute_approval` 上有唯一约束
`uq_dispute_approval_once_per_role_per_person` ⇒ **同一争议、同一角色、
同一人**只能有一条审批记录 ⇒ 重复审批在**数据库层**就写不进去。

## 对接点（依赖其它工单的部分）

| 依赖 | 本单做法 | 真实接入时改哪里 |
|---|---|---|
| **S2-IAM**（身份、角色与数据范围） | **接口桩**：`staff_role` 表 + `X-Actor-*` 头 | `app/api/deps.py::get_actor`、`app/services/approval.py::roles_of` |
| 归属判定规则 | `FirstReportWinsStrategy`（确定性、可替换） | `app/services/attribution.py` 换 `AttributionStrategy` 实现 |
| 通知服务 | **桩**：落 `notification_stub` 表 | `app/services/dispute.py::_notify` |
| 证据文件存储 | 附件只存**元数据**（file_id/name/url），文件由既有文件服务托管 | 本单不碰文件内容 |

## 验证记录

见 `docs/verification.md`（含真实运行的命令与原始输出）。

## 目录结构

```
app/
  api/         路由与依赖（S2-IAM 桩在 deps.py）
  core/        配置（只从环境变量读）
  db/          数据库会话
  models/      ORM 模型
  schemas/     Pydantic 请求/响应模型
  services/    业务逻辑
    approval.py     ★ 双人审批判定
    attribution.py  ★ 归属重算
    audit.py        审计日志
    dispute.py      争议提交/处理/超时提醒
    review.py       复核
  tasks.py     后台任务 CLI
tests/
  test_acceptance_criteria.py  ★ 逐条对应验收标准
  test_api.py                   接口测试
  test_reminder.py              超时提醒
alembic/       迁移
```
