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
from cndb.plugins.design.services.dsl.nodes import SystemDecl
from cndb.plugins.design.services.dsl.parse import parse_program


def _ok(
    content: str,
    overrides: dict[str, float] | None = None,
    *,
    resolver=None,
) -> dict[str, Any]:
    result = compile_design(content, overrides, resolver=resolver)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.ir is not None
    return result.ir


def _err(
    content: str,
    overrides: dict[str, float] | None = None,
    *,
    resolver=None,
) -> Diagnostic:
    result = compile_design(content, overrides, resolver=resolver)
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
        assert ir["version"] == 6
        assert ir["constraints"] == []
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
        assert f"module / system 声明数量超过上限 {MAX_MODULES}" in diagnostic.message

    def test_system_counts_toward_module_limit(self):
        modules = "\n".join(f"module m{i}() {{ box(w=1,h=1,d=1) }}" for i in range(MAX_MODULES - 1))
        content = modules + "\nsystem s { box(w=1,h=1,d=1) }\nsystem s2 { box(w=1,h=1,d=1) }"
        diagnostic = _err(content)
        assert f"module / system 声明数量超过上限 {MAX_MODULES}" in diagnostic.message

    def test_result_contract(self):
        """失败结果只有诊断、无半截 IR；成功结果无诊断."""
        ok_result = compile_design("box(w=1,h=1,d=1)")
        assert isinstance(ok_result, CompileResult)
        assert ok_result.diagnostics == ()
        err_result = compile_design("box(")
        assert err_result.ok is False
        assert err_result.ir is None
        assert err_result.diagnostics[0].severity == "error"


# ── 装配大纲（ADR 0083 D2 / D3） ─────────────────────────


