"""forms 插件服务层（facade —— 只做导入导出）."""

from __future__ import annotations

from cndb.plugins.forms.services.field_config import (
    resolve_form_fields,
    validate_field_config,
)
from cndb.plugins.forms.services.permissions import (
    FormAction,
    check_form_access,
    ensure_form_access,
    get_form_or_404,
)

__all__ = [
    "FormAction",
    "check_form_access",
    "ensure_form_access",
    "get_form_or_404",
    "resolve_form_fields",
    "validate_field_config",
]
