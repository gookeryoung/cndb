"""forms 插件包."""

from __future__ import annotations

from cndb.plugins.forms.models import FormDefinition
from cndb.plugins.forms.plugin import FormsPlugin, plugin

__all__ = ["FormDefinition", "FormsPlugin", "plugin"]
