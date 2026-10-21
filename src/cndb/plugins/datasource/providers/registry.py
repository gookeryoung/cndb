"""Provider 注册表 —— 内置适配器在此登记，UI 由 ``params_schema`` 自动发现.

内置六个：``http_json``（声明式通用）/
``tencent_kline``（A 股日线）/ ``sina_kline``（A 股日线，不复权）/
``eastmoney_kline``（多市场多周期复权 K 线）/ ``eastmoney_symbols``（全市场标的列表）/
``rss_atom``（订阅源）。
新增 provider 只需实现 ``SourceProvider`` 协议并在此 ``register_provider``。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cndb.plugins.datasource.providers.base import ProviderError, SourceProvider
from cndb.plugins.datasource.providers.eastmoney_kline import EastmoneyKlineProvider
from cndb.plugins.datasource.providers.eastmoney_symbols import EastmoneySymbolsProvider
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.providers.rss_atom import RssAtomProvider
from cndb.plugins.datasource.providers.sina_kline import SinaKlineProvider
from cndb.plugins.datasource.providers.tencent_kline import TencentKlineProvider

PROVIDERS: dict[str, SourceProvider] = {}

DEFAULT_PROVIDER = "http_json"


def register_provider(provider: SourceProvider, *, replace: bool = False) -> None:
    """登记 provider（重名默认报错，避免插件覆盖内置实现时静默生效）."""
    name = provider.name
    if not name:
        raise ProviderError("provider.name 不能为空")
    if name in PROVIDERS and not replace:
        raise ProviderError(f"provider 已注册: {name}")
    PROVIDERS[name] = provider


def get_provider(name: str | None = None) -> SourceProvider:
    """按名取 provider；未指定时返回默认 ``http_json``."""
    key = name or DEFAULT_PROVIDER
    provider = PROVIDERS.get(key)
    if provider is None:
        raise ProviderError(f"未知 provider: {key!r}，可选: {sorted(PROVIDERS)}")
    return provider


def list_providers() -> list[dict[str, Any]]:
    """供 ``GET /providers`` 返回的元信息列表（按名称排序，结果稳定）."""
    return [
        {
            "name": provider.name,
            "label": provider.label,
            "params_schema": dict(provider.params_schema),
            "default_cursor": provider.default_cursor,
            "supports_paging": provider.supports_paging,
        }
        for _, provider in sorted(PROVIDERS.items())
    ]


def register_builtins(providers: Iterable[SourceProvider] | None = None) -> None:
    """登记内置 provider（幂等，重复调用不报错）."""
    for provider in (
        providers
        if providers is not None
        else (
            HttpJsonProvider(),
            TencentKlineProvider(),
            SinaKlineProvider(),
            EastmoneyKlineProvider(),
            EastmoneySymbolsProvider(),
            RssAtomProvider(),
        )
    ):
        if provider.name in PROVIDERS:
            continue
        register_provider(provider)


register_builtins()

__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "get_provider",
    "list_providers",
    "register_builtins",
    "register_provider",
]
