"""结构 DSL 语法（ADR 0079 D2 / ADR 0086 D2-D4）：param / module / use / constraint / 图元 / 变换 / 布尔.

递归下降解析器：token 流 → AST（``nodes.Program``）；不做任何求值。
嵌套深度在解析期判定（I6）；param / module 仅允许出现在顶层。
"""

from __future__ import annotations

from cndb.plugins.design.services.dsl.lexer import (
    EOF,
    IDENT,
    NUMBER,
    STRING,
    DslSyntaxError,
    Token,
    tokenize,
)
from cndb.plugins.design.services.dsl.limits import MAX_NESTING_DEPTH
from cndb.plugins.design.services.dsl.nodes import (
    BinOp,
    BooleanCall,
    ConstraintDecl,
    ConstraintRef,
    Expr,
    FuncCall,
    Instance,
    ModuleCall,
    ModuleDecl,
    ModuleParam,
    Name,
    Num,
    ParamDecl,
    PrimitiveCall,
    Program,
    ProgramItem,
    SystemDecl,
    TransformCall,
    UnaryOp,
    UseCall,
    Vector,
)

#: 语句关键字（不能作图元 / 模块名）
KEYWORD_PARAM = "param"
KEYWORD_MODULE = "module"
#: 系统装配声明关键字（ADR 0084 D1：顶层根、无参数表、不可实例化）
KEYWORD_SYSTEM = "system"
#: 分文件引用关键字（ADR 0086 D2）
KEYWORD_USE = "use"
#: 实例标签关键字（ADR 0086 D4）
KEYWORD_AS = "as"
#: 装配约束关键字（ADR 0086 D4）
KEYWORD_CONSTRAINT = "constraint"
#: 约束类型（MVP 五类，ADR 0086 D4）
CONSTRAINT_TYPES = ("fixed", "coincident", "concentric", "distance", "angle")
#: 约束引用端的默认命名基准（ADR 0086 D4）
CONSTRAINT_ANCHORS = ("origin", "x", "y", "z")
#: 布尔块关键字
BOOLEANS = ("union", "difference", "intersection")
#: 变换关键字
TRANSFORMS = ("translate", "rotate", "scale", "mirror")
#: 图元（P0 固定六种，D2）
PRIMITIVES = ("box", "cyl", "sphere", "cone", "torus", "tube")

#: 表达式二元运算优先级（低 → 高）；同级左结合
_BIN_PRIORITIES: dict[str, int] = {
    "+": 1,
    "-": 1,
    "*": 2,
    "/": 2,
    "%": 2,
}

#: 求值白名单函数（语法层只按名放行，元数校验在求值层）
_FUNCTION_NAMES = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan2",
        "sqrt",
        "abs",
        "min",
        "max",
        "pow",
        "floor",
        "ceil",
        "round",
    }
)


