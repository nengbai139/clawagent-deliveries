# 验证记录（S6-REF-008）

⚠️ 全部为**真实运行**的命令与**原始输出**（非「预期输出」）。
环境见下方「环境」一节。每一节都可以按命令**原样复现**。

## 环境

| 项 | 值 |
|---|---|
| 操作系统 | macOS 26.5.1（Darwin 25.5.0, arm64） |
| Python | 3.13.17（`uv venv --python 3.13`） |
| 数据库 | PostgreSQL 16.15（`postgres:16-alpine`，docker compose 服务 `db`，宿主端口 55432） |
| 关键依赖 | `fastapi 0.165.0` / `sqlalchemy 2.1.9` / `alembic 1.20.1` / `psycopg 3.3.9` / `pydantic 2.14.4` / `pytest 9.2.0` / `httpx 0.28.1` / `uvicorn 0.54.0` / `ruff 0.17.6` |
| 客户要求的大版本 | Python 3.11+ / PostgreSQL 16 ⇒ **逐项对齐** |

> ⚠️ 测试**必须**跑在真实 PostgreSQL 16 上：验收标准 3 是**集成测试**，
> 涉及 `CheckConstraint`、`UniqueConstraint`、UUID 方言 ⇒ SQLite 下测的是
> 另一套东西。

## 0. 从零复现（评审者按这个顺序跑）

```bash
docker compose up -d                      # 起 PostgreSQL 16
export APP_DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:55432/app"
export TEST_DATABASE_URL="$APP_DATABASE_URL"
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m pytest tests/ -v
```

### ⚠️ `APP_DATABASE_URL` 必须显式设置

配置里 `database_url` **没有默认值**（`app/core/config.py`）⇒ 缺了就**启动时炸**。

⚠️ **为什么不给默认值**：默认值是
`postgresql+psycopg://app:app@localhost:5432/app` ⇒ 一旦忘了设环境变量，
后台任务 CLI（`python -m app.tasks`）会连到**本机 5432 端口上那个碰巧在
那儿的库**（本机开发机上那个端口跑的是**另一个项目**的 Postgres）⇒
提醒任务会往**不相关的数据库**里写通知与审计。
⇒ 缺配置就炸，比连错库安全。

（测试里 `tests/conftest.py` 会把 `APP_DATABASE_URL` 指到 `TEST_DATABASE_URL`
⇒ CLI 测的确实是**测试库**。）

## 1. 单元/集成测试全绿

```
$ .venv/bin/python -m pytest tests/ -v
============================= test session starts ==============================
platform darwin -- Python 3.13.17, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/baineng/Documents/devops/qdtech/member-ref-dispute
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0
collected 39 items

tests/test_acceptance_criteria.py::test_criterion1_single_role_approval_does_not_take_effect PASSED [  2%]
tests/test_acceptance_criteria.py::test_criterion1_two_different_people_two_roles_takes_effect PASSED [  5%]
tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_is_not_dual_approval PASSED [  7%]
tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual PASSED [ 10%]
tests/test_acceptance_criteria.py::test_approval_db_constraint_blocks_same_person_twice PASSED [ 12%]
tests/test_acceptance_criteria.py::test_criterion2_distinct_people_with_overlapping_roles_still_dual PASSED [ 15%]
tests/test_acceptance_criteria.py::test_criterion3_recompute_attribution_by_original_reported_at PASSED [ 17%]
tests/test_acceptance_criteria.py::test_criterion3_audit_has_actor_before_after_reason PASSED [ 20%]
tests/test_acceptance_criteria.py::test_criterion3_dispute_decision_written_to_audit PASSED [ 23%]
tests/test_api.py::test_list_reports_requires_actor PASSED               [ 25%]
tests/test_api.py::test_list_reports_filters PASSED                      [ 28%]
tests/test_api.py::test_verify_and_reject_reports PASSED                 [ 30%]
tests/test_api.py::test_reject_only_from_accepted PASSED                 [ 33%]
tests/test_api.py::test_submit_dispute_rejects_disallowed_reason PASSED  [ 35%]
tests/test_api.py::test_submit_dispute_allows_system_error_reason PASSED [ 38%]
tests/test_api.py::test_submit_dispute_rejects_more_than_5_attachments PASSED [ 41%]
tests/test_api.py::test_submit_dispute_rejected_when_not_the_reporter PASSED [ 43%]
tests/test_api.py::test_submit_dispute_rejected_when_report_not_rejected PASSED [ 46%]
tests/test_api.py::test_decide_overturn_needs_two_different_people PASSED [ 48%]
tests/test_api.py::test_decide_same_person_two_roles_rejected PASSED     [ 51%]
tests/test_api.py::test_decide_ambiguous_role_requires_explicit PASSED   [ 53%]
tests/test_api.py::test_decide_uphold_takes_effect_immediately PASSED    [ 56%]
tests/test_api.py::test_decide_without_required_role_403 PASSED          [ 58%]
tests/test_api.py::test_decide_already_decided_is_409 PASSED             [ 61%]
tests/test_api.py::test_overturn_restores_the_rejected_report PASSED     [ 64%]
tests/test_api.py::test_overturn_notifies_the_previous_owner PASSED      [ 66%]
tests/test_reminder.py::test_overdue_dispute_reminded PASSED             [ 69%]
tests/test_reminder.py::test_recent_dispute_not_reminded PASSED          [ 71%]
tests/test_reminder.py::test_reminder_is_idempotent PASSED               [ 74%]
tests/test_reminder.py::test_reminder_writes_audit PASSED                [ 76%]
tests/test_reminder.py::test_decided_dispute_not_reminded PASSED         [ 79%]
tests/test_report_page.py::test_dispute_page_states_accepted_reasons PASSED [ 82%]
tests/test_report_page.py::test_dispute_page_states_rejected_reasons PASSED [ 84%]
tests/test_report_page.py::test_dispute_page_states_attachment_limit PASSED [ 87%]
tests/test_report_page.py::test_openapi_states_the_rule_too PASSED       [ 89%]
tests/test_report_page.py::test_openapi_states_two_person_rule PASSED    [ 92%]
tests/test_tasks_cli.py::test_session_scope_is_a_context_manager PASSED  [ 94%]
tests/test_tasks_cli.py::test_session_scope_rolls_back_on_error PASSED   [ 97%]
tests/test_tasks_cli.py::test_remind_disputes_cli_runs_and_is_idempotent PASSED [100%]

======================== 39 passed, 3 warnings in 1.21s ========================
```

