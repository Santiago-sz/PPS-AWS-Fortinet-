"""
Uso del catálogo de campos de FortiOS en el generador.

`fortios_field_catalog.CATALOG` (archivo generado) lista, por clave de
endpoint, los nombres de campo observados en un equipo. Este módulo lo usa de
dos maneras, las dos del lado del generador:

  1. `prompt_section()` arma el texto que se agrega al system prompt de
     reduce: el catálogo como referencia de nombres de campo, con la versión
     de FortiOS de la que proviene y las reglas para el modelo.

  2. `find_unknown_field_references()` revisa un script ya aceptado por
     `script_validator` y devuelve los literales de texto usados como clave
     sobre datos del equipo que el catálogo no lista. `llm_client` lo usa
     como pista de corrección dentro del ciclo de reintento que ya existe.

La segunda NO es una compuerta. No rechaza ningún script, no reemplaza al
validador ni al sandbox y no decide el estado de ningún hallazgo: si un script
conserva un campo inexistente, se acepta igual y `toolkit` deja ese hallazgo
en `indeterminate` al ejecutar (decisión 12). El executor no importa este
módulo.

Heurística de detección (prefiere no avisar antes que señalar código válido):

  - Solo se mira `base["literal"]` en lectura. Una prueba de pertenencia
    (`"x" in d`) no se mira: el prompt enseña a usarla también para buscar
    texto dentro de un valor (`"https" in iface["allowaccess"]`).
  - `base` debe venir de `fgt.get("<endpoint>")`. El origen se sigue, sin
    orden de ejecución, por asignaciones, `for`, comprehensions, subíndices,
    parámetros y valores de retorno de las funciones del script. Sin origen
    conocido no se informa.
  - Un diccionario que arma el script (`{...}`, comprehension de diccionario,
    `dict(...)`) no tiene origen, aunque copie valores del equipo; tampoco una
    variable a la que el script le asigna claves (`d["x"] = ...`).
  - Si el valor puede venir de un endpoint sin verificar, ausente del catálogo
    o con la lista de campos truncada, no se informa.
  - El literal debe tener forma de nombre de campo de esquema. El diagnóstico
    no lista los nombres que no la tienen, así que no se pueden juzgar.
  - El nombre se busca entre los campos del endpoint y sus campos anidados,
    sin distinguir el nivel.

Lo que no detecta: claves pasadas por variable (`data[key]`), campos
consultados solo con `in`, y datos que pasan por un diccionario del script.
"""

import ast
import re

import fortios_field_catalog

STATUS_OBSERVED = "observed"

# Cantidad máxima de referencias que se copian al prompt de corrección, al
# evento de observabilidad y al manifest. El total se informa siempre.
MAX_LISTED_REFERENCES = 20

# Misma forma que usa el diagnóstico para decidir qué nombres lista.
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_\-]{0,63}")

_SHAPE_LABELS = {"object": "objeto", "list": "lista"}

_PROMPT_HEADER = """
CATALOGO DE CAMPOS POR ENDPOINT -- referencia autoritativa de nombres de campo.
Son los nombres de campo observados en las respuestas de un FortiGate con
FortiOS {version} (build {build}). El catalogo lista solo nombres, no valores.

Como leerlo:
  - `endpoint (objeto): a, b` -- `fgt.get("endpoint")` devuelve un dict con
    esos campos.
  - `endpoint (lista): a, b` -- devuelve una lista de dict; cada elemento
    tiene esos campos.
  - `campo{{x, y}}` -- el valor de `campo` es un dict, o una lista de dict, con
    los subcampos `x`, `y`.
  - `endpoint (sin verificar)` -- sus campos no se pudieron observar.

Reglas sobre nombres de campo (el script NO se rechaza por esto, pero un
campo inexistente deja el control sin veredicto):
  - Para leer un campo usa SOLO un nombre listado para ese endpoint, escrito
    exactamente igual. Antes de escribir cada lectura busca el nombre en la
    lista. No uses nombres de la CLI, de otra version de FortiOS ni de memoria
    si no figuran en la lista.
  - Si el control necesita un dato, busca primero un campo listado que lo
    exprese, en ese endpoint o en otro del catalogo.
  - Si ningun campo listado expresa ese dato, NO adivines ni inventes un
    nombre: no leas ese campo y registra el control con
    `report.finding(check_id, "indeterminate", evidencia)`, donde la evidencia
    diga que dato falta y en que endpoint se busco.
  - Un endpoint "sin verificar" se puede usar igual. Lee cada campo con la
    forma `d["clave"] if "clave" in d else None` y no supongas que existe.

Campos por endpoint:
"""


def _field_text(name: str, children: list[str]) -> str:
    return name + "{" + ", ".join(children) + "}" if children else name


