# ClawHunt 交付仓库

每张订单一个分支、一个 PR。分支命名：`order-<订单号>`。

> **本分支 `order-2980` 对应订单 #2980**（【S2-IAM-015】九个岗位角色定义与权限矩阵种子数据）。
> 本仓库按订单累积，每张订单各占一段；**本单内容在最前面的「订单 2980」段**，后面的「订单 2968」段是上一单，仅作迁移基线的上下文，不属于本单。

PR 正文里写清：改了什么、怎么验、验收标准逐条对应、评审人（@发布者）。

**为什么是公开仓库**：平台要求「交付物必须能被匿名取到」⇒ 私有仓库里的 PR 它的预检读不到 ⇒ 交付会被判不合格。

---

# 订单 2980 ·【S2-IAM-015】会员空间平台 · 九个岗位角色定义与权限矩阵种子数据

## 1. 技术栈

| 项 | 选型 | 说明 |
|----|------|------|
| 语言 | Python 3.11+（实测 3.12） | 与仓库既有工单一致 |
| Web | FastAPI | 角色增删查接口（`app/api/iam/roles.py`） |
| ORM | SQLAlchemy 2.0 声明式（`Mapped` / `mapped_column`） | `roles` / `role_permissions` 两张表 |
| 迁移 | Alembic | `migrations/versions/0001_roles.py`、`0002_role_permissions.py`，各含完整 downgrade |
| 数据库 | PostgreSQL 16（生产）/ SQLite（本地与测试） | 连接串**只从环境变量 `APP_DATABASE_URL` 读取** |
| 矩阵定义 | YAML（PyYAML） | `app/iam/roles/role_matrix.yml` 是唯一真源 |
| 测试 | pytest 8+ | `tests/iam/test_role_matrix.py`（19 个用例） |
| 第三方数据服务 | 无 | 未引入任何向境外发送数据的第三方 SDK |

## 2. 交付物清单

| # | 文件 | 内容 |
|---|------|------|
| 1 | `app/iam/roles/models.py` | `Role`（id/org_id/site_id/code/name/level/is_system/description + 统一审计与软删除字段）、`RolePermission`（role_id/permission_code/data_scope + 统一字段），`(role_id, permission_code)` 唯一 |
| 2 | `app/iam/roles/constants.py` | 角色层级（site/org）与数据范围（self/site/org）取值常量 |
| 3 | `app/iam/roles/role_matrix.yml` | **唯一真源**：36 条权限点白名单 + 9 个内置角色 × 权限点 × data_scope |
| 4 | `app/iam/roles/matrix.py` | 读取并校验 yml（未知 code / 非法 scope / 重复配置 ⇒ 报错，不静默跳过）；动作段按 code 最后一段解析 |
| 5 | `app/iam/roles/seed.py` | 幂等种子：按 (org_id, code) upsert 角色、按 (role_id, permission_code) upsert 权限行；不删除自定义角色 |
| 6 | `app/iam/roles/export.py` | 由 yml 渲染 Markdown 矩阵表（行=权限点，列=角色，单元格=data_scope 或 `—`） |
| 7 | `app/iam/roles/compare.py` | yml ↔ 数据库逐条三元组比对，差异不为 0 时非 0 退出码失败 |
| 8 | `app/iam/roles/service.py` | 角色读写与删除保护（内置角色删除 ⇒ 409，角色不存在 ⇒ 404） |
| 9 | `app/api/iam/roles.py` | `GET /api/iam/roles`、`POST /api/iam/roles`、`DELETE /api/iam/roles/{role_id}` |
| 10 | `app/iam/roles/cli.py`、`app/iam/roles/init_db.py` | 命令行公共支撑；本地建表辅助（正式迁移走 Alembic） |
| 11 | `alembic.ini`、`migrations/env.py`、`migrations/versions/0001_roles.py`、`migrations/versions/0002_create_role_permissions.py` | 两条迁移 + 完整 downgrade；连接串走 `APP_DATABASE_URL` |
| 12 | `docs/role_matrix.md` | **生成的** Markdown 矩阵表（勿手改） |
| 13 | `tests/iam/test_role_matrix.py` | pytest 测试，覆盖四条验收标准 |
| 14 | `scripts/show_role_matrix.py` | 取证脚本：打印 9 个角色的权限矩阵 + 409/404/2xx 响应体 |

## 3. 快速开始

```bash
pip install -r requirements.txt          # fastapi / sqlalchemy / alembic / pyyaml / pytest …
# 本次交付环境里 pypi.org 不可达，改用国内镜像安装（依赖版本按 requirements.txt 约束，与镜像无关）：
# pip install --user --break-system-packages -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# ① 建表（迁移）
export APP_DATABASE_URL='sqlite+pysqlite:///./local_roles.db'   # 生产换成 PostgreSQL 16
python3 -m alembic upgrade head

# ② 播种（幂等，可重复执行）
python3 -m app.iam.roles.seed

# ③ 生成 Markdown 矩阵表（写到 docs/role_matrix.md）
python3 -m app.iam.roles.export

# ④ 一致性比对（yml ↔ 数据库），差异不为 0 ⇒ 退出码 1
python3 -m app.iam.roles.compare

# ⑤ 跑测试
python3 -m pytest -v tests/iam/test_role_matrix.py
python3 -m pytest -v                       # 全量（含上一单 2968 的用例）
```

