"""文档 AI 动作（ADR 0020 P1）.

领域侧只负责：提示词动作声明、输入构造与长度裁剪；模型调用 / 留痕 / 错误分类走平台
``cndb.plugins.llm.services.gateway``。本模块 import 时把动作注册到平台目录，
``GET /api/v1/llm/actions`` 因此能看到 ``document.*``。

写回口径：本模块**不写任何文档数据**。选区改写由前端写回编辑器内存态，摘要 / 标签建议
仅返回结果（P1 不自动改文档元数据）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from cndb.plugins.llm.services.actions import ActionSpec, register

# 单次改写允许的选区上限（字），与网关 max_input_chars 口径配合
MAX_SELECTION_CHARS = 4000
# 摘要 / 标签建议的正文上限：超出截断并在响应里回传 truncated=true
MAX_DOCUMENT_CHARS = 12000
MAX_TAGS = 5

# 改写指令白名单（前端按钮与后端校验同源）
POLISH_INSTRUCTIONS: dict[str, str] = {
    "polish": "润色以下中文片段，使表达更通顺自然，保持原意、术语与事实不变",
    "shorten": "精简以下中文片段，去除冗余表达，保留全部关键信息",
    "expand": "扩写以下中文片段，补充必要的细节与过渡，不虚构事实",
    "formal": "把以下中文片段改写为更正式的书面表达",
    "translate": "翻译以下片段，保持原有 Markdown 结构与术语一致",
}

POLISH_SYSTEM_PROMPT = (
    "你是中文文档编辑助手。只改写用户给出的片段，保持原意、术语与事实，"
    "不要添加原文没有的信息，不要输出解释、标题或 Markdown 代码围栏。"
    '输出 JSON：{"text": "改写后的片段"}。'
)

SUMMARIZE_SYSTEM_PROMPT = (
    "你是文档摘要助手。阅读用户给出的文档正文，输出 JSON："
    '{"summary": "不超过 120 字的中文摘要", '
    '"key_points": ["3-5 条要点"], "suggested_tags": ["3-5 个 2-6 字中文标签"]}。'
    "只依据正文内容，不要编造正文没有的事实；无法总结时 summary 用空串、其余为空数组。"
)

TAGS_SYSTEM_PROMPT = (
    "你是文档标签助手。阅读用户给出的文档正文，输出 JSON："
    '{"suggested_tags": ["3-5 个 2-6 字中文标签"]}。'
    "标签要能概括主题，不要重复、不要编造正文没有的信息。"
)


class PolishOutput(BaseModel):
    """选区改写结果."""

    text: str = Field(min_length=1, max_length=MAX_SELECTION_CHARS * 2)

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("改写结果为空")
        return stripped


def _clean_tags(values: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        tag = str(raw or "").strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:MAX_TAGS]


class SummarizeOutput(BaseModel):
    """文档摘要 + 要点 + 标签建议."""

    summary: str = Field(default="", max_length=200)
    key_points: list[str] = Field(default_factory=list, max_length=5)
    suggested_tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator("summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        return value.strip()

    @field_validator("key_points", "suggested_tags")
    @classmethod
    def _strip_items(cls, values: list[str]) -> list[str]:
        return [str(item).strip() for item in values if str(item).strip()]


class SuggestTagsOutput(BaseModel):
    """标签建议."""

    suggested_tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator("suggested_tags")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        return _clean_tags(values)


POLISH = register(
    ActionSpec(
        name="document.polish",
        label="AI 改写",
        scope="document",
        output_schema=PolishOutput,
        system_prompt=POLISH_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=1500,
        json_mode=True,
        max_input_chars=MAX_SELECTION_CHARS + 500,
    )
)

SUMMARIZE = register(
    ActionSpec(
        name="document.summarize",
        label="AI 摘要",
        scope="document",
        output_schema=SummarizeOutput,
        system_prompt=SUMMARIZE_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=1800,
        json_mode=True,
        max_input_chars=MAX_DOCUMENT_CHARS + 200,
    )
)

SUGGEST_TAGS = register(
    ActionSpec(
        name="document.suggest_tags",
        label="AI 标签建议",
        scope="document",
        output_schema=SuggestTagsOutput,
        system_prompt=TAGS_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=800,
        json_mode=True,
        max_input_chars=MAX_DOCUMENT_CHARS + 200,
    )
)

# 路由用：动作名 → 规格
DOCUMENT_ACTIONS: dict[str, ActionSpec] = {
    "polish": POLISH,
    "summarize": SUMMARIZE,
    "suggest_tags": SUGGEST_TAGS,
}


def build_polish_content(
    selection: str,
    instruction: str,
    *,
    language: str | None = None,
    context: str | None = None,
) -> str:
    """构造选区改写的用户消息（指令 + 可选上下文 + 片段）."""
    lines = [f"任务：{POLISH_INSTRUCTIONS[instruction]}"]
    if language:
        lines.append(f"目标语言：{language}")
    if context:
        lines.append(f"上下文：{context}")
    lines.append("片段：")
    lines.append(selection)
    return "\n".join(lines)


def prepare_document_content(content: str) -> tuple[str, bool]:
    """文档正文 → 模型输入：超长截断（返回 ``(content, truncated)``）."""
    text = content.strip()
    if len(text) <= MAX_DOCUMENT_CHARS:
        return text, False
    return text[:MAX_DOCUMENT_CHARS], True


__all__ = [
    "DOCUMENT_ACTIONS",
    "MAX_DOCUMENT_CHARS",
    "MAX_SELECTION_CHARS",
    "POLISH",
    "POLISH_INSTRUCTIONS",
    "SUGGEST_TAGS",
    "SUMMARIZE",
    "PolishOutput",
    "SuggestTagsOutput",
    "SummarizeOutput",
    "build_polish_content",
    "prepare_document_content",
]
