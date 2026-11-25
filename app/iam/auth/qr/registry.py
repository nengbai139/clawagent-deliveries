"""适配器注册表：按 name 取协议实现。"""

from __future__ import annotations

from app.iam.auth.qr.provider import QrLoginProvider


class ProviderRegistry:
    """存放各厂商的 QrLoginProvider 实现。"""

    def __init__(self, providers: list[QrLoginProvider] | None = None) -> None:
        self._providers: dict[str, QrLoginProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: QrLoginProvider) -> None:
        name = (provider.name or "").strip().lower()
        if not name:
            raise ValueError("适配器必须有 name")
        self._providers[name] = provider

    def get(self, name: str) -> QrLoginProvider | None:
        return self._providers.get((name or "").strip().lower())

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def names(self) -> list[str]:
        return sorted(self._providers)