取证脚本（打印 9 个角色的权限矩阵 + 删除内置角色的 409 响应体）：

```bash
export APP_DATABASE_URL='sqlite+pysqlite:///./local_roles.db'
python3 scripts/show_role_matrix.py
```

## 4. 验收标准逐条对应

| 验收标准 | 实现 | 测试 / 证据 |
|----------|------|------------|
| **1. 种子执行后 9 个角色存在且 is_system=true，删除内置角色返回 409** | `app/iam/roles/seed.py`（9 个角色全部 `is_system=true`）、`app/iam/roles/service.py::delete_role`（内置角色抛 `role_is_system`）、`app/api/iam/roles.py`（映射为 409，错误体沿用仓库 `{"code","message"}` 格式） | `test_seed_creates_nine_system_roles`、`test_delete_system_role_returns_409`（断言 409 且记录仍在）、`test_delete_custom_role_succeeds`（自定义角色 2xx 可删）、`test_delete_missing_role_returns_404`（不存在 ⇒ 404 而非 409）、`test_seed_is_idempotent`；取证脚本输出见 §7.5 |
| **2. 测试断言 sys_admin 不含任何以 crm.、opp.、lead. 开头的权限点** | yml 中 `sys_admin` 只配 `iam.read/iam.write/iam.manage/sys.read/sys.manage/audit.read`（org） | `test_sys_admin_has_no_business_domain_permissions`：遍历 sys_admin 的权限点集合，断言不存在以 `crm.`/`opp.`/`lead.` 开头的 code，并断言集合非空、data_scope 全为 `org` |
| **3. 测试断言 executive 的权限点动作只有 read、read_basic、use 三种** | yml 中 `executive` 只配读类与使用类权限点（org） | `test_executive_actions_are_only_read_read_basic_use`：动作段（code 最后一段）⊆ {read, read_basic, use}，且三种都在集合内；另断言 write/manage/assign/export/publish/approve/read_sensitive 均不出现；data_scope 全 `org` |
| **4. Markdown 矩阵表由 role_matrix.yml 生成，与数据库内容一致（脚本比对通过）** | `app/iam/roles/export.py` 渲染 `docs/role_matrix.md`；`app/iam/roles/compare.py` 按 (role_code, permission_code, data_scope) 三元组比对 | `test_compare_script_reports_no_difference`（差异 0 条）、`test_markdown_matrix_matches_database`（解析 Markdown 表格逐格与数据库比对）、`test_markdown_row_count_matches_permission_count`（行数 = 36 = 白名单条数）、`test_compare_detects_extra_permission` / `test_compare_detects_scope_mismatch`（造差异能被检出）；脚本原始输出见 §7.4 |

## 5. 矩阵口径（9 个内置角色）

| 角色 code | 名称 | 层级 | 权限口径 |
|-----------|------|------|----------|
| `front_desk` | 前台接待 | site | 访客、签到、场地预约、活动查看、会员基本信息（`crm.read_basic`）、知识阅读、AI 助手 —— 只有这 9 个权限点 |
| `ops_specialist` | 运营专员 | site | 访客 / 签到 / 场地（读写分配）/ 活动读写 / 会员基本信息只读 + 知识与 AI |
| `member_manager` | 会员经理 | site | 会员资料**读为 site**，**写 / 跟进 / 敏感读为 self** |
| `opportunity_manager` | 商机经理 | site | **需求读取为 org**，**撮合写入（`opp.match`）为 self** |
| `bizdev_consultant` | 招商顾问 | site | 意向客户**读写均为 self** |
| `ops_supervisor` | 运营主管 | site | 本会所**运营（space）、商机（opp）、招商（lead）的读写 / 分配 / 导出**；**没有任何 iam.、sys. 权限** |
| `knowledge_admin` | 知识管理员 | org | **只有 kb 全部权限（org）+ `ai.review.approve` + `ai.assistant.use`** |
| `executive` | 管理层 | org | **只有 read / read_basic / use 三种动作**（org），无 write / manage / assign / export |
| `sys_admin` | 系统管理员 | org | **只有 iam. / sys. / audit. 权限**，不含任何 `crm.` / `opp.` / `lead.` 业务数据权限（职责分离） |

补充口径：

* 非组织数据维度的权限点（知识库 / AI 助手 / IAM / 系统 / 审计）统一按 `org` 落地；会员 / 商机 / 招商等业务数据按 `self` / `site` 落地。
* 动作段解析取 permission code 的**最后一段**（`crm.read_basic → read_basic`，`ai.assistant.use → use`），域段取第一段；域或对象名里出现 read / write 字样不影响判定。
* 权限点白名单共 36 条（见 yml 的 `permissions` 段）；yml 出现白名单外的 code ⇒ 种子直接报错退出。

## 6. 对接点（与其它工单的衔接）

