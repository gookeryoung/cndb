"""微信官方 API 客户端 —— jscode2session 封装."""

from __future__ import annotations

import logging
from typing import Any

import requests

from cndb.core.config import settings

logger = logging.getLogger(__name__)

_JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


def code2session(code: str) -> dict[str, Any]:
    """用小程序 wx.login() 得到的 code 向微信服务器换 openid + session_key.

    Args:
        code: 小程序端 wx.login() 返回的临时登录凭证

    Returns:
        微信返回的 session dict，包含 openid / session_key / unionid

    Raises:
        RuntimeError: 网络错误或微信返回 errcode != 0
        ValueError: settings.WECHAT_AUTH_ENABLED 为 False 或未配置 AppID/Secret
    """
    if not settings.WECHAT_AUTH_ENABLED:
        raise ValueError("WECHAT_AUTH_ENABLED 未开启")
    if not settings.WECHAT_APPID or not settings.WECHAT_SECRET:
        raise ValueError("WECHAT_APPID / WECHAT_SECRET 未配置")

    resp = requests.get(
        _JSCODE2SESSION_URL,
        params={
            "appid": settings.WECHAT_APPID,
            "secret": settings.WECHAT_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        logger.warning("微信 jscode2session 失败: %s", data)
        raise RuntimeError(
            f"微信返回错误: errcode={data['errcode']}, errmsg={data.get('errmsg')}",
        )

    return data  # { openid, session_key, unionid? }


__all__ = ["code2session"]
