"""个人「大模型连接」读取与请求配置补全（ADR 0020 P0，自 datasource 迁入）.

设计目标：把「地址 / 模型 / API Key」从每个同步任务里抽出来，用户配置一次即可：

- :func:`load_connection` 按用户读出个人连接配置；未配置时返回内置默认值（不落库、不报错）；
- :func:`resolve_request_spec_defaults` 把默认地址 / 模型补进请求声明，
  让数据源任务配置可以只保留用户提示词。**API Key 永远不写进 request_spec**（它随备份导出，
  只能存在于加密的 ``llm_user_config`` / 凭证会话里）。
- :func:`load_llm_connection` 为 ADR 0019 旧名兼容别名。

Key 缺失的判定与提示文案统一放在 router 层，本模块只负责取值。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.crypto import decrypt_secret
from cndb.plugins.llm.models import LlmUserConfig

# 内置默认连接：DeepSeek 的 OpenAI 兼容端点。用户只配提示词即可直接跑通。
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True, slots=True)
class LlmConnection:
    """个人大模型连接（解密后的运行期视图）."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    system_prompt: str = ""
    has_api_key: bool = False


def find_user_config(db: Session, user_id: int) -> LlmUserConfig | None:
    """读取用户个人连接原始记录（无记录返回 ``None``）."""
    return db.execute(select(LlmUserConfig).where(LlmUserConfig.user_id == user_id)).scalar_one_or_none()


# ADR 0019 旧名兼容（datasource / 测试仍可能按此名引用）
find_user_llm_config = find_user_config


def load_connection(db: Session, user_id: int) -> LlmConnection:
    """读取个人连接；无记录时返回内置默认值（api_key 为空）.

    ``api_key`` 列存的是 Fernet 密文，这里解密成可直接用于 ``Authorization`` 的值；
    解密失败（换过密钥 / 密文损坏）按空 Key 处理，由调用方给出「请重新配置」的提示，
    避免把排查引向无关的网络错误。
    """
    row = find_user_config(db, user_id)
    if row is None:
        return LlmConnection()
    try:
        api_key = decrypt_secret(row.api_key or "").strip()
    except ValueError:
        api_key = ""
    return LlmConnection(
        base_url=(row.base_url or "").strip() or DEFAULT_BASE_URL,
        model=(row.model or "").strip() or DEFAULT_MODEL,
        api_key=api_key,
        system_prompt=(row.system_prompt or "").strip(),
        has_api_key=bool(api_key),
    )


# ADR 0019 旧名兼容
load_llm_connection = load_connection


def resolve_request_spec_defaults(spec: Mapping[str, Any], conn: LlmConnection) -> dict[str, Any]:
    """复制请求声明并补齐 ``url_template`` / ``llm.model``（不写 api_key / system）.

    只补缺省值，不覆盖用户显式配置：任务里仍可单独指定别的地址或模型（兼容 ADR 0014 的存量任务）。
    """
    filled = dict(spec or {})
    if not str(filled.get("url_template") or "").strip():
        filled["url_template"] = conn.base_url or DEFAULT_BASE_URL

    raw_llm = filled.get("llm")
    llm: dict[str, Any] = dict(raw_llm) if isinstance(raw_llm, Mapping) else {}
    if not str(llm.get("model") or "").strip():
        llm["model"] = conn.model or DEFAULT_MODEL
    filled["llm"] = llm
    return filled


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LlmConnection",
    "find_user_config",
    "find_user_llm_config",
    "load_connection",
    "load_llm_connection",
    "resolve_request_spec_defaults",
]