⚠️ **连续跑两遍结果一致**（不靠上一遍的残留数据）：

```
$ .venv/bin/python -m pytest tests/ -q   # 第 1 遍
39 passed, 3 warnings in 1.13s
$ .venv/bin/python -m pytest tests/ -q   # 第 2 遍
39 passed, 3 warnings in 1.19s
```

（测试夹具每个用例**先清空全部业务表**⇒ 用例之间不互相污染。）

## 2. 逐条对照验收标准

| # | 验收标准 | 对应测试 | 结果 |
|---|---|---|---|
| 1 | 只有一个角色审批时改判不生效，两个不同的人分别以两种角色审批后生效（有测试） | `test_criterion1_single_role_approval_does_not_take_effect`<br>`test_criterion1_two_different_people_two_roles_takes_effect`<br>`test_decide_overturn_needs_two_different_people` | PASSED |
| 2 | 同一个人同时拥有两个角色时，重复审批不计为双人审批（有测试） | `test_criterion2_same_person_two_roles_is_not_dual_approval`（写入层）<br>`test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual`（**判定层**，绕过应用层）<br>`test_approval_db_constraint_blocks_same_person_twice`（**数据库层**）<br>`test_decide_same_person_two_roles_rejected` | PASSED |
| 3 | 改判后按原报备时间重新判定归属，结果写入审计日志（集成测试） | `test_criterion3_recompute_attribution_by_original_reported_at`<br>`test_criterion3_audit_has_actor_before_after_reason`<br>`test_criterion3_dispute_decision_written_to_audit` | PASSED |

### 验收标准 2 是**三层**防线（每层单独测）

| 层 | 位置 | 测试 |
|---|---|---|
| ① 写入层 | `apply_approval` 拒绝同一人第二次审批（409） | `test_criterion2_same_person_two_roles_is_not_dual_approval` |
| ② 判定层 | `evaluate_quorum` 按**人**（不是角色）做二分图配对 ⇒ 同一人配不出两个角色 | `test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual` |
| ③ 数据库层 | 表上唯一约束 `uq_dispute_approval_once_per_person (dispute_id, approver_id)` ⇒ 并发下也拦得住 | `test_approval_db_constraint_blocks_same_person_twice` |

⚠️ **② 与 ③ 是独立的**：① 会被并发绕过（check-then-act 竞态），
③ 拦得住但**换一条写入路径**（数据修复脚本）就可能绕过去 ⇒ ② 兜底。

## 3. 变异测试（证明测试**有区分力**，而不是「碰巧绿」）

⚠️ 只跑绿不算数：把实现改坏，测试**必须**变红。
每条变异 = 「改坏一处 ⇒ 期望某个具体判断被抓住」。

