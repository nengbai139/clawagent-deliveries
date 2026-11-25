"""FakeProvider：扫码登录适配器的测试替身。

能力：
- 可控的 code → 外部身份映射（register_code）；
- 可注入失败（fail_codes）与超时（timeout_codes）；
- 记录 build_authorize_url / exchange_code 的调用次数与入参，
  便于断言「无效 state 时不应调用 exchange_code」。
"""

from __future__ import annotations

from urllib.parse import urlencode

from app.iam.auth.qr.external_identity import ExternalIdentity
from app.iam.auth.qr.provider import QrProviderError


class FakeProvider:
    """实现 QrLoginProvider 协议的假适配器。"""

    def __init__(
        self,
        name: str = "fake",
        *,
        authorize_base: str = "https://qr.example.test/authorize",
        healthy: bool = True,
    ) -> None:
        self.name = name
        self.authorize_base = authorize_base
        self.healthy = healthy
        self._identities: dict[str, ExternalIdentity] = {}
        # 注入点：让指定 code 走失败 / 超时分支
        self.fail_codes: set[str] = set()
        self.timeout_codes: set[str] = set()
        # 调用记录
        self.build_calls: list[tuple[str, str]] = []
        self.exchange_calls: list[str] = []

    # ------------------------------------------------------------------ 配置
    def register_code(
        self,
        code: str,
        *,
        provider: str | None = None,
        corp_id: str = "corp-fake-001",
        external_user_id: str = "ext-user-001",
        display_name: str | None = "虚构员工",
        mobile: str | None = None,
    ) -> ExternalIdentity:
        identity = ExternalIdentity(
            provider=provider or self.name,
            corp_id=corp_id,
            external_user_id=external_user_id,
            display_name=display_name,
            mobile=mobile,
        )
        self._identities[code] = identity
        return identity

    def inject_failure(self, code: str) -> None:
        """该 code 兑换时抛 QrProviderError。"""
        self.fail_codes.add(code)

    def inject_timeout(self, code: str) -> None:
        """该 code 兑换时抛超时错误。"""
        self.timeout_codes.add(code)

    # ---------------------------------------------------------- QrLoginProvider
    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        self.build_calls.append((state, redirect_uri))
        query = urlencode(
            {
                "state": state,
                "redirect_uri": redirect_uri,
                "client": self.name,
            }
        )
        return f"{self.authorize_base}?{query}"

    def exchange_code(self, code: str) -> ExternalIdentity:
        self.exchange_calls.append(code)
        if code in self.timeout_codes:
            raise TimeoutError(f"fake provider 超时: {code}")
        if code in self.fail_codes:
            raise QrProviderError("fake provider 兑换失败", code="provider_error")
        identity = self._identities.get(code)
        if identity is None:
            raise QrProviderError("code 无效", code="invalid_code")
        return identity

    def health_check(self) -> bool:
        return self.healthy

    # ------------------------------------------------------------------ 断言辅助
    @property
    def exchange_call_count(self) -> int:
        return len(self.exchange_calls)
