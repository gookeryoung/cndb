# CI/容器化用 Dockerfile
# 使用国内镜像源拉取基础镜像（如不需要可替换为官方镜像）
# 备选镜像源前缀：docker.1ms.run / dockerpull.com / docker.xuanyuan.me
#
# 多阶段构建：
#   builder 阶段装编译工具链（build-essential/git）并执行 uv sync；
#   runtime 阶段只装运行必需的系统包，再从 builder 复制 /opt/venv。
#   编译工具、git、uv 缓存、uv 托管 Python 都不会进入最终镜像，
#   镜像体积与「exporting to image」阶段的导出耗时同步下降。

# ── builder 阶段：编译工具链 + 依赖安装 ──
FROM docker.m.daocloud.io/python:3.12-slim AS builder

# ---- 国内镜像源 ----
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# 环境变量：非交互 + 路径配置
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/uv-cache \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    # 固定用基础镜像自带的系统 Python，保证 venv 符号链接指向
    # /usr/local/bin/python3.12（runtime 阶段同样存在，跨阶段复制 venv 可用）。
    # 不能让 uv 默认选托管 Python——它装在 builder 的 /root 下，复制不过去
    UV_PYTHON=/usr/local/bin/python3.12

# 配置 apt 国内镜像（阿里云）并安装编译期系统依赖
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（国内镜像）
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/

WORKDIR /workspace
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# 同步依赖到 /opt/venv（CI 时直接复用）
RUN uv sync --frozen --no-install-project 2>/dev/null || uv sync --no-install-project

# ── runtime 阶段：只保留运行必需内容 ──
FROM docker.m.daocloud.io/python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/opt/venv/bin:${PATH}"

# 字体供 reportlab 生成 PDF / 报告模板渲染中文；curl 供健康检查与调试
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fontconfig \
        fonts-wqy-microhei \
        fonts-wqy-zenhei \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# uv 仍保留在镜像内，CI 任务可在容器内继续用 uv run / uv sync
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/

# venv 由 builder 以 UV_LINK_MODE=copy 生成（文件为实体拷贝，非缓存硬链接），
# 跨阶段复制后开箱可用
COPY --from=builder /opt/venv /opt/venv

# 持久化 uv 缓存目录（CI 可挂载到宿主机加速）
VOLUME ["/uv-cache"]

WORKDIR /workspace

# 默认入口
CMD ["/bin/bash"]
