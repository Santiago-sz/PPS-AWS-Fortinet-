"""
Validador estático de scripts de auditoría generados por LLM.

Contrato: validate(source: str, manifest: dict) -> ValidationResult.

Defensa por ALLOWLIST, no por denylist: se permite explícitamente un
subconjunto reducido de nodos AST, nombres y accesos a atributo; todo lo
demás se rechaza por defecto (fail closed), incluso construcciones que no
se conocían al escribir esta lista.

Orden de gates (ver design.md "Gate order"):
  1. ast.parse() — falla con failure_kind="syntax"
  2. Allowlist walk (nodos + nombres + atributos + caps estáticas) —
     failure_kind="allowlist"
  3. Contract check (cobertura completa de check_id) — failure_kind="contract",
     solo corre si el allowlist walk no encontró errores

Nota de diseño (CVE-2026-40158, hallazgo de sdd-explore): un validador que
solo mira `ast.Attribute.attr` para detectar dunders es evadible por
reflexión — `getattr(type, "__getattribute__")` hace viajar el string
peligroso como `ast.Constant`, no como `ast.Attribute`. Por eso la regla de
acceso a atributos acá es un ALLOWLIST de nombres de método exactos por
receptor (`fgt`: {get, endpoints}; `report`: {finding, note}), no un
denylist de "cualquier attr con __". Y `getattr`/`type` están además
denegados por nombre — dos capas independientes, no una sola.

`Try` se deniega deliberadamente para que un script generado no pueda
atrapar `SandboxBudgetExceeded` (design.md Decision #6).
"""

import ast
from dataclasses import dataclass, field

import fortigate_client

MAX_AST_NODES = 4000
MAX_NESTING = 3

# Nodos explícitamente prohibidos — mensajes de rechazo específicos y
# accionables (en vez de caer en el "no está en el allowlist" genérico).
_DENIED_NODE_TYPES: tuple[type, ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.ClassDef,
    ast.Lambda,
    ast.While,
    ast.Try,
    ast.Raise,
    ast.With,
    ast.AsyncWith,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.Starred,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
)
if hasattr(ast, "TryStar"):  # Python 3.11+
    _DENIED_NODE_TYPES = _DENIED_NODE_TYPES + (ast.TryStar,)

# Nodos permitidos — cualquier tipo de nodo que no esté acá NI en
# _DENIED_NODE_TYPES cae en el rechazo genérico "node_not_allowlisted".
_ALLOWED_NODE_TYPES: tuple[type, ...] = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Expr,
    ast.If,
    ast.IfExp,
    ast.For,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.comprehension,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Del,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.LShift,
    ast.RShift,
    ast.BitOr,
    ast.BitXor,
    ast.BitAnd,
    ast.MatMult,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.Invert,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Attribute,
    ast.keyword,
)

# Denegados por nombre — identificadores que jamás pueden aparecer como
# ast.Name, sin importar dónde (llamada, asignación, lo que sea).
_DENY_BY_NAME: frozenset[str] = frozenset(
    {
        "getattr",
        "setattr",
        "delattr",
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
        "dir",
        "type",
        "super",
        "__import__",
        "help",
        "breakpoint",
        "memoryview",
    }
)

# Único punto de verdad sobre qué método puede llamarse en cada capability.
_ALLOWED_METHODS: dict[str, frozenset[str]] = {
    "fgt": frozenset({"get", "endpoints"}),
    "report": frozenset({"finding", "note"}),
}

# Nodos que cuentan como un nivel de anidamiento para el cap de nesting.
_NESTING_NODE_TYPES = (ast.FunctionDef, ast.If, ast.For)


@dataclass(frozen=True)
class ValidationError:
    """Un rechazo puntual, siempre con un rule_id específico y accionable."""

    rule_id: str
    failure_kind: str  # "syntax" | "allowlist" | "contract"
    message: str
    line: int | None = None
    col: int | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[ValidationError, ...] = field(default_factory=tuple)


def _endpoint_catalog() -> frozenset[str]:
    return frozenset(label for _, label in fortigate_client.ENDPOINTS)


