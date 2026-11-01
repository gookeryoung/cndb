"""结构 DSL 判定层单测（ADR 0079 P0 测试清单）.

覆盖：词法 / 语法各语句形态、表达式求值与白名单函数、参数覆盖、模块默认值
与递归上限、六图元参数合法性、布尔与变换下推、诊断行 / 列、全部编译期限制
与编译确定性（I3）。
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from cndb.plugins.design.services.dsl import CompileResult, Diagnostic, compile_design
from cndb.plugins.design.services.dsl.lexer import DslSyntaxError, tokenize
from cndb.plugins.design.services.dsl.limits import (
    MAX_MODULES,
    MAX_NESTING_DEPTH,
    MAX_PARAMS,
    MAX_PRIMITIVES,
)
from cndb.plugins.design.services.dsl.parse import parse_program


def _ok(content: str, overrides: dict[str, float] | None = None) -> dict[str, Any]:
    result = compile_design(content, overrides)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.ir is not None
    return result.ir


def _err(content: str, overrides: dict[str, float] | None = None) -> Diagnostic:
    result = compile_design(content, overrides)
    assert not result.ok
    assert result.ir is None
    assert result.diagnostics
    return result.diagnostics[0]


#: ADR 0079 §2 的完整示例（带通孔的法兰板）
_EXAMPLE = """\
// 参数：驱动参数面板
param width = 80          // 长度单位 mm
param height = 40
param hole_d = 8

// 模块：带默认值的可复用结构
module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w/2, h/2, -1]) {
      cyl(d = hole_d, h = t + 2)
    }
  }
}

