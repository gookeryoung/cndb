"""smart_color 智能配色模块测试.

覆盖 3 条匹配路径 + fallback 调色板 + 调试函数的所有分支.
"""

from __future__ import annotations

from cndb.plugins.tables.field_types.smart_color import (
    fallback_palette,
    has_semantic_match,
    match_color,
    match_debug,
    suggest_colors,
)


class TestMatchColor:
    """核心 match_color 函数：3 条匹配路径 + 空值."""

    def test_empty_label(self):
        """空字符串 → None（覆盖 match_color if not label: 分支）."""
        assert match_color("") is None
        assert match_color("   ") is None

    def test_keyword_rule_positive(self):
        """路径 1: 关键词规则命中 —— 肯定词."""
        assert match_color("已完成") == "success"
        assert match_color("进行中") == "processing"
        assert match_color("是") == "green"

    def test_keyword_rule_priority(self):
        """路径 1: 优先级关键词 —— 不同等级."""
        assert match_color("紧急") == "red"
        assert match_color("高优先级") == "orange"
        assert match_color("低优先级") == "blue"

    def test_keyword_rule_with_number_suffix(self):
        """路径 1 + 数字后缀触发 _apply_number_bonus（L255 分支）."""
        # "紧急 1" → 命中紧急规则(red, weight=15) + 数字 1 ≤ 2 → 再加 5 分
        assert match_color("紧急 1") == "red"
        # "低优先级 5" → 命中低优先级规则(blue) + 数字 5 ≥ 4 → 再加 5 分
        assert match_color("低优先级 5") == "blue"

    def test_number_level_with_context(self):
        """路径 2: 纯数字等级 + 有上下文词（L268 has_context 分支）."""
        assert match_color("等级 1") == "red"
        assert match_color("等级 3") == "gold"
        assert match_color("优先级 5") == "green"

    def test_number_level_short_label(self):
        """路径 2: 无上下文但 label 短（≤10 字符）—— 数字本身就是语义."""
        # "3级" 或 "等级3" 都有上下文词"等级"；但 "5" 这种短 label 也应被识别
        assert match_color("等级2") == "orange"  # 数字 2 → orange
        assert match_color("优先级4") == "blue"  # 数字 4 → blue

    def test_grade_letter(self):
        """路径 3: 等级字母完整单词匹配."""
        assert match_color("Grade A") == "green"
        assert match_color("等级 B") == "cyan"
        assert match_color("级别 D") == "orange"

    def test_no_match_returns_none(self):
        """完全无语义的 label → None（让调用方走 fallback）."""
        assert match_color("选项阿尔法") is None
        assert match_color("xyz789") is None


class TestFallbackPalette:
    """fallback_palette 循环分配."""

    def test_loop(self):
        """按索引循环，每 8 次一轮."""
        assert fallback_palette(0) == "blue"
        assert fallback_palette(7) == "red"
        assert fallback_palette(8) == "blue"  # 回到起点
        assert fallback_palette(100) == "green"  # 100 % 8 = 4


class TestSuggestColors:
    """suggest_colors 混合策略."""

    def test_all_semantic(self):
        """全部语义命中 → 直接返回."""
        labels = ["已完成", "进行中", "紧急"]
        result = suggest_colors(labels)
        assert result == ["success", "processing", "red"]

    def test_all_fallback(self):
        """全部无语义 → 走 fallback 调色板."""
        labels = ["选项A", "选项B", "选项C", "选项D", "选项E", "选项F", "选项G", "选项H", "选项I"]
        result = suggest_colors(labels)
        assert len(result) == 9
        # 前 8 个应取自调色板且互不相同
        assert len(set(result[:8])) == 8
        # 第 9 个开始循环
        assert result[8] == result[0]

    def test_mixed_avoids_used(self):
        """语义命中 + fallback 混合时，fallback 应避开已用色."""
        labels = ["紧急", "选项X", "选项Y"]
        result = suggest_colors(labels)
        assert result[0] == "red"  # 语义命中
        # fallback 的两个应避开 "red"
        assert result[1] != "red"
        assert result[2] != "red"
        assert result[1] != result[2]

    def test_empty_input(self):
        """空列表 → 空列表."""
        assert suggest_colors([]) == []


class TestHasSemanticMatch:
    """has_semantic_match 快速判断."""

    def test_hit(self):
        assert has_semantic_match("已完成") is True
        assert has_semantic_match("紧急") is True

    def test_miss(self):
        assert has_semantic_match("选项XYZ") is False
        assert has_semantic_match("") is False


class TestMatchDebug:
    """match_debug 调试函数 —— 覆盖全部分支."""

    def test_empty_label(self):
        """空 label → (None, [])."""
        assert match_debug("") == (None, [])

    def test_keyword_match(self):
        """有关键词命中 —— scores 非空."""
        best, scores = match_debug("紧急且重要")
        assert best is not None
        assert len(scores) > 0
        # 每个 score 三元组：(color, score, description)
        for entry in scores:
            assert len(entry) == 3
            assert isinstance(entry[1], int)

    def test_number_level_fallback(self):
        """无语义关键词，走纯数字等级映射 —— scores 只含数字映射."""
        best, scores = match_debug("等级 2")
        assert best == "orange"
        # 应有 1 条 "纯数字等级映射"
        descs = [s[2] for s in scores]
        assert "纯数字等级映射" in descs

    def test_grade_letter_fallback(self):
        """无语义关键词，走等级字母映射."""
        best, scores = match_debug("Grade A")
        assert best == "green"
        descs = [s[2] for s in scores]
        assert "等级字母映射" in descs

    def test_no_match_at_all(self):
        """完全无语义 → (None, [])."""
        best, scores = match_debug("@@@###")
        assert best is None
        assert scores == []


class TestNormalizeAndNumbers:
    """底层辅助函数的边界覆盖."""

    def test_number_extract_hit(self):
        """尾部数字提取 —— 命中."""
        from cndb.plugins.tables.field_types.smart_color import _extract_number

        assert _extract_number("优先级 1") == 1
        assert _extract_number("P3") == 3
        assert _extract_number("等级 10") == 10

    def test_number_extract_miss(self):
        """尾部数字提取 —— 未命中."""
        from cndb.plugins.tables.field_types.smart_color import _extract_number

        assert _extract_number("进行中") is None
        assert _extract_number("选项A") is None

    def test_grade_letter_hit(self):
        """等级字母提取 —— 命中."""
        from cndb.plugins.tables.field_types.smart_color import _extract_grade_word

        assert _extract_grade_word("Grade A") == "a"
        assert _extract_grade_word("等级 B") == "b"
        assert _extract_grade_word("级别 C") == "c"

    def test_grade_letter_miss(self):
        """等级字母提取 —— 不匹配末尾单字母."""
        from cndb.plugins.tables.field_types.smart_color import _extract_grade_word

        assert _extract_grade_word("选项A") is None
        assert _extract_grade_word("进行中") is None
