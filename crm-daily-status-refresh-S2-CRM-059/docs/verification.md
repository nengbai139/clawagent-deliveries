# 验证记录（S2-CRM-059）

⚠️ 全部为**真实运行**的命令与**原始输出**（非「预期输出」）。
环境见下方「环境」一节。

## 环境

| 项 | 值 |
|---|---|
| 操作系统 | macOS 26.5.1（Darwin 25.5.0, arm64） |
| Python | 3.13.17（`uv venv --python 3.13`） |
| 数据库 | PostgreSQL 16.15（`postgres:16-alpine`，docker compose 服务 `db`，宿主端口 55433） |
| 锁 | Redis 7（docker compose 服务 `redis`，宿主端口 16380） |
| 关键依赖 | `fastapi 0.165.0` / `sqlalchemy 2.1.9` / `alembic 1.20.1` / `psycopg 3.3.9` / `pydantic 2.14.4` / `pytest 9.2.0` / `httpx 0.28.1` / `uvicorn 0.54.0` / `ruff 0.17.6` / `redis 8.1.0` |
| 客户要求的大版本 | Python 3.11+ / PostgreSQL 16 ⇒ **逐项对齐** |

> ⚠️ 测试**必须**跑在真实 PostgreSQL 16 上：验收标准 1/3 涉及
> `CheckConstraint`、JSONB、批量事务 ⇒ SQLite 下测的是另一套东西。

## 0. 从零复现（评审者按这个顺序跑）

```bash
docker compose up -d                      # PostgreSQL 16 + Redis 7
export CRM_DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:55433/app"
export CRM_REDIS_URL="redis://127.0.0.1:16380/0"
export CRM_DEFAULT_TZ="Asia/Shanghai"
export TEST_DATABASE_URL="$CRM_DATABASE_URL"
export CRM_TEST_REDIS_URL="$CRM_REDIS_URL"
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m ruff check crm tests
.venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-03-15
```

⚠️ **`CRM_DATABASE_URL` 必须显式设置**（`crm/core/config.py` 里**没有默认值**）
⇒ 缺了就启动时炸。这是故意的：默认值（`localhost:5432/...`）会让后台任务
连到**本机那个碰巧在跑的别的库** ⇒ 往不相关的数据库写状态变更。

## 1. 单元/集成测试全绿（真实 PostgreSQL 16）

```
$ .venv/bin/python -m pytest tests/ -v
============================= test session starts ==============================
platform darwin -- Python 3.13.17, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/baineng/Documents/devops/qdtech/crm-daily-status-refresh
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0
collected 41 items

tests/test_acceptance_criteria.py::test_criterion1_all_statuses_correct_after_one_run PASSED
tests/test_acceptance_criteria.py::test_criterion1_change_history_written_for_each_change PASSED
tests/test_acceptance_criteria.py::test_criterion2_second_run_changes_nothing PASSED
tests/test_acceptance_criteria.py::test_criterion3_failed_batch_others_still_commit PASSED
tests/test_acceptance_criteria.py::test_criterion3_failed_batch_does_not_rollback_other_batches PASSED
tests/test_acceptance_criteria.py::test_criterion4_backfill_uses_given_date PASSED
tests/test_acceptance_criteria.py::test_criterion4_cli_date_argument PASSED
tests/test_acceptance_criteria.py::test_soft_deleted_rows_are_skipped PASSED
tests/test_acceptance_criteria.py::test_paid_and_written_off_plans_are_skipped PASSED
tests/test_acceptance_criteria.py::test_batch_size_splits_into_several_batches PASSED
tests/test_acceptance_criteria.py::test_membership_derivation_table[active-365-active] PASSED
tests/test_acceptance_criteria.py::test_membership_derivation_table[active-10-expiring] PASSED
tests/test_acceptance_criteria.py::test_membership_derivation_table[active--1-expired] PASSED
tests/test_acceptance_criteria.py::test_membership_derivation_table[terminated--10-terminated] PASSED
tests/test_acceptance_criteria.py::test_membership_derivation_table[suspended--10-suspended] PASSED
tests/test_acceptance_criteria.py::test_expiring_window_is_configurable PASSED
tests/test_job_regressions.py::test_every_batch_failing_still_terminates PASSED
tests/test_job_regressions.py::test_scan_query_failure_aborts_instead_of_looping PASSED
tests/test_job_regressions.py::test_cursor_advances_after_a_failed_batch PASSED
tests/test_job_regressions.py::test_keyset_pagination_does_not_reprocess_changed_rows PASSED
tests/test_lock_and_cli.py::test_in_memory_lock_is_exclusive PASSED
tests/test_lock_and_cli.py::test_in_memory_lock_release_only_own_token PASSED
tests/test_lock_and_cli.py::test_acquire_lock_raises_when_busy PASSED
tests/test_lock_and_cli.py::test_lock_handle_reports_ownership PASSED
tests/test_lock_and_cli.py::test_redis_lock_is_exclusive_and_releases PASSED
tests/test_lock_and_cli.py::test_redis_lock_has_ttl PASSED
tests/test_lock_and_cli.py::test_cli_runs_and_writes_job_run PASSED
tests/test_lock_and_cli.py::test_cli_locked_returns_exit_code_2 PASSED
tests/test_lock_and_cli.py::test_cli_rejects_bad_date PASSED
tests/test_lock_and_cli.py::test_cli_help_lists_date_option PASSED
tests/test_migration_schema.py::test_migrated_columns_match_model PASSED
tests/test_migration_schema.py::test_migrated_constraints_match_model PASSED
tests/test_migration_schema.py::test_migration_creates_only_crm_job_run PASSED
tests/test_migration_schema.py::test_org_id_is_nullable_in_migration PASSED
tests/test_migration_schema.py::test_check_constraint_rejects_unknown_status PASSED
tests/test_ops_api.py::test_healthz PASSED
tests/test_ops_api.py::test_readyz PASSED
tests/test_ops_api.py::test_list_job_runs PASSED
tests/test_ops_api.py::test_list_job_runs_filters_by_date_and_name PASSED
tests/test_ops_api.py::test_list_job_runs_limit_is_capped PASSED
tests/test_ops_api.py::test_soft_deleted_runs_are_hidden PASSED

======================== 41 passed, 1 warning in 1.41s =========================
```

