"""幂等种子脚本：把 role_matrix.yml 里的 9 个内置角色写进数据库。

用法：
    python -m app.iam.roles.seed                      # 用 APP_DATABASE_URL
    python -m app.iam.roles.seed --database-url ...  # 覆盖数据库
    python -m app.iam.roles.seed --no-prune           # 保留矩阵外的既有权限行

幂等性：
    * 角色按 (org_id, code) upsert，重复执行不产生重复行；
    * 权限行按 (role_id, permission_code) upsert；
    * 不删除任何自定义角色（非内置角色一律不碰）；
    * 默认会清掉内置角色上矩阵之外的权限行（yml 是唯一真源），
      传 --no-prune 可保留。
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
from app.iam.roles.matrix import Matrix, MatrixError, RoleSpec, load_matrix
from app.iam.roles.models import Role, RolePermission, utcnow


@dataclass
class SeedReport:
    """种子执行结果（用于测试断言幂等：第二次执行 created/updated 计数不增长）。"""

    roles_created: int = 0
    roles_updated: int = 0
    permissions_written: int = 0
    permissions_pruned: int = 0
    role_codes: list[str] = field(default_factory=list)
    # 库里当前有效的权限行总数（幂等性证据：重复执行后该数字不变）
    permissions_total: int = 0

    @property
    def total_roles(self) -> int:
        return self.roles_created + self.roles_updated

    def summary(self) -> str:
        return (
            f"角色：新建 {self.roles_created} 个，更新 {self.roles_updated} 个；"
            f"权限点：写入 {self.permissions_written} 条，清理矩阵外 {self.permissions_pruned} 条；"
            f"库内权限行总数：{self.permissions_total}"
        )


def _upsert_role(
    session: Session, spec: RoleSpec, *, org_id: str, created_by: str | None
) -> tuple[Role, bool]:
    stmt = select(Role).where(Role.org_id == org_id, Role.code == spec.code).limit(1)
    role = session.execute(stmt).scalar_one_or_none()
    if role is None:
        role = Role(
            org_id=org_id,
            code=spec.code,
            name=spec.name,
            level=spec.level,
            is_system=spec.is_system,
            description=spec.description,
            created_by=created_by,
        )
        session.add(role)
        session.flush()
        return role, True

    role.name = spec.name
    role.level = spec.level
    role.is_system = spec.is_system
    role.description = spec.description
    role.deleted_at = None
    role.updated_at = utcnow()
    return role, False


def _upsert_permission(
    session: Session,
    *,
    role: Role,
    permission_code: str,
    data_scope: str,
    created_by: str | None,
) -> bool:
    stmt = (
        select(RolePermission)
        .where(
            RolePermission.role_id == role.id,
            RolePermission.permission_code == permission_code,
        )
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        session.add(
            RolePermission(
                org_id=role.org_id,
                site_id=role.site_id,
                role_id=role.id,
                permission_code=permission_code,
                data_scope=data_scope,
                created_by=created_by,
            )
        )
        return True

    row.data_scope = data_scope
    row.deleted_at = None
    row.updated_at = utcnow()
    return False


def seed_roles(
    session: Session,
    *,
    matrix: Matrix | None = None,
    org_id: str | None = None,
    prune: bool = True,
    created_by: str | None = "seed",
) -> SeedReport:
    """把矩阵写进库。返回执行报告。"""
    matrix = matrix or load_matrix()
    target_org = org_id or matrix.org_id
    report = SeedReport()

    for spec in matrix.roles:
        role, created = _upsert_role(
            session, spec, org_id=target_org, created_by=created_by
        )
        if created:
            report.roles_created += 1
        else:
            report.roles_updated += 1
        report.role_codes.append(spec.code)

        wanted = {p.code: p.data_scope for p in spec.permissions}
        for permission_code, data_scope in wanted.items():
            created_row = _upsert_permission(
                session,
                role=role,
                permission_code=permission_code,
                data_scope=data_scope,
                created_by=created_by,
            )
            if created_row:
                report.permissions_written += 1

        if prune:
            existing = session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.deleted_at.is_(None),
                )
            ).scalars()
            for row in existing:
                if row.permission_code not in wanted:
                    row.deleted_at = utcnow()
                    row.updated_at = utcnow()
                    report.permissions_pruned += 1

    session.commit()
    report.permissions_total = len(
        session.execute(
            select(RolePermission).where(RolePermission.deleted_at.is_(None))
        ).scalars().all()
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.iam.roles.seed",
        description="按 role_matrix.yml 幂等写入 9 个内置角色与权限矩阵",
    )
    parser.add_argument("--database-url", default=None, help="覆盖 APP_DATABASE_URL")
    parser.add_argument("--org-id", default=None, help="覆盖矩阵里的 org_id")
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="保留内置角色上矩阵之外的既有权限行（默认会清理）",
    )
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
        report = seed_roles(
            session,
            matrix=matrix,
            org_id=args.org_id,
            prune=not args.no_prune,
        )

    print(f"数据库：{url}")
    print(f"角色（{report.total_roles} 个）：{', '.join(report.role_codes)}")
    print(report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