def prompt_section(catalog: dict | None = None) -> str:
    """Texto del catálogo para el system prompt de reduce.

    Depende solo del catálogo: mismo catálogo, mismo texto, de modo que el
    system prompt siga siendo un prefijo estable para el caché de prompts.
    """
    catalog = fortios_field_catalog.CATALOG if catalog is None else catalog
    lines = [
        _PROMPT_HEADER.format(
            version=catalog["fortios_version"], build=catalog["fortios_build"]
        ).rstrip("\n")
    ]
    for key in sorted(catalog["endpoints"]):
        entry = catalog["endpoints"][key]
        if entry["status"] != STATUS_OBSERVED or not entry["fields"]:
            lines.append(f"- {key} (sin verificar)")
            continue
        fields = ", ".join(_field_text(name, entry["fields"][name]) for name in entry["fields"])
        lines.append(f"- {key} ({_SHAPE_LABELS.get(entry['shape'], 'objeto')}): {fields}")
    return "\n".join(lines) + "\n"


def _known_names(entry: dict) -> frozenset[str] | None:
    """Nombres aceptados para un endpoint, o None si no se lo puede juzgar."""
    if entry.get("status") != STATUS_OBSERVED or entry.get("fields_truncated"):
        return None
    fields = entry.get("fields") or {}
    if not fields:
        return None
    names = set(fields)
    for children in fields.values():
        names.update(children)
    return frozenset(names)


