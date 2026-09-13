"""选择字段选项的智能配色模块.

根据选项 label 的语义自动匹配最合适的 Ant Design 预设色名，返回值可直接
作为 ``SelectOption.color`` 存储，前端 ``<Tag color=...>`` 可直接消费。

核心思路：
1. 预定义若干**语义域**（domain），每个域绑定一个 antd 色名和一组关键词
2. 对输入 label 做小写归一化 + 去除空白/标点后，逐个域匹配关键词，累加得分
3. 支持 label 中出现数字（如 "P1"、"等级 3"）的场景，数字越小优先级越高
4. 全部域都未命中时，调用 :func:`fallback_palette` 按列表位置分配默认色
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# ─────────────── Ant Design 预设色名（与前端 tagColors.ts 保持一致） ──────────

# 可用于 SelectOption.color 的有效色名；前端 <Tag> 组件直接消费
ANTD_PRESET_COLORS: tuple[str, ...] = (
    "blue",
    "purple",
    "cyan",
    "green",
    "magenta",
    "pink",
    "red",
    "orange",
    "yellow",
    "volcano",
    "geekblue",
    "lime",
    "gold",
)

# 状态类色名（success/processing/error/warning/default）—— antd status 预设
ANTD_STATUS_COLORS: tuple[str, ...] = (
    "success",
    "processing",
    "error",
    "default",
    "warning",
)

# 智能配色专用调色板（从 antd 预设中挑出适合做连续区分的 8 种）
# 顺序是调色板的自然顺序，fallback 时按选项索引循环取用
_PALETTE: tuple[str, ...] = (
    "blue",
    "green",
    "orange",
    "purple",
    "cyan",
    "magenta",
    "gold",
    "red",
)


# ─────────────── 语义域定义 ──────────────────────────────────────────────────


class _ColorRule:
    """单条语义配色规则."""

    __slots__ = ("color", "description", "keywords", "weight")

    def __init__(self, color: str, keywords: Iterable[str], *, weight: int = 10, description: str = "") -> None:
        self.color = color
        self.description = description or color
        self.keywords: tuple[str, ...] = tuple(k.lower() for k in keywords)
        self.weight = weight


# 规则表按"匹配优先级"排序（高 weight 先试）。同一 label 命中多条规则时，
# 权重最高的那条胜出。权重基数 10，带数字后缀的会再加权。
#
# 注意：关键词避免使用单字母（a/b/c/f/y/n 等），因为它们容易在普通词中
# 意外命中（如 "选项A" 中的 A 不应匹配 "优秀/grade_a" 规则）。
_RULES: tuple[_ColorRule, ...] = (
    # ── 布尔 / 是或否（最常见） ──
    _ColorRule(
        "green", ("是", "yes", "true", "对", "同意", "通过", "ok", "done", "已完成", "完成"), description="肯定/完成"
    ),
    _ColorRule(
        "default",
        ("否", "no", "false", "错", "拒绝", "不通过", "未完成", "pending", "待处理", "待办"),
        description="否定/待办",
    ),
    # ── 状态域：进行中 / 已完成 / 已取消 ──
    _ColorRule(
        "processing",
        ("进行中", "处理中", "执行中", "ongoing", "running", "in_progress", "active"),
        description="进行中",
    ),
    _ColorRule(
        "success", ("已完成", "完成", "已解决", "已处理", "closed", "resolved", "finished"), description="已完成"
    ),
    _ColorRule(
        "error",
        ("已取消", "取消", "废弃", "已关闭", "驳回", "rejected", "canceled", "cancelled", "abandoned"),
        description="已取消/驳回",
    ),
    # ── 优先级 / 紧急度 ──
    # weight=15 让 "紧急" 类优先于其他语义
    _ColorRule(
        "red",
        ("紧急", "urgent", "critical", "p0", "最高优先级", "立即处理", "立即"),
        weight=15,
        description="紧急/最高优先级",
    ),
    _ColorRule("orange", ("高优先级", "较高", "high", "p2", "重要", "优先", "高"), description="高优先级/重要"),
    _ColorRule("gold", ("中等", "medium", "normal", "一般", "p3", "普通", "常规", "中"), description="中等/一般"),
    _ColorRule(
        "blue", ("低优先级", "较低", "low", "p4", "p5", "次要", "minimal", "不急", "低"), description="低优先级/次要"
    ),
    # ── 进度/完成度 ──
    _ColorRule("green", ("100%", "全部", "完全", "full", "complete", "全部完成"), description="完全/100%"),
    _ColorRule("cyan", ("75%", "大部分", "mostly", "多数", "基本完成"), description="75%/大部分"),
    _ColorRule("gold", ("50%", "一半", "half", "中等进度", "进行中"), description="50%/一半"),
    _ColorRule("orange", ("25%", "小部分", "少量", "刚开始"), description="25%/少量"),
    _ColorRule("default", ("0%", "无", "none", "空", "empty", "未开始"), description="0%/无"),
    # ── 风险等级 ──
    _ColorRule("error", ("极高风险", "高风险", "风险极高", "critical_risk", "high_risk", "危险"), description="高风险"),
    _ColorRule("warning", ("中风险", "较高风险", "medium_risk", "moderate", "有风险"), description="中风险"),
    _ColorRule("green", ("低风险", "安全", "safe", "low_risk", "no_risk", "无风险"), description="低风险/安全"),
    # ── 评分/等级（文字描述） ──
    _ColorRule(
        "red", ("极差", "很差", "failed", "grade_d", "非常差", "糟糕", "terrible", "bad"), description="极差/失败"
    ),
    _ColorRule("orange", ("较差", "及格", "poor", "grade_c", "pass", "勉强"), description="较差/及格"),
    _ColorRule("gold", ("中等", "平均", "ok", "grade_b", "average", "一般般"), description="中等"),
    _ColorRule(
        "green", ("良好", "优秀", "很好", "grade_a", "excellent", "great", "perfect", "出色"), description="优秀"
    ),
    # ── 金额/费用程度 ──
    _ColorRule("red", ("免费", "free", "零元", "无偿", "赠送"), description="免费"),
    _ColorRule("orange", ("昂贵", "expensive", "premium", "高价", "很贵", "贵"), description="昂贵"),
    _ColorRule("green", ("便宜", "廉价", "cheap", "low_cost", "低价", "实惠", "划算", "不贵"), description="便宜/划算"),
    # ── 频率域 ──
    _ColorRule("red", ("从不", "never", "零次", "完全不"), description="从不"),
    _ColorRule("orange", ("偶尔", "很少", "rarely", "seldom", "罕见", "极少"), description="偶尔"),
    _ColorRule("gold", ("有时", "sometimes", "some", "偶尔发生"), description="有时"),
    _ColorRule("blue", ("经常", "often", "频繁", "时常"), description="经常"),
    _ColorRule("green", ("总是", "每天", "always", "daily", "hourly", "每次"), description="总是/每天"),
    # ── 角色/身份（粗粒度） ──
    _ColorRule(
        "purple",
        ("管理员", "admin", "administrator", "root", "超级管理员", "owner", "所有者"),
        description="管理员/Owner",
    ),
    _ColorRule("blue", ("编辑", "editor", "写权限", "可编辑"), description="编辑者"),
    _ColorRule(
        "default", ("只读", "read_only", "查看", "reader", "viewer", "访客", "guest", "浏览"), description="只读/访客"
    ),
    # ── 待定/未知 ──
    _ColorRule(
        "processing", ("待定", "待确认", "tbd", "pending_confirm", "unknown", "未知", "未确定"), description="待定/未知"
    ),
)


# ─────────────── 核心算法 ────────────────────────────────────────────────────

# 提取 label 尾部的数字（如 "优先级 1" → 1, "P3" → 3, "等级 5" → 5）
_NUM_SUFFIX_RE = re.compile(r"(\d+)\s*$")
# 完整单词匹配的等级字母（如 "Grade A"、"B级"——但不包括 "选项A" 这种末尾单字母）
# 匹配：开头或紧跟非字母的字母 a-f，后跟非字母或结尾
_GRADE_WORD_RE = re.compile(r"(?:grade\s*|等级\s*|级别\s*|level\s*|^)([a-fA-F])(?:\s*级|\s*$|\b)")


def _normalize(text: str) -> str:
    """归一化 label：去空白、小写、全半角标点统一。"""
    t = text.strip().lower()
    # 全角标点 → 半角
    for a, b in (("（", "("), ("）", ")"), ("，", ","), ("：", ":"), ("－", "-"), ("　", "")):
        t = t.replace(a, b)
    return t


def _extract_number(text: str) -> int | None:
    """从 label 尾部提取数字（如 "优先级 1" → 1, "P3" → 3）。"""
    m = _NUM_SUFFIX_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def _extract_grade_word(text: str) -> str | None:
    """提取完整单词匹配的等级字母（如 'Grade A' → a, '等级 B' → b）.

    不会误匹配 "选项A" 这种末尾单字母。
    """
    m = _GRADE_WORD_RE.search(text)
    if m:
        return m.group(1).lower()
    return None


# 数字等级 → 建议颜色的直接映射（当 label 仅为 "等级 3" 这种无文字描述时使用）
_NUMBER_LEVEL_COLORS: dict[int, str] = {
    1: "red",  # 最高级/最紧急
    2: "orange",
    3: "gold",
    4: "blue",
    5: "green",  # 最低级/最不紧急
}

# 等级字母 → 颜色映射
_GRADE_LETTER_COLORS: dict[str, str] = {
    "a": "green",
    "b": "cyan",
    "c": "gold",
    "d": "orange",
    "e": "red",
    "f": "red",
}

# 数字辅助加权：规则描述匹配 + 数字阈值 → 加分
_NUMBER_BONUSES: tuple[tuple[tuple[str, ...], int, int], ...] = (
    # (描述关键词元组, 数字上限, 加分)
    (("紧急", "最高", "高优先级"), 2, 5),
    (("低优先级", "次要"), 4, 5),
    (("优秀", "良好"), 4, 3),
)


def _apply_number_bonus(score: int, rule: _ColorRule, num: int) -> int:
    """根据规则描述和数字后缀做加权修正.

    数字越小优先级越高（红色域加分）；数字越大越好/越低（绿色域加分）。
    """
    for keywords, threshold, bonus in _NUMBER_BONUSES:
        if any(kw in rule.description for kw in keywords) and (
            (threshold <= 2 and num <= threshold) or (threshold >= 4 and num >= threshold)
        ):
            return score + bonus
    return score


def _match_keyword_rules(text: str) -> tuple[str | None, int]:
    """路径 1：关键词规则匹配，返回 (最佳色, 得分)."""
    best_color: str | None = None
    best_score = 0
    num = _extract_number(text)

    for rule in _RULES:
        score = 0
        for kw in rule.keywords:
            if kw in text:
                score += rule.weight
        if score == 0:
            continue
        if num is not None:
            score = _apply_number_bonus(score, rule, num)
        if score > best_score:
            best_score = score
            best_color = rule.color

    return best_color, best_score


def _match_number_level(text: str) -> str | None:
    """路径 2：纯数字等级映射（如 "等级 3", "优先级 1" —— 无文字描述时）."""
    num = _extract_number(text)
    if num is None:
        return None
    has_context = any(ctx in text for ctx in ("等级", "级别", "优先级", "level", "priority", "p"))
    if has_context or len(text) <= 10:  # label 较短时，数字本身就是主要语义
        return _NUMBER_LEVEL_COLORS.get(num)
    return None


def _match_grade_letter(text: str) -> str | None:
    """路径 3：完整单词匹配的等级字母."""
    grade = _extract_grade_word(text)
    if grade is not None:
        return _GRADE_LETTER_COLORS.get(grade)
    return None


def match_color(label: str) -> str | None:
    """根据单个选项 label 匹配最合适的 antd 预设色名.

    匹配策略：
    1. 对 label 做归一化（小写 + 去空白/标点）
    2. 依次扫描所有规则，每个规则命中任意关键词即累加得分
    3. 如果 label 含数字后缀（如 "等级 1"），结合 "等级/优先级" 等上下文词做数字匹配
       数字越小优先级越高 → 红色域；数字越大 → 绿色域
    4. 如果 label 含完整单词匹配的等级字母（如 "Grade A"），映射到对应颜色
    5. 返回得分最高的色名；全部未命中返回 None（让调用方走 fallback）

    Args:
        label: 选项显示文本（SelectOption.label）.

    Returns:
        antd 预设色名字符串（如 "green", "error", "orange"），或 None.
    """
    if not label:
        return None
    text = _normalize(label)

    color, _score = _match_keyword_rules(text)
    if color is not None:
        return color

    color = _match_number_level(text)
    if color is not None:
        return color

    return _match_grade_letter(text)


def fallback_palette(index: int) -> str:
    """当语义匹配完全失败时，按选项在列表中的位置循环分配调色板.

    这保证了同一组未命名选项（如 ["选项A", "选项B", "选项C"]）也能得到
    稳定且彼此区分的颜色。

    Args:
        index: 选项在列表中的位置（0-based）.

    Returns:
        antd 预设色名.
    """
    return _PALETTE[index % len(_PALETTE)]


def suggest_colors(labels: list[str]) -> list[str]:
    """一键为一组选项 label 生成建议颜色.

    混合策略：
    1. 逐个调用 :func:`match_color` 用语义匹配
    2. 未命中的按 fallback 调色板分配，且保证与已命中的颜色不重复

    Args:
        labels: 选项显示文本列表.

    Returns:
        与 labels 等长的 antd 色名列表.
    """
    result: list[str | None] = [match_color(lbl) for lbl in labels]

    # 收集已使用的颜色集合，让 fallback 尽量避开
    used: set[str] = {c for c in result if c is not None}
    fallback_idx = 0

    out: list[str] = []
    for c in result:
        if c is not None:
            out.append(c)
            continue
        # fallback：循环调色板，跳过已用色
        while True:
            pick = fallback_palette(fallback_idx)
            fallback_idx += 1
            if pick not in used:
                used.add(pick)
                out.append(pick)
                break
    return out


def has_semantic_match(label: str) -> bool:
    """快速判断一个 label 是否能被语义规则命中."""
    return match_color(label) is not None


# ─────────────── 调试/可观测 ────────────────────────────────────────────────


def match_debug(label: str) -> tuple[str | None, list[tuple[str, int, str]]]:
    """返回 (最终色名, [(规则色, 得分, 规则描述), ...])，用于调试或单测.

    仅用于验证算法的可预测性，生产路径走 :func:`match_color` 即可。
    """
    if not label:
        return None, []
    text = _normalize(label)
    scores: list[tuple[str, int, str]] = []

    for rule in _RULES:
        score = 0
        for kw in rule.keywords:
            if kw in text:
                score += rule.weight
        if score:
            scores.append((rule.color, score, rule.description))

    def _sort_key(item: tuple[str, int, str]) -> int:
        return item[1]

    scores.sort(key=_sort_key, reverse=True)

    # 补充路径 2/3 的调试信息
    if not scores:
        num = _extract_number(text)
        if num is not None:
            has_ctx = any(ctx in text for ctx in ("等级", "级别", "优先级", "level", "priority", "p"))
            if has_ctx or len(text) <= 10:
                mapped = _NUMBER_LEVEL_COLORS.get(num)
                if mapped:
                    scores.append((mapped, 5, "纯数字等级映射"))

        grade = _extract_grade_word(text)
        if grade is not None:
            mapped = _GRADE_LETTER_COLORS.get(grade)
            if mapped:
                scores.append((mapped, 5, "等级字母映射"))

    best = scores[0][0] if scores else None
    return best, scores


__all__ = [
    "ANTD_PRESET_COLORS",
    "ANTD_STATUS_COLORS",
    "fallback_palette",
    "has_semantic_match",
    "match_color",
    "match_debug",
    "suggest_colors",
]
