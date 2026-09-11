# 生产运行镜像：多阶段构建 — 前端编译 + Python 运行时
# 构建上下文须为仓库根（而非 deploy/），因为需要访问 frontend/ 和 src/
# 使用国内镜像源（不需要可替换为官方）
#   备选: docker.1ms.run / dockerpull.com / docker.xuanyuan.me

# ═══════════════════════════════════════════════════════════════════
# 阶段 1：前端构建
# ═══════════════════════════════════════════════════════════════════
FROM docker.m.daocloud.io/node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


# ═══════════════════════════════════════════════════════════════════
# 阶段 2：Python 运行时
# ═══════════════════════════════════════════════════════════════════
FROM docker.m.daocloud.io/python:3.14-slim

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# 安装 uv（国内镜像）
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# 先复制依赖描述文件利用层缓存
COPY pyproject.toml uv.lock README.md ./

# 仅同步运行依赖（--no-dev）
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# 复制后端源码
COPY src/ ./src/

# 复制前端构建产物到后端静态目录
COPY --from=frontend-builder /app/frontend/dist/ ./src/cndb/static/

# 非 root 用户运行
RUN useradd --create-home --shell /bin/false cndb \
    && chown -R cndb:cndb /app

USER cndb

EXPOSE 8000

# uvicorn 启动，--workers 多进程
CMD ["uvicorn", "cndb.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
