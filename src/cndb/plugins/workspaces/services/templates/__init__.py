"""工作区模板服务（需求 0094）：规格校验 / diff / 影响预览 / 实例化与流程门禁."""

from __future__ import annotations

from cndb.plugins.workspaces.services.templates.diff import diff_specs
from cndb.plugins.workspaces.services.templates.engine import (
    advance_stage,
    apply_spec_to_workspace,
    lifecycle_state,
    preview_impact,
)
from cndb.plugins.workspaces.services.templates.spec import (
    TemplateSpecError,
    normalize_spec,
    spec_counts,
)

__all__ = [
    "TemplateSpecError",
    "advance_stage",
    "apply_spec_to_workspace",
    "diff_specs",
    "lifecycle_state",
    "normalize_spec",
    "preview_impact",
    "spec_counts",
]
