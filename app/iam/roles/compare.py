"""一致性比对：role_matrix.yml 渲染出的矩阵 vs 数据库里的角色-权限关系。

比对按 (role_code, permission_code, data_scope) 三元组集合比较，不依赖行序 / 列序。
差异不为 0 时以非 0 退出码失败，并逐条打印差异（不只报「大致一致」）。

用法：
    python -m app.iam.roles.compare
    python -m app.iam.roles.compare --database-url ...
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.iam.roles.cli import (
    build_cli_engine,
    ensure_tables_exist,
    resolve_database_url,
    session_scope,
)
from app.iam.roles.matrix import Matrix, MatrixError, load_matrix
from app.iam.roles.models import Role, RolePermission


@dataclass
class CompareResult:
    """比对结果。"""

    missing: list[tuple[str, str, str]] = field(default_factory=list)
    extra: list[tuple[str, str, str]] = field(default_factory=list)
    scope_mismatch: list[tuple[str, str, str, str]] = field(default_factory=list)

    @property
    def diff_count(self) -> int:
        return len(self.missing) + len(self.extra) + len(self.scope_mismatch)

    @property
    def consistent(self) -> bool:
        return self.diff_count == 0

    def describe(self) -> list[str]:
        lines: list[str] = []
        for role_code, permission_code, scope in self.missing:
            lines.append(
                f"[缺失] 矩阵里有、库里没有：role={role_code} permission={permission_code} "
                f"data_scope={scope}"
            )
        for role_code, permission_code, scope in self.extra:
            lines.append(
                f"[多余] 库里有、矩阵里没有：role={role_code} permission={permission_code} "
                f"data_scope={scope}"
            )
        for role_code, permission_code, yml_scope, db_scope in self.scope_mismatch:
            lines.append(
                f"[范围不一致] role={role_code} permission={permission_code} "
                f"yml={yml_scope} db={db_scope}"
            )
        return lines


def db_triples(session: Session) -> dict[tuple[str, str], str]:
    """从库里读出 (role_code, permission_code) → data_scope。"""
    roles = {
        role.id: role
        for role in session.execute(
            select(Role).where(Role.deleted_at.is_(None))
        ).scalars()
    }
    result: dict[tuple[str, str], str] = {}
    for row in session.execute(
        select(RolePermission).where(RolePermission.deleted_at.is_(None))
    ).scalars():
        role = roles.get(row.role_id)
        if role is None:
            continue
        result[(role.code, row.permission_code)] = row.data_scope
    return result


def compare(session: Session, *, matrix: Matrix | None = None) -> CompareResult:
    """比对矩阵与数据库。"""
    matrix = matrix or load_matrix()
    result = CompareResult()

    db_map = db_triples(session)
    yml_map: dict[tuple[str, str], str] = {}
    for role in matrix.roles:
        for perm in role.permissions:
            yml_map[(role.code, perm.code)] = perm.data_scope

    for key, scope in sorted(yml_map.items()):
        if key not in db_map:
            result.missing.append((key[0], key[1], scope))
        elif db_map[key] != scope:
            result.scope_mismatch.append((key[0], key[1], scope, db_map[key]))

    for key, scope in sorted(db_map.items()):
        if key not in yml_map:
            result.extra.append((key[0], key[1], scope))

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.iam.roles.compare",
        description="比对 role_matrix.yml 与数据库里的角色-权限矩阵",
    )
    parser.add_argument("--database-url", default=None, help="覆盖 APP_DATABASE_URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        matrix = load_matrix()
    except MatrixError as exc:
        print(f"矩阵文件不合法：{exc}", file=sys.stderr)
        return 2

    url = resolve_database_url(args.database_url)
    engine = build_cli_engine(url)
    try:
        ensure_tables_exist(engine)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    with session_scope(engine) as session:
        result = compare(session, matrix=matrix)

    print(f"数据库：{url}")
    print(f"矩阵：{len(matrix.roles)} 个角色 × {len(matrix.permission_codes)} 条权限点")
    if result.consistent:
        print("比对结果：一致，差异 0 条")
        return 0

    print(f"比对结果：不一致，差异 {result.diff_count} 条")
    for line in result.describe():
        print(line)
    return 1


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