* **权限点注册表（另一单）**：本单内置 36 条权限点 code 的占位白名单（`app/iam/roles/matrix.py::PERMISSION_CODES` + yml 的 `permissions` 段）。正式清单合入后，只需替换这两处，代码不用改；yml 引用白名单外的 code 会直接报错，不会静默写入。
* **运行时权限鉴权接入（另一单）**：本单只负责「角色 ⇒ 权限点 ⇒ data_scope」的数据，不在请求链路上做鉴权。`/api/iam/roles` 目前只要求已登录员工 + 组织隔离；「谁可以改角色」由运行时鉴权工单接入。
* **员工与角色绑定**：`employees` 与 `roles` 的绑定关系（谁属于哪个角色）不在本单范围，本单只交付角色与权限矩阵本身。
* **PostgreSQL 16**：本单用 SQLite 跑通了全部脚本与测试；生产连接串通过 `APP_DATABASE_URL` 注入（`postgresql+psycopg://...`），迁移脚本不含 SQLite 专有语法。
* **既有迁移基线**：`employees` / `user_identities` / `audit_logs`（订单 2968）目前仍走 `create_all`；Alembic 基线由 S2-IAM 主线统一出，本单的两条迁移已按基线可直接串联的方式编写（`0001_roles` → `0002_role_permissions`）。

## 7. 原始输出（证据）

### 7.1 建表 + 播种（幂等）

```console
$ export APP_DATABASE_URL='sqlite+pysqlite:///./local_roles.db'
$ python3 -m alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_roles, 创建 roles 表（S2-IAM-015 角色与权限矩阵）
INFO  [alembic.runtime.migration] Running upgrade 0001_roles -> 0002_role_permissions, 创建 role_permissions 表（S2-IAM-015 角色与权限矩阵）

$ python3 -m app.iam.roles.seed
数据库：sqlite+pysqlite:///./local_roles.db
角色（9 个）：front_desk, ops_specialist, member_manager, opportunity_manager, bizdev_consultant, ops_supervisor, knowledge_admin, executive, sys_admin
角色：新建 9 个，更新 0 个；权限点：写入 71 条，清理矩阵外 0 条；库内权限行总数：71

$ python3 -m app.iam.roles.seed          # 第二次：幂等，记录数不变
数据库：sqlite+pysqlite:///./local_roles.db
角色（9 个）：front_desk, ops_specialist, member_manager, opportunity_manager, bizdev_consultant, ops_supervisor, knowledge_admin, executive, sys_admin
角色：新建 0 个，更新 9 个；权限点：写入 0 条，清理矩阵外 0 条；库内权限行总数：71

$ python3 -c "import sqlite3; c=sqlite3.connect('local_roles.db'); print('roles:', c.execute('select count(*) from roles').fetchone()[0]); print('role_permissions:', c.execute('select count(*) from role_permissions').fetchone()[0])"
roles: 9
role_permissions: 71
```

### 7.2 pytest（本单 19 个用例）

```console
$ python3 -m pytest -v tests/iam/test_role_matrix.py
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 19 items

tests/iam/test_role_matrix.py::test_seed_creates_nine_system_roles PASSED [  5%]
tests/iam/test_role_matrix.py::test_role_levels_follow_matrix PASSED     [ 10%]
tests/iam/test_role_matrix.py::test_delete_system_role_returns_409 PASSED [ 15%]
tests/iam/test_role_matrix.py::test_delete_custom_role_succeeds PASSED   [ 21%]
tests/iam/test_role_matrix.py::test_delete_missing_role_returns_404 PASSED [ 26%]
tests/iam/test_role_matrix.py::test_seed_is_idempotent PASSED            [ 31%]
tests/iam/test_role_matrix.py::test_seed_rejects_unknown_permission_code PASSED [ 36%]
tests/iam/test_role_matrix.py::test_sys_admin_has_no_business_domain_permissions PASSED [ 42%]
tests/iam/test_role_matrix.py::test_executive_actions_are_only_read_read_basic_use PASSED [ 47%]
tests/iam/test_role_matrix.py::test_matrix_matrix_data_scopes_follow_spec PASSED [ 52%]
tests/iam/test_role_matrix.py::test_compare_script_reports_no_difference PASSED [ 57%]
tests/iam/test_role_matrix.py::test_markdown_matrix_matches_database PASSED [ 63%]
tests/iam/test_role_matrix.py::test_markdown_row_count_matches_permission_count PASSED [ 68%]
tests/iam/test_role_matrix.py::test_export_markdown_writes_file PASSED   [ 73%]
tests/iam/test_role_matrix.py::test_compare_detects_extra_permission PASSED [ 78%]
tests/iam/test_role_matrix.py::test_compare_detects_scope_mismatch PASSED [ 84%]
tests/iam/test_role_matrix.py::test_permission_whitelist_has_36_unique_codes PASSED [ 89%]
tests/iam/test_role_matrix.py::test_every_whitelisted_permission_is_used_by_some_role PASSED [ 94%]
tests/iam/test_role_matrix.py::test_role_codes_are_stable PASSED         [100%]

=============================== warnings summary ===============================
/tmp/clawagent-home-3325426589/.local/lib/python3.12/site-packages/fastapi/testclient.py:1
  /tmp/clawagent-home-3325426589/.local/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 19 passed, 1 warning in 1.41s =========================
```

### 7.3 全量测试（上一单 2968 的用例不受影响）

```console
$ python3 -m pytest -v
...
======================== 46 passed, 1 warning in 3.29s =========================
```

### 7.4 一致性比对脚本（yml ↔ 数据库）