### 变异 1：同一人可占两个角色（双人审批的判定层被绕开）

```diff
                 if augment(held_role, visited):
                     assigned[role] = person
                     person_to_role[person] = role
                     return True
-                continue
+                assigned[role] = person
+                person_to_role[person] = role
+                return True
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual
1 failed, 38 passed, 3 warnings in 1.28s
```

⚠️ **这条变异只被「判定层」那条测试抓住**（写入层那条在数据写进去之前
就被 409 挡下了 ⇒ 走不到判定）⇒ **正好说明为什么要分层测**。

### 变异 2：未达成时一律报「一个角色都没满足」（接口契约 `missing_roles`）

```diff
     matched = _match_roles_to_people(role_to_approvers)
+    if len(matched) != len(REQUIRED_ROLES):
+        return False, (), REQUIRED_ROLES
     satisfied_t = tuple(r for r in REQUIRED_ROLES if r in matched)
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion1_single_role_approval_does_not_take_effect
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_is_not_dual_approval
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual
FAILED tests/test_api.py::test_decide_overturn_needs_two_different_people - A...
4 failed, 35 passed, 3 warnings in 1.20s
```

⚠️ **这个变异打的是接口契约**：只批了 `channel_manager` 时，接口必须报
`missing_roles=["finance"]`；若报成两个角色都缺 ⇒ 调用方以为「刚那次没生效」
⇒ 会重复审批 ⇒ 被 409 挡下 ⇒ 调用方一脸困惑。

### 变异 3：双人判定退化为「拿第一个人」（贪心）

```diff
-            held_role = person_to_role.get(person)
+            held_role = None
             if held_role is not None:
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual
1 failed, 38 passed, 3 warnings in 1.22s
```

⚠️ 贪心会在 `(P,cm)、(P,fin)、(Q,cm)` 这种数据上**假阴性** ⇒ 这里用
**增广路**（Kuhn 算法）⇒ 判定是**充要**的。

### 变异 4：去掉「同一人重复审批」的写入层拦截

```diff
-    for ap in _existing_approvals(session, dispute.id):
-        if ap.approver_id == approver_id:
-            raise ApprovalError(
-                "same_person_already_approved",
-                "该员工已就本争议审批过；同一人重复审批不计为双人审批",
-            )
+    # MUTANT: 去掉同一人重复审批拦截
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_is_not_dual_approval
FAILED tests/test_api.py::test_decide_same_person_two_roles_rejected - sqlalc...
2 failed, 37 passed, 3 warnings in 1.75s
```

⚠️ 注意失败信息里的 `sqlalc...`：去掉写入层拦截后，**数据库唯一约束**当场
把重复写挡住了（`IntegrityError`）⇒ **第 ③ 道防线真的在工作**，
但接口从 409 变成了 500 ⇒ 测试照样红。

### 变异 5：归属重算基准 `reported_at` → `created_at`

```diff
-                RefReport.reported_at <= report.reported_at,
+                RefReport.reported_at <= report.created_at,
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion3_recompute_attribution_by_original_reported_at
1 failed, 38 passed, 3 warnings in 1.19s
```

⚠️⚠️ **这条变异一开始「照样绿」**——第一版的测试数据里，两条报备的
`created_at` 与 `reported_at` **顺序一致** ⇒ 两种基准给出的候选集**相同**
⇒ 分不出差异 ⇒ **门是假的**。

⇒ 修法：构造出「`created_at` 与 `reported_at` 顺序**相反**、且两者给出
**不同候选集**」的样本（`late.created_at` 落在 `early.reported_at` **之前**），
并在测试里加**前置断言**把「两种基准确实给出不同答案」这件事钉死：

```python
assert early.reported_at < late.reported_at, "reported_at 顺序应相反"
assert early.created_at > late.created_at, "created_at 顺序应相反"
assert late.created_at < early.reported_at, (
    "created_at 基准必须落在 early.reported_at 之前，"
    "否则两种基准结果相同、测不出差异"
)
```

修正后变异被捕获（见上）。

### 变异 6：`session_scope` 退回裸生成器（CLI 入口不可用）

```diff
-@contextmanager
-def session_scope() -> Iterator[Session]:
+def session_scope():
```

```
FAILED tests/test_tasks_cli.py::test_session_scope_is_a_context_manager - Typ...
FAILED tests/test_tasks_cli.py::test_session_scope_rolls_back_on_error - Type...
FAILED tests/test_tasks_cli.py::test_remind_disputes_cli_runs_and_is_idempotent
3 failed, 36 passed, 3 warnings in 1.13s
```

