# 生产运行镜像：gunicorn 承载 Django 应用（构建上下文须为仓库根）
# 使用国内镜像源拉取基础镜像（如不需要可替换为官方镜像）
FROM docker.m.daocloud.io/python:3.12-slim

# ---- 国内镜像源 ----
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=cndb.settings.prod

# 安装 uv（仅运行依赖，无需构建工具链）
RUN pip install --no-cache-dir uv

WORKDIR /app

# 先复制依赖描述文件利用层缓存，再同步运行依赖（不含 dev 组）
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY manage.py ./
RUN uv sync --frozen --no-dev

# 收集静态文件并去除包管理器缓存
RUN python manage.py collectstatic --noinput \
    && rm -rf /root/.cache /uv-cache

# 非 root 运行
RUN useradd --create-home --shell /bin/false cndb && chown -R cndb:cndb /app
USER cndb

EXPOSE 8000

# gunicorn：4 worker、超时 60 秒、转发代理头
CMD ["gunicorn", "cndb.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "--forwarded-allow-ips", "*"]