```console
$ python3 -m app.iam.roles.export
已生成矩阵表：docs/role_matrix.md
角色 9 个，权限点 36 条

$ python3 -m app.iam.roles.compare
数据库：sqlite+pysqlite:///./local_roles.db
矩阵：9 个角色 × 36 条权限点
比对结果：一致，差异 0 条

# 造一条矩阵外的权限点后，比对必须报出差异并以非 0 退出码失败
$ python3 -m app.iam.roles.compare
数据库：sqlite+pysqlite:///./local_roles.db
矩阵：9 个角色 × 36 条权限点
比对结果：不一致，差异 1 条
[多余] 库里有、矩阵里没有：role=front_desk permission=crm.read_sensitive data_scope=self
$ echo $?
1
```

### 7.5 取证脚本：删除内置角色 ⇒ 409

```console
$ python3 scripts/show_role_matrix.py
### ① roles 表里的 9 个内置角色
  - bizdev_consultant      招商顾问   level=site  is_system=True 权限点数=4
  - executive              管理层    level=org   is_system=True 权限点数=10
  - front_desk             前台接待   level=site  is_system=True 权限点数=9
  - knowledge_admin        知识管理员  level=org   is_system=True 权限点数=6
  - member_manager         会员经理   level=site  is_system=True 权限点数=7
  - opportunity_manager    商机经理   level=site  is_system=True 权限点数=5
  - ops_specialist         运营专员   level=site  is_system=True 权限点数=12
  - ops_supervisor         运营主管   level=site  is_system=True 权限点数=12
  - sys_admin              系统管理员  level=org   is_system=True 权限点数=6

### ② 每个角色的权限点与数据范围（来自 role_permissions）
  bizdev_consultant: ai.assistant.use=org, kb.read=org, lead.read=self, lead.write=self
  executive: ai.assistant.use=org, checkin.read=org, crm.read=org, crm.read_basic=org, event.read=org, kb.read=org, lead.read=org, opp.read=org, space.read=org, visitor.read=org
  front_desk: ai.assistant.use=org, checkin.read=site, checkin.write=site, crm.read_basic=site, event.read=site, kb.read=org, space.read=site, visitor.read=site, visitor.write=site
  knowledge_admin: ai.assistant.use=org, ai.review.approve=org, kb.manage=org, kb.publish=org, kb.read=org, kb.write=org
  member_manager: ai.assistant.use=org, crm.follow_up=self, crm.read=site, crm.read_basic=site, crm.read_sensitive=self, crm.write=self, kb.read=org
  opportunity_manager: ai.assistant.use=org, kb.read=org, opp.match=self, opp.read=org, opp.write=self
  ops_specialist: ai.assistant.use=org, checkin.read=site, checkin.write=site, crm.read_basic=site, event.read=site, event.write=site, kb.read=org, space.assign=site, space.read=site, space.write=site, visitor.read=site, visitor.write=site
  ops_supervisor: lead.assign=site, lead.export=site, lead.read=site, lead.write=site, opp.assign=site, opp.export=site, opp.read=site, opp.write=site, space.assign=site, space.export=site, space.read=site, space.write=site
  sys_admin: audit.read=org, iam.manage=org, iam.read=org, iam.write=org, sys.manage=org, sys.read=org

### ③ DELETE 内置角色 ⇒ 409
  HTTP 409
  {'code': 'role_is_system', 'message': '内置角色不可删除：front_desk'}

### ④ DELETE 不存在的角色 ⇒ 404
  HTTP 404
  {'code': 'role_not_found', 'message': '角色不存在'}

### ⑤ 自定义角色可正常删除 ⇒ 2xx
  创建：HTTP 200 id=bfe1c0d5-223f-47f3-9644-ed783f6f20b6
  删除：HTTP 200
  {'status': 'deleted', 'id': 'bfe1c0d5-223f-47f3-9644-ed783f6f20b6', 'code': 'evidence_temp_role'}
```

### 7.6 生成的 Markdown 矩阵表（节选，完整见 `docs/role_matrix.md`）

```markdown
| 权限点 | 动作 | front_desk<br>前台接待 | ops_specialist<br>运营专员 | member_manager<br>会员经理 | opportunity_manager<br>商机经理 | bizdev_consultant<br>招商顾问 | ops_supervisor<br>运营主管 | knowledge_admin<br>知识管理员 | executive<br>管理层 | sys_admin<br>系统管理员 |
|---|---|---|---|---|---|---|---|---|---|---|
| `visitor.read` | read | site | site | — | — | — | — | — | org | — |
| `visitor.write` | write | site | site | — | — | — | — | — | — | — |
| `checkin.read` | read | site | site | — | — | — | — | — | org | — |
| `checkin.write` | write | site | site | — | — | — | — | — | — | — |
| `space.read` | read | site | site | — | — | — | site | — | org | — |
| `space.write` | write | — | site | — | — | — | site | — | — | — |
| `space.assign` | assign | — | site | — | — | — | site | — | — | — |
| `space.export` | export | — | — | — | — | — | site | — | — | — |
```

### 7.7 迁移可逆（downgrade → upgrade）

```console
$ python3 -m alembic downgrade base
INFO  [alembic.runtime.migration] Running downgrade 0002_role_permissions -> 0001_roles, 创建 role_permissions 表（S2-IAM-015 角色与权限矩阵）
INFO  [alembic.runtime.migration] Running downgrade 0001_roles -> , 创建 roles 表（S2-IAM-015 角色与权限矩阵）
剩余表: ['alembic_version']

$ python3 -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_roles, 创建 roles 表（S2-IAM-015 角色与权限矩阵）
INFO  [alembic.runtime.migration] Running upgrade 0001_roles -> 0002_role_permissions, 创建 role_permissions 表（S2-IAM-015 角色与权限矩阵）
```