```
$ .venv/bin/python -m ruff check crm tests
All checks passed!
```

## 2. 逐条对照验收标准

| # | 验收标准 | 对应测试 | 结果 |
|---|---|---|---|
| 1 | 构造会籍进入 expiring 与 expired、合同到期、回款进入 due 与 overdue 的虚构数据，运行一次后状态全部正确（冻结时间测试） | `test_criterion1_all_statuses_correct_after_one_run`（基准日固定 2026-03-15）<br>`test_criterion1_change_history_written_for_each_change`<br>`test_membership_derivation_table[5 组]` | PASSED |
| 2 | 同一天连续运行两次，第二次变化数为 0 且无新增历史（测试断言） | `test_criterion2_second_run_changes_nothing` | PASSED |
| 3 | 人为让一批更新失败时其他批次照常提交，进程退出码非 0，crm_job_run.status=partial（测试断言） | `test_criterion3_failed_batch_others_still_commit`<br>`test_criterion3_failed_batch_does_not_rollback_other_batches` | PASSED |
| 4 | 用 --date 补跑时按指定日期派生状态（测试断言） | `test_criterion4_backfill_uses_given_date`（服务层）<br>`test_criterion4_cli_date_argument`（**CLI 入口层**） | PASSED |

⚠️ **工单里没单列、但原文明确要求的，也各有测试**：软删除行不参与派生
（`test_soft_deleted_rows_are_skipped`）、`paid`/`written_off` 不参与派生
（`test_paid_and_written_off_plans_are_skipped`）、分批真的分批
（`test_batch_size_splits_into_several_batches`）、人工状态（`terminated`/
`suspended`）不被碰（派生表用例）、提醒窗口可配
（`test_expiring_window_is_configurable`）。

## 3. 变异测试（证明测试**有区分力**，而不是「碰巧绿」）

⚠️ 全绿只说明「没崩」，不说明「测的是不是那个东西」⇒ 每条变异都指向一处
**具体判断**，改坏之后必须有测试变红。脚本：`scripts/mutation_check.py`
（每条变异单独跑 pytest；**挂住超过 180s 也算被抓到**——因为变异可能引入
死循环）。

