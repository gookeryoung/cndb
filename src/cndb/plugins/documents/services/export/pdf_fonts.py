"""PDF 中文字体发现与注册（fc-match / fc-list / 目录扫描三策略 + 缓存）。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_pdf_font_state: list[str | None] = [None]

# 标准 Linux 字体扫描目录（按优先级排序，后安装的字体通常放 .local/share/fonts）
_LINUX_FONT_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.local/share/fonts",
    "~/.fonts",
]

# CJK 字体家族关键词（文件名或 family 名包含这些关键词即视为候选）
_CJK_FONT_KEYWORDS = (
    "wqy",
    "wenquanyi",
    "sourcehansans",
    "sourcehan",
    "notosansmonocjk",
    "notosanscjk",
    "notosanssc",
    "droidsansfallback",
    "droidsans",
    "han",
    "simhei",
    "simsun",
    "yahei",
    "msyh",
    "msyh.ttc",
    "uming",
    "ukai",
    "uming.ttc",
    "ukai.ttc",
    "fandol",
)


def _run_command(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
    """执行外部命令，返回 (returncode, stdout). 超时或 FileNotFound 时返回 (-1, '')."""
    import shutil
    import subprocess

    if shutil.which(cmd[0]) is None:
        return -1, ""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


# fc-match 返回的家族名称若不含下列关键词，视为非 CJK 字体（fontconfig 回退到西文字体）
_KNOWN_CJK_FAMILY_HINTS = (
    "cjk",
    "han",
    "wenquanyi",
    "wqy",
    "source han",
    "sourcehan",
    "droidsansfallback",
    "droid sans fallback",
    "ming",
    "kai",
    "hei",
    "yahei",
    "simsun",
    "simhei",
    "msyh",
    "microsoft yahei",
    "noto sans",  # 注意：Noto Sans (非 CJK) 也匹配；配合 :lang=zh 保证结果为中文候选
    "ar pl",
    "fandol",
    "uming",
    "ukai",
    "文泉驛",
    "文泉驿",
    "思源",
    "黑体",
    "宋体",
    "楷体",
)


def _is_cjk_family(family_name: str) -> bool:
    """判断 fontconfig 返回的 family name 是否指向 CJK 字体（大小写不敏感）."""
    if not family_name:
        return False
    lower = family_name.lower()
    return any(hint in lower for hint in _KNOWN_CJK_FAMILY_HINTS)


def _cjk_font_candidates() -> list[tuple[str, str, int | None]]:
    """返回中文字体候选列表 (注册名, 文件路径, subfontIndex).

    发现策略（按顺序，靠前优先级高）:
    1. fc-match 精确匹配常见 CJK 字体家族（利用 fontconfig 解析 TTC index）
    2. fc-list :lang=zh 枚举所有已注册中文字体（fontconfig 优先选择）
    3. 扫描标准 Linux 字体目录下含 CJK 关键词的 .ttf/.ttc
    4. 项目内字体资源路径（前端 fonts/ 目录）
    5. Windows 绝对路径（C:/Windows/Fonts）
    6. 裸文件名（保留兼容，几乎总是失败）

    说明：reportlab 的 TTFont 只支持 TrueType 轮廓（.ttf / .ttc），
    OpenType/CFF（.otf 或 TTC 内 CFF）会被 TTFont 拒绝，这里不主动过滤，
    交给 _ensure_pdf_font 逐个尝试，失败即跳过。
    """
    from pathlib import Path

    candidates: list[tuple[str, str, int | None]] = []
    seen: set[tuple[str, str, int | None]] = set()

    def _add(name: str, path: str, index: int | None) -> None:
        key = (name, path, index)
        if key in seen:
            return
        seen.add(key)
        candidates.append(key)

    # ── 策略 1：fc-match 精确匹配常见 CJK 字体家族 ──
    fc_match_families = [
        ("WenQuanYi Micro Hei", "WQY-MicroHei"),
        ("WenQuanYi Zen Hei", "WQY-ZenHei"),
        ("Source Han Sans CN", "SourceHanSansCN"),
        ("Source Han Sans SC", "SourceHanSansCN"),
        ("Noto Sans SC", "NotoSansSC"),
        ("Noto Sans CJK SC", "NotoSansCJK-SC"),
        ("Droid Sans Fallback", "DroidSansFallback"),
        ("AR PL UMing CN", "ARPL-UMing-CN"),
        ("AR PL UKai CN", "ARPL-UKai-CN"),
        ("Fandol Song", "Fandol-Song"),
        ("SimHei", "SimHei"),
        ("Microsoft YaHei", "MSYaHei"),
    ]
    for family, reg_name in fc_match_families:
        # 加 :lang=zh 让 fontconfig 优先返回带中文 glyph 的字体
        _rc, out = _run_command(["fc-match", f"{family}:lang=zh", "-f", "%{file}|%{family}|%{index}"])
        if _rc != 0:
            continue
        line = out.strip()
        if not line or line.count("|") < 2:
            continue
        file_part, family_part, idx_part = [p.strip() for p in line.split("|", 2)]
        if not file_part or not Path(file_part).is_file():
            continue
        # 若 fontconfig 因找不到目标家族回退到西文字体（如 DejaVu Sans），跳过
        if not _is_cjk_family(family_part):
            continue
        try:
            index = int(idx_part)
        except (ValueError, AttributeError):
            index = 0
        _add(reg_name, file_part, index if index > 0 else None)

    # ── 策略 2：fc-list :lang=zh 枚举全部已注册中文字体 ──
    _rc, out = _run_command(["fc-list", ":lang=zh", "file", "family", ":index"])
    if _rc == 0 and out.strip():
        for raw_line in out.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            # fc-list 输出格式：file: family1,family2:lang=zh;lang=zh-cn:index
            # 简化解析：取首段 file，忽略后续 family/lang 部分
            if ":" not in raw_line:
                continue
            file_path, _rest = raw_line.split(":", 1)
            file_path = file_path.strip()
            if not file_path or not Path(file_path).is_file():
                continue
            # 从 :index=? 后缀里取 subfontIndex
            idx_match = None
            for seg in _rest.split(":"):
                seg = seg.strip()
                if seg.startswith("index="):
                    try:
                        idx_match = int(seg.split("=", 1)[1])
                    except ValueError:
                        idx_match = None
                    break
            # 提取 family 名作为注册名（取冒号分隔后的第一段 family）
            family_part = _rest.split(":", 1)[0].strip()
            reg_name = family_part.split(",", 1)[0] if family_part else Path(file_path).stem
            if idx_match is not None and idx_match > 0:
                _add(reg_name, file_path, idx_match)
            else:
                _add(reg_name, file_path, None)

    # ── 策略 3：扫描标准 Linux 字体目录 ──
    for raw_dir in _LINUX_FONT_DIRS:
        try:
            dir_path = Path(raw_dir).expanduser()
            if not dir_path.is_dir():
                continue
            for ext in ("*.ttf", "*.ttc"):
                for f in dir_path.rglob(ext):
                    fname_lower = f.name.lower()
                    if any(kw in fname_lower for kw in _CJK_FONT_KEYWORDS):
                        reg_name = f.stem[:32]  # 控制长度，避免字体族名过长
                        _add(reg_name, str(f), None)
        except OSError:
            continue

    # ── 策略 4：项目内字体资源 ──
    # 前端 fonts/noto-sans-sc/ 目录含 woff2，reportlab 需要 ttf/otf，
    # 这里也把目录加入扫描；若将来补充 ttf 版本可自动命中
    _project_root = Path(__file__).resolve().parents[6]  # .../src/cndb/plugins/documents/services/export → /workspace
    for _sub in ("frontend/public/fonts", "src/cndb/fonts"):
        _res_dir = _project_root / _sub
        if not _res_dir.is_dir():
            continue
        for ext in ("*.ttf", "*.ttc", "*.otf"):
            for f in _res_dir.rglob(ext):
                reg_name = f.stem[:32]
                _add(reg_name, str(f), None)

    # ── 策略 5：Windows 绝对路径 ──
    win_fonts = "C:/Windows/Fonts"
    _add("SimHei", f"{win_fonts}/simhei.ttf", None)
    _add("MicrosoftYaHei", f"{win_fonts}/msyh.ttc", 0)
    _add("MicrosoftJhengHei", f"{win_fonts}/msjh.ttc", 0)
    _add("SimSun", f"{win_fonts}/simsun.ttc", 0)

    return candidates


def _ensure_pdf_font() -> str | None:
    """注册 reportlab 中文字体（懒加载），返回注册名；全部失败返回 None.

    注册成功后同时注册同名字体族（normal/bold/italic 均映射同一字体），
    使 RML <b>/<i> 标签不会因缺少粗体/斜体变体而崩溃.

    三态缓存:
        None   → 未扫描过
        ""     → 已扫描过, 系统无可用 CJK 字体
        非空 str → 已注册成功的字体族名
    这样在无中文字体的环境下第二次调用直接返回 None, 不再重跑 fc-match / 目录扫描.
    """
    if _pdf_font_state[0] is not None:
        return _pdf_font_state[0] or None
    try:
        from pathlib import Path

        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for font_name, font_file, subfont_index in _cjk_font_candidates():
            if not font_file or not Path(font_file).is_file():
                continue
            # 跳过已知 OpenType/CFF 字体文件扩展名（TTFont 只接受 TrueType 轮廓）
            if font_file.lower().endswith(".otf"):
                logger.debug("跳过 CFF 字体 %s（reportlab TTFont 不支持）", font_file)
                continue
            try:
                if subfont_index is not None:
                    pdfmetrics.registerFont(TTFont(font_name, font_file, subfontIndex=subfont_index))
                else:
                    pdfmetrics.registerFont(TTFont(font_name, font_file))
                pdfmetrics.registerFontFamily(
                    font_name,
                    normal=font_name,
                    bold=font_name,
                    italic=font_name,
                    boldItalic=font_name,
                )
                _pdf_font_state[0] = font_name
                logger.info("PDF 中文字体已注册: %s (%s)", font_name, font_file)
                return font_name
            except Exception:
                logger.debug("候选中文字体注册失败: %s，尝试下一个", font_file, exc_info=True)
                continue
        # 全部候选耗尽仍未注册成功 —— 缓存空串, 避免每次 PDF 渲染都重跑 fontconfig
        _pdf_font_state[0] = ""
        logger.warning("reportlab 中文字体不可用，PDF 中文字符可能显示异常（已缓存扫描结果）")
    except Exception:
        logger.debug("reportlab 字体注册跳过", exc_info=True)
        _pdf_font_state[0] = ""
    return None
