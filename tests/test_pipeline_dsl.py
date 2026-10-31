"""流水线 DSL 编译与表达式白名单测试（ADR 0076 D2 / D3 / I2）."""

from __future__ import annotations

import pytest

from cndb.plugins.pipeline.services.dsl.expressions import (
    ExpressionEvalError,
    evaluate_expression,
    is_expression,
    parse_expression,
)
from cndb.plugins.pipeline.services.dsl.parse import (
    MAX_NAME_LENGTH,
    compile_workflow,
    topological_jobs,
)
from cndb.plugins.pipeline.services.errors import CheckError, DslError

VALID_DSL = """
name: 每日质量巡检
on:
  manual: true
  events: [record.updated]
  schedule: "0 6 * * *"
vars:
  max_null_rate: 0.05
jobs:
  表基础体检:
    steps:
      - uses: table/null-rate
        with:
          table: 人员
          fields: all
          max_rate: ${{ vars.max_null_rate }}
  文档检查:
    needs: 表基础体检
    if: ${{ jobs.表基础体检.conclusion == 'success' }}
    steps:
      - uses: document/links
"""


class TestCompileWorkflow:
    """YAML → IR 的结构与参数校验."""

    def test_compile_valid_workflow(self) -> None:
        ir = compile_workflow(VALID_DSL)
        assert ir.name == "每日质量巡检"
        assert ir.triggers == {"manual": True, "events": ["record.updated"], "schedule": "0 6 * * *"}
        assert ir.vars == {"max_null_rate": 0.05}
        assert [job.job_id for job in ir.jobs] == ["表基础体检", "文档检查"]
        assert ir.jobs[0].steps[0].uses == "table/null-rate"
        assert ir.jobs[0].steps[0].severity == "warn"
        assert ir.jobs[1].needs == ("表基础体检",)

    def test_default_triggers_and_fallback_name(self) -> None:
        ir = compile_workflow(
            """
jobs:
  a:
    steps:
      - uses: document/links
""",
            fallback_name="兜底名称",
        )
        assert ir.name == "兜底名称"
        assert ir.triggers == {"manual": True}

    def test_ir_roundtrip(self) -> None:
        ir = compile_workflow(VALID_DSL)
        assert compile_workflow_from_dict(ir.to_dict()) == ir

    def test_topological_order(self) -> None:
        ir = compile_workflow(
            """
name: 排序
jobs:
  后置:
    needs: 前置
    steps:
      - uses: document/links
  前置:
    steps:
      - uses: document/links
  独立:
    steps:
      - uses: document/links
"""
        )
        assert [job.job_id for job in topological_jobs(ir.jobs)] == ["前置", "独立", "后置"]


def compile_workflow_from_dict(data: dict) -> object:
    """IR 快照还原（避免测试直接依赖内部构造细节）."""
    from cndb.plugins.pipeline.services.dsl.parse import WorkflowIR

    return WorkflowIR.from_dict(data)