```
$ .venv/bin/python scripts/mutation_check.py
✅ 捕获  变异 1：分批条件写成 .where(where)（元组当成一个条件）
✅ 捕获  变异 2：失败批次不推进游标（会反复处理同一批）
✅ 捕获  变异 3：状态没变化也照样写（幂等被破坏）
✅ 捕获  变异 4：不写变更历史
✅ 捕获  变异 5：每次变化各自一个 operation_id（不是「一次运行共用一个」）
✅ 捕获  变异 6：批次失败直接抛出（不继续下一批）
✅ 捕获  变异 7：有失败批次也算 success（partial 判据被破坏）
✅ 捕获  变异 8：会籍的人工状态也参与派生
✅ 捕获  变异 9：忽略 --date（永远按「今天」派生）
✅ 捕获  变异 10：改判后不回写状态（只写历史）

共 10 条变异，捕获 10 条。
```

### 变异 1 的细节（本单开发时真踩的坑）

```diff
                 select(model)
-                .where(*where)
+                .where(where)
                 .order_by(model.id)
                 .limit(batch_size)
```

⚠️ `where` 是**多个条件**的元组 ⇒ `.where(where)` 把它当成**一个**条件 ⇒
SQLAlchemy 抛 `ArgumentError` ⇒ **每一批都失败** ⇒ 而失败分支推进不了游标
⇒ **整个任务永远转下去**（运维那边看到的是「任务不结束」）。

⇒ 修法两处：① `.where(*where)`；② **取批失败时显式中止本类对象**
（游标推进不了 ⇒ 再来一次还是同样的错 ⇒ 只能中止）⇒
`tests/test_job_regressions.py::test_scan_query_failure_aborts_instead_of_looping`
钉住这条。

### 变异 2 的细节

```diff
-            # ⚠️ 失败批次的行**也要推进游标** ⇒ 否则反复重试同一批 ⇒ 死循环。
-            last_id = max(r.id for r in rows)
+            # MUTANT: 失败批次不推进游标
```

⇒ 被 `test_cursor_advances_after_a_failed_batch` 抓住（断言「没有哪一批被
处理两次」）。

### 变异 3 / 4 / 5 的细节（幂等与历史）

```diff
-        if target == row.status:
-            continue
+        # MUTANT: 没变化也照样写
```
⇒ 被 `test_criterion2_second_run_changes_nothing` 抓住（第二次跑变化数应 0）。

```diff
-    record: Callable[..., Any] = record_change,
+    record: Callable[..., Any] = lambda *a, **k: None,  # MUTANT: 不写历史
```
⇒ 被 `test_criterion2_second_run_changes_nothing` 抓住（历史数应不变）。

```diff
-            operation_id=operation_id,
+            operation_id=uuid.uuid4().hex,  # MUTANT: 每次变化另算
```
⇒ 被 `test_criterion1_change_history_written_for_each_change` 抓住（历史必须
共用**一次运行**的 operation_id）。

## 4. 迁移（`alembic upgrade` / `downgrade` / `upgrade` 完整循环）

```
$ docker exec crmjob-pg psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 6c1f0a52b7d9, S2-CRM-059: 新建 crm_job_run（日终任务运行记录）

$ docker exec crmjob-pg psql -U app -d app -c "\dt"
              List of relations
 Schema |        Name        | Type  | Owner
--------+--------------------+-------+-------
 public | alembic_version    | table | app
 public | crm_change_history | table | app
 public | crm_contract       | table | app
 public | crm_job_run        | table | app
 public | crm_membership     | table | app
 public | crm_payment_plan   | table | app
(6 rows)

$ .venv/bin/python -m alembic downgrade base
$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 6c1f0a52b7d9, S2-CRM-059: 新建 crm_job_run（日终任务运行记录）
```

⚠️ 表结构来自 Alembic 迁移；**测试夹具**里另外四张表（会籍/合同/回款计划/
变更历史，**属别的工单**）用 `create_all` 建 —— 本单的迁移**不碰它们**
（碰了 ⇒ 别的工单合入时撞车）⇒ `test_migration_creates_only_crm_job_run`
钉住这条。

### ⚠️ 迁移与 ORM 模型的表结构**逐项对比**（不是「看一眼」）

⚠️ 测试用 `create_all`（**模型**的表结构），生产用 **Alembic**（**迁移**的
表结构）⇒ 两边不一致 ⇒ **测试跑的是另一套东西**。

⇒ 做法：**真跑一遍迁移**（跑在另一个 schema 上，不污染业务库）⇒ 再把两边的
列 / 可空性 / 类型 / 约束 / 索引**逐项对比**：

