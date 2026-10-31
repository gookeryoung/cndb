"""pipeline 插件业务异常（统一映射为 HTTP 状态码）."""

from __future__ import annotations

from cndb.core.errors import CndbError


class PipelineError(CndbError):
    """流水线业务异常基类."""

    status_code = 400
    code = "pipeline_error"


class DslError(PipelineError):
    """DSL 编译 / 校验失败（保存期或纯校验端点返回 400）."""

    status_code = 400
    code = "pipeline_dsl_invalid"


class PipelineConflictError(PipelineError):
    """同一流水线已有活跃运行（单飞冲突，409）."""

    status_code = 409
    code = "pipeline_conflict"


class CheckError(PipelineError):
    """检查动作入参 / 目标解析失败（使该 step 失败，不牵连其他 step）."""

    status_code = 400
    code = "pipeline_check_error"


__all__ = ["CheckError", "DslError", "PipelineConflictError", "PipelineError"]