def _outline(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return ir["outline"]["children"]


def _outline_parts(node: dict[str, Any]) -> int:
    """大纲子树里的零件（图元）计数."""
    if node["kind"] == "part":
        return 1
    return sum(_outline_parts(child) for child in node["children"])


def _geom_primitives(node: dict[str, Any]) -> int:
    """几何 IR 子树里的图元计数（布尔节点递归，图元为叶）."""
    if "children" in node:
        return sum(_geom_primitives(child) for child in node["children"])
    return 1


class TestOutline:
    """大纲与 nodes 同源同次编译：组件 / 分组 / 零件三类节点 + 1 基源位置."""

    def test_full_example_outline(self):
        ir = _ok(_EXAMPLE)
        (assembly,) = _outline(ir)
        assert assembly["kind"] == "assembly"
        assert assembly["name"] == "plate"
        # 顶层实例调用语句（_EXAMPLE 第 16 行）
        assert (assembly["line"], assembly["col"]) == (16, 1)
        (group,) = assembly["children"]
        assert group["kind"] == "group"
        assert group["op"] == "difference"
        assert (group["line"], group["col"]) == (8, 3)
        part_box, part_cyl = group["children"]
        # 整块是一个顶层 CSG 节点：组内所有零件共享块下标（ADR 0103 §4#1）
        assert (assembly["node_index"], group["node_index"]) == (0, 0)
        assert part_box == {"kind": "part", "primitive": "box", "line": 9, "col": 5, "node_index": 0}
        assert part_cyl == {"kind": "part", "primitive": "cyl", "line": 11, "col": 7, "node_index": 0}

    def test_top_level_part(self):
        ir = _ok("box(w=1,h=1,d=1)")
        assert _outline(ir) == [{"kind": "part", "primitive": "box", "line": 1, "col": 1, "node_index": 0}]

    def test_nested_modules_hierarchy(self):
        content = "module inner() {\n  box(w=1,h=1,d=1)\n}\nmodule outer() {\n  inner()\n}\nouter()"
        ir = _ok(content)
        (outer,) = _outline(ir)
        assert (outer["kind"], outer["name"], outer["line"], outer["col"]) == ("assembly", "outer", 7, 1)
        (inner,) = outer["children"]
        assert (inner["kind"], inner["name"], inner["line"], inner["col"]) == ("assembly", "inner", 5, 3)
        assert inner["children"] == [{"kind": "part", "primitive": "box", "line": 2, "col": 3, "node_index": 0}]

    def test_boolean_group_node(self):
        content = "difference {\n  box(w=2,h=2,d=2)\n  cyl(d=1,h=4)\n}"
        ir = _ok(content)
        (group,) = _outline(ir)
        assert group["kind"] == "group"
        assert group["op"] == "difference"
        assert (group["line"], group["col"]) == (1, 1)
        assert [child["line"] for child in group["children"]] == [2, 3]
        assert [child["primitive"] for child in group["children"]] == ["box", "cyl"]

    def test_transform_is_transparent(self):
        content = "translate([1,2,3]) {\n  box(w=1,h=1,d=1)\n}"
        ir = _ok(content)
        # 变换不建大纲节点，零件保持顶层层级；几何仍带 transform 栈
        assert _outline(ir) == [{"kind": "part", "primitive": "box", "line": 2, "col": 3, "node_index": 0}]
        assert ir["nodes"][0]["transform"] == {"ops": [["translate", [1.0, 2.0, 3.0]]]}

    def test_empty_program_outline(self):
        assert _ok("")["outline"] == {"children": []}
        assert _ok("param a = 1")["outline"] == {"children": []}

    def test_module_multi_instance_keeps_declaration_lines(self):
        content = "module p() {\n  box(w=1,h=1,d=1)\n}\np()\np()"
        ir = _ok(content)
        assert len(_outline(ir)) == 2
        assert [node["line"] for node in _outline(ir)] == [4, 5]
        assert [node["node_index"] for node in _outline(ir)] == [0, 1]
        for node in _outline(ir):
            assert node["children"] == [
                {"kind": "part", "primitive": "box", "line": 2, "col": 3, "node_index": node["node_index"]}
            ]

    def test_outline_parts_match_geometry(self):
        """I1：大纲零件数 = 几何图元数（同源同次编译）."""
        for content in (
            _EXAMPLE,
            "union {\n  box(w=1,h=1,d=1)\n  sphere(r=1)\n}",
            "translate([0,0,0]) box(w=1,h=1,d=1)",
        ):
            ir = _ok(content)
            outline_total = sum(_outline_parts(node) for node in _outline(ir))
            geometry_total = sum(_geom_primitives(node) for node in ir["nodes"])
            assert outline_total == geometry_total

    def test_outline_has_no_param_bindings(self):
        """D3：大纲只带名称 / 类型 / 源位置 / 节点下标，不写模块参数绑定值."""
        ir = _ok("module m(a) {\n  box(w=a,h=1,d=1)\n}\nm(3)")
        (assembly,) = _outline(ir)
        assert set(assembly) == {"kind", "name", "line", "col", "children", "node_index"}

    def test_outline_absent_on_failure(self):
        assert compile_design("box(").ir is None


def _walk_outline(nodes: list[dict[str, Any]]):
    """深度遍历大纲子树（含自身）."""
    for node in nodes:
        yield node
        yield from _walk_outline(node.get("children") or [])


class TestOutlineNodeIndex:
    """IR v5：大纲节点携带首个所属顶层 ``nodes`` 下标（ADR 0103 D7 / I3）."""

    def test_version_is_6(self):
        assert _ok("box(w=1,h=1,d=1)")["version"] == 6

    def test_index_within_nodes_range(self):
        for content in (
            _EXAMPLE,
            _SYSTEM_EXAMPLE,
            "translate([1,0,0]) box(w=1,h=1,d=1)\nsphere(r=2)",
        ):
            ir = _ok(content)
            total = len(ir["nodes"])
            for node in _walk_outline(_outline(ir)):
                index = node["node_index"]
                assert index is None or 0 <= index < total

    def test_toplevel_instances_index_in_order(self):
        ir = _ok("box(w=1,h=1,d=1)\ncyl(d=2,h=3)\nsphere(r=1)")
        assert [node["node_index"] for node in _outline(ir)] == [0, 1, 2]

    def test_group_children_share_block_index(self):
        """布尔块是单个顶层 CSG 节点：组内所有零件共享块下标（§4#1）."""
        ir = _ok("difference {\n  box(w=2,h=2,d=2)\n  cyl(d=1,h=4)\n}\nbox(w=1,h=1,d=1)")
        group, part = _outline(ir)
        assert group["node_index"] == 0
        assert [child["node_index"] for child in group["children"]] == [0, 0]
        assert part["node_index"] == 1

    def test_transform_does_not_change_index(self):
        ir = _ok("translate([1,0,0]) {\n  box(w=1,h=1,d=1)\n  cyl(d=1,h=1)\n}")
        assert [node["node_index"] for node in _outline(ir)] == [0, 1]
        assert len(ir["nodes"]) == 2

    def test_empty_module_index_is_none(self):
        ir = _ok("module empty() {\n}\nempty()\nbox(w=1,h=1,d=1)")
        assembly, part = _outline(ir)
        assert assembly["node_index"] is None
        assert part["node_index"] == 0

    def test_use_instance_index_shifted_to_caller(self):
        """被引用文件模板下标是文件内相对值，注入引用方后整体平移到顶层基址."""
        resolver = _make_resolver({"wheel": (11, "param d = 40\ncyl(d = d, h = 16)\n")})
        ir = _ok('box(w=1,h=1,d=1)\nuse "wheel"(d = 30) as w1', resolver=resolver)
        top, used = _outline_children(ir)
        assert top["node_index"] == 0
        assert used["node_index"] == 1
        assert used["children"][0]["node_index"] == 1


# ── 系统装配声明（ADR 0084 D1 / D3） ─────────────────────


_SYSTEM_EXAMPLE = """param wheel_d = 40
module wheel(d) {
  difference {
    cyl(d = d, h = 16)
    cyl(d = d * 0.35, h = 18)
  }
}
module chassis() {
  box(size = [120, 60, 8])
}
system rover {
  chassis()
  translate([40, 0, 0]) wheel(wheel_d)
  translate([-40, 0, 0]) wheel(wheel_d)
}
"""


class TestSystem:
    """system 是顶层单例根：系统级大纲节点 + 纯组织层（几何等价）+ 不可实例化."""

    def test_parse_system_decl(self):
        program = parse_program("system s { box(w=1,h=1,d=1) }")
        (system,) = program.systems
        assert (system.name, system.line, system.col) == ("s", 1, 1)
        assert len(system.body) == 1
        assert [item for item in program.items if isinstance(item, SystemDecl)] == [system]

    def test_system_outline_node(self):
        ir = _ok(_SYSTEM_EXAMPLE)
        (system,) = _outline(ir)
        assert system["kind"] == "system"
        assert system["name"] == "rover"
        assert (system["line"], system["col"]) == (11, 1)
        chassis, wheel_a, wheel_b = system["children"]
        assert chassis["kind"] == "assembly" and chassis["name"] == "chassis"
        assert wheel_a["kind"] == "assembly" and wheel_a["name"] == "wheel"
        assert wheel_b["kind"] == "assembly" and wheel_b["name"] == "wheel"
        # 变换透明穿透：平移不占层级，组件直接挂在 system 下
        assert wheel_a["children"][0]["kind"] == "group"
        assert [part["primitive"] for part in wheel_a["children"][0]["children"]] == ["cyl", "cyl"]

    def test_system_is_pure_organization_layer(self):
        """I2：把系统体平铺到顶层，nodes / params 完全一致（几何链路零感知）."""
        system_ir = _ok(_SYSTEM_EXAMPLE)
        flat = (
            "param wheel_d = 40\n"
            "module wheel(d) {\n"
            "  difference {\n"
            "    cyl(d = d, h = 16)\n"
            "    cyl(d = d * 0.35, h = 18)\n"
            "  }\n"
            "}\n"
            "module chassis() {\n"
            "  box(size = [120, 60, 8])\n"
            "}\n"
            "chassis()\n"
            "translate([40, 0, 0]) wheel(wheel_d)\n"
            "translate([-40, 0, 0]) wheel(wheel_d)\n"
        )
        flat_ir = _ok(flat)
        assert system_ir["nodes"] == flat_ir["nodes"]
        assert system_ir["params"] == flat_ir["params"]

    def test_multiple_systems_in_declaration_order(self):
        content = "system a { box(w=1,h=1,d=1) }\nsystem b { sphere(r=1) }"
        ir = _ok(content)
        assert [node["name"] for node in _outline(ir)] == ["a", "b"]
        assert [node["children"][0]["primitive"] for node in _outline(ir)] == ["box", "sphere"]

    def test_system_interleaved_with_top_level_instances(self):
        """nodes 顺序 = 顶层语句顺序（系统体就地展开，I2）."""
        content = "box(w=1,h=1,d=1)\nsystem s { cyl(d=1,h=1) }\nsphere(r=1)"
        ir = _ok(content)
        assert [node["op"] for node in ir["nodes"]] == ["box", "cyl", "sphere"]
        kinds = [node["kind"] for node in _outline(ir)]
        assert kinds == ["part", "system", "part"]

    def test_empty_system_body(self):
        ir = _ok("system s { }")
        (system,) = _outline(ir)
        assert system["children"] == []
        assert ir["nodes"] == []

    def test_no_system_outline_matches_v2_shape(self):
        """I5：无 system 的原文大纲仍只有 assembly / group / part（v5 只多 node_index）."""
        ir = _ok("module m() { box(w=1,h=1,d=1) } m()")
        (node,) = _outline(ir)
        assert node["kind"] == "assembly"
        assert set(node) == {"kind", "name", "line", "col", "children", "node_index"}

    def test_system_cannot_be_instantiated(self):
        diagnostic = _err("system s { box(w=1,h=1,d=1) }\ns()")
        assert "是 system 声明，不可实例化" in diagnostic.message

    def test_system_duplicate_decl(self):
        diagnostic = _err("system s { box(w=1,h=1,d=1) }\nsystem s { sphere(r=1) }")
        assert "重复的 system 声明 's'" in diagnostic.message

    def test_system_name_conflicts_with_module(self):
        diagnostic = _err("module n() { box(w=1,h=1,d=1) }\nsystem n { sphere(r=1) }")
        assert "重复的 system 声明 'n'" in diagnostic.message

    def test_system_name_conflicts_with_primitive(self):
        diagnostic = _err("system box { sphere(r=1) }")
        assert "与关键字 / 图元重名" in diagnostic.message

    def test_system_rejects_param_list(self):
        diagnostic = _err("system s(a) { box(w=1,h=1,d=1) }")
        assert "system 不接受参数表" in diagnostic.message

    def test_system_nested_declaration_rejected(self):
        diagnostic = _err("module m() { system s { box(w=1,h=1,d=1) } }")
        assert "关键字 'system' 不能作为实例" in diagnostic.message

    def test_system_keyword_not_usable_as_identifier(self):
        diagnostic = _err("box(d = system)")
        assert "关键字 'system' 不能作为标识符引用" in diagnostic.message

    def test_system_body_uses_global_params(self):
        ir = _ok("param g = 3\nsystem s { box(w=g, h=g, d=g) }")
        (system,) = _outline(ir)
        assert system["children"] == [{"kind": "part", "primitive": "box", "line": 2, "col": 12, "node_index": 0}]
        assert ir["nodes"] == [{"op": "box", "size": [3.0, 3.0, 3.0]}]

    def test_system_outline_parts_match_geometry(self):
        ir = _ok(_SYSTEM_EXAMPLE)
        outline_total = sum(_outline_parts(node) for node in _outline(ir))
        geometry_total = sum(_geom_primitives(node) for node in ir["nodes"])
        assert outline_total == geometry_total

    def test_system_compile_is_deterministic(self):
        first = json.dumps(_ok(_SYSTEM_EXAMPLE), sort_keys=True)
        second = json.dumps(_ok(_SYSTEM_EXAMPLE), sort_keys=True)
        assert first == second


# ── 分文件引用 use（ADR 0086 P0） ────────────────────────


def _make_resolver(files: dict[str, tuple[int, str]]):
    """构造 resolver：file_key → (file_id, content)；kind 固定 part."""
    from cndb.plugins.design.services.dsl.nodes import FileSource

    def resolve(key: str):
        if key not in files:
            return None
        file_id, content = files[key]
        return FileSource(
            file_id=file_id,
            file_key=key,
            kind="part",
            content=content,
            version_number=1,
            content_hash="",
        )

    return resolve


def _outline_children(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return ir["outline"]["children"]


class TestUseCall:
    _WHEEL = "param d = 40\ncyl(d = d, h = 16)\n"

    def test_use_expands_part_file(self):
        resolver = _make_resolver({"wheel": (11, self._WHEEL)})
        ir = _ok('use "wheel"(d = 30) as w1', resolver=resolver)
        assert ir["nodes"] == [{"op": "cyl", "d": 30.0, "h": 16, "fn": 64}]
        (outline,) = _outline_children(ir)
        assert outline["kind"] == "assembly"
        assert outline["name"] == "w1"
        assert outline["ref"] == {"source": "workspace", "file_id": 11, "file_key": "wheel", "kind": "part"}
        assert outline["file_id"] == 11

    def test_use_without_label_keeps_author_pose(self):
        resolver = _make_resolver({"wheel": (11, "cyl(d = 10, h = 5)\n")})
        ir = _ok('use "wheel"', resolver=resolver)
        assert ir["nodes"] == [{"op": "cyl", "d": 10, "h": 5, "fn": 64}]

    def test_use_multiple_instances_independent(self):
        resolver = _make_resolver({"wheel": (11, self._WHEEL)})
        ir = _ok('use "wheel"(d = 30) as a\nuse "wheel"(d = 50) as b', resolver=resolver)
        assert [n["d"] for n in ir["nodes"]] == [30.0, 50.0]

    def test_use_missing_file_errors(self):
        diag = _err('use "ghost"', resolver=_make_resolver({}))
        assert "ghost" in diag.message

    def test_use_unknown_param_errors(self):
        resolver = _make_resolver({"wheel": (11, "cyl(d = 10, h = 5)\n")})
        diag = _err('use "wheel"(x = 1)', resolver=resolver)
        assert "x" in diag.message

    def test_use_positional_and_named(self):
        resolver = _make_resolver({"p": (11, "param a = 1\nparam b = 2\nbox(w = a, h = b, d = 3)\n")})
        ir = _ok('use "p"(10, b = 20)', resolver=resolver)
        assert ir["nodes"][0]["size"] == [10.0, 20.0, 3.0]

    def test_use_without_resolver_errors(self):
        diag = _err('use "wheel"')
        assert "解析器" in diag.message

    def test_use_transform_wraps_part(self):
        resolver = _make_resolver({"wheel": (11, "cyl(d = 10, h = 5)\n")})
        ir = _ok('translate([5, 0, 0]) use "wheel"', resolver=resolver)
        assert ir["nodes"][0]["transform"]["ops"] == [["translate", [5, 0, 0]]]

    def test_use_nested_part_reference(self):
        resolver = _make_resolver(
            {
                "inner": (12, "box(w = 1, h = 1, d = 1)\n"),
                "outer": (13, 'use "inner" as i\ncyl(d = 2, h = 2)\n'),
            }
        )
        ir = _ok('use "outer" as o', resolver=resolver)
        assert len(ir["nodes"]) == 2
        (outline,) = _outline_children(ir)
        assert outline["children"][0]["file_id"] == 12

    def test_dependencies_snapshot_recorded(self):
        resolver = _make_resolver({"wheel": (11, "cyl(d = 10, h = 5)\n"), "axle": (12, "box(w = 1, h = 1, d = 1)\n")})
        result = compile_design('use "wheel" as a\nuse "axle" as b', resolver=resolver)
        assert result.ok
        keys = {d.file_key: d.file_id for d in result.dependencies}
        assert keys == {"wheel": 11, "axle": 12}

    def test_closure_budget_files(self):
        from cndb.plugins.design.services.dsl import limits

        count = limits.MAX_CLOSURE_FILES + 2
        files = {f"p{i}": (1000 + i, "box(w = 1, h = 1, d = 1)\n") for i in range(count)}
        content = "\n".join(f'use "p{i}" as c{i}' for i in range(count))
        diag = _err(content, resolver=_make_resolver(files))
        assert "上限" in diag.message

    def test_closure_budget_bytes(self):
        big = "box(w = 1, h = 1, d = 1)\n" * 40000  # 约 1MB
        diag = _err('use "big"', resolver=_make_resolver({"big": (1, big)}))
        assert "上限" in diag.message

    def test_ref_depth_limit(self):
        files: dict[str, tuple[int, str]] = {}
        for i in range(12):
            body = "box(w = 1, h = 1, d = 1)\n" if i == 0 else f'use "p{i - 1}" as c\nbox(w = 1, h = 1, d = 1)\n'
            files[f"p{i}"] = (100 + i, body)
        diag = _err('use "p11"', resolver=_make_resolver(files))
        assert "深度" in diag.message

    def test_circular_reference_detected(self):
        files = {
            "a": (1, 'use "b" as x\nbox(w = 1, h = 1, d = 1)\n'),
            "b": (2, 'use "a" as y\nbox(w = 1, h = 1, d = 1)\n'),
        }
        diag = _err('use "a"', resolver=_make_resolver(files))
        assert "循环引用" in diag.message

    def test_part_file_cannot_declare_system(self):
        diag = _err('use "p"', resolver=_make_resolver({"p": (1, "system s { box(w = 1, h = 1, d = 1) }\n")}))
        assert "system" in diag.message

    def test_use_compile_is_deterministic(self):
        resolver = _make_resolver({"wheel": (11, self._WHEEL)})
        content = 'use "wheel"(d = 30) as w1'
        first = json.dumps(_ok(content, resolver=resolver), sort_keys=True)
        second = json.dumps(_ok(content, resolver=resolver), sort_keys=True)
        assert first == second


# ── 装配约束（ADR 0086 P0） ──────────────────────────────

_PART_WHEEL = "param d = 40\ncyl(d = d, h = 16)\n"
_PART_AXLE = "cyl(d = 10, h = 80)\n"


def _two_parts_resolver():
    return _make_resolver({"wheel": (11, _PART_WHEEL), "axle": (12, _PART_AXLE)})


class TestConstraints:
    def test_fixed_keeps_author_pose(self):
        ir = _ok(
            'use "wheel"(d = 30) as w\nconstraint c1 fixed(a = w.origin)',
            resolver=_two_parts_resolver(),
        )
        # wheel 的原点即图元原点：fixed 不加变换
        assert ir["nodes"][0] == {"op": "cyl", "d": 30.0, "h": 16, "fn": 64}

    def test_coincident_moves_second(self):
        ir = _ok(
            'use "wheel" as w\nuse "axle" as a\n'
            "constraint c1 fixed(a = w.origin)\n"
            "constraint c2 coincident(a = w.origin, b = a.origin, offset = [0, 0, 12])",
            resolver=_two_parts_resolver(),
        )
        assert ir["nodes"][1]["transform"]["ops"] == [["translate", [0, 0, 12]]]
        (entry,) = [c for c in ir["constraints"] if c["id"] == "c2"]
        assert entry["status"] == "ok"

    def test_distance_positions_by_value(self):
        ir = _ok(
            'use "wheel" as w\nuse "axle" as a\n'
            "constraint c1 fixed(a = w.origin)\n"
            "constraint c2 distance(a = w.origin, b = a.origin, value = 40)",
            resolver=_two_parts_resolver(),
        )
        # 缺省方向 +Z：平移 40
        assert ir["nodes"][1]["transform"]["ops"] == [["translate", [0.0, 0.0, 40.0]]]

    def test_concentric_aligns_axes(self):
        ir = _ok(
            'use "wheel" as w\nrotate([90, 0, 0]) use "axle" as a\n'
            "constraint c1 fixed(a = w.origin)\n"
            "constraint c2 concentric(a = w.z, b = a.z)",
            resolver=_two_parts_resolver(),
        )
        # a 的 z 轴被转到 X 向，concentric 需旋回与 w.z 平行
        ops = ir["nodes"][1]["transform"]["ops"]
        assert any(op[0] == "rotate" for op in ops)

    def test_conflict_errors(self):
        diag = _err(
            'use "wheel" as w\nuse "axle" as a\n'
            "constraint c1 fixed(a = w.origin)\n"
            "constraint c2 coincident(a = w.origin, b = a.origin, offset = [0, 0, 12])\n"
            "constraint c3 distance(a = w.origin, b = a.origin, value = 40)",
            resolver=_two_parts_resolver(),
        )
        assert "冲突" in diag.message

    def test_duplicate_label_errors(self):
        diag = _err(
            'use "wheel" as w\nuse "axle" as w',
            resolver=_two_parts_resolver(),
        )
        assert "标签" in diag.message

    def test_unknown_label_reference_errors(self):
        diag = _err(
            'use "wheel" as w\nconstraint c1 fixed(a = ghost.origin)',
            resolver=_two_parts_resolver(),
        )
        assert "ghost" in diag.message

    def test_angle_requires_axis_anchor(self):
        diag = _err(
            'use "wheel" as w\nuse "axle" as a\nconstraint c1 angle(a = w.origin, b = a.origin, value = 90)',
            resolver=_two_parts_resolver(),
        )
        assert "轴向" in diag.message

    def test_underconstrained_warning(self):
        result = compile_design(
            'use "wheel" as w\nuse "axle" as a\nconstraint c1 distance(a = w.origin, b = a.origin, value = 40)',
            resolver=_two_parts_resolver(),
        )
        assert result.ok
        assert any(d.severity == "warning" for d in result.diagnostics)
        (entry,) = result.ir["constraints"]
        assert entry["status"] == "warning"

    def test_constraints_inside_system_scope(self):
        ir = _ok(
            'use "wheel" as w\nuse "axle" as a\n'
            "system chassis {\n"
            '  use "wheel" as w2\n'
            '  use "axle" as a2\n'
            "  constraint c1 fixed(a = w2.origin)\n"
            "  constraint c2 coincident(a = w2.origin, b = a2.origin, offset = [0, 0, 5])\n"
            "}\n",
            resolver=_two_parts_resolver(),
        )
        # system 内约束只作用于该作用域；顶层实例保持作者位姿
        assert ir["nodes"][0] == {"op": "cyl", "d": 40, "h": 16, "fn": 64}
        assert ir["nodes"][1] == {"op": "cyl", "d": 10, "h": 80, "fn": 64}
        assert len(ir["constraints"]) == 2

    def test_constraint_compile_is_deterministic(self):
        content = (
            'use "wheel" as w\nuse "axle" as a\n'
            "constraint c1 fixed(a = w.origin)\n"
            "constraint c2 coincident(a = w.origin, b = a.origin, offset = [0, 0, 12])"
        )
        first = json.dumps(_ok(content, resolver=_two_parts_resolver()), sort_keys=True)
        second = json.dumps(_ok(content, resolver=_two_parts_resolver()), sort_keys=True)
        assert first == second

    def test_unlabeled_instances_keep_author_pose(self):
        ir = _ok(
            'use "wheel"\nuse "axle"\nbox(w = 1, h = 1, d = 1)',
            resolver=_two_parts_resolver(),
        )
        assert ir["constraints"] == []
        assert ir["nodes"][0] == {"op": "cyl", "d": 40, "h": 16, "fn": 64}