class TestCompileErrors:
    """保存期校验：非法 DSL 必须抛 ``DslError`` / ``CheckError``."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("", "不能为空"),
            ("   \n  ", "不能为空"),
            ("- a\n- b\n", "顶层必须是映射"),
            ("name: [\n", "YAML 解析失败"),
            ("name: 名称\nunknown: 1\njobs: {a: {steps: [{uses: document/links}]}}\n", "未知键"),
            ("name: 名称\njobs: {}\n", "jobs 必须是非空映射"),
            ("jobs:\n  a:\n    steps:\n      - uses: document/links\n", "缺少 name"),
            ("name: 名称\njobs:\n  1:\n    steps:\n      - uses: document/links\n", "job 标识"),
            ("name: 名称\njobs:\n  a:\n    unknown: 1\n    steps:\n      - uses: document/links\n", "未知键"),
            ("name: 名称\njobs:\n  a:\n    needs: 999\n    steps:\n      - uses: document/links\n", "needs"),
            ("name: 名称\njobs:\n  a:\n    needs: b\n    steps:\n      - uses: document/links\n", "依赖不存在的 job"),
            (
                "name: 名称\njobs:\n  a:\n    needs: a\n    steps:\n      - uses: document/links\n",
                "不能依赖自身",
            ),
            (
                "name: 名称\njobs:\n  a:\n    needs: b\n    steps:\n      - uses: document/links\n"
                "  b:\n    needs: a\n    steps:\n      - uses: document/links\n",
                "存在环",
            ),
            ("name: 名称\njobs:\n  a:\n    steps: []\n", "非空列表"),
            ("name: 名称\njobs:\n  a:\n    steps: x\n", "非空列表"),
            ("name: 名称\njobs:\n  a:\n    steps:\n      - x\n", "必须是映射"),
            ("name: 名称\njobs:\n  a:\n    steps:\n      - with: {}\n", "uses 必须是"),
            (
                "name: 名称\njobs:\n  a:\n    steps:\n      - uses: table/null-rate\n        with: []\n",
                "with 必须是映射",
            ),
            (
                "name: 名称\njobs:\n  a:\n    steps:\n      - uses: table/null-rate\n"
                "        with: {table: 人员, max_rate: {a: 1}}\n",
                "不支持嵌套对象",
            ),
            (
                "name: 名称\njobs:\n  a:\n    steps:\n      - uses: document/links\n        severity: fatal\n",
                "severity",
            ),
            (
                "name: 名称\njobs:\n  a:\n    steps:\n      - uses: document/links\n        continue-on-error: 'yes'\n",
                "continue-on-error",
            ),
            (
                "name: 名称\nvars: {1bad: 1}\njobs:\n  a:\n    steps:\n      - uses: document/links\n",
                "vars 键",
            ),
            (
                "name: 名称\nvars: {a: [1]}\njobs:\n  a:\n    steps:\n      - uses: document/links\n",
                "vars.a",
            ),
        ],
    )
    def test_invalid_content(self, content: str, expected: str) -> None:
        with pytest.raises(DslError) as exc:
            compile_workflow(content)
        assert expected in exc.value.detail

    def test_name_too_long(self) -> None:
        with pytest.raises(DslError):
            compile_workflow(f"name: {'a' * (MAX_NAME_LENGTH + 1)}\njobs: {{a: {{steps: [{{uses: document/links}}]}}}}")

    @pytest.mark.parametrize(
        "on_block",
        [
            "on: manual\n",
            "on: {unknown: 1}\n",
            "on: {manual: 'yes'}\n",
            "on: {events: [1]}\n",
            "on: {schedule: '0 6 * *'}\n",
            "on: {schedule: 123}\n",
        ],
    )
    def test_invalid_triggers(self, on_block: str) -> None:
        content = f"name: 名称\n{on_block}jobs:\n  a:\n    steps:\n      - uses: document/links\n"
        with pytest.raises(DslError):
            compile_workflow(content)

    def test_invalid_vars_expression(self) -> None:
        with pytest.raises(DslError):
            compile_workflow(
                "name: 名称\nvars: {a: '${{ bad( }}'}\njobs:\n  a:\n    steps:\n      - uses: document/links\n"
            )

    def test_if_not_expression(self) -> None:
        with pytest.raises(DslError):
            compile_workflow("name: 名称\njobs:\n  a:\n    if: 'true'\n    steps:\n      - uses: document/links\n")

    def test_if_binary_expression(self) -> None:
        with pytest.raises(DslError):
            compile_workflow(
                "name: 名称\njobs:\n  a:\n    if: '${{ 1 + 1 }}'\n    steps:\n      - uses: document/links\n"
            )


class TestCheckParams:
    """``uses`` / ``with`` 的保存期 schema 校验."""

    def _dsl(self, uses: str, params: str) -> str:
        return f"name: 名称\njobs:\n  a:\n    steps:\n      - uses: {uses}\n        with: {params}\n"

    def test_unknown_action(self) -> None:
        with pytest.raises(CheckError) as exc:
            compile_workflow(self._dsl("unknown/action", "{}"))
        assert "未知检查动作" in exc.value.detail

    def test_unknown_param(self) -> None:
        with pytest.raises(CheckError) as exc:
            compile_workflow(self._dsl("table/null-rate", "{table: 人员, foo: 1}"))
        assert "不支持参数" in exc.value.detail

    @pytest.mark.parametrize(
        ("uses", "params", "expected"),
        [
            ("table/null-rate", "{table: 人员, max_rate: abc}", "类型不匹配"),
            ("table/null-rate", "{table: 人员, max_rate: null}", "类型不匹配"),
            ("table/null-rate", "{table: 人员, fields: 1}", "类型不匹配"),
            ("table/duplicates", "{table: 人员, fields: [姓名], ignore_case: 'yes'}", "类型不匹配"),
            ("table/duplicates", "{table: 人员}", "缺少必填参数"),
        ],
    )
    def test_static_type_mismatch(self, uses: str, params: str, expected: str) -> None:
        with pytest.raises(CheckError) as exc:
            compile_workflow(self._dsl(uses, params))
        assert expected in exc.value.detail

    def test_expression_value_skips_static_check(self) -> None:
        ir = compile_workflow(
            "name: 名称\nvars: {rate: 0.01}\njobs:\n  a:\n    steps:\n      - uses: table/null-rate\n"
            "        with: {table: 人员, max_rate: '${{ vars.rate }}'}\n"
        )
        assert ir.jobs[0].steps[0].params["max_rate"] == "${{ vars.rate }}"

    def test_list_expression_params(self) -> None:
        ir = compile_workflow(
            "name: 名称\njobs:\n  a:\n    steps:\n      - uses: document/broken-refs\n"
            "        with: {scopes: ['${{ vars.scope }}', chart]}\n"
        )
        assert ir.jobs[0].steps[0].params["scopes"] == ["${{ vars.scope }}", "chart"]

    def test_continue_on_error_and_severity(self) -> None:
        ir = compile_workflow(
            "name: 名称\njobs:\n  a:\n    steps:\n      - uses: document/links\n"
            "        severity: error\n        continue-on-error: true\n"
        )
        step = ir.jobs[0].steps[0]
        assert step.severity == "error"
        assert step.continue_on_error is True


class TestExpressions:
    """白名单表达式：字面量 / 变量 / 运算符 / 函数 / 错误路径."""

    def test_is_expression(self) -> None:
        assert is_expression("${{ vars.x }}")
        assert not is_expression("vars.x")
        assert not is_expression(123)
        assert not is_expression("${{ vars.x }} trailing")

    def test_literals_and_operators(self) -> None:
        assert evaluate_expression("${{ 1 }}", {}) == 1
        assert evaluate_expression("${{ 1.5 }}", {}) == 1.5
        assert evaluate_expression("${{ true }}", {}) is True
        assert evaluate_expression("${{ null }}", {}) is None
        assert evaluate_expression("${{ !false }}", {}) is True
        assert evaluate_expression("${{ (1 < 2) && (3 >= 2) }}", {}) is True
        assert evaluate_expression("${{ 1 == 1 || 2 == 3 }}", {}) is True
        assert evaluate_expression("${{ 2 != 1 }}", {}) is True
        assert evaluate_expression("${{ 1 <= 1 }}", {}) is True

    def test_string_escape(self) -> None:
        assert evaluate_expression(r"${{ 'it\'s' }}", {}) == "it's"

    def test_variable_path_and_chinese_identifiers(self) -> None:
        context = {
            "vars": {"max": 0.05},
            "on": {"event": "record.updated"},
            "jobs": {"表基础体检": {"conclusion": "success"}},
        }
        assert evaluate_expression("${{ vars.max }}", context) == 0.05
        assert evaluate_expression("${{ on.event }}", context) == "record.updated"
        assert evaluate_expression("${{ jobs.表基础体检.conclusion }}", context) == "success"

    def test_functions(self) -> None:
        assert evaluate_expression("${{ len('abc') }}", {}) == 3
        assert evaluate_expression("${{ contains('abc', 'b') }}", {}) is True
        assert evaluate_expression("${{ startswith('abc', 'ab') }}", {}) is True
        assert evaluate_expression("${{ endswith('abc', 'bc') }}", {}) is True
        assert evaluate_expression("${{ to_number('1.5') }}", {}) == 1.5

    def test_unknown_variable(self) -> None:
        with pytest.raises(ExpressionEvalError):
            evaluate_expression("${{ vars.missing }}", {"vars": {}})

    def test_compare_type_mismatch(self) -> None:
        with pytest.raises(ExpressionEvalError):
            evaluate_expression("${{ 1 < 'a' }}", {})

    @pytest.mark.parametrize(
        "source",
        [
            "${{ len(1) }}",
            "${{ contains(1, 'a') }}",
            "${{ to_number('abc') }}",
        ],
    )
    def test_function_type_errors(self, source: str) -> None:
        with pytest.raises(ExpressionEvalError):
            evaluate_expression(source, {})

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("${{ }}", "不能为空"),
            ("${{ a + b }}", "无法识别"),
            ("${{ a == }}", "内容不完整"),
            ("${{ len('abc' }}", "缺少右括号"),
            ("${{ a == b c }}", "多余内容"),
            ("${{ sha256(a) }}", "不支持的函数"),
            ("${{ len(a, b) }}", "参数个数"),
            ("${{ (a }}", "缺少右括号"),
        ],
    )
    def test_parse_errors(self, source: str, expected: str) -> None:
        with pytest.raises(DslError) as exc:
            parse_expression(source)
        assert expected in exc.value.detail

    def test_injection_is_literal_not_code(self) -> None:
        """注入串只会作为字符串字面量比较，不触达 Python 运行时."""
        payload = "__import__('os').system('x')"
        assert evaluate_expression(f'${{{{ "{payload}" }}}}', {}) == payload
