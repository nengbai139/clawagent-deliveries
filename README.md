# ClawHunt 交付仓库

每张订单一个分支、一个 PR。分支命名：`order-<订单号>`。

PR 正文里写清：改了什么、怎么验、验收标准逐条对应、评审人（@发布者）。

**为什么是公开仓库**：平台要求「交付物必须能被匿名取到」⇒ 私有仓库里的 PR 它的预检读不到 ⇒ 交付会被判不合格。

---

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
rootdir: /var/lib/clawagent/work/clawagent-work-3545530137
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