---

<!-- 以下是上一单（#2968）的内容，不是本单；保留是因为本单的迁移基线建立在它之上 -->

# 订单 2968 ·【S2-IAM-011】会员空间平台 · 扫码登录适配器接口、state 校验与身份绑定流程

## 1. 交付物清单

| # | 文件 | 内容 |
|---|------|------|
| 1 | `app/iam/auth/qr/provider.py` | `QrLoginProvider` Protocol：`name` / `build_authorize_url(state, redirect_uri)` / `exchange_code(code)` / `health_check()`；另含 `QrProviderError` |
| 2 | `app/iam/auth/qr/external_identity.py` | `ExternalIdentity(provider, corp_id, external_user_id, display_name, mobile 可空)` |
| 3 | `app/iam/auth/qr/registry.py` | 适配器注册表（按 name 取实现，企业微信 / 飞书各注册一个即可） |
| 4 | `app/iam/auth/qr/state.py` | state 生成（32 字节随机）、Redis 存取、Cookie 绑定、一次性消费 |
| 5 | `app/iam/auth/qr/bind_ticket.py` | `bind_ticket` 签发与单次消费 |
| 6 | `app/iam/auth/qr/redirect.py` | `redirect_uri` 白名单校验（规范化后精确比较、fail-closed） |
| 7 | `app/api/iam/auth/qr.py` | `GET /api/iam/auth/qr/{provider}/start`、`GET /api/iam/auth/qr/{provider}/callback` |
| 8 | `app/api/iam/me/identities.py` | `POST /api/iam/me/identities/bind`、`DELETE /api/iam/me/identities/{provider}`、`GET /api/iam/me/identities` |
| 9 | `app/api/iam/auth/login.py` | 口令登录（绑定流程里员工用它换令牌；与扫码登录共用后续步骤） |
| 10 | `app/api/iam/auth/totp.py` | TOTP 挑战票据提交入口（**TOTP 校验器本身不在本单范围**，见 §6 对接点） |
| 11 | `app/iam/identities.py` | `user_identities` 的读写（按三元组查、绑定、解绑） |
| 12 | `app/iam/auth/service.py` | 登录后续步骤（是否 TOTP、签发令牌、`amr`） |
| 13 | `tests/fakes/fake_qr_provider.py` | `FakeProvider`：可控 code → 身份映射，可注入失败与超时 |
| 14 | `tests/iam/test_qr_login.py` | pytest 测试（覆盖四条验收标准） |
| 15 | `app/main.py` | 应用装配（`create_app()` 工厂，可注入引擎 / Redis / 适配器） |
| 16 | `scripts/show_qr_flow.py` | 取证脚本：打印扫码登录全流程每一步的响应体（README §9.3 的来源） |

## 2. 通用流程与时序图

```mermaid
sequenceDiagram
    autonumber
    participant B as 浏览器
    participant API as /api/iam/auth/qr
    participant R as Redis
    participant P as QrLoginProvider(企业微信/飞书)
    participant DB as user_identities

    B->>API: GET /api/iam/auth/qr/{provider}/start?redirect_uri=...
    API->>API: 校验 redirect_uri ∈ APP_QR_REDIRECT_ALLOWLIST（空 ⇒ fail-closed 400）
    API->>R: SET auth:qrstate:{state} = {provider, redirect_uri, browser_token} EX 300
    API->>R: SET auth:qrstate:issued:{state} EX 3600（用于区分过期/无效）
    API-->>B: 200 {authorize_url, state} + Set-Cookie: qr_state=<browser_token>; HttpOnly; SameSite=Lax
    B->>P: 打开 authorize_url 扫码授权
    P-->>B: 302 回跳 /api/iam/auth/qr/{provider}/callback?code=&state=
    B->>API: GET /api/iam/auth/qr/{provider}/callback?code=&state=（带 qr_state Cookie）
    API->>R: 校验 state：存在 / 未用过 / 与 Cookie 一致
    alt state 非法（篡改·过期·重复使用·Cookie 不匹配）
        API-->>B: 400 {code: state_invalid|state_expired|state_used}（流程终止，不消耗上游 code）
    else state 合法（一次性消费）
        API->>P: exchange_code(code)
        P-->>API: ExternalIdentity(provider, corp_id, external_user_id, display_name, mobile?)
        API->>DB: SELECT user_identities WHERE provider=? AND corp_id=? AND external_user_id=?
        alt 查不到（未绑定）
            API->>R: SET auth:qrbind:{bind_ticket} EX 300
            API-->>B: 200 {step: bind_required, bind_ticket}
            B->>API: POST /api/iam/auth/login（账号口令）→ access_token
            B->>API: POST /api/iam/me/identities/bind {bind_ticket} + Bearer
            API->>DB: 写入 user_identities + 审计日志
            API-->>B: 200 {status: bound}
        else 查到且员工 active
            API->>API: 与口令登录相同的后续步骤（TOTP 由 APP_QR_LOGIN_SKIP_TOTP 决定）
            API-->>B: 200 {step: login_complete, access_token, amr: qr}
        else 查到但员工 disabled / 跨组织
            API-->>B: 403 {code: employee_not_active}（不泄露身份是否存在）
        end
    end
    B->>API: DELETE /api/iam/me/identities/{provider} + Bearer（解绑）
    API->>DB: 软删除绑定关系 + 审计日志
    API-->>B: 200 {status: unbound}
```