```
$ .venv/bin/python -m pytest tests/test_migration_schema.py -v
tests/test_migration_schema.py::test_migrated_columns_match_model PASSED
tests/test_migration_schema.py::test_migrated_constraints_match_model PASSED
tests/test_migration_schema.py::test_migration_creates_only_crm_job_run PASSED
tests/test_migration_schema.py::test_org_id_is_nullable_in_migration PASSED
tests/test_migration_schema.py::test_check_constraint_rejects_unknown_status PASSED
```

⚠️ **这条检查当场抓到一个真 bug**：模型里 `crm_job_run.org_id` 改成了**可空**
（系统级运行记录不属于任何租户），**迁移里忘了改** ⇒ 运行记录**根本写不进去**
（`NotNullViolation`）⇒ **整个任务在生产上跑不起来**，而模型侧的测试还是绿的。

⚠️ 迁移与模型**都必须**是 `org_id` 可空 ⇒ 两边不一致就是「测试跑的是另一套
东西」⇒ `test_org_id_is_nullable_in_migration` 单独钉住。

### 关键约束确实进了迁移

```
$ docker exec crmjob-pg psql -U app -d app -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype='c' AND conrelid='crm_job_run'::regclass;"
     conname          | pg_get_constraintdef
--------------------+---------------------------------------------
 ck_crm_job_run_status | CHECK (((status)::text = ANY ((ARRAY['success'::character varying, 'partial'::character varying, 'failed'::character varying])::text[])))
```

⚠️ `status` 枚举**在数据库层也钉住**（不只靠应用层）。

## 5. 端到端（**真实进程**跑真实 CLI，不是调函数）

```
===== [准备] 清库并造虚构数据（基准日 2026-03-15）=====
造好：会籍 5 条 / 合同 3 条 / 回款 4 条
   membership dcca60d8-… active end_date= 2026-03-14
   membership 32b3b18d-… active end_date= 2026-03-25
   membership 6c112ba6-… active end_date= 2027-03-15
   membership 6f8e2df0-… terminated end_date= 2026-03-05
   membership 54629e14-… suspended end_date= 2026-03-05
   contract   66123b89-… active end_date= 2026-03-14
   contract   5f0acca1-… active end_date= 2026-04-14
   contract   d91b0b5e-… terminated end_date= 2026-03-06
   payment    c5662a22-… pending due_date= 2026-03-15
   payment    deccfe90-… pending due_date= 2026-03-12
   payment    76d927fa-… pending due_date= 2026-03-20
   payment    217bf4e5-… paid   due_date= 2026-03-12

===== ① 跑一次（真实进程）=====
$ .venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-03-15
{
  "job_name": "daily_status_refresh",
  "run_date": "2026-03-15",
  "operation_id": "d245ba5795e54395ab625d274e290676",
  "status": "success",
  "stats": {
    "objects": {
      "membership": {
        "scanned": 3,
        "changed": 2,
        "by_target_status": { "expired": 1, "expiring": 1 },
        "failed_batches": []
      },
      "contract": {
        "scanned": 1,
        "changed": 1,
        "by_target_status": { "expired": 1 },
        "failed_batches": []
      },
      "payment_plan": {
        "scanned": 3,
        "changed": 2,
        "by_target_status": { "due": 1, "overdue": 1 },
        "failed_batches": []
      }
    },
    "total_scanned": 7,
    "total_changed": 5,
    "failed_batches": [],
    "elapsed_ms": 115,
    "started_at": "2026-11-22T19:21:40.281766+00:00",
    "finished_at": "2026-11-22T19:21:40.397163+00:00"
  }
}
[exit=0]
```

⚠️ `scanned` 与 `changed` 分开统计：`membership scanned=3`（`terminated`/
`suspended` **不参与扫描**）、`changed=2`；`payment_plan scanned=3`
（`paid` 不参与扫描）、`changed=2`。

