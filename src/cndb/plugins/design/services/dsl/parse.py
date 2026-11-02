"""结构 DSL 语法（ADR 0079 D2）：param / module / 图元 / 变换 / 布尔.

递归下降解析器：token 流 → AST（``nodes.Program``）；不做任何求值。
嵌套深度在解析期判定（I6）；param / module 仅允许出现在顶层。
"""

from __future__ import annotations

from cndb.plugins.design.services.dsl.lexer import EOF, IDENT, NUMBER, DslSyntaxError, Token, tokenize
from cndb.plugins.design.services.dsl.limits import MAX_NESTING_DEPTH
from cndb.plugins.design.services.dsl.nodes import (
    BinOp,
    BooleanCall,
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
    Vector,
)

#: 语句关键字（不能作图元 / 模块名）
KEYWORD_PARAM = "param"
KEYWORD_MODULE = "module"
#: 系统装配声明关键字（ADR 0084 D1：顶层根、无参数表、不可实例化）
KEYWORD_SYSTEM = "system"
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
        return value in (KEYWORD_PARAM, KEYWORD_MODULE, KEYWORD_SYSTEM) or value in BOOLEANS or value in TRANSFORMS

    # ── 顶层 ─────────────────────────────────────────────

    def parse_program(self) -> Program:
        """解析整个编译单元：param / module / system 声明与顶层实例（任意顺序）."""
        params: list[ParamDecl] = []
        modules: list[ModuleDecl] = []
        systems: list[SystemDecl] = []
        instances: list[Instance] = []
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
            else:
                instance = self._parse_instance(depth=1)
                instances.append(instance)
                items.append(instance)
        return Program(
            params=tuple(params),
            modules=tuple(modules),
            instances=tuple(instances),
            systems=tuple(systems),
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
        """系统装配声明：``system 名 { instance* }``（顶层根、无参数表，ADR 0084 D3）."""
        start = self._expect_ident("system 关键字")
        name = self._expect_ident("系统名")
        if name.value in PRIMITIVES or self._is_keyword(name.value):
            raise DslSyntaxError(f"系统名 '{name.value}' 与关键字 / 图元重名", name.line, name.col)
        if self._peek().kind == "(":
            token = self._peek()
            raise DslSyntaxError("system 不接受参数表（系统是单例根，可配置性请用顶层 param）", token.line, token.col)
        body = self._parse_block_instances(depth=2, what="系统体")
        return SystemDecl(name=name.value, body=body, line=start.line, col=start.col)

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

    def _parse_module_call(self) -> ModuleCall:
        """模块实例化：``name(位置参数..., 命名参数...)``（命名须在位置之后）."""
        head = self._next()
        self._expect("(", "(")
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
        return ModuleCall(name=head.value, positional=tuple(positional), named=named, line=head.line, col=head.col)

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
    "KEYWORD_MODULE",
    "KEYWORD_PARAM",
    "KEYWORD_SYSTEM",
    "PRIMITIVES",
    "TRANSFORMS",
    "DslSyntaxError",
    "Parser",
    "parse_program",
]
