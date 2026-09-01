"""Django 基础配置：所有环境共享."""

from __future__ import annotations

import os
from pathlib import Path

# 项目根目录（src layout：settings/base.py 上溯 4 级到仓库根）
BASE_DIR = Path(__file__).resolve().parents[3]

# 安全密钥：生产环境必须通过环境变量注入，开发环境使用不安全默认值
SECRET_KEY = os.environ.get("CNDB_SECRET_KEY", "dev-insecure-secret-key")

DEBUG = False

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 三方
    "rest_framework",
    # 平台应用
    "cndb.accounts",
    "cndb.workspaces",
    "cndb.tables",
    "cndb.tokens",
    "cndb.webui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cndb.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "cndb.wsgi.application"
ASGI_APPLICATION = "cndb.asgi.application"

# 数据库：默认 SQLite（开发/测试），CNDB_DB=postgres 切换 PostgreSQL
if os.environ.get("CNDB_DB", "sqlite").lower() == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("CNDB_DB_NAME", "cndb"),
            "USER": os.environ.get("CNDB_DB_USER", "cndb"),
            "PASSWORD": os.environ.get("CNDB_DB_PASSWORD", ""),
            "HOST": os.environ.get("CNDB_DB_HOST", "localhost"),
            "PORT": os.environ.get("CNDB_DB_PORT", "5432"),
        },
    }
else:
    _SQLITE_PATH = BASE_DIR / "data" / "cndb.sqlite3"
    _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _SQLITE_PATH,
        },
    }

# 自定义用户模型
AUTH_USER_MODEL = "accounts.User"

# 登录页地址：未登录访问主应用时重定向到 webui 登录页
LOGIN_URL = "/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF 全局配置：会话 + Token 认证，默认需登录，分页每页 50 条
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "cndb.tokens.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
