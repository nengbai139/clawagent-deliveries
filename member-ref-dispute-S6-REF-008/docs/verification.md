# 验证记录（S6-REF-008）

⚠️ 全部为**真实运行**的命令与**原始输出**（非「预期输出」）。
环境见下方「环境」一节。

## 环境

| 项 | 值 |
|---|---|
| 操作系统 | macOS（Darwin 25.5.0, arm64） |
| Python | 3.13.17（`uv venv --python 3.13`） |
| 数据库 | PostgreSQL 16（`postgres:16-alpine`，docker 一次性容器，端口 55432） |
| 依赖 | `fastapi` / `sqlalchemy 2.1.9` / `alembic` / `psycopg` / `pydantic 2` / `pytest 9.2.0` / `httpx` |
| 客户要求的大版本 | Python 3.11+ / PostgreSQL 16 ⇒ **逐项对齐** |

> ⚠️ 测试**必须**跑在真实 PostgreSQL 16 上：验收标准 3 是**集成测试**，
> 涉及 `CheckConstraint` / `UniqueConstraint` / `pgvector` 的 UUID 方言 ⇒
> SQLite 下测的是另一套东西。

## 1. 单元/集成测试全绿

```
$ .venv/bin/python -m pytest tests/ -v
============================= test session starts ==============================
platform darwin -- Python 3.13.17, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/baineng/Documents/devops/qdtech/member-ref-dispute
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0
collected 25 items

tests/test_acceptance_criteria.py::test_criterion1_single_role_approval_does_not_take_effect PASSED [  4%]
tests/test_acceptance_criteria.py::test_criterion1_two_different_people_two_roles_takes_effect PASSED [  8%]
tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_is_not_dual_approval PASSED [ 12%]
tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual PASSED [ 16%]
tests/test_acceptance_criteria.py::test_criterion2_distinct_people_with_overlapping_roles_still_dual PASSED [ 20%]
tests/test_acceptance_criteria.py::test_criterion3_recompute_attribution_by_original_reported_at PASSED [ 24%]
tests/test_acceptance_criteria.py::test_criterion3_audit_has_actor_before_after_reason PASSED [ 28%]
tests/test_acceptance_criteria.py::test_criterion3_dispute_decision_written_to_audit PASSED [ 32%]
tests/test_api.py::test_list_reports_requires_actor PASSED               [ 36%]
tests/test_api.py::test_list_reports_filters PASSED                      [ 40%]
tests/test_api.py::test_verify_and_reject_reports PASSED                 [ 44%]
tests/test_api.py::test_reject_only_from_accepted PASSED                 [ 48%]
tests/test_api.py::test_submit_dispute_rejects_disallowed_reason PASSED  [ 52%]
tests/test_api.py::test_submit_dispute_allows_system_error_reason PASSED [ 56%]
tests/test_api.py::test_submit_dispute_rejects_more_than_5_attachments PASSED [ 60%]
tests/test_api.py::test_decide_overturn_needs_two_different_people PASSED [ 64%]
tests/test_api.py::test_decide_same_person_two_roles_rejected PASSED     [ 68%]
tests/test_api.py::test_decide_ambiguous_role_requires_explicit PASSED   [ 72%]
tests/test_api.py::test_decide_uphold_takes_effect_immediately PASSED    [ 76%]
tests/test_api.py::test_decide_without_required_role_403 PASSED          [ 80%]
tests/test_reminder.py::test_overdue_dispute_reminded PASSED             [ 84%]
tests/test_reminder.py::test_recent_dispute_not_reminded PASSED          [ 88%]
tests/test_reminder.py::test_reminder_is_idempotent PASSED               [ 92%]
tests/test_reminder.py::test_reminder_writes_audit PASSED                [ 96%]
tests/test_reminder.py::test_decided_dispute_not_reminded PASSED         [100%]
======================== 25 passed, 1 warning in 0.93s =========================
```

## 2. 逐条对照验收标准