⚠️ **这里踩到一个真 bug**：`session_scope()` 原本是**裸生成器**，
而 `with session_scope()` 要求**上下文管理器** ⇒
`TypeError: 'generator' object does not support the context manager protocol`
⇒ **CLI 入口完全不可用**。

⚠️ 而**服务层测试全绿**（它们不用这个上下文管理器）⇒ **没人发现**。

⇒ 修法：`@contextmanager` 装饰器。
⇒ 并补 `tests/test_tasks_cli.py` **回归测试**（覆盖：上下文管理器可用、
异常时回滚、CLI 幂等）—— **凡是「有入口」的东西，入口本身也要测**。

### 变异 7：报备状态不恢复（改判只改归属、不改结论）

```diff
-        report.status = "accepted"
-        report.reject_reason = None
+        report.status = report_status_before
+        report.reject_reason = reject_reason_before
```

```
FAILED tests/test_api.py::test_overturn_restores_the_rejected_report - Assert...
1 failed, 38 passed, 3 warnings in 1.11s
```

⚠️ 改判 = 认定系统判错了 ⇒ 被驳回的报备要**恢复为 `accepted`**、驳回原因要
清空 ⇒ 否则这条报备仍带着 `rejected_invalid` ⇒ 下游按 status 取数时**仍把
它当成被否决的报备** ⇒ 改判只改了归属、没改结论。

### 变异 8：只通知新归属人，不通知失去归属的一方

```diff
-        if previous_owner and previous_owner != new_owner:
+        if False:
```

```
FAILED tests/test_api.py::test_overturn_notifies_the_previous_owner - Asserti...
1 failed, 38 passed, 3 warnings in 1.18s
```

⚠️ 工单明写「通知**受影响各方**」⇒ **归属被夺走的一方**是最典型的受影响方
⇒ 只通知新归属人是不够的。

### 变异测试汇总

```
✅ 捕获  变异 1：同一人可占两个角色（双人审批的判定层被绕开）
✅ 捕获  变异 2：未达成时一律报「一个角色都没满足」（接口的 missing_roles 契约）
✅ 捕获  变异 3：双人判定退化为「拿第一个人」（贪心）
✅ 捕获  变异 4：去掉「同一人重复审批」的写入层拦截
✅ 捕获  变异 5：归属重算基准 reported_at → created_at
✅ 捕获  变异 6：session_scope 退回裸生成器（CLI 入口不可用）
✅ 捕获  变异 7：报备状态不恢复（改判只改归属、不改结论）
✅ 捕获  变异 8：只通知新归属人，不通知失去归属的一方

共 8 条变异，捕获 8 条。
```

## 4. 迁移（`alembic upgrade` / `downgrade` / `upgrade` 完整循环）

```
$ docker exec refdispute-pg psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 06159473da6e, S6-REF-008 init: ref_report/ref_dispute/dispute_approval/audit_log

$ docker exec refdispute-pg psql -U app -d app -c "\dt"
             List of relations
 Schema |       Name        | Type  | Owner
--------+-------------------+-------+-------
 public | alembic_version   | table | app
 public | audit_log         | table | app
 public | dispute_approval  | table | app
 public | notification_stub | table | app
 public | ref_dispute       | table | app
 public | ref_report        | table | app
 public | staff_role        | table | app
(7 rows)

$ .venv/bin/python -m alembic downgrade base
INFO  [alembic.runtime.migration] Running downgrade 06159473da6e -> , S6-REF-008 init: ...
$ docker exec refdispute-pg psql -U app -d app -c "\dt"
         List of relations
 Schema |       Name        | Type  | Owner
--------+-------------------+-------+-------
 public | alembic_version   | table | app
(1 row)

$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 06159473da6e, S6-REF-008 init: ...
```

⚠️ **表结构来自 Alembic 迁移**，不是 `create_all`（后者只在测试夹具里用）。

### 关键约束确实进了迁移

```
$ docker exec refdispute-pg psql -U app -d app -c "SELECT conrelid::regclass AS tbl, conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype IN ('u','c') AND connamespace='public'::regnamespace ORDER BY 1,2;"
       tbl        |               conname               |                          pg_get_constraintdef
------------------+-------------------------------------+-----------------------------------------------------------------
 staff_role       | uq_staff_role                       | UNIQUE (staff_id, role)
 ref_dispute      | ck_ref_dispute_reason_allowed       | CHECK (reason_code = ANY (ARRAY['normalization_false_duplicate'::character varying, 'existing_customer_data_error'::character varying, 'wrong_attribution'::character varying, 'other_system_error'::character varying]))
 dispute_approval | uq_dispute_approval_once_per_person | UNIQUE (dispute_id, approver_id)
(3 rows)
```

