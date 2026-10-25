"""help 插件响应模型（ADR 0029 §3）."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HelpExampleTableResponse(BaseModel):
    """示例中的一张 CSV 表."""

    file: str = Field(description="CSV 文件名（下载白名单）")
    title: str = Field(description="表标题")
    description: str = Field(description="字段与用途说明")
    rows: int = Field(description="示例说明用的近似行数")


class HelpExampleResponse(BaseModel):
    """一个示例场景."""

    key: str = Field(description="场景 key（下载路径参数）")
    name: str = Field(description="场景名称")
    summary: str = Field(description="场景说明")
    tables: list[HelpExampleTableResponse] = Field(description="可下载的 CSV 表")
    highlights: list[str] = Field(description="推荐视图 / 分析能力")
    steps: list[str] = Field(description="导入与练习步骤")


class HelpExampleListResponse(BaseModel):
    """示例清单响应."""

    items: list[HelpExampleResponse] = Field(description="全部示例场景")


__all__ = ["HelpExampleListResponse", "HelpExampleResponse", "HelpExampleTableResponse"]
