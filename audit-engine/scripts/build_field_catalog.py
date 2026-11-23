#!/usr/bin/env python3
"""
Build the versioned FortiOS field catalogue from shape diagnostics.

The generator used to guess field names. This script turns one or more
`shapes.json` files written by `diagnose_fortigate_local.py` into
`generator/fortios_field_catalog.py`: per endpoint key, whether the endpoint
returns an object or a list, the FortiOS version it was observed on and the
field names seen, with one nested level. The generator gives that catalogue to
the model as the reference for field names.

Input and output hold structure only. The diagnostic never stores a value read
from the device; this script adds a second barrier and refuses a file that
does not declare `contains_device_values: false`, and it keeps only names that
look like FortiOS schema field names (lowercase letters, digits, `-`, `_`).

Merging rules, for several diagnostics of the same device:

  - all of them must report the same FortiOS version and build;
  - field names of one endpoint are merged by union (a second diagnostic read
    with another admin profile may see an endpoint the first one saw empty);
  - when the default scope came back empty, the `scope_global` probe of the
    same diagnostic is used if it has fields;
  - an endpoint that never showed a field is written as "unknown" with an
    empty field list and the reason: `not_answered` (HTTP or network error),
    `empty_list` (no object to look at), `no_fields` or `not_in_diagnostic`.
    No name is ever invented.

The output is deterministic: endpoints, fields and nested fields are sorted,
and no timestamp is written, so regenerating from the same diagnostics gives
the same file.

Usage (from audit-engine/):
  python scripts/build_field_catalog.py local-runs/diagnostics/<run>/shapes.json [more.json ...]
  python scripts/build_field_catalog.py <shapes.json> --output some/other/path.py

Exit codes:
  0  catalogue written
  2  input error, nothing written

This file lives in scripts/, which is not packaged into the Lambda zip. The
catalogue it writes lives in generator/ and is packaged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPTS_DIR.parent
if str(ENGINE_DIR / "executor") not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR / "executor"))

from fortigate_client import ENDPOINTS  # noqa: E402

EXIT_OK = 0
EXIT_INPUT = 2

DEFAULT_OUTPUT = ENGINE_DIR / "generator" / "fortios_field_catalog.py"
SUPPORTED_SHAPES_SCHEMA = 1
CATALOG_SCHEMA_VERSION = 1

STATUS_OBSERVED = "observed"
STATUS_UNKNOWN = "unknown"

# Same pattern as the diagnostic: a key is a schema field name or it is dropped.
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_\-]{0,63}")
_VERSION = re.compile(r"v?\d{1,2}\.\d{1,3}\.\d{1,3}")
_SHAPES = {"dict": "object", "list": "list"}

_MODULE_HEADER = '''\
"""
Catálogo de campos de FortiOS por endpoint. ARCHIVO GENERADO: no editar a mano.

Lo escribe `scripts/build_field_catalog.py` a partir de la salida del
diagnóstico de solo lectura (`scripts/diagnose_fortigate_local.py`). Contiene
solo estructura: por cada clave de endpoint, si la respuesta es un objeto o
una lista, la versión de FortiOS en que se observó y los NOMBRES de los
campos, con un nivel anidado. No contiene ningún valor leído de un equipo.

Proviene de un único equipo, una versión de FortiOS y un perfil de
administración: otros modelos o versiones pueden tener campos distintos. Los
endpoints con `status: "unknown"` no pudieron observarse y su lista de campos
está vacía a propósito. Diseño, límites y regeneración en
docs/context/decisions/13-catalogo-de-campos-generador.md.
"""

import json

CATALOG = json.loads(
    """