plate(width, height, 12)
"""


# ── 词法 ─────────────────────────────────────────────────


class TestLexer:
    def test_tokens_basic(self):
        tokens = tokenize("box(d = 1.5, h = .5)")
        values = [t.value for t in tokens[:-1]]
        assert values == ["box", "(", "d", "=", "1.5", ",", "h", "=", ".5", ")"]
        kinds = [t.kind for t in tokens]
        assert kinds[-1] == "EOF"

    def test_line_col_tracking(self):
        tokens = tokenize("param x = 1\nparam y = 2")
        second = tokens[4]
        assert (second.value, second.line, second.col) == ("param", 2, 1)

    def test_comments_ignored(self):
        tokens = tokenize("// 行注释\n/* 块注释 */ box")
        idents = [t for t in tokens if t.kind == "IDENT"]
        assert [t.value for t in idents] == ["box"]

    def test_unclosed_block_comment(self):
        with pytest.raises(DslSyntaxError, match="块注释未闭合"):
            tokenize("/* 未闭合")

    def test_unknown_character(self):
        with pytest.raises(DslSyntaxError, match="无法识别的字符"):
            tokenize("box $ 1")


# ── 语法 ─────────────────────────────────────────────────


class TestParser:
    def test_program_structure(self):
        program = parse_program(_EXAMPLE)
        assert [p.name for p in program.params] == ["width", "height", "hole_d"]
        assert [m.name for m in program.modules] == ["plate"]
        assert len(program.instances) == 1

    def test_module_params_with_defaults(self):
        program = parse_program("module m(a, b = 2, c = a) { box(w=1,h=1,d=1) } m(1)")
        params = program.modules[0].params
        assert [p.name for p in params] == ["a", "b", "c"]
        assert params[0].default is None
        assert params[1].default is not None

    def test_primitive_args_must_be_named(self):
        with pytest.raises(DslSyntaxError, match="图元参数须为"):
            parse_program("box(1, 2, 3)")

    def test_primitive_arg_missing_eq(self):
        with pytest.raises(DslSyntaxError, match="名 = 值"):
            parse_program("box(w 1)")

    def test_duplicate_primitive_arg(self):
        with pytest.raises(DslSyntaxError, match="参数 'w' 重复"):
            parse_program("box(w=1, w=2)")

    def test_keyword_cannot_be_reference(self):
        with pytest.raises(DslSyntaxError, match="不能作为标识符引用"):
            parse_program("box(d = param)")

    def test_unknown_function_call(self):
        with pytest.raises(DslSyntaxError, match="未知函数 'foo'"):
            parse_program("param a = foo(1)")

    def test_module_name_conflicts_with_keyword(self):
        with pytest.raises(DslSyntaxError, match="重名"):
            parse_program("module union(a) { box(w=1,h=1,d=1) } union(1)")

    def test_empty_boolean_block(self):
        with pytest.raises(DslSyntaxError, match="union 块不能为空"):
            parse_program("union {}")

    def test_empty_transform_block(self):
        with pytest.raises(DslSyntaxError, match="块不能为空"):
            parse_program("translate([1,1,1]) {}")

    def test_unclosed_module_body(self):
        with pytest.raises(DslSyntaxError, match="未闭合"):
            parse_program("module m() { box(w=1,h=1,d=1)")

    def test_positional_after_named_in_module_call(self):
        with pytest.raises(DslSyntaxError, match="位置参数不能出现在命名参数之后"):
            parse_program("module m(a, b) { box(w=1,h=1,d=1) } m(a=1, 2)")

    def test_keyword_as_instance(self):
        with pytest.raises(DslSyntaxError, match="不能作为实例"):
            parse_program("union { param }")

    def test_param_in_module_body_rejected(self):
        with pytest.raises(DslSyntaxError, match="不能作为实例"):
            parse_program("module m() { param a = 1 }")

    def test_expect_eq_eof(self):
        with pytest.raises(DslSyntaxError, match="文件结尾"):
            parse_program("param a")

    def test_param_name_not_ident(self):
        with pytest.raises(DslSyntaxError, match="应为参数名"):
            parse_program("param 1 = 2")

    def test_instance_head_not_ident(self):
        with pytest.raises(DslSyntaxError, match="应为实例"):
            parse_program("union { 1 }")

    def test_boolean_block_nesting_exceeded(self):
        content = "union { " * 17 + "box(w=1,h=1,d=1)" + " }" * 17
        diagnostic = _err(content)
        assert f"嵌套深度超过上限 {MAX_NESTING_DEPTH}" in diagnostic.message

    def test_zero_arg_function_call(self):
        # 语法层允许零参调用（解析分支），求值层按元数报错
        diagnostic = _err("param a = min()")
        assert "参数个数应为 1~8，实为 0" in diagnostic.message

    def test_primitive_no_args(self):
        diagnostic = _err("box()")
        assert "box 缺少必需参数" in diagnostic.message

    def test_expression_expected_error_describes_punct(self):
        with pytest.raises(DslSyntaxError, match="应为表达式，实际是 '\\)'"):
            parse_program("param a = )")

    def test_named_arg_duplicate_in_module_call(self):
        with pytest.raises(DslSyntaxError, match="命名参数 'a' 重复"):
            parse_program("module m(a) { box(w=a,h=1,d=1) } m(a=1, a=2)")

    def test_boolean_block_depth_exceeded(self):
        # 31 层变换后第 32 层实例合法，其布尔块入口在深度 33 报错
        content = "translate([0,0,0]) " * (MAX_NESTING_DEPTH - 1) + "union { box(w=1,h=1,d=1) }"
        diagnostic = _err(content)
        assert f"嵌套深度超过上限 {MAX_NESTING_DEPTH}" in diagnostic.message

    def test_nesting_depth_exceeded(self):
        content = "translate([0,0,0]) " * (MAX_NESTING_DEPTH + 1) + "box(w=1,h=1,d=1)"
        diagnostic = _err(content)
        assert f"嵌套深度超过上限 {MAX_NESTING_DEPTH}" in diagnostic.message

    def test_nesting_depth_at_limit_ok(self):
        # 顶层实例在深度 1 解析，因此恰好可容纳 31 层变换包裹
        content = "translate([0,0,0]) " * (MAX_NESTING_DEPTH - 1) + "box(w=1,h=1,d=1)"
        ir = _ok(content)
        assert ir["nodes"][0]["op"] == "box"


# ── 编译基础 ──────────────────────────────────────────────


class TestCompileBasics:
    def test_full_example_ir(self):
        ir = _ok(_EXAMPLE)
        assert ir["version"] == 1
        assert ir["units"] == {"length": "mm", "angle": "deg"}
        assert ir["params"] == [
            {"name": "width", "value": 80},
            {"name": "height", "value": 40},
            {"name": "hole_d", "value": 8},
        ]
        (node,) = ir["nodes"]
        assert node["op"] == "difference"
        box, cyl = node["children"]
        assert box == {"op": "box", "size": [80, 40, 12]}
        assert cyl["op"] == "cyl"
        assert cyl["d"] == 8
        assert cyl["h"] == 14
        assert cyl["fn"] == 64
        assert cyl["transform"] == {"ops": [["translate", [40.0, 20.0, -1.0]]]}

    def test_empty_program_ok(self):
        ir = _ok("")
        assert ir["nodes"] == []
        assert ir["params"] == []

    def test_params_only_no_instances(self):
        ir = _ok("param a = 1")
        assert ir["nodes"] == []

    def test_pi_constant(self):
        ir = _ok("param r = PI * 2\nsphere(r = r)")
        assert ir["params"][0]["value"] == pytest.approx(math.pi * 2)

    def test_param_references_previous(self):
        ir = _ok("param a = 2\nparam b = a * 3")
        assert ir["params"][1]["value"] == 6

    def test_param_overrides(self):
        ir = _ok(_EXAMPLE, overrides={"width": 120, "hole_d": 10})
        assert ir["params"][0]["value"] == 120
        assert ir["params"][2]["value"] == 10
        box, cyl = ir["nodes"][0]["children"]
        assert box["size"] == [120, 40, 12]
        assert cyl["d"] == 10

    def test_override_unknown_name(self):
        diagnostic = _err(_EXAMPLE, overrides={"nope": 1})
        assert "未知参数覆盖 'nope'" in diagnostic.message

    def test_override_rejects_bool(self):
        diagnostic = _err(_EXAMPLE, overrides={"width": True})
        assert "覆盖值必须为数值" in diagnostic.message

    def test_override_rejects_non_finite(self):
        diagnostic = _err(_EXAMPLE, overrides={"width": float("inf")})
        assert "覆盖值必须为有限数值" in diagnostic.message

    def test_override_rejects_string(self):
        diagnostic = _err(_EXAMPLE, overrides={"width": "80"})  # type: ignore[dict-item]
        assert "覆盖值必须为数值" in diagnostic.message

    def test_duplicate_param(self):
        diagnostic = _err("param a = 1\nparam a = 2")
        assert "重复的 param 声明 'a'" in diagnostic.message

    def test_param_named_pi(self):
        diagnostic = _err("param PI = 3")
        assert "PI 为内置常量" in diagnostic.message

    def test_param_value_not_finite(self):
        # 400 位数字面量求值为 inf（不抛异常），触发有限值校验
        diagnostic = _err(f"param a = {'9' * 400}")
        assert "值必须为有限数值" in diagnostic.message

    def test_function_overflow(self):
        diagnostic = _err("param a = pow(10, 999)")
        assert "数值越界" in diagnostic.message

    def test_determinism(self):
        assert compile_design(_EXAMPLE).ir == compile_design(_EXAMPLE).ir

    def test_ir_json_serializable(self):
        json.dumps(_ok(_EXAMPLE))

    def test_diagnostic_position(self):
        diagnostic = _err("box(w=1,h=1,d=1)\ncyl(d = 1)")
        assert diagnostic.line == 2
        assert diagnostic.col == 1
        assert diagnostic.severity == "error"

    def test_vector_in_wrong_context(self):
        diagnostic = _err("cyl(d = [1,2,3], h = 1)")
        assert "向量只能用于图元的 size 参数" in diagnostic.message

    def test_size_must_be_vector(self):
        diagnostic = _err("box(size = 5)")
        assert "应为向量" in diagnostic.message


# ── 表达式 ────────────────────────────────────────────────


class TestExpressions:
    def _param(self, expr: str) -> float:
        return _ok(f"param a = {expr}")["params"][0]["value"]

    def test_arithmetic_priority(self):
        # 1 + (2*3) - ((4/2) % 3) = 5
        assert self._param("1 + 2 * 3 - 4 / 2 % 3") == pytest.approx(5.0)

    def test_left_associativity(self):
        assert self._param("10 - 2 - 3") == pytest.approx(5.0)

    def test_parentheses(self):
        assert self._param("(1 + 2) * 3") == pytest.approx(9.0)

    def test_unary_minus(self):
        assert self._param("-5 + -3") == pytest.approx(-8.0)

    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("sqrt(16)", 4.0),
            ("min(3, 1, 2)", 1.0),
            ("max(3, 1, 2)", 3.0),
            ("pow(2, 3)", 8.0),
            ("floor(2.7)", 2.0),
            ("ceil(2.1)", 3.0),
            ("round(2.5)", 2.0),
            ("abs(-3)", 3.0),
            ("sin(0)", 0.0),
            ("cos(0)", 1.0),
            ("tan(0)", 0.0),
            ("asin(1)", math.pi / 2),
            ("acos(1)", 0.0),
            ("atan2(1, 1)", math.pi / 4),
        ],
    )
    def test_builtin_functions(self, expr: str, expected: float):
        assert self._param(expr) == pytest.approx(expected)

    def test_division_by_zero(self):
        diagnostic = _err("param a = 1 / 0")
        assert "除数为零" in diagnostic.message

    def test_modulo_by_zero(self):
        diagnostic = _err("param a = 1 % 0")
        assert "右操作数为零" in diagnostic.message

    def test_unknown_identifier(self):
        diagnostic = _err("param a = undefined")
        assert "未知标识符 'undefined'" in diagnostic.message

    def test_function_arity(self):
        diagnostic = _err("param a = atan2(1)")
        assert "参数个数应为 2~2" in diagnostic.message

    def test_function_domain_error(self):
        diagnostic = _err("param a = sqrt(-1)")
        assert "数值越界" in diagnostic.message

    def test_eval_layer_unknown_function(self):
        """求值层对未白名单函数兜底拒绝（语法层之外的直接调用路径）."""
        from cndb.plugins.design.services.dsl.expressions import DslEvalError, eval_expr
        from cndb.plugins.design.services.dsl.nodes import FuncCall, Num

        with pytest.raises(DslEvalError, match="未知函数 'foo'"):
            eval_expr(FuncCall(name="foo", args=(Num(1.0, 1, 1),), line=1, col=1), {})


# ── 图元 ──────────────────────────────────────────────────


class TestPrimitives:
    def test_box_whd(self):
        ir = _ok("box(w=10, h=20, d=30)")
        assert ir["nodes"] == [{"op": "box", "size": [10.0, 20.0, 30.0]}]

    def test_box_size_and_whd_conflict(self):
        diagnostic = _err("box(size=[1,1,1], w=1)")
        assert "size 与 w/h/d 不可同时使用" in diagnostic.message

    def test_box_missing_args(self):
        diagnostic = _err("box(w=1, h=1)")
        assert "box 缺少必需参数 d" in diagnostic.message

    def test_box_negative_size(self):
        diagnostic = _err("box(size=[1,-1,1])")
        assert "参数 y 必须为正数" in diagnostic.message

    def test_unknown_primitive_arg(self):
        diagnostic = _err("box(width=1, h=1, d=1)")
        assert "box 不支持参数 'width'" in diagnostic.message

    def test_cyl_missing_required(self):
        diagnostic = _err("cyl(h=10)")
        assert "cyl 缺少必需参数 d" in diagnostic.message

    def test_sphere_missing_required(self):
        diagnostic = _err("sphere(fn=32)")
        assert "sphere 缺少必需参数 r" in diagnostic.message

    def test_cone_degenerate(self):
        diagnostic = _err("cone(d1=0, d2=0, h=10)")
        assert "d1 与 d2 不能同时为 0" in diagnostic.message

    def test_cone_negative_diameter(self):
        diagnostic = _err("cone(d1=-1, d2=2, h=10)")
        assert "参数 d1 不能为负" in diagnostic.message

    def test_tube_inner_not_smaller(self):
        diagnostic = _err("tube(od=10, id=10, h=5)")
        assert "id 必须小于 od" in diagnostic.message

    def test_cone_missing_required(self):
        diagnostic = _err("cone(d1=8, h=10)")
        assert "cone 缺少必需参数 d2" in diagnostic.message

    def test_torus_missing_required(self):
        diagnostic = _err("torus(r=10)")
        assert "torus 缺少必需参数 tube" in diagnostic.message

    def test_tube_missing_required(self):
        diagnostic = _err("tube(od=10, id=4)")
        assert "tube 缺少必需参数 h" in diagnostic.message

    def test_all_primitives_ir(self):
        ir = _ok(
            "torus(r=10, tube=2)\n"
            "tube(od=10, id=4, h=5)\n"
            "cone(d1=8, d2=0, h=10)\n"
            "sphere(r=5)\n"
            "cyl(d=6, h=8)\n"
            "box(size=[1,2,3])"
        )
        ops = [node["op"] for node in ir["nodes"]]
        assert ops == ["torus", "tube", "cone", "sphere", "cyl", "box"]
        assert ir["nodes"][0] == {"op": "torus", "r": 10.0, "tube": 2.0, "fn": 64}
        assert ir["nodes"][1] == {"op": "tube", "od": 10.0, "id": 4.0, "h": 5.0, "fn": 64}
        assert ir["nodes"][2] == {"op": "cone", "d1": 8.0, "d2": 0.0, "h": 10.0, "fn": 64}
        assert ir["nodes"][3] == {"op": "sphere", "r": 5.0, "fn": 64}

    def test_fn_custom_value(self):
        ir = _ok("cyl(d=1, h=1, fn=8)")
        assert ir["nodes"][0]["fn"] == 8

    def test_fn_fractional(self):
        diagnostic = _err("cyl(d=1, h=1, fn=3.5)")
        assert "fn 必须为整数" in diagnostic.message

    @pytest.mark.parametrize("fn", [2, 300])
    def test_fn_out_of_range(self, fn: int):
        diagnostic = _err(f"cyl(d=1, h=1, fn={fn})")
        assert "fn 取值须在 3~256" in diagnostic.message

    def test_primitive_count_exceeded(self):
        calls = "m()\n" * (MAX_PRIMITIVES // 2 + 1)
        content = "module m() { box(w=1,h=1,d=1)\nbox(w=1,h=1,d=1) } " + calls
        diagnostic = _err(content)
        assert f"图元实例总数超过上限 {MAX_PRIMITIVES}" in diagnostic.message

    def test_primitive_count_at_limit_ok(self):
        content = "module m() { box(w=1,h=1,d=1) } " + "m()\n" * MAX_PRIMITIVES
        assert len(_ok(content)["nodes"]) == MAX_PRIMITIVES


# ── 变换与布尔 ────────────────────────────────────────────


class TestTransformsAndBooleans:
    def test_transform_single_instance(self):
        ir = _ok("rotate([0, 90, 0]) cyl(d=1, h=1)")
        assert ir["nodes"][0]["transform"] == {"ops": [["rotate", [0.0, 90.0, 0.0]]]}

    def test_transform_order_outer_first(self):
        ir = _ok("translate([1,0,0]) rotate([0,90,0]) box(w=1,h=1,d=1)")
        ops = ir["nodes"][0]["transform"]["ops"]
        assert ops == [["translate", [1.0, 0.0, 0.0]], ["rotate", [0.0, 90.0, 0.0]]]

    def test_transform_block_pushes_to_all_children(self):
        ir = _ok("mirror([1,0,0]) { box(w=1,h=1,d=1)\nbox(w=2,h=2,d=2) }")
        assert [node["transform"]["ops"] for node in ir["nodes"]] == [
            [["mirror", [1.0, 0.0, 0.0]]],
            [["mirror", [1.0, 0.0, 0.0]]],
        ]

    def test_nested_same_kind_transforms(self):
        ir = _ok("translate([1,0,0]) translate([0,1,0]) box(w=1,h=1,d=1)")
        assert ir["nodes"][0]["transform"]["ops"] == [
            ["translate", [1.0, 0.0, 0.0]],
            ["translate", [0.0, 1.0, 0.0]],
        ]

    def test_scale_transform(self):
        ir = _ok("scale([2,2,2]) sphere(r=1)")
        assert ir["nodes"][0]["transform"]["ops"] == [["scale", [2.0, 2.0, 2.0]]]

    def test_boolean_nesting(self):
        ir = _ok("union { box(w=1,h=1,d=1)\ndifference { cyl(d=1,h=1) sphere(r=1) } }")
        (node,) = ir["nodes"]
        assert node["op"] == "union"
        assert node["children"][1]["op"] == "difference"
        assert [child["op"] for child in node["children"][1]["children"]] == ["cyl", "sphere"]

    def test_transform_inside_boolean_pushes_to_leaf(self):
        ir = _ok("difference { box(size=[4,4,4]) translate([2,2,-1]) cyl(d=1, h=6) }")
        cyl = ir["nodes"][0]["children"][1]
        assert cyl["transform"] == {"ops": [["translate", [2.0, 2.0, -1.0]]]}


# ── 模块 ──────────────────────────────────────────────────


class TestModules:
    def test_positional_args(self):
        ir = _ok("module m(a, b) { box(w=a, h=b, d=1) } m(3, 4)")
        assert ir["nodes"][0]["size"] == [3.0, 4.0, 1.0]

    def test_named_and_mixed_args(self):
        ir = _ok("module m(a, b = 2) { box(w=a, h=b, d=1) } m(b=5, a=1)")
        assert ir["nodes"][0]["size"] == [1.0, 5.0, 1.0]
        ir = _ok("module m(a, b = 2) { box(w=a, h=b, d=1) } m(1, b=5)")
        assert ir["nodes"][0]["size"] == [1.0, 5.0, 1.0]

    def test_default_value(self):
        ir = _ok("module m(a, b = a * 2) { box(w=a, h=b, d=1) } m(3)")
        assert ir["nodes"][0]["size"] == [3.0, 6.0, 1.0]

    def test_default_references_global_param(self):
        ir = _ok("param t = 4\nmodule m(a = t) { box(w=a, h=1, d=1) } m()")
        assert ir["nodes"][0]["size"][0] == 4.0

    def test_too_many_positional(self):
        diagnostic = _err("module m(a) { box(w=a,h=1,d=1) } m(1, 2)")
        assert "最多接收 1 个参数，实为 2" in diagnostic.message

    def test_unknown_named_arg(self):
        diagnostic = _err("module m(a) { box(w=a,h=1,d=1) } m(b=1)")
        assert "没有参数 'b'" in diagnostic.message

    def test_duplicate_binding(self):
        diagnostic = _err("module m(a) { box(w=a,h=1,d=1) } m(1, a=2)")
        assert "参数 'a' 重复绑定" in diagnostic.message

    def test_missing_required_arg(self):
        diagnostic = _err("module m(a, b) { box(w=a,h=b,d=1) } m(1)")
        assert "缺少参数 'b'" in diagnostic.message

    def test_unknown_module(self):
        diagnostic = _err("m()")
        assert "未知模块 'm'" in diagnostic.message

    def test_duplicate_module_decl(self):
        content = "module m() { box(w=1,h=1,d=1) }\nmodule m() { cyl(d=1,h=1) }\nm()"
        diagnostic = _err(content)
        assert "重复的 module 声明 'm'" in diagnostic.message

    def test_default_value_not_finite(self):
        content = f"module m(a = {'9' * 400}) {{ box(w=a, h=1, d=1) }} m()"
        diagnostic = _err(content)
        assert "必须为有限数值" in diagnostic.message

    def test_body_references_global_params(self):
        ir = _ok("param g = 7\nmodule m(w) { box(w=w, h=g, d=1) } m(2)")
        assert ir["nodes"][0]["size"] == [2.0, 7.0, 1.0]

    def test_recursion_depth_exceeded(self):
        diagnostic = _err("module m() { m() } m()")
        assert "递归深度超过上限" in diagnostic.message

    def test_chain_recursion_at_limit_ok(self):
        parts = [f"module m{i}() {{ m{i + 1}() }}" for i in range(1, 16)] + ["module m16() { box(w=1,h=1,d=1) }"]
        ir = _ok("\n".join(parts) + "\nm1()")
        assert ir["nodes"][0]["op"] == "box"

    def test_chain_recursion_exceeded(self):
        parts = [f"module m{i}() {{ m{i + 1}() }}" for i in range(1, 17)] + ["module m17() { box(w=1,h=1,d=1) }"]
        diagnostic = _err("\n".join(parts) + "\nm1()")
        assert "递归深度超过上限" in diagnostic.message

    def test_transform_pushes_into_module_body(self):
        ir = _ok("module m() { box(w=1,h=1,d=1) } translate([1,2,3]) m()")
        assert ir["nodes"][0]["transform"] == {"ops": [["translate", [1.0, 2.0, 3.0]]]}


# ── 编译期限制 ────────────────────────────────────────────


class TestLimits:
    def test_content_too_large(self):
        content = "//" + "x" * (256 * 1024) + "\nbox(w=1,h=1,d=1)"
        diagnostic = _err(content)
        assert "原文超过 256KB 上限" in diagnostic.message

    def test_params_exceeded(self):
        content = "\n".join(f"param a{i} = {i}" for i in range(MAX_PARAMS + 1))
        diagnostic = _err(content)
        assert f"param 数量超过上限 {MAX_PARAMS}" in diagnostic.message

    def test_modules_exceeded(self):
        content = "\n".join(f"module m{i}() {{ box(w=1,h=1,d=1) }}" for i in range(MAX_MODULES + 1))
        diagnostic = _err(content)
        assert f"module 数量超过上限 {MAX_MODULES}" in diagnostic.message

    def test_result_contract(self):
        """失败结果只有诊断、无半截 IR；成功结果无诊断."""
        ok_result = compile_design("box(w=1,h=1,d=1)")
        assert isinstance(ok_result, CompileResult)
        assert ok_result.diagnostics == ()
        err_result = compile_design("box(")
        assert err_result.ok is False
        assert err_result.ir is None
        assert err_result.diagnostics[0].severity == "error"
