# 角色-权限矩阵

> 本表由 `app/iam/roles/role_matrix.yml` 生成（`python -m app.iam.roles.export`），**请勿手改**。
> 行 = 权限点，列 = 角色，单元格 = 数据范围：`self`（仅本人）/ `site`（本会所）/ `org`（全组织）；`—` 表示该角色没有这个权限点。
> 数据库由同一份 yml 播种（`python -m app.iam.roles.seed`），一致性由 `python -m app.iam.roles.compare` 保证。

> 矩阵版本：v1；组织：会员空间平台（虚构组织）（`org-0001`）；权限点白名单：36 条；角色：9 个。

> 真源文件：`app/iam/roles/role_matrix.yml`

## 1. 角色定义

| 角色 code | 名称 | 层级 | 内置 | 说明 |
|---|---|---|---|---|
| `front_desk` | 前台接待 | site | 是 | 前台接待：访客、签到、场地预约、活动查看、会员基本信息、知识阅读与 AI 助手 |
| `ops_specialist` | 运营专员 | site | 是 | 运营专员：访客、签到、场地与活动日常运营，会员基本信息只读 |
| `member_manager` | 会员经理 | site | 是 | 会员经理：会员资料读取到本会所，写入 / 跟进 / 敏感字段读取仅限本人负责的会员 |
| `opportunity_manager` | 商机经理 | site | 是 | 商机经理：需求读取到全组织，撮合结果写入仅限本人 |
| `bizdev_consultant` | 招商顾问 | site | 是 | 招商顾问：意向客户的读取与写入均仅限本人负责的客户 |
| `ops_supervisor` | 运营主管 | site | 是 | 运营主管：本会所的运营、商机、招商读写 / 分配 / 导出；不含任何 iam / sys 权限 |
| `knowledge_admin` | 知识管理员 | org | 是 | 知识管理员：kb 全部权限（org）+ AI 产出审批与 AI 助手使用 |
| `executive` | 管理层 | org | 是 | 管理层：只读与使用类权限（org），不含 write / manage / assign / export |
| `sys_admin` | 系统管理员 | org | 是 | 系统管理员：只持 iam / sys / audit 权限，不含任何 crm / opp / lead 业务数据权限（职责分离） |

## 2. 权限矩阵

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
| `event.read` | read | site | site | — | — | — | — | — | org | — |
| `event.write` | write | — | site | — | — | — | — | — | — | — |
| `crm.read` | read | — | — | site | — | — | — | — | org | — |
| `crm.read_basic` | read_basic | site | site | site | — | — | — | — | org | — |
| `crm.read_sensitive` | read_sensitive | — | — | self | — | — | — | — | — | — |
| `crm.write` | write | — | — | self | — | — | — | — | — | — |
| `crm.follow_up` | follow_up | — | — | self | — | — | — | — | — | — |
| `opp.read` | read | — | — | — | org | — | site | — | org | — |
| `opp.write` | write | — | — | — | self | — | site | — | — | — |
| `opp.match` | match | — | — | — | self | — | — | — | — | — |
| `opp.assign` | assign | — | — | — | — | — | site | — | — | — |
| `opp.export` | export | — | — | — | — | — | site | — | — | — |
| `lead.read` | read | — | — | — | — | self | site | — | org | — |
| `lead.write` | write | — | — | — | — | self | site | — | — | — |
| `lead.assign` | assign | — | — | — | — | — | site | — | — | — |
| `lead.export` | export | — | — | — | — | — | site | — | — | — |
| `kb.read` | read | org | org | org | org | org | — | org | org | — |
| `kb.write` | write | — | — | — | — | — | — | org | — | — |
| `kb.manage` | manage | — | — | — | — | — | — | org | — | — |
| `kb.publish` | publish | — | — | — | — | — | — | org | — | — |
| `ai.assistant.use` | use | org | org | org | org | org | — | org | org | — |
| `ai.review.approve` | approve | — | — | — | — | — | — | org | — | — |
| `iam.read` | read | — | — | — | — | — | — | — | — | org |
| `iam.write` | write | — | — | — | — | — | — | — | — | org |
| `iam.manage` | manage | — | — | — | — | — | — | — | — | org |
| `sys.read` | read | — | — | — | — | — | — | — | — | org |
| `sys.manage` | manage | — | — | — | — | — | — | — | — | org |
| `audit.read` | read | — | — | — | — | — | — | — | — | org |

## 3. 图例

- 数据范围：`self` 仅本人数据；`site` 本会所数据；`org` 全组织数据。
- 内置角色（`is_system=true`）不可删除，删除请求返回 409；权限点可由系统管理员调整（运行时鉴权接入见另一单）。
- 职责分离：系统管理员只持 `iam.` / `sys.` / `audit.` 权限，不含任何 `crm.` / `opp.` / `lead.` 业务数据权限。
- 管理层只持 `read` / `read_basic` / `use` 三种动作的权限点。