## 3. 三处已定口径

1. **绑定 Cookie 名 `qr_state`**：属性 `HttpOnly` + `SameSite=Lax`，生产环境（`APP_ENV=prod`）加 `Secure`；路径 `/`。
   Cookie 里放的是 `browser_token`（与 state 一一对应的 32 字节随机串），Redis 里 `auth:qrstate:{state}` 也存一份，回调时两者必须一致 ⇒ state 不能被别的浏览器盗用。
2. **provider 名取小写**：路径里的 provider 一律 `strip().lower()`（`wecom` / `feishu`），并与 `user_identities.provider` 同值。
3. **bind_ticket 单次有效且有短 TTL**：存 `auth:qrbind:{ticket}`，默认 300 秒；取用即删；票据所属外部身份与当前登录人不一致时拒绝绑定
   （同一外部身份已绑定到**另一员工** ⇒ 409 `identity_already_bound`；已绑定到**本人** ⇒ 200 `already_bound` 幂等）。

## 4. state 校验规则

| 情形 | 判定依据 | HTTP | 错误码 |
|------|----------|------|--------|
| state 不存在 / 被篡改 / 与 Cookie 不一致 / 缺 Cookie | `auth:qrstate:{state}` 查不到或 `browser_token` 不匹配 | 400 | `state_invalid` |
| state 过期 | 主键已消失但 `auth:qrstate:issued:{state}` 还在 | 400 | `state_expired` |
| state 重复使用 | `auth:qrstate:used:{state}` 存在 | 400 | `state_used` |

* state 校验**先于** `exchange_code`：无效 state 不会消耗上游 code（测试断言 `FakeProvider.exchange_code` 未被调用）。
* 消费用 `WATCH/MULTI/EXEC` 原子完成：校验通过 ⇒ 删主键 + 打「已使用」标记，保证一次性。

## 5. 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_ENV` | `local` | `prod` 时 Cookie 加 `Secure` |
| `APP_DATABASE_URL` | `sqlite+pysqlite:///:memory:` | 生产用 PostgreSQL 16：`postgresql+psycopg://...` |
| `REDIS_URL` | `redis://localhost:6379/0` | state / bind_ticket / TOTP challenge 的存储 |
| `APP_TOKEN_SECRET` | `dev-only-change-me` | 令牌签名密钥（生产必配） |
| `APP_TOKEN_TTL_SECONDS` | `3600` | 访问令牌有效期 |
| `APP_QR_STATE_TTL_SECONDS` | `300` | state 有效期（5 分钟） |
| `APP_QR_BIND_TICKET_TTL_SECONDS` | `300` | bind_ticket 有效期 |
| `APP_QR_TOTP_CHALLENGE_TTL_SECONDS` | `300` | TOTP 挑战票据有效期 |
| `APP_QR_LOGIN_SKIP_TOTP` | `false` | `true` ⇒ 扫码登录跳过 TOTP 直接签发令牌 |
| `APP_QR_LOGIN_FORCE_TOTP` | `false` | `true` ⇒ 所有扫码登录强制走 TOTP |
| `APP_QR_REDIRECT_ALLOWLIST` | 空 | `redirect_uri` 白名单，逗号分隔；**为空时 fail-closed（400）** |

## 6. 对接点（与其它工单的衔接）

* **企业微信 / 飞书真实 Provider**：本单**不含**。实现 `QrLoginProvider` 协议后，
  在 `app/main.py` 的 `create_app(providers=[...])` 里注册即可，通用流程一行不用改。
* **TOTP 二次验证**：本单**不含**实现，只留协议与入口。部署方实现 `app/iam/auth/totp.py` 的
  `TotpVerifier`（`verify(secret, code) -> bool`）并注入 `app.state.totp_verifier`；
  未注入时 `/api/iam/auth/totp/verify` 返回 501 `totp_not_implemented`。
* **S2-INFRA（云环境 / CI/CD / 运维）**：本单只用到 Redis 与 PostgreSQL，连接串全部走环境变量；
  Redis 不可用时 start / callback 直接 500（不做降级放行）。
* **用户体系**：本单自带最小 `employees` 表（`status` 字段取值 `active` / `disabled`），
  若 S2-IAM 主线已合入同名表，把 `app/iam/models.py` 的字段对齐即可，接口层不用动。
* **数据库迁移**：本单用 SQLAlchemy 2.0 声明式模型（`app/iam/models.py`）+ `create_all` 便于本地与测试；
  Alembic 迁移脚本随 S2-IAM 基线一起出（`app/core/db.py::create_all` 是临时通道，上线前换成 `alembic upgrade head`）。

## 7. 怎么跑

```bash
pip install -r requirements.txt
pytest -v tests/iam/test_qr_login.py
```

本地起服务（需要 Redis 与 PostgreSQL）：

