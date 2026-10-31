"""检查动作包门面：只做导入导出（内置动作的注册由 ``registry.load_builtins`` 触发）."""

from __future__ import annotations

from cndb.plugins.pipeline.services.checks.base import (
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
    resolve_fields,
)
from cndb.plugins.pipeline.services.checks.registry import (
    coerce_params,
    get_check,
    iter_check_names,
    iter_check_specs,
    load_builtins,
    register_check,
    require_check,
    validate_static_params,
)

__all__ = [
    "CheckContext",
    "CheckInput",
    "CheckSpec",
    "FindingDraft",
    "coerce_params",
    "get_check",
    "iter_check_names",
    "iter_check_specs",
    "load_builtins",
    "register_check",
    "require_check",
    "resolve_fields",
    "validate_static_params",
]
