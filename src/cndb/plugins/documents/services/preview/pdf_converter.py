"""PPTX → PDF 转换客户端（ADR 0129 P0）：只调用独立 pdf-worker.

口径：

- **默认关闭**：``PPTX_PDF_CONVERTER_URL`` 为空时不发起任何请求；
- **只读输入**：请求体是原件字节，转换器不得回写原件；
- **失败分类**：超时 / 连接失败 / worker 5xx / 429 归为瞬时错误（可重试一次），
  其余 4xx、非 PDF 响应、响应超限归为永久错误（不重试）；
- **有界**：响应体积上限固定，避免异常 worker 把内存打满。

本模块不关心缓存与队列，只负责「一份 PPTX 字节 → 一份 PDF 字节」。
"""

from __future__ import annotations

import httpx2

from cndb.core.config import settings

#: 转换结果体积上限（防御异常 worker 返回超大响应）
MAX_PDF_BYTES = 512 * 1024 * 1024


class PdfConverterDisabledError(Exception):
    """未配置转换器地址（功能关闭）."""


class PdfConversionError(Exception):
    """转换失败（``retryable`` 表示瞬时错误，可自动重试一次）."""

    def __init__(self, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


def is_configured() -> bool:
    """转换器是否已配置（URL 非空即视为启用）."""
    return bool((settings.PPTX_PDF_CONVERTER_URL or "").strip())


def convert_pptx_to_pdf(data: bytes) -> bytes:
    """把 PPTX 字节发送给 pdf-worker，返回校验过的 PDF 字节.

    Raises:
        PdfConverterDisabledError: 未配置转换器地址。
        PdfConversionError: 网络失败 / worker 拒绝 / 非 PDF 响应 / 响应超限。
    """
    if not is_configured():
        raise PdfConverterDisabledError("未配置 PPTX PDF 转换器")

    url = f"{settings.PPTX_PDF_CONVERTER_URL.strip().rstrip('/')}/convert"
    headers = {
        "Content-Type": "application/octet-stream",
        "Accept": "application/pdf",
    }
    token = (settings.PPTX_PDF_CONVERTER_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx2.Client(timeout=settings.PPTX_PDF_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(url, content=data, headers=headers)
    except (httpx2.TimeoutException, httpx2.ConnectError) as exc:
        raise PdfConversionError("转换器响应超时或无法连接", retryable=True) from exc
    except httpx2.RequestError as exc:
        raise PdfConversionError(f"转换器请求失败：{exc}", retryable=True) from exc

    if response.status_code in (429,) or response.status_code >= 500:
        raise PdfConversionError(f"转换器暂时不可用（{response.status_code}）", retryable=True)
    if response.status_code >= 400:
        raise PdfConversionError(f"转换器拒绝转换（{response.status_code}）", retryable=False)

    body = response.content
    if len(body) > MAX_PDF_BYTES:
        raise PdfConversionError("转换结果超出体积上限", retryable=False)
    if not body.startswith(b"%PDF-"):
        raise PdfConversionError("转换器返回的不是 PDF", retryable=False)
    return body


__all__ = [
    "MAX_PDF_BYTES",
    "PdfConversionError",
    "PdfConverterDisabledError",
    "convert_pptx_to_pdf",
    "is_configured",
]
