"""Pydantic Schema 包.

API 请求/响应体的 Pydantic 模型应放在各自的 schema 文件中
（如 schemas/user.py、schemas/task.py），再经由本 __init__.py re-export。
"""

from __future__ import annotations
