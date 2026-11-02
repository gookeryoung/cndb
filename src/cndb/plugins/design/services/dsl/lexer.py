"""结构 DSL 词法（ADR 0079 D2 / ADR 0086 D2）：行 / 列跟踪 + 注释 + 数值 / 标识 / 字符串 / 标点."""

from __future__ import annotations

from dataclasses import dataclass


class DslSyntaxError(Exception):
    """语法错误（词法 / 语法），携带 1 基行 / 列."""

    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


@dataclass(frozen=True, slots=True)
class Token:
    """词法单元：kind + 原文 + 1 基行 / 列."""

    kind: str
    value: str
    line: int
    col: int


# token kind 常量（标点用自身字符，数值 / 标识 / 字符串 / EOF 用命名常量）
NUMBER = "NUMBER"
IDENT = "IDENT"
#: 字符串字面量（``use "file_key"`` 的文件 key；不转义、不支持跨行）
STRING = "STRING"
EOF = "EOF"

#: 单字符标点 → token kind
_PUNCT = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "{": "{",
    "}": "}",
    ",": ",",
    "=": "=",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "%": "%",
    ".": ".",
}

_DIGITS = "0123456789"
_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_CHARS = _IDENT_START | set(_DIGITS)


def _is_digit(ch: str) -> bool:
    return ch in _DIGITS


def tokenize(content: str) -> list[Token]:
    """把 DSL 原文切成 token 列表（EOF 结尾）.

    - 行内注释 ``//`` 与块注释 ``/* */``（未闭合报错）；
    - 数值：``12`` / ``3.14`` / ``.5``（不支持科学计数法）；
    - 字符串：``"wheel"``（成对双引号、不支持转义 / 跨行，ADR 0086 D2）；
    - 标识符：字母 / 下划线开头，可含数字。
    """
    tokens: list[Token] = []
    i, n = 0, len(content)
    line, col = 1, 1

    def advance(count: int = 1) -> None:
        """前进 count 个字符并维护行 / 列."""
        nonlocal i, line, col
        for _ in range(count):
            if i < n and content[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = content[i]
        # 空白
        if ch in " \t\r\n":
            advance()
            continue
        # 行内注释
        if ch == "/" and i + 1 < n and content[i + 1] == "/":
            while i < n and content[i] != "\n":
                advance()
            continue
        # 块注释
        if ch == "/" and i + 1 < n and content[i + 1] == "*":
            start_line, start_col = line, col
            advance(2)
            while i < n and not (content[i] == "*" and i + 1 < n and content[i + 1] == "/"):
                advance()
            if i >= n:
                raise DslSyntaxError("块注释未闭合（缺少 */）", start_line, start_col)
            advance(2)
            continue
        # 字符串字面量（文件 key）
        if ch == '"':
            start_line, start_col = line, col
            advance()
            start = i
            while i < n and content[i] != '"':
                if content[i] in "\r\n":
                    raise DslSyntaxError("字符串字面量未闭合（缺少双引号）", start_line, start_col)
                advance()
            if i >= n:
                raise DslSyntaxError("字符串字面量未闭合（缺少双引号）", start_line, start_col)
            tokens.append(Token(STRING, content[start:i], start_line, start_col))
            advance()  # 消费收尾双引号
            continue
        # 数值（先于标点：``.5`` 是数值，``w.origin`` 的 ``.`` 才是标点）
        if _is_digit(ch) or (ch == "." and i + 1 < n and _is_digit(content[i + 1])):
            start_line, start_col = line, col
            start = i
            while i < n and _is_digit(content[i]):
                advance()
            if i < n and content[i] == ".":
                advance()
                while i < n and _is_digit(content[i]):
                    advance()
            tokens.append(Token(NUMBER, content[start:i], start_line, start_col))
            continue
        # 标点
        if ch in _PUNCT:
            tokens.append(Token(_PUNCT[ch], ch, line, col))
            advance()
            continue
        # 标识符
        if ch in _IDENT_START:
            start_line, start_col = line, col
            start = i
            while i < n and content[i] in _IDENT_CHARS:
                advance()
            tokens.append(Token(IDENT, content[start:i], start_line, start_col))
            continue
        raise DslSyntaxError(f"无法识别的字符 {ch!r}", line, col)

    tokens.append(Token(EOF, "", line, col))
    return tokens


__all__ = [
    "EOF",
    "IDENT",
    "NUMBER",
    "STRING",
    "DslSyntaxError",
    "Token",
    "tokenize",
]