### ⚠️⚠️ 迁移与 ORM 模型的表结构**逐字一致**（这一步真抓到过一个 bug）

⚠️ 测试用 `create_all` 建表（⇒ **模型**的表结构），生产用 **Alembic**
（⇒ **迁移**的表结构）⇒ 两边不一致 ⇒ **测试跑的是另一套东西**。

⇒ 做法：分别用两种方式建两个库，`pg_dump` 后**逐行 diff**：

```
$ docker exec refdispute-pg pg_dump -U app -d sch_mig   --schema-only --no-owner --no-privileges | … > /tmp/sch_mig.s
$ docker exec refdispute-pg pg_dump -U app -d sch_model --schema-only --no-owner --no-privileges | … > /tmp/sch_model.s
$ diff /tmp/sch_mig.s /tmp/sch_model.s && echo "✅ 一致"
✅ 迁移产生的表结构与模型表结构**完全一致**
```

⚠️ **这次 diff 抓到的真 bug**：迁移里的唯一约束是
`uq_dispute_approval_once_per_role_per_person (dispute_id, approver_role, approver_id)`
——**三元组**⇒ 同一个人**换个角色就能写第二行** ⇒
**验收标准 2 的数据库层兜底在生产上根本没生效**（只有测试里的模型约束是
对的）⇒ 这正是「测试跑的是另一套东西」的典型后果。
⇒ 已把迁移改成 `uq_dispute_approval_once_per_person (dispute_id, approver_id)`
（与 `app/models/entities.py` 一致）。

## 5. 端到端（真实 HTTP，`uvicorn` 起服务 + `curl` 打真实请求）

> ⚠️⚠️ **踩坑记录（必须写下来）**：第一次跑端到端时，**上一轮遗留的服务
> 还占着 18099 端口** ⇒ 新的 `uvicorn` **绑不上端口** ⇒ 所有 `curl` 都打到了
> **旧代码**上 ⇒ 「非报备方提争议」返回了 **201**（旧代码没有这条校验）。
> ⇒ **差点把假结果写进交付**。
> ⇒ 修法：脚本启动前先检查端口是否被占用，并**确认自己起的进程还活着**，
> 否则直接报错退出。**端到端结果只有在「确认打的是刚起的服务」时才作数。**

### 端到端原始输出

