"""外部身份结构：扫码登录换回来的「外部系统里的这个人」。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalIdentity:
    """外部身份。

    provider / corp_id / external_user_id 三元组是 user_identities 表的唯一键，
    平台用它把「企业微信里的某人」映射到「平台里的某个员工」。
    """

    provider: str
    corp_id: str
    external_user_id: str
    display_name: str | None = None
    mobile: str | None = None

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "corp_id": self.corp_id,
            "external_user_id": self.external_user_id,
            "display_name": self.display_name,
            "mobile": self.mobile,
        }
