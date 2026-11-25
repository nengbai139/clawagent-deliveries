"""外部身份与员工的绑定关系读写。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.iam.auth.qr.external_identity import ExternalIdentity
from app.iam.models import Employee, UserIdentity, utcnow


def find_employee_by_identity(
    session: Session, identity: ExternalIdentity
) -> Employee | None:
    """按 (provider, corp_id, external_user_id) 查已绑定的员工。"""
    stmt = (
        select(UserIdentity)
        .where(
            UserIdentity.provider == identity.provider,
            UserIdentity.corp_id == identity.corp_id,
            UserIdentity.external_user_id == identity.external_user_id,
            UserIdentity.deleted_at.is_(None),
        )
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return session.get(Employee, row.employee_id)


def find_identity_by_triple(
    session: Session, identity: ExternalIdentity
) -> UserIdentity | None:
    stmt = select(UserIdentity).where(
        UserIdentity.provider == identity.provider,
        UserIdentity.corp_id == identity.corp_id,
        UserIdentity.external_user_id == identity.external_user_id,
        UserIdentity.deleted_at.is_(None),
    )
    return session.execute(stmt).scalar_one_or_none()


def list_identities(session: Session, employee_id: str) -> list[UserIdentity]:
    stmt = select(UserIdentity).where(
        UserIdentity.employee_id == employee_id,
        UserIdentity.deleted_at.is_(None),
    )
    return list(session.execute(stmt).scalars())


def find_identity_by_triple_including_deleted(
    session: Session, identity: ExternalIdentity
) -> UserIdentity | None:
    """含软删除记录地查三元组。

    user_identities 上有 (provider, corp_id, external_user_id) 唯一约束，
    软删除的行依然占着这个键，所以重新绑定时要复用旧行而不是插新行。
    """
    stmt = select(UserIdentity).where(
        UserIdentity.provider == identity.provider,
        UserIdentity.corp_id == identity.corp_id,
        UserIdentity.external_user_id == identity.external_user_id,
    )
    return session.execute(stmt).scalar_one_or_none()


def bind_identity(
    session: Session,
    *,
    employee: Employee,
    identity: ExternalIdentity,
    created_by: str,
) -> UserIdentity:
    """建立绑定关系；已有软删除记录时复活该行（保持唯一约束成立）。"""
    row = find_identity_by_triple_including_deleted(session, identity)
    if row is None:
        row = UserIdentity(
            org_id=employee.org_id,
            site_id=employee.site_id,
            employee_id=employee.id,
            provider=identity.provider,
            corp_id=identity.corp_id,
            external_user_id=identity.external_user_id,
            display_name=identity.display_name,
            mobile=identity.mobile,
            created_by=created_by,
        )
        session.add(row)
    else:
        row.org_id = employee.org_id
        row.site_id = employee.site_id
        row.employee_id = employee.id
        row.display_name = identity.display_name
        row.mobile = identity.mobile
        row.deleted_at = None
        row.updated_at = utcnow()
        row.created_by = created_by
    session.commit()
    return row


def unbind_identities(
    session: Session, *, employee_id: str, provider: str
) -> list[UserIdentity]:
    """解绑：软删除该员工在该 provider 下的全部绑定关系。"""
    rows = list_identities(session, employee_id)
    target = [row for row in rows if row.provider == provider]
    now = utcnow()
    for row in target:
        row.deleted_at = now
        row.updated_at = now
    if target:
        session.commit()
    return target