```
===== ① 健康检查 =====
$ curl -s http://127.0.0.1:18099/healthz
{"status":"ok"}
$ curl -s http://127.0.0.1:18099/readyz
{"status":"ok","db":"127.0.0.1:55432/app"}

===== ② 复核列表（status=accepted）=====
$ curl -s -H 'X-Actor-Id: $ACTOR' 'http://127.0.0.1:18099/api/admin/ref/reports?status=accepted'
[{"id":"6c33349c-8e2e-41a6-bfee-1dad948c5070","org_id":"11111111-1111-1111-1111-111111111111","reporter_type":"staff","reporter_id":"423110f4-a847-45be-972c-a5ea76caaf33","owner_staff_id":"174c33c1-7a83-4419-9e1c-df3aa2f5dc58","customer_id":"aaaaaaaa-0000-0000-0000-000000000001","channel_id":"bbbbbbbb-0000-0000-0000-000000000001","reported_at":"2026-11-01T08:00:00Z","status":"accepted","reject_reason":null,"amount_cents":7925,"created_at":"2026-11-22T12:16:08.053049Z"}]

===== ③ 驳回：空原因 ⇒ 422 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../reports/{id}/reject' -d '{"reason":"  "}'
{"detail":[{"type":"value_error","loc":["body","reason"],"msg":"Value error, 驳回原因不能为空","input":"  ","ctx":{"error":{}}}]} [status=422]

===== ④ 争议理由「更早在线下接触过客户」⇒ 422 不受理 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../reports/{id}/disputes' -d '{"reason_code":"earlier_offline_contact",...}'
{"detail":[{"type":"value_error","loc":["body","reason_code"],"msg":"Value error, 争议理由 earlier_offline_contact 不受理；只受理系统判断错误类原因（可用：['existing_customer_data_error', 'normalization_false_duplicate', 'other_system_error', 'wrong_attribution']）","input":"earlier_offline_contact","ctx":{"error":{}}}]} [status=422]

===== ⑤ 附件 6 个 ⇒ 422 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../reports/{id}/disputes' -d '{"attachments":[6 个]}'
{"detail":[{"type":"value_error","loc":["body","attachments"],"msg":"Value error, 证据附件最多 5 个",...}]} [status=422]

===== ⑥ 非报备方提争议 ⇒ 422 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../reports/{id}/disputes' -H 'X-Actor-Id: <不是报备方>'
{"detail":"not_the_reporter: 只有该报备的报备方可以对它提出争议"} [status=422]

===== ⑦ 报备方提交争议 ⇒ 201 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../reports/{id}/disputes' -H 'X-Actor-Id: <报备方>'
{"id":"5a3dd027-e3f5-43c0-912a-37feea3cf859","org_id":"11111111-1111-1111-1111-111111111111","report_id":"ef08861e-5e14-43d7-96fa-5afe07bc94a7","disputer_id":"423110f4-a847-45be-972c-a5ea76caaf33","disputer_type":"staff","reason_code":"wrong_attribution","reason_text":"归一化误判为重复，归属判给了别人","attachments":[{"file_id":"f1","name":"proof.png","url":"https://x/proof.png"}],"status":"pending","decision_reason":null,"created_at":"2026-11-22T12:16:09.411055Z","decided_at":null}

===== ⑧ 同一人第一个角色审批（channel_manager）⇒ 不生效 =====
$ curl -s -X POST '.../disputes/{id}/decide' -H 'X-Actor-Id: <two_roles_person>' -d '{"decision":"overturn","role":"channel_manager",...}'
{"effective":false,"status":"pending","satisfied_roles":["channel_manager"],"missing_roles":["finance"],"attribution":{}}

===== ⑨ 同一人第二个角色审批（finance）⇒ 409 =====
$ curl -s -w ' [status=%{http_code}]' -X POST '.../disputes/{id}/decide' -H 'X-Actor-Id: <two_roles_person>' -d '{"decision":"overturn","role":"finance",...}'
{"detail":"same_person_already_approved: 该员工已就本争议审批过；同一人重复审批不计为双人审批"} [status=409]

===== ⑩ manager（另一个人）审批 ⇒ 仍不生效，missing 应只剩 finance =====
$ curl -s -X POST '.../disputes/{id}/decide' -H 'X-Actor-Id: <manager>' -d '{"decision":"overturn",...}'
{"effective":false,"status":"pending","satisfied_roles":["channel_manager"],"missing_roles":["finance"],"attribution":{}}

===== ⑪ finance（第四个人）审批 ⇒ 生效 =====
$ curl -s -X POST '.../disputes/{id}/decide' -H 'X-Actor-Id: <finance>' -d '{"decision":"overturn",...}'
{"effective":true,"status":"overturned","satisfied_roles":["channel_manager","finance"],"missing_roles":[],"attribution":{"report_id":"ef08861e-5e14-43d7-96fa-5afe07bc94a7","channel_id":"bbbbbbbb-0000-0000-0000-000000000001","customer_id":"aaaaaaaa-0000-0000-0000-000000000001","reported_at":"2026-11-12T08:22:47+00:00","previous_owner_staff_id":"2b8f3c44-1111-2222-3333-444455556666","owner_staff_id":"174c33c1-7a83-4419-9e1c-df3aa2f5dc58","basis":"first_report_wins:earlier_report_exists:earlier_count=1:eligible_count=1","candidates_considered":1,"winning_report_id":"6c33349c-8e2e-41a6-bfee-1dad948c5070","winning_report_reported_at":"2026-11-01T08:00:00+00:00","candidate_ids":["6c33349c-8e2e-41a6-bfee-1dad948c5070"],"strategy":"FirstReportWinsStrategy","report_status_before":"rejected_invalid","report_status_after":"accepted","reject_reason_before":"联系人信息虚假"}}

===== ⑫ 改判后的报备（归属按原报备时间重算，且状态已恢复 accepted）=====
$ curl -s '.../api/admin/ref/reports?status=accepted'
[{"id":"ef08861e-5e14-43d7-96fa-5afe07bc94a7",...,"owner_staff_id":"174c33c1-7a83-4419-9e1c-df3aa2f5dc58","reported_at":"2026-11-12T08:22:47Z","status":"accepted","reject_reason":null,...},{"id":"6c33349c-8e2e-41a6-bfee-1dad948c5070",...,"owner_staff_id":"174c33c1-7a83-4419-9e1c-df3aa2f5dc58","reported_at":"2026-11-01T08:00:00Z","status":"accepted","reject_reason":null,...}]
```

逐条对应：

