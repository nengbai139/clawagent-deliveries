# 会员空间平台 · 日终状态刷新任务（会籍到期、合同到期与回款逾期批量派生）

工单 **S2-CRM-059**。实现 CRM 日终状态刷新任务：入口
`python -m crm.jobs.daily_status_refresh`，由调度器每天 00:10 调用一次，
也可用 `--date YYYY-MM-DD` 补跑指定日期。

> ⚠️ 本仓库使用**虚构的测试数据**，不含任何真实个人信息或企业信息；
> 交付物中不出现客户名称。

## 技术栈（对齐客户统一技术约定）

| 项 | 选型 |
|---|---|
| 语言 | Python 3.11+（开发与验证用 3.13） |
| Web 框架 | FastAPI（**仅运维只读查询口**，见下） |
| ORM | SQLAlchemy 2（`Mapped[]` 声明式） |
| 迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 缓存/锁 | Redis 7（并发锁） |
| 测试 | pytest + httpx（`TestClient` 打真实 HTTP） |

金额一律以「**分**」存整数；配置与密钥只从环境变量读取；
未引入任何向境外发送数据的第三方 SDK。

⚠️ **本单的交付物是「任务」不是「业务接口」**：HTTP 侧**只有**一个只读的
运维查询口（`GET /api/admin/crm/job-runs`，供运维查 `crm_job_run`），
刻意不扩业务接口范围。

## 快速开始

### 1. 起依赖（PostgreSQL 16 + Redis 7）

```bash
docker compose up -d
```

（`docker-compose.yml`：`db` 用宿主端口 **55433**、`redis` 用 **16380**
⇒ 不和本机已有的 5432/6379 撞端口。）

### 2. 建虚拟环境并安装

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

### 3. 配置

```bash
export CRM_DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:55433/app"
export CRM_REDIS_URL="redis://127.0.0.1:16380/0"
export CRM_DEFAULT_TZ="Asia/Shanghai"      # 调度器按这个时区的 00:10 跑
```

> ⚠️ `CRM_DATABASE_URL` 等**只在环境变量里**，不写进仓库。
> ⚠️ **`CRM_DATABASE_URL` 没有默认值**（`crm/core/config.py`）⇒ 缺了就启动
> 时炸。这是故意的：默认值（`localhost:5432/...`）会让后台任务连到**本机那个
> 碰巧在跑的别的库** ⇒ 往不相关的数据库写状态变更。

### 4. 迁移

```bash
.venv/bin/python -m alembic upgrade head
```

### 5. 跑任务

```bash
# 跑「今天」（按 CRM_DEFAULT_TZ 时区）
.venv/bin/python -m crm.jobs.daily_status_refresh

# 补跑指定基准日
.venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-03-15
```

**退出码**：`0` 成功 / `1` 有批次失败（`partial` 或 `failed`）/ `2` 并发锁被
别的实例占着（本次不跑）。

### 6. 跑测试

```bash
export TEST_DATABASE_URL="$CRM_DATABASE_URL"
export CRM_TEST_REDIS_URL="$CRM_REDIS_URL"   # 可选：设了就跑「真 Redis」的锁用例
.venv/bin/python -m pytest tests/ -v
```

> ⚠️ 测试**必须跑在真实 PostgreSQL 16** 上（不用 SQLite）：验收标准 1/3 涉及
> `CheckConstraint`、JSONB、批量事务 ⇒ SQLite 下测的是**另一套东西**。

## 任务做什么

### 三类对象

| 对象 | 规则 | 派生函数 |
|---|---|---|
| **会籍** | 未删除且 `status` 不在 `terminated`/`suspended` ⇒ 重新派生 ⇒ **只更新状态真的变化的行** | `derive_membership_status(membership, today)`（**桩**） |
| **合同** | `status=active` 且 `end_date` 早于 `today` ⇒ 改为 `expired` | 工单原文写死，无派生函数 |
| **回款计划** | 未删除且 `status` 不在 `paid`/`written_off` ⇒ 重新派生 ⇒ 只更新变化的行 | `derive_payment_status(plan, today)`（**桩**） |

⚠️ **人工状态不碰**：`terminated` / `suspended`（会籍）、`paid` /
`written_off`（回款）是人工设的 ⇒ 系统不参与派生。

### 分批与失败处理

- 每类对象**每批 1000 行**（`CRM_BATCH_SIZE` 可调），**每批一个独立事务**；
- 单批失败 ⇒ **只回滚该批**、记录错误、**继续下一批**；
- 最终**以非零退出码结束**（`1`），并把 `crm_job_run.status` 记成
  `partial`（有失败也有成功）或 `failed`（全失败）。

⚠️ **分页用「键集」（`id > 上一页最大 id`），不用 `OFFSET`**：派生会把
`status` 改掉 ⇒ 改过的行**仍然满足**扫描条件 ⇒ 用 `OFFSET` 分页会**反复读到
同一批** ⇒ 永远走不到头（死循环）。键集分页与「行在扫描途中被改」无关。

⚠️ **失败批次也必须推进游标**，否则会反复重试同一批 ⇒ 同样死循环。
⇒ 取批本身就失败（游标推进不了）⇒ **显式中止本类对象**并记进
`failed_batches`，而不是无限重试。

### 变更历史

每次状态变化写一条历史（`record_change`，**桩**）：`actor_type=system`，
**同一次运行共用一个 `operation_id`** ⇒ 一次跑出来的历史能串成一组。

### 幂等