'''
_MODULE_FOOTER = '''
"""
)
'''


class CatalogInputError(Exception):
    """A diagnostic cannot be used to build the catalogue."""


def _is_field_name(name) -> bool:
    return isinstance(name, str) and _FIELD_NAME.fullmatch(name) is not None


def _check_shapes(shapes, position: int) -> tuple[str, int]:
    """Validate one diagnostic and return its (FortiOS version, build)."""
    where = f"diagnostic #{position}"
    if not isinstance(shapes, dict):
        raise CatalogInputError(f"{where}: not a JSON object")
    if shapes.get("schema_version") != SUPPORTED_SHAPES_SCHEMA:
        raise CatalogInputError(
            f"{where}: unsupported schema_version (expected {SUPPORTED_SHAPES_SCHEMA})"
        )
    if shapes.get("contains_device_values") is not False:
        raise CatalogInputError(
            f"{where}: contains_device_values is not false; refusing to read field names from it"
        )
    if shapes.get("counts_only"):
        raise CatalogInputError(f"{where}: written with --counts-only, it has no field names")
    if not isinstance(shapes.get("endpoints"), list):
        raise CatalogInputError(f"{where}: no endpoints list")

    fortios = shapes.get("fortios")
    version = fortios.get("version") if isinstance(fortios, dict) else None
    build = fortios.get("build") if isinstance(fortios, dict) else None
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise CatalogInputError(f"{where}: the FortiOS version is missing")
    if isinstance(build, bool) or not isinstance(build, int):
        raise CatalogInputError(f"{where}: the FortiOS build is missing")
    return version, build


def _fields_of(entry: dict) -> dict[str, set[str]]:
    """Field names of one diagnostic entry, with their nested names."""
    fields: dict[str, set[str]] = {}
    raw = entry.get("fields")
    if not isinstance(raw, dict):
        return fields
    for name, detail in raw.items():
        if not _is_field_name(name):
            continue
        children = detail.get("item_fields") if isinstance(detail, dict) else None
        fields[name] = {
            child
            for child in (children if isinstance(children, list) else [])
            if _is_field_name(child)
        }
    return fields


def _observation(entry: dict) -> dict:
    """What one diagnostic entry says about its endpoint."""
    fields = _fields_of(entry)
    source = entry
    scope_global = entry.get("scope_global")
    if not fields and isinstance(scope_global, dict):
        global_fields = _fields_of(scope_global)
        if global_fields:
            fields, source = global_fields, scope_global

    results_type = source.get("results_type")
    shape = _SHAPES.get(results_type, "unknown")
    if fields:
        reason = None
    elif not source.get("answered"):
        reason = "not_answered"
    elif results_type == "list" and not source.get("item_count"):
        reason = "empty_list"
    else:
        reason = "no_fields"

    unlisted = source.get("unprintable_field_count")
    return {
        "fields": fields,
        "shape": shape,
        "reason": reason,
        "unlisted": unlisted if isinstance(unlisted, int) and not isinstance(unlisted, bool) else 0,
        "truncated": bool(source.get("fields_truncated")),
    }


# An unknown endpoint keeps the most informative reason seen across diagnostics.
_REASON_RANK = {"not_in_diagnostic": 0, "not_answered": 1, "no_fields": 2, "empty_list": 3}


def _merge(observations: list[dict], version: str) -> dict:
    observed = [o for o in observations if o["fields"]]
    if observed:
        merged: dict[str, set[str]] = {}
        for observation in observed:
            for name, children in observation["fields"].items():
                merged.setdefault(name, set()).update(children)
        return {
            "status": STATUS_OBSERVED,
            "reason": None,
            "shape": observed[0]["shape"],
            "fortios_version": version,
            "fields": {name: sorted(merged[name]) for name in sorted(merged)},
            "unlisted_field_count": max(o["unlisted"] for o in observed),
            "fields_truncated": any(o["truncated"] for o in observed),
        }

    best = max(observations, key=lambda o: _REASON_RANK[o["reason"]], default=None)
    return {
        "status": STATUS_UNKNOWN,
        "reason": best["reason"] if best else "not_in_diagnostic",
        "shape": best["shape"] if best else "unknown",
        "fortios_version": None,
        "fields": {},
        "unlisted_field_count": 0,
        "fields_truncated": False,
    }


def build_catalog(shapes_list: list[dict]) -> dict:
    """Merge diagnostics into the catalogue. Pure: reads and writes no file."""
    if not shapes_list:
        raise CatalogInputError("at least one diagnostic is required")

    versions = [_check_shapes(shapes, i) for i, shapes in enumerate(shapes_list, start=1)]
    if len(set(versions)) != 1:
        found = ", ".join(sorted({f"{version} build {build}" for version, build in versions}))
        raise CatalogInputError(
            f"the diagnostics come from different FortiOS versions ({found}); "
            "build one catalogue per version"
        )
    version, build = versions[0]

    known_keys = [label for _, label in ENDPOINTS]
    observations: dict[str, list[dict]] = {key: [] for key in known_keys}
    for shapes in shapes_list:
        for entry in shapes["endpoints"]:
            if isinstance(entry, dict) and entry.get("key") in observations:
                observations[entry["key"]].append(_observation(entry))

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "fortios_version": version,
        "fortios_build": build,
        "endpoints": {key: _merge(observations[key], version) for key in sorted(known_keys)},
    }


def render_module(catalog: dict) -> str:
    """Python source of the catalogue module. Same catalogue, same bytes."""
    body = json.dumps(catalog, indent=1, sort_keys=True, ensure_ascii=True)
    if '"""' in body or "\\" in body:
        raise CatalogInputError("the catalogue holds a character that a field name cannot have")
    return _MODULE_HEADER + body + _MODULE_FOOTER


def _summary(catalog: dict) -> str:
    endpoints = catalog["endpoints"]
    observed = [key for key, entry in endpoints.items() if entry["status"] == STATUS_OBSERVED]
    unknown = [key for key in endpoints if key not in observed]
    top = sum(len(endpoints[key]["fields"]) for key in observed)
    nested = sum(len(c) for key in observed for c in endpoints[key]["fields"].values())
    lines = [
        f"FortiOS {catalog['fortios_version']} build {catalog['fortios_build']}",
        f"observed endpoints: {len(observed)} ({top} field names, {nested} nested names)",
        f"unknown endpoints: {len(unknown)}",
    ]
    lines.extend(f"  - {key}: {endpoints[key]['reason']}" for key in unknown)
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build generator/fortios_field_catalog.py from shape diagnostics (names only)."
    )
    parser.add_argument("shapes", nargs="+", type=Path, help="shapes.json files to merge")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="module to write")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        shapes_list = [json.loads(path.read_text(encoding="utf-8")) for path in args.shapes]
        catalog = build_catalog(shapes_list)
        source = render_module(catalog)
    except (OSError, ValueError, CatalogInputError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT

    args.output.write_text(source, encoding="utf-8", newline="\n")
    print(_summary(catalog))
    print(f"written: {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