def _endpoint_of(node: ast.AST) -> str | None:
    """Clave de endpoint si `node` es `fgt.get("<literal>")`."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "fgt"
        and func.attr == "get"
    ):
        return None
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _builds_own_dict(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict | ast.DictComp):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _target_names(element)]
    return []


class _Origins:
    """De qué endpoints puede venir cada valor de un script.

    Análisis sin orden de ejecución: junta los hechos del script (asignaciones,
    bucles, llamadas, retornos) y los propaga hasta que no cambian. Aproxima
    por exceso el conjunto de endpoints de cada variable, lo que solo puede
    ampliar los nombres aceptados.
    """

    def __init__(self, tree: ast.AST):
        self.functions: dict[str, ast.FunctionDef] = {}
        self.locals: dict[str | None, set[str]] = {None: set()}
        self.own: set[tuple[str | None, str]] = set()
        self.env: dict[tuple[str | None, str], set[str]] = {}
        self.returns: dict[str, set[str]] = {}
        # (variable ligada, expresión de la que toma el valor)
        self._bindings: list[tuple[tuple[str | None, str], ast.AST, str | None]] = []
        self._returns: list[tuple[str, ast.AST]] = []
        self._calls: list[tuple[ast.Call, str | None]] = []
        self.subscripts: list[tuple[ast.Subscript, str | None]] = []
        self._collect(tree, None)
        self._propagate()

    # -- recolección ------------------------------------------------------

    def _bind(self, scope: str | None, target: ast.AST, value: ast.AST) -> None:
        for name in _target_names(target):
            self.locals.setdefault(scope, set()).add(name)
            self._bindings.append(((scope, name), value, scope))
            if _builds_own_dict(value):
                self.own.add((scope, name))
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and isinstance(target.slice, ast.Constant)
            and isinstance(target.slice.value, str)
        ):
            # El script escribe sus propias claves en esta variable.
            self._mark_own(scope, target.value.id)

    def _mark_own(self, scope: str | None, name: str) -> None:
        self.own.add((scope, name))
        self.own.add((None, name))

    def _collect(self, node: ast.AST, scope: str | None) -> None:
        if isinstance(node, ast.FunctionDef):
            self.functions[node.name] = node
            inner = node.name
            arguments = node.args
            params = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
            self.locals.setdefault(inner, set()).update(param.arg for param in params)
            for child in node.body:
                self._collect(child, inner)
            return

        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind(scope, target, node.value)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            if node.value is not None:
                self._bind(scope, node.target, node.value)
        elif isinstance(node, ast.For):
            self._bind(scope, node.target, node.iter)
        elif isinstance(node, ast.comprehension):
            self._bind(scope, node.target, node.iter)
        elif isinstance(node, ast.Return) and scope is not None and node.value is not None:
            self._returns.append((scope, node.value))
        elif isinstance(node, ast.Call):
            self._calls.append((node, scope))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            self.subscripts.append((node, scope))

        for child in ast.iter_child_nodes(node):
            self._collect(child, scope)

    # -- propagación ------------------------------------------------------

    def _key(self, scope: str | None, name: str) -> tuple[str | None, str]:
        if scope is not None and name in self.locals.get(scope, ()):
            return (scope, name)
        return (None, name)

    def of(self, node: ast.AST, scope: str | None) -> set[str]:
        """Endpoints de los que puede venir el valor de `node`."""
        if isinstance(node, ast.Name):
            key = self._key(scope, node.id)
            return set() if key in self.own else set(self.env.get(key, ()))
        if isinstance(node, ast.Subscript):
            return self.of(node.value, scope)
        if isinstance(node, ast.Call):
            endpoint = _endpoint_of(node)
            if endpoint is not None:
                return {endpoint}
            if _builds_own_dict(node) or not isinstance(node.func, ast.Name):
                return set()
            if node.func.id in self.functions:
                return set(self.returns.get(node.func.id, ()))
            # Builtin seguro (sorted, list, ...): conserva el origen.
            return self._union((*node.args, *(k.value for k in node.keywords)), scope)
        if isinstance(node, ast.IfExp):
            return self._union((node.body, node.orelse), scope)
        if isinstance(node, ast.BoolOp):
            return self._union(node.values, scope)
        if isinstance(node, ast.BinOp):
            return self._union((node.left, node.right), scope)
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            return self._union(node.elts, scope)
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            return self.of(node.elt, scope)
        # Dict, DictComp, constantes, f-strings, comparaciones: sin origen.
        return set()

    def _union(self, nodes, scope: str | None) -> set[str]:
        result: set[str] = set()
        for node in nodes:
            result |= self.of(node, scope)
        return result

    def _add(self, key: tuple[str | None, str], endpoints: set[str]) -> bool:
        current = self.env.setdefault(key, set())
        if endpoints <= current:
            return False
        current |= endpoints
        return True

    def _propagate_call(self, call: ast.Call, scope: str | None) -> bool:
        if not (isinstance(call.func, ast.Name) and call.func.id in self.functions):
            return False
        function = self.functions[call.func.id]
        positional = [*function.args.posonlyargs, *function.args.args]
        changed = False
        for param, argument in zip(positional, call.args, strict=False):
            changed |= self._add((function.name, param.arg), self.of(argument, scope))
        for keyword in call.keywords:
            if keyword.arg is not None:
                changed |= self._add((function.name, keyword.arg), self.of(keyword.value, scope))
        return changed

    def _propagate(self) -> None:
        # Cada pasada solo agrega endpoints a conjuntos acotados por el
        # catálogo, así que termina; el tope evita cualquier sorpresa.
        for _ in range(50):
            changed = False
            for key, value, scope in self._bindings:
                changed |= self._add(key, self.of(value, scope))
            for call, scope in self._calls:
                changed |= self._propagate_call(call, scope)
            for function, value in self._returns:
                found = self.of(value, function)
                current = self.returns.setdefault(function, set())
                if not found <= current:
                    current |= found
                    changed = True
            if not changed:
                return


def find_unknown_field_references(source: str, catalog: dict | None = None) -> list[dict]:
    """Claves literales leídas sobre datos del equipo que el catálogo no lista.

    Devuelve una lista de `{"field", "endpoints", "line"}` ordenada por línea,
    con cada par (campo, endpoints) una sola vez. Nunca levanta una excepción:
    ante un script que no se puede analizar devuelve una lista vacía, porque
    esta revisión no puede hacer fallar una generación.
    """
    catalog = fortios_field_catalog.CATALOG if catalog is None else catalog
    try:
        tree = ast.parse(source)
        origins = _Origins(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []

    endpoints_catalog = catalog.get("endpoints") or {}
    found: dict[tuple[str, tuple[str, ...]], int] = {}
    for node, scope in origins.subscripts:
        key = node.slice
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        field = key.value
        if _FIELD_NAME.fullmatch(field) is None:
            continue
        try:
            endpoints = origins.of(node.value, scope)
        except RecursionError:
            continue
        if not endpoints:
            continue
        known = [_known_names(endpoints_catalog.get(endpoint) or {}) for endpoint in endpoints]
        if any(names is None for names in known):
            continue
        if any(field in names for names in known):
            continue
        identity = (field, tuple(sorted(endpoints)))
        line = getattr(node, "lineno", 0)
        if identity not in found or line < found[identity]:
            found[identity] = line

    ordered = sorted(found.items(), key=lambda item: (item[1], item[0]))
    return [
        {"field": field, "endpoints": list(endpoints), "line": line}
        for (field, endpoints), line in ordered
    ]


def summarize(references: list[dict], catalog: dict | None = None) -> dict:
    """Resumen para el manifest y los eventos: total, versión del catálogo y
    las primeras referencias. Solo nombres que escribió el script y claves de
    endpoint; nunca un valor leído de un equipo (el generador no lee ninguno).
    """
    catalog = fortios_field_catalog.CATALOG if catalog is None else catalog
    return {
        "fortios_version": catalog["fortios_version"],
        "unknown_field_references": len(references),
        "references": [dict(reference) for reference in references[:MAX_LISTED_REFERENCES]],
    }