| # | 验收标准 | 对应测试 | 结果 |
|---|---|---|---|
| 1 | 只有一个角色审批时改判不生效，两个不同的人分别以两种角色审批后生效（有测试） | `test_criterion1_single_role_approval_does_not_take_effect`<br>`test_criterion1_two_different_people_two_roles_takes_effect`<br>`test_decide_overturn_needs_two_different_people` | PASSED |
| 2 | 同一个人同时拥有两个角色时，重复审批不计为双人审批（有测试） | `test_criterion2_same_person_two_roles_is_not_dual_approval`<br>`test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual`<br>`test_decide_same_person_two_roles_rejected` | PASSED |
| 3 | 改判后按原报备时间重新判定归属，结果写入审计日志（集成测试） | `test_criterion3_recompute_attribution_by_original_reported_at`<br>`test_criterion3_audit_has_actor_before_after_reason`<br>`test_criterion3_dispute_decision_written_to_audit` | PASSED |

## 3. 变异测试（证明测试**有区分力**，而不是「碰巧绿」）

⚠️ 只跑绿不算数：把实现改坏，测试**必须**变红。

### 变异 1：去掉「同一人重复审批」拦截（写入层）

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
FAILED tests/test_api.py::test_decide_same_person_two_roles_rejected - assert...
2 failed, 23 passed, 1 warning in 0.97s
```

### 变异 2：双人判定退化为「拿第一个人」（判定层）

```diff
         picked = None
         for person in sorted(approvers, key=str):
-            if person not in used_people:
-                picked = person
-                break
+            picked = person
+            break
```

```
FAILED tests/test_acceptance_criteria.py::test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual
1 failed, 24 passed, 1 warning in 0.90s
```

⚠️ 这条**独立于**变异 1：它打的是**判定**（`evaluate_quorum` 的二分图
配对），不是**写入** ⇒ 证明「双人」这个性质由**判定**保证，不只由
**写入**保证（换一条写入路径绕过去也认不出来）。

### 变异 3：归属重算基准 `reported_at` → `created_at`

```diff
-                RefReport.reported_at <= report.reported_at,
+                RefReport.reported_at <= report.created_at,
```

```
        assert result["effective"] is True
        assert dispute.status == "overturned"
>       assert late.owner_staff_id == early_owner
E       AssertionError: assert UUID('43760730-...') == UUID('fff4ab0f-...')
FAILED tests/test_acceptance_criteria.py::test_criterion3_recompute_attribution_by_original_reported_at
1 failed, 24 passed, 1 warning in 0.92s
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

## 4. 迁移（`alembic upgrade` / `downgrade` / `upgrade` 完整循环）