```bash
export APP_DATABASE_URL='postgresql+psycopg://user:pass@host:5432/db'
export REDIS_URL='redis://host:6379/0'
export APP_TOKEN_SECRET='<生产密钥>'
export APP_QR_REDIRECT_ALLOWLIST='https://portal.example.test/iam/qr/callback'
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

## 8. 验收标准逐条对应

| 验收标准 | 实现 | 测试 |
|----------|------|------|
| 1. state 被篡改/过期/重复使用 ⇒ callback 400 | `app/iam/auth/qr/state.py::QrStateStore.consume` | `test_callback_with_tampered_state_returns_400`、`test_callback_with_expired_state_returns_400`、`test_callback_with_reused_state_returns_400`、`test_callback_with_mismatched_cookie_returns_400`、`test_callback_with_missing_cookie_returns_400` |
| 2. 未绑定 ⇒ `bind_required`；绑定后再次扫码直接登录 | `app/api/iam/auth/qr.py`、`app/api/iam/me/identities.py` | `test_unbound_identity_returns_bind_required_then_bind_then_login`、`test_bind_ticket_is_single_use`、`test_unbind_then_scan_returns_bind_required_again` |
| 3. redirect_uri 不在白名单 ⇒ start 400 | `app/iam/auth/qr/redirect.py` | `test_start_with_redirect_uri_not_in_allowlist_returns_400`、`test_start_with_allowlist_empty_fails_closed`、`test_start_rejects_same_path_on_other_host`、`test_start_rejects_redirect_uri_with_extra_query` |
| 4. disabled 员工扫码 ⇒ 403 | `app/api/iam/auth/qr.py`（`employee_not_active`） | `test_disabled_employee_qr_login_returns_403`、`test_cross_org_identity_returns_403` |

## 9. pytest 原始输出

### 9.1 全量测试

```console
$ python3 -m pytest -v
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 27 items

tests/iam/test_qr_login.py::test_start_returns_authorize_url_and_sets_http_only_cookie PASSED [  3%]
tests/iam/test_qr_login.py::test_callback_with_tampered_state_returns_400 PASSED [  7%]
tests/iam/test_qr_login.py::test_callback_with_missing_cookie_returns_400 PASSED [ 11%]
tests/iam/test_qr_login.py::test_callback_with_mismatched_cookie_returns_400 PASSED [ 14%]
tests/iam/test_qr_login.py::test_callback_with_expired_state_returns_400 PASSED [ 18%]
tests/iam/test_qr_login.py::test_callback_with_really_expired_state_returns_400 PASSED [ 22%]
tests/iam/test_qr_login.py::test_callback_with_reused_state_returns_400 PASSED [ 25%]
tests/iam/test_qr_login.py::test_callback_with_unknown_provider_returns_404 PASSED [ 29%]
tests/iam/test_qr_login.py::test_unbound_identity_returns_bind_required_then_bind_then_login PASSED [ 33%]
tests/iam/test_qr_login.py::test_bind_ticket_is_single_use PASSED        [ 37%]
tests/iam/test_qr_login.py::test_bind_requires_authentication PASSED     [ 40%]
tests/iam/test_qr_login.py::test_unbind_then_scan_returns_bind_required_again PASSED [ 44%]
tests/iam/test_qr_login.py::test_start_with_redirect_uri_not_in_allowlist_returns_400 PASSED [ 48%]
tests/iam/test_qr_login.py::test_start_with_allowlist_empty_fails_closed PASSED [ 51%]
tests/iam/test_qr_login.py::test_start_rejects_redirect_uri_same_path_other_host PASSED [ 55%]
tests/iam/test_qr_login.py::test_start_rejects_redirect_uri_with_extra_query PASSED [ 59%]
tests/iam/test_qr_login.py::test_start_accepts_allowlist_entry_with_trailing_slash PASSED [ 62%]
tests/iam/test_qr_login.py::test_disabled_employee_qr_login_returns_403 PASSED [ 66%]
tests/iam/test_qr_login.py::test_cross_org_identity_returns_403 PASSED   [ 70%]
tests/iam/test_qr_login.py::test_qr_login_requires_totp_by_default PASSED [ 74%]
tests/iam/test_qr_login.py::test_qr_login_skips_totp_when_env_flag_true PASSED [ 77%]
tests/iam/test_qr_login.py::test_provider_exchange_failure_returns_502 PASSED [ 81%]
tests/iam/test_qr_login.py::test_state_consumed_even_when_identity_unbound PASSED [ 85%]
tests/iam/test_qr_login.py::test_callback_with_invalid_code_returns_502[unknown-code] PASSED [ 88%]
tests/iam/test_qr_login.py::test_fake_provider_satisfies_protocol PASSED [ 92%]
tests/iam/test_qr_login.py::test_provider_registry_is_case_insensitive PASSED [ 96%]
tests/iam/test_qr_login.py::test_state_store_uses_expected_keys PASSED   [100%]

=============================== warnings summary ===============================
../../../../../tmp/clawagent-home-127765740/.local/lib/python3.12/site-packages/fastapi/testclient.py:1
  /tmp/clawagent-home-127765740/.local/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 27 passed, 1 warning in 1.80s =========================
```

### 9.2 逐条验收的复跑命令（对应 §6 验证步骤）

```console
$ python3 -m pytest -v tests/iam/test_qr_login.py -k state
6 passed, 19 deselected          # 篡改 / 过期 / 重复使用 / Cookie 不匹配 ⇒ 400

$ python3 -m pytest -v -k bind_required
2 passed, 23 deselected          # 未绑定 ⇒ bind_required；绑定后可直接登录；解绑后再次 bind_required