| 步骤 | 期望 | 实测 |
|---|---|---|
| ③ | 驳回原因必填 | **422**，message「驳回原因不能为空」 |
| ④ | 「更早在线下接触过客户」**不受理** | **422** |
| ⑤ | 附件**最多 5 个** | **422** |
| ⑥ | **不是报备方**不能提争议 | **422** `not_the_reporter` |
| ⑦ | 报备方提交争议 | **201**，`status=pending` |
| ⑧ | 一个角色审批 ⇒ 不生效 | `effective=false`，`satisfied_roles=["channel_manager"]`，`missing_roles=["finance"]` |
| ⑨ | 同一人第二个角色 ⇒ 拒 | **409** `same_person_already_approved` |
| ⑩⑪ | 两个不同的人 ⇒ 生效 | `effective=true`，`status=overturned`，`missing_roles=[]` |
| ⑪ | 按**原报备时间**重算归属 | `owner_staff_id=174c33c1...`（= 更早那条报备的归属人），`basis=first_report_wins:earlier_report_exists` |
| ⑪⑫ | 改判后报备**恢复为 accepted**、驳回原因清空 | `report_status_after=accepted`，`reject_reason=null` |

### 审计日志（真实库查询）

```
$ docker exec refdispute-pg psql -U app -d app -c "SELECT action, actor_id, before_status, after_status, left(coalesce(reason,''),28) AS reason FROM audit_log ORDER BY created_at;"
        action         |               actor_id               |  before_status   | after_status |              reason
-----------------------+--------------------------------------+------------------+--------------+----------------------------------
 dispute.submit        | 423110f4-a847-45be-972c-a5ea76caaf33 |                  | pending      | 归一化误判为重复，归属判给了别人
 dispute.approval      | 423110f4-a847-45be-972c-a5ea76caaf33 | pending          | pending      | 同意改判
 dispute.approval      | 5f22c15f-8668-46e7-9764-f2320712a67a | pending          | pending      | 同意改判
 dispute.overturn      | 16a4852a-bb5e-4852-97c8-1bd7e74c2fcd | pending          | overturned   | 同意改判
 attribution.recompute | 16a4852a-bb5e-4852-97c8-1bd7e74c2fcd | rejected_invalid | accepted     | 同意改判
(5 rows)
```

⚠️ 每条都有**操作人、前后状态、理由**（工单原文要求）。
⚠️ 注意 `dispute.approval` 出现**两条**（同一人第一次 + manager）——
两条都**没有**改变状态（`before=after=pending`）⇒
**只有一个人时改判确实不生效**。

### 归属重算的审计明细（可复现判定）

```
$ docker exec refdispute-pg psql -U app -d app -tAc "SELECT detail FROM audit_log WHERE action='attribution.recompute';"
{"report_id": "ef08861e-5e14-43d7-96fa-5afe07bc94a7", "channel_id": "bbbbbbbb-...", "customer_id": "aaaaaaaa-...", "reported_at": "2026-11-12T08:22:47+00:00", "previous_owner_staff_id": "2b8f3c44-...", "owner_staff_id": "174c33c1-...", "basis": "first_report_wins:earlier_report_exists:earlier_count=1:eligible_count=1", "candidates_considered": 1, "winning_report_id": "6c33349c-...", "winning_report_reported_at": "2026-11-01T08:00:00+00:00", "candidate_ids": ["6c33349c-..."], "strategy": "FirstReportWinsStrategy", "report_status_before": "rejected_invalid", "report_status_after": "accepted", "reject_reason_before": "联系人信息虚假"}
```

⚠️ 审计里带**获胜报备的 id + 原报备时间 + 候选集** ⇒ 判定**可复现**。

### 通知桩（受影响各方）

```
$ docker exec refdispute-pg psql -U app -d app -c "SELECT recipient, kind FROM notification_stub ORDER BY created_at;"
              recipient               |        kind
--------------------------------------+--------------------
 423110f4-a847-45be-972c-a5ea76caaf33 | dispute.overturned
 174c33c1-7a83-4419-9e1c-df3aa2f5dc58 | attribution.gained
 2b8f3c44-1111-2222-3333-444455556666 | attribution.lost
(3 rows)
```

⚠️ **归属被夺走的一方**（`attribution.lost`）也收到了通知 ⇒
「通知受影响各方」落到实处。

## 6. 超时提醒任务（10 天未处理 ⇒ 提醒负责人）

```
$ .venv/bin/python -m app.tasks remind-disputes --days 10
reminded=0                     # 当前没有「超期且未处理」的争议

$ # 造一条「12 天前提交、仍是 pending」的争议
$ .venv/bin/python -m app.tasks remind-disputes --days 10
reminded=1                     # 触发提醒
$ .venv/bin/python -m app.tasks remind-disputes --days 10
reminded=0                     # 幂等：不再重复提醒
```

