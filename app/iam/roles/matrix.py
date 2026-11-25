"""读取 role_matrix.yml 并做校验。

yml 是矩阵的唯一真源：
    * 种子脚本读它写库；
    * Markdown 矩阵表由它渲染；
    * 一致性比对脚本拿它跟数据库逐格比对。

校验规则（不通过直接抛 MatrixError，调用方负责退出码）：
    * 权限点 code 必须在本单内置的 36 条白名单里（未知 code ⇒ 报错，不静默跳过）；
    * data_scope 必须是 self / site / org；level 必须是 site / org；
    * 同一角色内不得重复出现同一权限点；角色 code 不得重复。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.iam.roles.constants import DATA_SCOPES, ROLE_LEVELS

# role_matrix.yml 的默认位置（与本模块同目录）
MATRIX_PATH = Path(__file__).resolve().parent / "role_matrix.yml"

# ---------------------------------------------------------------------------
# 权限点白名单（36 条）
#
# 正式的权限点注册表由「S2-IAM 权限点注册表」工单发布；未合入时本单内置一份
# 占位白名单，接入点见 README「对接点」一节。本白名单只做「yml 不得出现
# 未知 code」的校验，不承担运行时鉴权职责。
# ---------------------------------------------------------------------------
PERMISSION_CODES: tuple[str, ...] = (
    "visitor.read",
    "visitor.write",
    "checkin.read",
    "checkin.write",
    "space.read",
    "space.write",
    "space.assign",
    "space.export",
    "event.read",
    "event.write",
    "crm.read",
    "crm.read_basic",
    "crm.read_sensitive",
    "crm.write",
    "crm.follow_up",
    "opp.read",
    "opp.write",
    "opp.match",
    "opp.assign",
    "opp.export",
    "lead.read",
    "lead.write",
    "lead.assign",
    "lead.export",
    "kb.read",
    "kb.write",
    "kb.manage",
    "kb.publish",
    "ai.assistant.use",
    "ai.review.approve",
    "iam.read",
    "iam.write",
    "iam.manage",
    "sys.read",
    "sys.manage",
    "audit.read",
)

# 业务数据域前缀：系统管理员不得持有（职责分离）
BUSINESS_DOMAIN_PREFIXES = ("crm.", "opp.", "lead.")


class MatrixError(ValueError):
    """role_matrix.yml 内容不合法。"""


def matrix_path() -> Path:
    """默认矩阵文件路径。"""
    return MATRIX_PATH


def action_of(permission_code: str) -> str:
    """取权限点代码的最后一段作为动作。

    crm.read_basic → read_basic；ai.assistant.use → use。
    域段或对象名里出现 read / write 字样不影响判定（只看最后一段）。
    """
    return permission_code.rsplit(".", 1)[-1]


def domain_of(permission_code: str) -> str:
    """取权限点代码的第一段作为域（ai.assistant.use → ai）。"""
    return permission_code.split(".", 1)[0]


@dataclass(frozen=True)
class PermissionSpec:
    """角色持有的一个权限点。"""

    code: str
    data_scope: str


@dataclass(frozen=True)
class RoleSpec:
    """一个角色的定义。"""

    code: str
    name: str
    level: str
    is_system: bool
    description: str
    permissions: tuple[PermissionSpec, ...]

    @property
    def permission_codes(self) -> tuple[str, ...]:
        return tuple(p.code for p in self.permissions)

    def scope_of(self, permission_code: str) -> str | None:
        for item in self.permissions:
            if item.code == permission_code:
                return item.data_scope
        return None


@dataclass(frozen=True)
class Matrix:
    """整张矩阵。"""

    version: int
    org_id: str
    org_name: str
    permission_codes: tuple[str, ...]
    roles: tuple[RoleSpec, ...]

    def role(self, code: str) -> RoleSpec | None:
        for item in self.roles:
            if item.code == code:
                return item
        return None

    @property
    def role_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.roles)

    def triples(self) -> set[tuple[str, str, str]]:
        """(role_code, permission_code, data_scope) 三元组集合。"""
        return {
            (role.code, perm.code, perm.data_scope)
            for role in self.roles
            for perm in role.permissions
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MatrixError(message)


def load_matrix(path: Path | str = MATRIX_PATH) -> Matrix:
    """读取并校验 role_matrix.yml。"""
    path = Path(path)
    _require(path.is_file(), f"矩阵文件不存在：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), "矩阵文件顶层必须是映射")

    version = int(raw.get("version", 1))
    org_id = str(raw.get("org_id") or "").strip()
    org_name = str(raw.get("org_name") or "").strip()
    _require(bool(org_id), "矩阵文件缺少 org_id")

    # 权限点白名单：yml 里声明的清单若存在，必须与内置白名单一致
    declared = [str(item.get("code")) for item in raw.get("permissions") or []]
    permission_codes = tuple(declared) if declared else PERMISSION_CODES

    roles: list[RoleSpec] = []
    seen_codes: set[str] = set()
    for raw_role in raw.get("roles") or []:
        code = str(raw_role.get("code") or "").strip()
        _require(bool(code), "角色缺少 code")
        _require(code not in seen_codes, f"角色 code 重复：{code}")
        seen_codes.add(code)

        level = str(raw_role.get("level") or "").strip()
        _require(level in ROLE_LEVELS, f"角色 {code} 的 level 非法：{level}")

        name = str(raw_role.get("name") or "").strip()
        _require(bool(name), f"角色 {code} 缺少 name")

        perms: list[PermissionSpec] = []
        seen_perms: set[str] = set()
        for raw_perm in raw_role.get("permissions") or []:
            perm_code = str(raw_perm.get("code") or "").strip()
            scope = str(raw_perm.get("data_scope") or "").strip()
            _require(
                perm_code in PERMISSION_CODES,
                f"角色 {code} 引用了白名单外的权限点：{perm_code}",
            )
            _require(
                scope in DATA_SCOPES,
                f"角色 {code} 的 {perm_code} 的 data_scope 非法：{scope}",
            )
            _require(
                perm_code not in seen_perms,
                f"角色 {code} 重复配置权限点：{perm_code}",
            )
            seen_perms.add(perm_code)
            perms.append(PermissionSpec(code=perm_code, data_scope=scope))

        roles.append(
            RoleSpec(
                code=code,
                name=name,
                level=level,
                is_system=bool(raw_role.get("is_system", True)),
                description=str(raw_role.get("description") or "").strip(),
                permissions=tuple(perms),
            )
        )

    _require(bool(roles), "矩阵文件里没有任何角色")

    # 角色引用全部校验通过后，再校验 yml 自己声明的权限点白名单
    if declared:
        unknown = [c for c in declared if c not in PERMISSION_CODES]
        _require(not unknown, f"权限点白名单含未知 code：{unknown}")
        missing = [c for c in PERMISSION_CODES if c not in declared]
        _require(not missing, f"权限点白名单缺少 code：{missing}")

    return Matrix(
        version=version,
        org_id=org_id,
        org_name=org_name,
        permission_codes=permission_codes,
        roles=tuple(roles),
    )