```
===== ② 再跑一次（同一天）⇒ 变化数 0、无新增历史（幂等）=====
$ .venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-03-15
  total_changed = 0
  status        = success
[exit=0]

===== ③ 跑完后的状态（真实库查询）=====
     obj      |   status   | count
--------------+------------+-------
 contract     | active     |     1
 contract     | expired    |     1
 contract     | terminated |     1
 membership   | active     |     1
 membership   | expired    |     1
 membership   | expiring   |     1
 membership   | suspended  |     1
 membership   | terminated |     1
 payment_plan | due        |     1
 payment_plan | overdue     |     1
 payment_plan | paid       |     1
 payment_plan | pending    |     1
(12 rows)

===== ④ 变更历史（每次变化一条，同一次运行共用 operation_id）=====
 entity_type  | from_value | to_value | actor_type |    op    | effective_date
--------------+------------+----------+------------+----------+----------------
 membership   | active     | expired  | system     | d245ba57 | 2026-03-15
 membership   | active     | expiring | system     | d245ba57 | 2026-03-15
 contract     | active     | expired  | system     | d245ba57 | 2026-03-15
 payment_plan | pending    | overdue  | system     | d245ba57 | 2026-03-15
 payment_plan | pending    | due      | system     | d245ba57 | 2026-03-15
(5 rows)

===== ⑤ crm_job_run（每次运行一条）=====
       job_name       |  run_date  | status  | changed | ms
----------------------+------------+---------+---------+-----
 daily_status_refresh | 2026-03-15 | success | 5       | 115
 daily_status_refresh | 2026-03-15 | success | 0       | 103
(2 rows)

===== ⑥ 并发锁：第二个实例 ⇒ 退出码 2 =====
{"job_name": "daily_status_refresh", "status": "locked", "error": "锁 crm:lock:daily_status_refresh 被别的实例持有 ⇒ 本次不跑"}
[exit=2]

===== ⑦ 补跑：换一个基准日 ⇒ 按那天派生 =====
$ .venv/bin/python -m crm.jobs.daily_status_refresh --date 2026-02-01
  run_date      = 2026-02-01
  total_changed = 4
 effective_date | count
----------------+-------
 2026-02-01     |     4
 2026-03-15     |     5
(2 rows)

===== ⑧ 运维只读接口 =====
$ curl -s http://127.0.0.1:18098/healthz
{"status":"ok"}
$ curl -s 'http://127.0.0.1:18098/api/admin/crm/job-runs?limit=2'
   2026-02-01 success changed= 4
   2026-03-15 success changed= 0
```

逐条对应：

| 步骤 | 期望 | 实测 |
|---|---|---|
| ① | 会籍 → `expired`/`expiring`，合同 → `expired`，回款 → `due`/`overdue` | `by_target_status` 与 ③ 的库内状态逐项对上 |
| ① | 人工状态不参与派生 | `terminated`/`suspended` 两行**原样未动**（③） |
| ① | 已结清不参与派生 | `paid` 那行**原样未动**（③） |
| ② | 同一天再跑 ⇒ 变化数 0 | `total_changed = 0` |
| ④ | 每次变化一条历史、`actor_type=system`、共用一个 operation_id | 5 行，`op` 全是 `d245ba57` |
| ⑤ | 每次运行一条记录 | 2 行（第一次 5 变化、第二次 0 变化） |
| ⑥ | 锁被占 ⇒ 非零退出码 | **exit=2** |
| ⑦ | `--date` 按指定日期派生 | `run_date=2026-02-01`，历史里 `effective_date` 两个日期各归各的 |

## 6. 已知局限

1. **两个派生函数是接口桩**（工单原文允许：「未合入时按函数签名写桩」）。
   桩里的规则（会籍到期前 30 天算 `expiring`、回款到期当天算 `due`）是为了
   让本单**可测**而定的 ⇒ **真实现合入后，本单的冻结时间用例要按真规则重算
   期望值**（README「对接点」一节已写明）。
2. **`crm_change_history` 表属别的工单**：本单只声明 ORM，测试夹具建表；
   `record_change` 是桩 ⇒ 真实现合入后换函数体即可（签名是契约）。
3. **`crm_job_run.org_id` 可空**：日终任务是跨租户的系统级任务 ⇒ 一条运行
   记录不属于任何租户 ⇒ 硬塞租户 id 是错的。
4. **通知/推送没有**：工单没要求（提醒由调度器侧负责）。
5. **单机单副本假设**：锁是 Redis 级的 ⇒ 跨副本也互斥；但「锁过期就中止」
   意味着**跑超 30 分钟会被中止** ⇒ 大批量时要么调 `CRM_LOCK_TTL_SECONDS`，
   要么分多次跑。
6. **失败批次不自动重试**：失败批的行本次跳过 ⇒ 运维看
   `crm_job_run.stats.failed_batches` ⇒ 按 `--date` 补跑。
7. **无鉴权中间件**：本单只有运维只读查询口，**没有任何写接口** ⇒ 但
   `GET /api/admin/crm/job-runs` 本身没有鉴权 ⇒ 上线前必须接到 S2-IAM 的
   鉴权中间件后面。
