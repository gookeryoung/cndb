"""纯文本源转换（需求 0135 / 需求 0010 C9）：按原文读入为 Markdown 正文.

与其他转换器的区别：
- **不解析 front-matter**：``.yaml`` / ``.txt`` 开头的 ``---`` 是内容本身，不是元数据；
- **不剥离一级标题**：``#`` 在日志 / 配置里常是注释，不是标题；
- **不做空白重排 / 转义**：只统一换行并去掉首尾空行，保留缩进、对齐与连续空行
  （日志、CSV、配置的结构信息全在空白里）。

标题统一取文件名（去扩展名），由调用方 ``clean_title`` 清洗。
"""

from __future__ import annotations

from pathlib import Path

from .normalize import decode_text


def convert_text(data: bytes, path: str) -> tuple[str, str, list[str]]:
    """把纯文本字节流读为 ``(标题, 正文, 告警)``；标题取文件名."""
    text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    return Path(path).stem, text.strip("\n"), []


__all__ = ["convert_text"]