class _AllowlistVisitor(ast.NodeVisitor):
    """Camina el AST completo aplicando el allowlist + las caps estáticas.

    No usa `ast.walk()` a propósito: necesita trackear profundidad de
    anidamiento en el mismo recorrido (entrar/salir de FunctionDef/If/For).
    """

    def __init__(self, checks_by_id: dict[str, dict], endpoint_catalog: frozenset[str]):
        self.errors: list[ValidationError] = []
        self.node_count = 0
        self._depth = 0
        self._nesting_flagged = False
        self.checks_by_id = checks_by_id
        self.endpoint_catalog = endpoint_catalog
        self.referenced_check_ids: set[str] = set()

    def _add(self, rule_id: str, message: str, node: ast.AST | None = None) -> None:
        self.errors.append(
            ValidationError(
                rule_id=rule_id,
                failure_kind="allowlist",
                message=message,
                line=getattr(node, "lineno", None),
                col=getattr(node, "col_offset", None),
            )
        )

    def generic_visit(self, node: ast.AST) -> None:
        self.node_count += 1

        if isinstance(node, _DENIED_NODE_TYPES):
            node_name = type(node).__name__
            self._add(f"denied_node:{node_name}", f"'{node_name}' is not allowed", node)
            return  # no need to descend into a subtree we already reject

        if not isinstance(node, _ALLOWED_NODE_TYPES):
            node_name = type(node).__name__
            self._add(
                f"node_not_allowlisted:{node_name}",
                f"'{node_name}' is not in the AST allowlist",
                node,
            )
            return

        if isinstance(node, ast.Name):
            self._check_name(node)
        elif isinstance(node, ast.Attribute):
            self._check_attribute(node)
        elif isinstance(node, ast.Call):
            self._check_call(node)

        is_nesting_node = isinstance(node, _NESTING_NODE_TYPES)
        if is_nesting_node:
            self._depth += 1
            if self._depth > MAX_NESTING and not self._nesting_flagged:
                self._nesting_flagged = True
                self._add(
                    "max_nesting_exceeded",
                    f"nesting depth {self._depth} exceeds the cap of {MAX_NESTING}",
                    node,
                )

        super().generic_visit(node)

        if is_nesting_node:
            self._depth -= 1

    def _check_name(self, node: ast.Name) -> None:
        name = node.id
        if "__" in name:
            self._add("denied_name:dunder", f"identifier '{name}' contains '__'", node)
        elif name in _DENY_BY_NAME:
            self._add("denied_name:builtin", f"'{name}' is a denied builtin", node)

    def _check_attribute(self, node: ast.Attribute) -> None:
        if "__" in node.attr:
            self._add("denied_name:dunder", f"attribute '.{node.attr}' contains '__'", node)
            return

        receiver = node.value
        if isinstance(receiver, ast.Name) and receiver.id in _ALLOWED_METHODS:
            if node.attr not in _ALLOWED_METHODS[receiver.id]:
                self._add(
                    "attribute_not_allowlisted",
                    f"'{receiver.id}.{node.attr}' is not an allowlisted method",
                    node,
                )
            return

        self._add(
            "attribute_not_allowlisted",
            f"attribute access '.{node.attr}' is only allowed on fgt/report",
            node,
        )

    def _check_call(self, node: ast.Call) -> None:
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            return

        receiver, method = func.value.id, func.attr

        if receiver == "fgt" and method == "get":
            self._check_literal_string_arg(
                node, "endpoint_arg_not_literal", self._check_endpoint_literal
            )
        elif receiver == "report" and method in ("finding", "note"):
            self._check_literal_string_arg(
                node,
                "check_id_not_literal",
                lambda n, value: self._check_check_id_literal(
                    n, value, count_for_coverage=(method == "finding")
                ),
            )

    def _check_literal_string_arg(self, node: ast.Call, not_literal_rule: str, on_value) -> None:
        if not node.args or not (
            isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
        ):
            self._add(not_literal_rule, "argument 0 must be a string literal", node)
            return
        on_value(node, node.args[0].value)

    def _check_endpoint_literal(self, node: ast.Call, value: str) -> None:
        if value not in self.endpoint_catalog:
            self._add(
                "endpoint_not_in_catalog", f"'{value}' is not a known FortiGate endpoint", node
            )

    def _check_check_id_literal(self, node: ast.Call, value: str, count_for_coverage: bool) -> None:
        if count_for_coverage:
            self.referenced_check_ids.add(value)
        if value not in self.checks_by_id:
            self._add(
                "check_id_unknown", f"check_id '{value}' is not present in the manifest", node
            )


def _checks_by_id(manifest: dict | None) -> dict[str, dict]:
    checks = (manifest or {}).get("checks") or []
    return {c["check_id"]: c for c in checks if isinstance(c, dict) and c.get("check_id")}


def _contract_errors(
    manifest: dict | None, referenced_check_ids: set[str]
) -> list[ValidationError]:
    errors = []
    for check_id in _checks_by_id(manifest):
        if check_id not in referenced_check_ids:
            errors.append(
                ValidationError(
                    rule_id="check_id_coverage_incomplete",
                    failure_kind="contract",
                    message=(f"check_id '{check_id}' is never reported via report.finding()"),
                )
            )
    return errors


def validate(source: str, manifest: dict | None) -> ValidationResult:
    """Valida un script generado contra el allowlist AST + el manifest.

    Nunca ejecuta `source` — es puro análisis estático.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ValidationResult(
            valid=False,
            errors=(
                ValidationError(
                    rule_id="syntax_error",
                    failure_kind="syntax",
                    message=str(e),
                    line=e.lineno,
                    col=e.offset,
                ),
            ),
        )

    visitor = _AllowlistVisitor(_checks_by_id(manifest), _endpoint_catalog())
    visitor.visit(tree)

    if visitor.node_count > MAX_AST_NODES:
        visitor.errors.append(
            ValidationError(
                rule_id="max_nodes_exceeded",
                failure_kind="allowlist",
                message=(
                    f"script has {visitor.node_count} AST nodes, exceeds cap of {MAX_AST_NODES}"
                ),
            )
        )

    if visitor.errors:
        return ValidationResult(valid=False, errors=tuple(visitor.errors))

    contract_errors = _contract_errors(manifest, visitor.referenced_check_ids)
    if contract_errors:
        return ValidationResult(valid=False, errors=tuple(contract_errors))

    return ValidationResult(valid=True, errors=())
