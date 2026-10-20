"""通用文件导入的异常类型（供转换器与读取器共享，避免循环导入）."""

from __future__ import annotations


class UnsupportedImport(Exception):
    """单条文件无法导入：格式不支持 / 文件损坏 / 超出单文件限制.

    调用方（``reader.convert_batch``）捕获后只跳过该条，不中断整批（ADR 0010 I5）。
    """


__all__ = ["UnsupportedImport"]
