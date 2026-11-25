"""扫码登录适配器协议。

企业微信、飞书两个实现各自实现本协议，通用流程（start / callback / bind / unbind）
只依赖协议，不认识具体厂商。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.iam.auth.qr.external_identity import ExternalIdentity


class QrProviderError(Exception):
    """适配器与上游厂商交互失败（网络、鉴权、code 无效等）。"""

    def __init__(self, message: str, *, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@runtime_checkable
class QrLoginProvider(Protocol):
    """扫码登录适配器。

    实现约定：
    - name：小写的厂商标识（如 wecom / feishu），用于路由与 user_identities.provider；
    - build_authorize_url：拼出用户去扫的授权地址，state 必须原样带上；
    - exchange_code：用回调里拿到的 code 换回外部身份；
    - health_check：健康检查，供运维探针调用。
    """

    @property
    def name(self) -> str:
        """厂商标识（小写）。"""
        ...

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        """构造授权地址。"""
        ...

    def exchange_code(self, code: str) -> ExternalIdentity:
        """用授权码换取外部身份。"""
        ...

    def health_check(self) -> bool:
        """健康检查。"""
        ...
