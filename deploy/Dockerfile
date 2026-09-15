# cndb2 生产部署镜像
# 构建上下文须为仓库根：
#   docker build -f deploy/Dockerfile --target app -t cndb2:app .
#   docker build -f deploy/Dockerfile --target web  -t cndb2:web  .
# 或直接用 docker compose（见 docker-compose.yml，默认一次性构建两个 target）
#
# 使用国内镜像源（如不需要可替换为官方）：
#   docker.m.daocloud.io / docker.1ms.run / dockerpull.com / docker.xuanyuan.me

# ═══════════════════════════════════════════════════════════════════
# 阶段 1：前端构建（两个 runtime 共享同一份产物）
# ═══════════════════════════════════════════════════════════════════
FROM docker.m.daocloud.io/node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


# ═══════════════════════════════════════════════════════════════════
# 阶段 2：Python 运行时（--target app）
# 职责：FastAPI + SQLAlchemy + 插件；/api/* 动态接口
# 前端静态资源已由 nginx 容器直出，此容器仍保留 SPA fallback 作为安全网
# ═══════════════════════════════════════════════════════════════════
FROM docker.m.daocloud.io/python:3.12-slim AS app

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

# 安装 curl（healthcheck 用）和 uv
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ curl uv

WORKDIR /app

# 先复制依赖描述文件利用层缓存
COPY pyproject.toml uv.lock README.md ./

# 仅同步运行依赖
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# 复制后端源码
COPY src/ ./src/

# 保留前端构建产物：即使 nginx 容器不可用，此 fallback 也能独立跑 SPA
COPY --from=frontend-builder /app/frontend/dist/ ./src/cndb/static/

# 非 root 用户运行
RUN useradd --create-home --shell /bin/false cndb \
    && chown -R cndb:cndb /app

USER cndb

EXPOSE 8000

# uvicorn 启动，--workers 多进程，--proxy-headers 让反向代理正确识别客户端 IP
CMD ["uvicorn", "cndb.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]


# ═══════════════════════════════════════════════════════════════════
# 阶段 3：Nginx 运行时（--target web）
# 职责：直出前端静态（/assets 长缓存）+ SPA fallback + /api/* 反代到 app
# ═══════════════════════════════════════════════════════════════════
FROM docker.m.daocloud.io/library/nginx:1.27-alpine AS web

# 复制前端构建产物到 nginx 默认根目录
COPY --from=frontend-builder /app/frontend/dist/ /usr/share/nginx/html/

# 复制 nginx 生产配置
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口（容器内）
EXPOSE 80

# 用默认入口启动 nginx（前台模式由 Dockerfile 的 CMD 继承）
CMD ["nginx", "-g", "daemon off;"]