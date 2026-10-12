"""issues 插件 Pydantic schemas：请求体模型."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IssueCreate(BaseModel):
    """创建问题请求体."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = "other"


class IssueCommentCreate(BaseModel):
    """问题评论请求体."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1)


__all__ = ["IssueCommentCreate", "IssueCreate"]