$ python3 -m pytest -v -k redirect_uri
3 passed, 22 deselected          # 非白名单 redirect_uri ⇒ 400（且不写 Redis）

$ python3 -m pytest -v -k disabled
1 passed, 24 deselected          # disabled 员工 ⇒ 403
```

### 9.3 各步骤响应体原始输出（脚本见 §9.4）

```text
### ① start（成功）
HTTP 200
{
  "provider": "fake",
  "authorize_url": "https://qr.example.test/authorize?state=DButgqYiMZyNwSmVOYc5boSJAQQvBh3trFx5ygKcfA0&redirect_uri=https%3A%2F%2Fportal.example.test%2Fiam%2Fqr%2Fcallback&client=fake",
  "state": "DButgqYiMZyNwSmVOYc5boSJAQQvBh3trFx5ygKcfA0",
  "expires_in": 300
}
Set-Cookie: qr_state=axG9pF7Vhp_xXvb5OwStOgWcGARLzTOzsZR0Y4YWhp4; HttpOnly; Max-Age=300; Path=/; SameSite=lax

### ② callback（未绑定 ⇒ bind_required）
HTTP 200
{
  "step": "bind_required",
  "bind_ticket": "ajDBUlX_GbtPJzK5HF-1hlYmgeSfyjcB",
  "provider": "fake",
  "external_user_id": "ext-user-001",
  "display_name": "虚构员工",
  "expires_in": 300
}

### ③ 口令登录
HTTP 200
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDlkNDVmYS1hNmY2LTRkNTMtYTU0MC1iNmRmODQwYWZlYTEiLCJvcmdfaWQiOiJvcmctMDAxIiwiYW1yIjoicHdkIiwiaWF0IjoxNzk1NTcwMTA0LCJleHAiOjE3OTU1NzM3MDQsImp0aSI6IjUwOGY5OGYyLTRhNjUtNGMyMC05NWU1LWVhODMyZGJmZDU5ZCJ9.0WNpsH6QPo8AmvqgfsJKM6syM2Bq8HUixrnqBBJ7B4I",
  "token_type": "bearer",
  "expires_in": 3600,
  "amr": "pwd",
  "employee": {
    "id": "009d45fa-a6f6-4d53-a540-b6df840afea1",
    "org_id": "org-001",
    "username": "zhang.san",
    "display_name": "张三（虚构）"
  }
}

### ④ bind（绑定完成）
HTTP 200
{
  "status": "bound",
  "provider": "fake",
  "corp_id": "corp-fake-001",
  "external_user_id": "ext-user-001"
}

### ⑤ 再扫一次（已绑定 ⇒ 直接登录，amr=qr）
HTTP 200
{
  "step": "login_complete",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDlkNDVmYS1hNmY2LTRkNTMtYTU0MC1iNmRmODQwYWZlYTEiLCJvcmdfaWQiOiJvcmctMDAxIiwiYW1yIjoicXIiLCJpYXQiOjE3OTU1NzAxMDQsImV4cCI6MTc5NTU3MzcwNCwianRpIjoiMzhiYTk1MTQtZGNhYy00YTM2LWJlZTQtNjAwZmViMjAzM2U0In0.kKU4xDOK_ui7tj_kbf_8QZ81BRcJ4OyOXDVEIVV4LsI",
  "token_type": "bearer",
  "expires_in": 3600,
  "amr": "qr",
  "employee": {
    "id": "009d45fa-a6f6-4d53-a540-b6df840afea1",
    "org_id": "org-001",
    "username": "zhang.san",
    "display_name": "张三（虚构）"
  }
}

### ⑥ callback（state 被篡改 ⇒ 400）
HTTP 400
{
  "code": "state_invalid",
  "message": "state 无效"
}

### ⑦ callback（state 重复使用 ⇒ 400）
HTTP 400
{
  "code": "state_used",
  "message": "state 已被使用"
}

### ⑧ start（redirect_uri 不在白名单 ⇒ 400）
HTTP 400
{
  "code": "redirect_uri_not_allowed",
  "message": "redirect_uri 不在白名单内"
}
Redis 中的 state 键: ['auth:qrstate:issued:DButgqYiMZyNwSmVOYc5boSJAQQvBh3trFx5ygKcfA0', 'auth:qrstate:used:DButgqYiMZyNwSmVOYc5boSJAQQvBh3trFx5ygKcfA0', 'auth:qrstate:issued:GLkfPw8BN0FFqhuLu77UA4R6_DYDCKgycLNLXuZmW5M', 'auth:qrstate:used:GLkfPw8BN0FFqhuLu77UA4R6_DYDCKgycLNLXuZmW5M']

### ⑨ callback（员工 disabled ⇒ 403）
HTTP 403
{
  "code": "employee_not_active",
  "message": "员工账号不可用，无法登录"
}

### ⑩ unbind（解绑）
HTTP 200
{
  "status": "unbound",
  "provider": "fake",
  "count": 2
}
```

### 9.4 取证脚本

`scripts/show_qr_flow.py`：用 FakeProvider 跑一遍完整流程并打印每一步的 HTTP 状态码与响应体
（未绑定 → 绑定 → 再登录 → 篡改 state → 重复使用 state → 非白名单 redirect_uri → disabled 员工 → 解绑）。
复跑方式：

```bash
python3 scripts/show_qr_flow.py
```

---