同一天重复运行**不产生新的状态变化与历史** ⇒ 因为「状态没变化就不动它」
（连 `updated_at` 都不改）⇒ 第二次跑全是「没变化」⇒ 不写、不记。

### 并发

Redis 锁 `crm:lock:daily_status_refresh`（TTL 30 分钟，`CRM_LOCK_KEY` /
`CRM_LOCK_TTL_SECONDS` 可调）：

- 用 `SET key token NX EX ttl` 实现（**原子**）；
- 释放时**只删自己持有的锁**（Lua compare-and-delete）；
- ⚠️ **每批之前检查锁还在不在自己手里** ⇒ TTL 过期就**立刻中止**
  ⇒ 两个实例不会同时改同一批数据。

### 产出

- **stdout**：JSON 汇总（各对象扫描数、变化数、按目标状态计数、失败批次、耗时）；
- **`crm_job_run`**：一行运行记录（`job_name` / `run_date` / `started_at` /
  `finished_at` / `stats` jsonb / `status`）。

## 调度建议

```cron
# 每天 00:10（按 CRM_DEFAULT_TZ 的「本地 00:10」）
10 0 * * * cd /opt/crm-daily-status-refresh && CRM_DATABASE_URL=... CRM_REDIS_URL=... .venv/bin/python -m crm.jobs.daily_status_refresh >> /var/log/crm-daily-status-refresh.log 2>&1
```

⚠️ **建议用 cron / K8s CronJob，不要在应用进程里起后台定时器**：进程内
定时器在容器重启或多副本时会**重复触发或漏触发**。

⚠️ **多副本部署时锁才有用**：锁是 Redis 级的 ⇒ 跨副本也互斥；单进程本地跑
用内存锁实现（`InMemoryLockBackend`，**只对单进程有效**）。

### 补跑

```bash
.venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-03-15
```

⚠️ `--date` **改的是派生基准日**（不是「补昨天」）：会籍/回款按那天的日期
派生 ⇒ 补跑历史某天，得到的是「那天应有的状态」。

⚠️ 补跑**不会**把已经回滚掉的批次自动重试 ⇒ 失败的批次看
`crm_job_run.stats.failed_batches` ⇒ 按里面的 `entity_type` 与
`batch_no` 定位 ⇒ 再用对应日期补跑。

## 数据模型

| 表 | 归属 | 本单的迁移建它吗 |
|---|---|---|
| `crm_job_run` | **本单** | ✅ 建 |
| `crm_membership` | CRM 核心对象（别的工单） | ❌ 不建（测试夹具里建） |
| `crm_contract` | 同上 | ❌ 不建 |
| `crm_payment_plan` | 回款计划（别的工单） | ❌ 不建 |
| `crm_change_history` | 变更历史（别的工单） | ❌ 不建 |

统一约定：业务表均含 `id`(UUID) / `org_id` / `site_id` / `created_at` /
`created_by` / `updated_at` / `deleted_at`（**软删除**）。

⚠️ **`crm_job_run.org_id` 是可空的**（其它业务表是 NOT NULL）：日终任务是
**跨租户的系统级任务** ⇒ 它的一条运行记录**不属于任何租户** ⇒ 硬塞租户 id
反而是错的。⚠️ 迁移里必须同样可空 ⇒ **两边不一致就是「测试跑的是另一套
东西」** ⇒ `tests/test_migration_schema.py` 会**真跑一遍迁移**再逐项对比。

## 对接点（依赖其它工单的部分）

| 依赖 | 本单做法 | 真实接入时改哪里 |
|---|---|---|
| **会籍校验**（会籍状态派生） | **接口桩**：`crm/derive/membership.py::derive_membership_status(membership, today)` | 换函数体，**签名是契约**（调用方不动） |
| **回款校验**（回款状态派生） | **接口桩**：`crm/derive/payment.py::derive_payment_status(plan, today)` | 同上 |
| **变更历史** | **接口桩**：`crm/change_history.py::record_change(...)` | 同上 |
| **S2-IAM** | 本单不需要（任务无用户身份；操作人固定 `actor_type=system`） | — |

⚠️ **桩的语义不是业务真相**：桩里的规则（会籍到期前 30 天算 `expiring`、
回款到期当天算 `due`）是为了让本单**可测**而定的 ⇒ 真实现合入后，
**本单的冻结时间用例要按真规则重算期望值**。

## 验证记录

见 `docs/verification.md`（真实命令与原始输出、**10 条变异测试**、
迁移与模型表结构的逐项 diff、端到端 CLI 真实运行）。

## 目录结构

```
crm/
  api/          运维只读接口（deps.py / ops.py）
  core/         配置（只从环境变量读）
  db/           数据库会话与事务边界
  derive/       ★ 派生函数桩（会籍 / 回款）—— 别的工单合入时换函数体
  jobs/
    daily_status_refresh.py  ★ 任务本体（分批 / 幂等 / 失败处理）
  locks.py      ★ Redis 并发锁（可注入后端）
  models/       ORM 模型（哪些表是本单的，见「数据模型」）
  change_history.py  ★ record_change 桩
alembic/        迁移（只建 crm_job_run）
scripts/
  mutation_check.py   变异测试（证明测试有区分力）
tests/
  test_acceptance_criteria.py  ★ 逐条对应验收标准
  test_job_regressions.py      ★ 回归测试（死循环等真踩过的坑）
  test_migration_schema.py     ★ 迁移与模型表结构逐项对比
  test_lock_and_cli.py         并发锁 + CLI 入口
  test_ops_api.py              运维只读接口
docker-compose.yml     验收环境（PostgreSQL 16 + Redis 7）
```