class Parser:
    """递归下降解析器：``parse_program()`` 是唯一入口."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # ── token 辅助 ───────────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        idx = min(self._pos + offset, len(self._tokens) - 1)
        return self._tokens[idx]

    def _next(self) -> Token:
        token = self._peek()
        if token.kind != EOF:  # pragma: no branch - EOF 不推进位置（防越界）
            self._pos += 1
        return token

    def _expect(self, kind: str, what: str) -> Token:
        token = self._peek()
        if token.kind != kind:
            raise DslSyntaxError(f"应为{what}，实际是 {self._describe(token)}", token.line, token.col)
        return self._next()

    @staticmethod
    def _describe(token: Token) -> str:
        if token.kind == EOF:
            return "文件结尾"
        if token.kind in (IDENT, NUMBER):
            return f"'{token.value}'"
        return f"'{token.value}'"

    def _expect_ident(self, what: str) -> Token:
        token = self._peek()
        if token.kind != IDENT:
            raise DslSyntaxError(f"应为{what}，实际是 {self._describe(token)}", token.line, token.col)
        return self._next()

    @staticmethod
    def _is_keyword(value: str) -> bool:
        return (
            value
            in (
                KEYWORD_PARAM,
                KEYWORD_MODULE,
                KEYWORD_SYSTEM,
                KEYWORD_USE,
                KEYWORD_AS,
                KEYWORD_CONSTRAINT,
            )
            or value in BOOLEANS
            or value in TRANSFORMS
        )

    # ── 顶层 ─────────────────────────────────────────────

    def parse_program(self) -> Program:
        """解析整个编译单元：param / module / system / constraint 声明与顶层实例（任意顺序）."""
        params: list[ParamDecl] = []
        modules: list[ModuleDecl] = []
        systems: list[SystemDecl] = []
        instances: list[Instance] = []
        constraints: list[ConstraintDecl] = []
        items: list[ProgramItem] = []

        while self._peek().kind != EOF:
            token = self._peek()
            if token.kind == IDENT and token.value == KEYWORD_PARAM:
                decl = self._parse_param_decl()
                params.append(decl)
                items.append(decl)
            elif token.kind == IDENT and token.value == KEYWORD_MODULE:
                module = self._parse_module_decl()
                modules.append(module)
                items.append(module)
            elif token.kind == IDENT and token.value == KEYWORD_SYSTEM:
                system = self._parse_system_decl()
                systems.append(system)
                items.append(system)
            elif token.kind == IDENT and token.value == KEYWORD_CONSTRAINT:
                constraint = self._parse_constraint_decl()
                constraints.append(constraint)
                items.append(constraint)
            else:
                instance = self._parse_instance(depth=1)
                instances.append(instance)
                items.append(instance)
        return Program(
            params=tuple(params),
            modules=tuple(modules),
            instances=tuple(instances),
            systems=tuple(systems),
            constraints=tuple(constraints),
            items=tuple(items),
        )

    def _parse_param_decl(self) -> ParamDecl:
        start = self._expect_ident("param 关键字")
        name = self._expect_ident("参数名")
        self._expect("=", "=")
        value = self._parse_expr()
        return ParamDecl(name=name.value, value=value, line=start.line, col=start.col)

    def _parse_module_decl(self) -> ModuleDecl:
        start = self._expect_ident("module 关键字")
        name = self._expect_ident("模块名")
        if name.value in PRIMITIVES or self._is_keyword(name.value):
            raise DslSyntaxError(f"模块名 '{name.value}' 与关键字 / 图元重名", name.line, name.col)
        self._expect("(", "(")
        params: list[ModuleParam] = []
        if self._peek().kind != ")":
            while True:
                pname = self._expect_ident("模块形参名")
                default: Expr | None = None
                if self._peek().kind == "=":
                    self._next()
                    default = self._parse_expr()
                params.append(ModuleParam(name=pname.value, default=default))
                if self._peek().kind != ",":
                    break
                self._next()
        self._expect(")", ")")
        body = self._parse_block_instances(depth=2, what="模块体")
        return ModuleDecl(name=name.value, params=tuple(params), body=body, line=start.line, col=start.col)

    def _parse_system_decl(self) -> SystemDecl:
        """系统装配声明：``system 名 { instance* constraint* }``（ADR 0084 D3 / ADR 0086 D4）."""
        start = self._expect_ident("system 关键字")
        name = self._expect_ident("系统名")
        if name.value in PRIMITIVES or self._is_keyword(name.value):
            raise DslSyntaxError(f"系统名 '{name.value}' 与关键字 / 图元重名", name.line, name.col)
        if self._peek().kind == "(":
            token = self._peek()
            raise DslSyntaxError("system 不接受参数表（系统是单例根，可配置性请用顶层 param）", token.line, token.col)
        if MAX_NESTING_DEPTH < 2:
            token = self._peek()
            raise DslSyntaxError(f"嵌套深度超过上限 {MAX_NESTING_DEPTH}", token.line, token.col)
        self._expect("{", "系统体开块 {")
        body: list[Instance | ConstraintDecl] = []
        while self._peek().kind != "}":
            if self._peek().kind == EOF:
                token = self._peek()
                raise DslSyntaxError("系统体未闭合（缺少 }）", token.line, token.col)
            token = self._peek()
            if token.kind == IDENT and token.value == KEYWORD_CONSTRAINT:
                body.append(self._parse_constraint_decl())
                continue
            body.append(self._parse_instance(depth=2))
        self._expect("}", "}")
        return SystemDecl(name=name.value, body=tuple(body), line=start.line, col=start.col)

    def _parse_constraint_decl(self) -> ConstraintDecl:
        """约束声明：``constraint <id> <type>(key = 值, …)``（ADR 0086 D4）.

        ``a`` / ``b`` 必须为 ``标签.基准`` 引用；``offset`` / ``value`` 为表达式。
        """
        start = self._expect_ident("constraint 关键字")
        id_token = self._expect_ident("约束 id")
        kind_token = self._expect_ident("约束类型")
        if kind_token.value not in CONSTRAINT_TYPES:
            raise DslSyntaxError(
                f"未知约束类型 '{kind_token.value}'（可用：{'/'.join(CONSTRAINT_TYPES)}）",
                kind_token.line,
                kind_token.col,
            )
        self._expect("(", "(")
        refs: dict[str, ConstraintRef] = {}
        values: dict[str, Expr] = {}
        if self._peek().kind != ")":
            while True:
                arg_name = self._expect_ident("约束参数名")
                self._expect("=", "=")
                if arg_name.value in refs or arg_name.value in values:
                    raise DslSyntaxError(f"约束参数 '{arg_name.value}' 重复", arg_name.line, arg_name.col)
                if arg_name.value in ("a", "b"):
                    refs[arg_name.value] = self._parse_constraint_ref()
                else:
                    values[arg_name.value] = self._parse_expr()
                if self._peek().kind != ",":
                    break
                self._next()
        self._expect(")", ")")
        return ConstraintDecl(
            id=id_token.value,
            kind=kind_token.value,
            refs=refs,
            values=values,
            line=start.line,
            col=start.col,
        )

    def _parse_constraint_ref(self) -> ConstraintRef:
        """解析 ``标签.基准``：基准取值 origin / x / y / z."""
        label = self._expect_ident("实例标签")
        self._expect(".", "约束引用中的 .")
        anchor = self._expect_ident("命名基准（origin / x / y / z）")
        if anchor.value not in CONSTRAINT_ANCHORS:
            raise DslSyntaxError(
                f"未知命名基准 '{anchor.value}'（可用：{'/'.join(CONSTRAINT_ANCHORS)}）",
                anchor.line,
                anchor.col,
            )
        return ConstraintRef(label=label.value, anchor=anchor.value, line=label.line, col=label.col)

    # ── 实例 ─────────────────────────────────────────────

    def _parse_block_instances(self, depth: int, what: str) -> tuple[Instance, ...]:
        """解析 ``{ instance* }`` 块（模块体 / 布尔块共用）."""
        if depth > MAX_NESTING_DEPTH:
            token = self._peek()
            raise DslSyntaxError(f"嵌套深度超过上限 {MAX_NESTING_DEPTH}", token.line, token.col)
        self._expect("{", what + "开块 {")
        instances: list[Instance] = []
        while self._peek().kind != "}":
            if self._peek().kind == EOF:
                token = self._peek()
                raise DslSyntaxError(f"{what}未闭合（缺少 }}）", token.line, token.col)
            instances.append(self._parse_instance(depth=depth + 1))
        self._expect("}", "}")
        return tuple(instances)

    def _parse_instance(self, depth: int) -> Instance:
        """解析一个实例：图元 / 变换 / 布尔 / 模块调用."""
        if depth > MAX_NESTING_DEPTH:
            token = self._peek()
            raise DslSyntaxError(f"嵌套深度超过上限 {MAX_NESTING_DEPTH}", token.line, token.col)
        head = self._peek()
        if head.kind != IDENT:
            raise DslSyntaxError(
                f"应为实例（图元 / 变换 / 布尔 / 模块调用），实际是 {self._describe(head)}", head.line, head.col
            )
        if head.value in PRIMITIVES:
            return self._parse_primitive_call()
        if head.value == KEYWORD_USE:
            return self._parse_use_call()
        if head.value in TRANSFORMS:
            return self._parse_transform_call(depth)
        if head.value in BOOLEANS:
            kind = self._next()
            children = self._parse_block_instances(depth=depth + 1, what=kind.value + " 块")
            if not children:
                raise DslSyntaxError(f"{kind.value} 块不能为空（至少一个子实例）", kind.line, kind.col)
            return BooleanCall(kind=head.value, children=children, line=kind.line, col=kind.col)
        if self._is_keyword(head.value):
            raise DslSyntaxError(f"关键字 '{head.value}' 不能作为实例", head.line, head.col)
        return self._parse_module_call()

    def _parse_primitive_call(self) -> PrimitiveCall:
        """图元调用：``name(命名参数...)``，仅命名参数."""
        head = self._next()
        self._expect("(", "(")
        args: dict[str, Expr] = {}
        if self._peek().kind != ")":
            while True:
                if self._peek().kind != IDENT:
                    token = self._peek()
                    raise DslSyntaxError(
                        f"图元参数须为「名 = 值」形式，实际是 {self._describe(token)}",
                        token.line,
                        token.col,
                    )
                if self._peek(1).kind != "=":
                    token = self._peek()
                    raise DslSyntaxError(
                        f"图元参数须为「名 = 值」形式，'{token.value}' 后应为 =",
                        token.line,
                        token.col,
                    )
                arg_name = self._next()
                self._expect("=", "=")
                if arg_name.value in args:
                    raise DslSyntaxError(f"图元参数 '{arg_name.value}' 重复", arg_name.line, arg_name.col)
                args[arg_name.value] = self._parse_expr()
                if self._peek().kind != ",":
                    break
                self._next()
        self._expect(")", ")")
        return PrimitiveCall(name=head.value, args=args, line=head.line, col=head.col)

    def _parse_transform_call(self, depth: int) -> TransformCall:
        """变换包裹：``kind([x,y,z]) 实例`` 或 ``kind([x,y,z]) { 实例* }``."""
        head = self._next()
        self._expect("(", "(")
        vector = self._parse_vector()
        self._expect(")", ")")
        if self._peek().kind == "{":
            children = self._parse_block_instances(depth=depth + 1, what=head.value + " 块")
            if not children:
                raise DslSyntaxError(f"{head.value} 块不能为空（至少一个子实例）", head.line, head.col)
        else:
            children = (self._parse_instance(depth=depth + 1),)
        return TransformCall(kind=head.value, vector=vector, children=children, line=head.line, col=head.col)

    def _parse_vector(self) -> tuple[Expr, Expr, Expr]:
        """解析 ``[expr, expr, expr]`` 三维向量."""
        self._expect("[", "向量开括号 [")
        x = self._parse_expr()
        self._expect(",", ",")
        y = self._parse_expr()
        self._expect(",", ",")
        z = self._parse_expr()
        self._expect("]", "向量闭括号 ]")
        return (x, y, z)

    def _parse_use_call(self) -> UseCall:
        """分文件引用：``use "file_key"(参数...) [as 标签]``（ADR 0086 D2）."""
        head = self._next()
        key = self._peek()
        if key.kind != STRING:
            raise DslSyntaxError(
                f'use 后应为文件 key 字符串（如 "wheel"），实际是 {self._describe(key)}', key.line, key.col
            )
        self._next()
        if not key.value:
            raise DslSyntaxError("文件 key 不能为空", key.line, key.col)
        # 参数表可选：``use "wheel"`` 与 ``use "wheel"(d = 30)`` 均合法
        positional: list[Expr] = []
        named: dict[str, Expr] = {}
        if self._peek().kind == "(":
            self._next()  # 消费开括号
            positional, named = self._parse_call_args()
        label = self._parse_optional_label()
        return UseCall(
            file_key=key.value,
            positional=tuple(positional),
            named=named,
            line=head.line,
            col=head.col,
            label=label,
        )

    def _parse_optional_label(self) -> str | None:
        """可选 ``as 标签``：仅模块 / use 实例可带（ADR 0086 D4）."""
        token = self._peek()
        if token.kind != IDENT or token.value != KEYWORD_AS:
            return None
        self._next()
        label = self._expect_ident("实例标签")
        if label.value in PRIMITIVES or self._is_keyword(label.value):
            raise DslSyntaxError(f"实例标签 '{label.value}' 与关键字 / 图元重名", label.line, label.col)
        return label.value

    def _parse_module_call(self) -> ModuleCall:
        """模块实例化：``name(位置参数..., 命名参数...) [as 标签]``（命名须在位置之后）."""
        head = self._next()
        self._expect("(", "(")
        positional, named = self._parse_call_args()
        label = self._parse_optional_label()
        return ModuleCall(
            name=head.value,
            positional=tuple(positional),
            named=named,
            line=head.line,
            col=head.col,
            label=label,
        )

    def _parse_call_args(self) -> tuple[list[Expr], dict[str, Expr]]:
        """解析 ``(位置参数..., 命名参数...)``（消费收尾 ``)``；命名须在位置之后）."""
        positional: list[Expr] = []
        named: dict[str, Expr] = {}
        if self._peek().kind != ")":
            while True:
                # 命名参数模式：IDENT '='
                if self._peek().kind == IDENT and self._peek(1).kind == "=":
                    arg_name = self._next()
                    self._expect("=", "=")
                    if arg_name.value in named:
                        raise DslSyntaxError(f"命名参数 '{arg_name.value}' 重复", arg_name.line, arg_name.col)
                    named[arg_name.value] = self._parse_expr()
                else:
                    if named:
                        token = self._peek()
                        raise DslSyntaxError("位置参数不能出现在命名参数之后", token.line, token.col)
                    positional.append(self._parse_expr())
                if self._peek().kind != ",":
                    break
                self._next()
        self._expect(")", ")")
        return positional, named

    # ── 表达式 ───────────────────────────────────────────

    def _parse_expr(self) -> Expr:
        """解析表达式入口：一元负号 → 加减乘除取模（左结合）."""
        return self._parse_binary(min_priority=1)

    def _parse_binary(self, min_priority: int) -> Expr:
        left = self._parse_unary()
        while True:
            token = self._peek()
            priority = _BIN_PRIORITIES.get(token.value, 0) if token.kind != EOF else 0
            if priority < min_priority:
                return left
            op = self._next()
            # 右侧按更高优先级递归：同级左结合（1+2*3 = 1+(2*3)）
            right = self._parse_binary(priority + 1)
            left = BinOp(op=op.value, left=left, right=right, line=op.line, col=op.col)

    def _parse_unary(self) -> Expr:
        """一元负号（可叠加：--1 合法）."""
        token = self._peek()
        if token.kind == "-" and token.value == "-":
            self._next()
            return UnaryOp(op="-", operand=self._parse_unary(), line=token.line, col=token.col)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        """数值 / 标识符 / 括号 / 函数调用."""
        token = self._peek()
        if token.kind == NUMBER:
            self._next()
            return Num(value=float(token.value), line=token.line, col=token.col)
        if token.kind == IDENT:
            self._next()
            if self._peek().kind == "(":
                if token.value not in _FUNCTION_NAMES:
                    raise DslSyntaxError(
                        f"未知函数 '{token.value}'（可用：{'/'.join(sorted(_FUNCTION_NAMES))}）",
                        token.line,
                        token.col,
                    )
                self._next()  # 消费 "("
                args: list[Expr] = []
                if self._peek().kind != ")":
                    while True:
                        args.append(self._parse_expr())
                        if self._peek().kind != ",":
                            break
                        self._next()
                self._expect(")", ")")
                return FuncCall(name=token.value, args=tuple(args), line=token.line, col=token.col)
            if self._is_keyword(token.value):
                raise DslSyntaxError(f"关键字 '{token.value}' 不能作为标识符引用", token.line, token.col)
            return Name(name=token.value, line=token.line, col=token.col)
        if token.kind == "(":
            self._next()
            inner = self._parse_expr()
            self._expect(")", ")")
            return inner
        if token.kind == "[":
            # 向量字面量：仅在图元 size 参数位置有语义，其余场景由求值层拒绝
            return Vector(items=self._parse_vector(), line=token.line, col=token.col)
        raise DslSyntaxError(f"应为表达式，实际是 {self._describe(token)}", token.line, token.col)


def parse_program(content: str) -> Program:
    """解析 DSL 原文为 Program（词法 + 语法，无求值）."""
    return Parser(tokenize(content)).parse_program()


__all__ = [
    "BOOLEANS",
    "CONSTRAINT_ANCHORS",
    "CONSTRAINT_TYPES",
    "KEYWORD_AS",
    "KEYWORD_CONSTRAINT",
    "KEYWORD_MODULE",
    "KEYWORD_PARAM",
    "KEYWORD_SYSTEM",
    "KEYWORD_USE",
    "PRIMITIVES",
    "TRANSFORMS",
    "DslSyntaxError",
    "Parser",
    "parse_program",
]