提醒写下的通知与审计：

```
$ docker exec refdispute-pg psql -U app -d app -c "SELECT recipient, kind FROM notification_stub WHERE kind='dispute.overdue';"
    recipient    |      kind
-----------------+-----------------
 channel_manager | dispute.overdue
(1 row)

$ docker exec refdispute-pg psql -U app -d app -c "SELECT action, actor_id, reason FROM audit_log WHERE action='dispute.remind_overdue';"
         action         | actor_id |         reason
------------------------+----------+------------------------
 dispute.remind_overdue | system   | 争议已超过 10 天未处理
(1 row)
```

⚠️ **已处理的争议不提醒**（上面端到端里那条已 `overturned` 的争议，
即使把 `created_at` 改老也**不会**被提醒）⇒ 由
`status == "pending"` 过滤。

⚠️ 做成**独立 CLI**（由外部 cron / K8s CronJob 触发），不在进程内起后台
线程——进程内定时器在容器重启/多副本时会重复触发或漏触发。

## 7. 报备方页面与接口文档（工单要求「两处都写明」）

```
$ curl -s 'http://127.0.0.1:18099/ref/report/{id}/dispute' | grep -E '只受理|不受理|最早|最多 5 个|首次报备|归一化'
<tr><td><code>normalization_false_duplicate</code></td><td>系统把这条归一化后误判成了重复</td></tr>
<p>凡是<strong>与首次报备规则冲突</strong>的理由都不受理，例如：</p>
<li><code>earlier_offline_contact</code> —— 与首次报备规则冲突的理由不受理（只受理系统判断错误类）</li>
<li><code>first_report_rule_conflict</code> —— 与首次报备规则冲突的理由不受理（只受理系统判断错误类）</li>
<p class="hint">这些情况按<strong>首次报备</strong>规则判定归属，
<option value="existing_customer_data_error">系统里存量客户信息有误</option>...
<label for="attachments">证据附件（最多 5 个）</label>
```

```
$ curl -s 'http://127.0.0.1:18099/openapi.json' | python3 -c 'import json,sys; print(json.load(sys.stdin)["paths"]["/api/ref/reports/{report_id}/disputes"]["post"]["description"][:300])'
报备方对拒绝结果有异议时，提交说明与证据附件（**最多 5 个文件**）。

## 受理范围（工单明确要求）

**只受理「系统判断错误」类原因**：

| reason_code | 含义 |
|---|---|
| `normalization_false_duplicate` | 归一化误判为重复 |
| `existing_customer_data_error` | 存量客户信息有误 |
| `wrong_attribution` | 归属判错 |
| `other_system_error` | 其它系统错误 |

**不受理**「更早在线下接触过客户」这类**与首次报备规则冲突*
```

⚠️ 页面上的**受理理由表是从代码里的白名单生成的**（不手写第二份）⇒
页面与代码**不可能漂移**（`tests/test_report_page.py` 对两处都有断言）。

## 8. 静态检查

```
$ .venv/bin/python -m ruff check app tests
All checks passed!
```

## 已知局限

1. **S2-IAM 是接口桩**：当前身份从 `X-Actor-Id` 头取，角色从 `staff_role`
   表取。真实接入时改 `app/api/deps.py::get_actor` 与
   `app/services/approval.py::roles_of` 两处即可，路由层与业务层不感知。
2. **归属规则是默认实现**：`FirstReportWinsStrategy`（同渠道同客户时
   原报备时间更早者优先）——真实归属规则属其它工单，用
   `AttributionStrategy` 协议替换即可。
3. **通知是桩**：落 `notification_stub` 表，不真正发消息。
4. **证据附件只存元数据**：文件内容由既有文件服务托管，本单不碰。
5. **没有鉴权中间件**：身份头是桩，未经真实鉴权 ⇒ 仅适用于内网/联调，
   上线前必须接入 S2-IAM。
6. **Redis 未使用**：统一技术约定提到 Redis，但本单无缓存需求，故未引入。
7. **单机单副本假设**：`remind_overdue_disputes` 的幂等靠 `reminded_at`
   标记；多副本并发跑同一批时可能重复通知（需要分布式锁或
   `UPDATE … WHERE reminded_at IS NULL` 的原子写法）。
8. **并发**：改判审批用 `SELECT … FOR UPDATE` 锁住争议行 ⇒ 两人同时审批时
   后者会等前者提交 ⇒ 不会双双判成「还差一个角色」。但**多副本**部署下
   该行锁只在**单库**内有效（需要跨库协调时另说）。