```
$ docker exec refdispute-pg psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 06159473da6e, S6-REF-008 init: ...

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

```bash
$ grep -E "ck_ref_dispute|uq_dispute_approval|uq_staff_role" alembic/versions/*.py
    sa.UniqueConstraint('staff_id', 'role', name='uq_staff_role')
    sa.CheckConstraint("reason_code IN ('normalization_false_duplicate', 'existing_customer_data_error', 'wrong_attribution', 'other_system_error')", name='ck_ref_dispute_reason_allowed'),
    sa.UniqueConstraint('dispute_id', 'approver_role', 'approver_id', name='uq_dispute_approval_once_per_role_per_person')
```

## 5. 端到端（真实 HTTP，`uvicorn` 起服务 + `curl`/urllib 打真实请求）

```
$ .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18099
$ curl -s http://127.0.0.1:18099/healthz
{"status":"ok"}
$ curl -s http://127.0.0.1:18099/readyz
{"status":"ok","db":"127.0.0.1:55432/app"}
```

接口清单（`GET /openapi.json`）：

```
  GET /api/admin/ref/disputes/{dispute_id}
  POST /api/admin/ref/disputes/{dispute_id}/decide
  GET /api/admin/ref/reports
  POST /api/admin/ref/reports/{report_id}/reject
  POST /api/admin/ref/reports/{report_id}/verify
  POST /api/ref/reports/{report_id}/disputes
  GET /healthz
  GET /readyz
```

### 端到端原始输出

```
[准备] report_late=ef08861e-5e14-43d7-96fa-5afe07bc94a7  report_early=6c33349c-8e2e-41a6-bfee-1dad948c5070
[准备] manager=5f22c15f-8668-46e7-9764-f2320712a67a  finance=16a4852a-bb5e-4852-97c8-1bd7e74c2fcd  two_roles_person=423110f4-a847-45be-972c-a5ea76caaf33

① 复核列表 status=200  条数=1
② 驳回（空原因）status=422  detail=[{'type': 'value_error', 'loc': ['body', 'reason'], 'msg': 'Value error, 驳回原因不能为空', ...}]
③ 争议理由(线下先见过) status=422  detail=[{'type': 'value_error', 'loc': ['body', 'reason_code'], 'msg': "Value...
④ 附件 6 个 status=422  detail=[{'type': 'value_error', 'loc': ['body', 'attachments'], 'msg': 'Value
⑤ 提交争议 status=201  dispute_id=298bd59b-55ff-48e6-9815-c0d6d11f5a95  附件数=1
⑥ 同一人第一次审批 status=200  effective=False  missing=['finance']
⑦ 同一人第二次审批 status=409  detail=same_person_already_approved: 该员工已就本争议审批过；同一人重复审批不计为双人审批
⑧ manager 审批 status=200  effective=False  missing=['finance']
⑨ finance 审批 status=200  effective=True  status=overturned
   归属重算结果: {"report_id": "ef08861e-...", "reported_at": "2026-11-12T08:22:47.110314+00:00", "owner_staff_id": "174c33c1-7a83-4419-9e1c-df3aa2f5dc58", "basis": "first_report_wins:earlier_report_exists:earlier_count=1", "candidates_considered": 1}
```

逐条对应：

| 步骤 | 期望 | 实测 |
|---|---|---|
| ② | 驳回原因必填 | **422**，message「驳回原因不能为空」 |
| ③ | 「更早在线下接触过客户」**不受理** | **422** |
| ④ | 附件**最多 5 个** | **422** |
| ⑥ | 一个角色审批 ⇒ 不生效 | `effective=False`，`missing=['finance']` |
| ⑦ | 同一人第二个角色 ⇒ 拒 | **409** `same_person_already_approved` |
| ⑧⑨ | 两个不同的人 ⇒ 生效 | `effective=True`，`status=overturned` |
| ⑨ | 按**原报备时间**重算归属 | `owner_staff_id=174c33c1...`（= 更早那条报备的归属人），`basis=first_report_wins:earlier_report_exists` |

### 审计日志（真实库查询）

```
$ docker exec refdispute-pg psql -U app -d app -c "SELECT action, actor_id, before_status, after_status, left(coalesce(reason,''),28) AS reason, left(coalesce(detail,''),60) AS detail FROM audit_log ORDER BY created_at;"

         action         |               actor_id               | before_status   | after_status   |      reason      |                            detail
-----------------------+--------------------------------------+------------------+------------------+------------------+--------------------------------------------------------------
 dispute.submit        | 423110f4-a847-45be-972c-a5ea76caaf33 |                  | pending          | 归一化误判为重复 | {"report_id": "ef08861e-...", "reaso
 dispute.approval      | 423110f4-a847-45be-972c-a5ea76caaf33 | pending          | pending          | 同意改判         | {"role": "channel_manager", "satisfied_roles": ["channel_man
 dispute.approval      | 5f22c15f-8668-46e7-9764-f2320712a67a | pending          | pending          | 同意改判         | {"role": "channel_manager", "satisfied_roles": ["channel_man
 dispute.overturn      | 16a4852a-bb5e-4852-97c8-1bd7e74c2fcd | pending          | overturned       | 同意改判         | {"role": "finance", "satisfied_roles": ["channel_manager", "
 attribution.recompute | 16a4852a-bb5e-4852-97c8-1bd7e74c2fcd | rejected_invalid | rejected_invalid | 同意改判         | {"report_id": "ef08861e-...", "repor
(5 rows)
```

⚠️ 每条都有**操作人、前后状态、理由**（工单原文要求）。
⚠️ 注意 `dispute.approval` 出现**两条**：同一人第一次（`423110f4`）与
manager（`5f22c15f`）——两条都**没有**改变状态（`before=after=pending`）⇒
**只有一个人时改判确实不生效**。

## 6. 超时提醒任务

```
$ .venv/bin/python -m app.tasks remind-disputes --days 10
reminded=1
```

（覆盖：>10 天才提醒、<10 天不提醒、**幂等**（第二次 `reminded=0`）、
已处理的争议不提醒、提醒写审计。）

## 7. 静态检查

```
$ .venv/bin/python -m ruff check app tests
（无输出 = 无问题）
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
