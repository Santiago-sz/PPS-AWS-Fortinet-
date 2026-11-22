#!/usr/bin/env python3
"""
Read-only shape diagnostic of the FortiGate REST API, run on the workstation.

For every endpoint of the client's catalogue (`fortigate_client.ENDPOINTS`)
it issues the same GET the pipeline issues and reports the STRUCTURE of the
answer, never its content:

  - whether the endpoint answered and the HTTP status;
  - the top-level keys of the JSON envelope;
  - the type of `results` (list, dict, absent, ...);
  - the number of items when it is a list;
  - the field names of the items (or of the object), with the JSON types seen
    for each field and, for child tables, their own field names.

It exists to answer questions such as "what does `system/admin` return to
this API token: how many items, with which fields?" before the toolkit is
changed to treat absent data as `indeterminate`.

No value read from the device is printed or stored: no names, addresses,
comments, hashes, serial or hostname. Field names come from the FortiOS
schema and are not configuration. Two rules keep user-defined names out:

  - a key is only printed if it looks like a schema field name (lowercase
    letters, digits, `-` and `_`); any other key is counted, not printed;
  - an object whose values are all objects is treated as a mapping keyed by
    user-defined names: its keys are counted, never printed.

`--counts-only` drops every field name and keeps the counts. The FortiOS
version and build are reported when the envelope carries them in the expected
format; the serial number and the hostname never are. The host and the token
are not written to the output either.

The client turns HTTP and network errors into `None`, which hides the status
and the envelope. This script therefore sends its own GET, built from the
client's URL, headers and TLS context (same request, same timeout), instead of
changing the client. It needs no AWS access.

Environment (same as run_executor_local.py):
  FORTIGATE_HOST        host or host:port, no scheme
  FORTIGATE_TOKEN       REST API token (read-only profile)
  FORTIGATE_VERIFY_SSL  optional, default "true"
  LOG_LEVEL             optional, default INFO

Usage (from audit-engine/):
  python scripts/diagnose_fortigate_local.py
  python scripts/diagnose_fortigate_local.py --only admins,api_users
  python scripts/diagnose_fortigate_local.py --probe-global-scope
  python scripts/diagnose_fortigate_local.py --counts-only

Exit codes:
  0  every endpoint answered
  1  shapes written, but at least one endpoint failed or was not requested
  2  configuration or input error, nothing requested
  3  the first request failed, nothing written

This file lives in scripts/, which is not packaged into the Lambda zip.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPTS_DIR.parent
for _path in (ENGINE_DIR / "executor", SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import local_run_common as common  # noqa: E402

from fortigate_client import ENDPOINTS, FortiGateClient  # noqa: E402

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_CONFIG = 2
EXIT_FIRST_REQUEST = 3

DEFAULT_OUTPUT_DIR = ENGINE_DIR / "local-runs" / "diagnostics"
REQUEST_TIMEOUT_S = 15  # same value as FortiGateClient._get
MAX_FIELD_NAMES = 500
MAX_CONSECUTIVE_NETWORK_FAILURES = 3
SCHEMA_VERSION = 1

# Endpoints whose field names are also printed on stdout: the ones behind the
# findings under review (administrators, logging, NTP, FortiGuard).
FOCUS_ENDPOINTS = (
    "admins",
    "api_users",
    "admin_profiles",
    "log_settings",
    "log_syslogd",
    "log_fortianalyzer",
    "log_memory",
    "ntp",
    "fortiguard",
)

_FIELD_NAME = re.compile(r"[a-z][a-z0-9_\-]{0,63}")
_VERSION = re.compile(r"v?\d{1,2}\.\d{1,3}\.\d{1,3}")
_ENVELOPE_COUNTERS = ("matched_count", "next_idx", "size", "total")
_API_STATUS_VALUES = ("success", "error")

# Module attribute so that tests can replace the transport.
_urlopen = urllib.request.urlopen


def _run_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _type_name(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "other"


def _is_field_name(key) -> bool:
    return isinstance(key, str) and _FIELD_NAME.fullmatch(key) is not None


def _keyed_by_name(mapping: dict) -> bool:
    """True for a mapping whose values are all objects: its keys are most
    likely user-defined names, so they are counted and never printed."""
    return bool(mapping) and all(isinstance(value, dict) for value in mapping.values())


def _child_field_names(values: list) -> list[str]:
    """Field names of the child objects found in `values` (one level only)."""
    names: set[str] = set()
    for value in values:
        children = value if isinstance(value, list) else [value]
        for child in children:
            if not isinstance(child, dict):
                continue
            if _keyed_by_name(child):
                for grandchild in child.values():
                    names.update(key for key in grandchild if _is_field_name(key))
            else:
                names.update(key for key in child if _is_field_name(key))
    return sorted(names)[:MAX_FIELD_NAMES]


def _describe_objects(objects: list[dict], counts_only: bool) -> dict:
    """Field names of a list of objects: union, presence count and types."""
    seen: dict[str, list] = {}
    unprintable: set = set()
    for obj in objects:
        for key, value in obj.items():
            if _is_field_name(key):
                seen.setdefault(key, []).append(value)
            else:
                unprintable.add(key if isinstance(key, str) else repr(key))

    fields: dict[str, dict] = {}
    if not counts_only:
        for name in sorted(seen)[:MAX_FIELD_NAMES]:
            values = seen[name]
            entry: dict = {
                "present_in": len(values),
                "types": sorted({_type_name(value) for value in values}),
            }
            lists = [value for value in values if isinstance(value, list)]
            if lists:
                entry["list_len_min"] = min(len(value) for value in lists)
                entry["list_len_max"] = max(len(value) for value in lists)
            child_names = _child_field_names(values)
            if child_names:
                entry["item_fields"] = child_names
            fields[name] = entry

    return {
        "field_count": len(seen),
        "fields": fields,
        "fields_truncated": (not counts_only) and len(seen) > MAX_FIELD_NAMES,
        "unprintable_field_count": len(unprintable),
    }


def describe_envelope(envelope, counts_only: bool = False) -> dict:
    """Shape of one JSON answer. Pure: holds no value of the answer."""
    shape: dict = {
        "envelope_keys": [],
        "envelope_counts": {},
        "api_status": None,
        "results_type": "absent",
        "item_count": None,
        "item_types": {},
        "keyed_by_name": False,
        "field_count": 0,
        "fields": {},
        "fields_truncated": False,
        "unprintable_field_count": 0,
    }
    if not isinstance(envelope, dict):
        return shape

    shape["envelope_keys"] = sorted(key for key in envelope if _is_field_name(key))
    shape["envelope_counts"] = {
        key: envelope[key]
        for key in _ENVELOPE_COUNTERS
        if isinstance(envelope.get(key), int) and not isinstance(envelope.get(key), bool)
    }
    if envelope.get("status") in _API_STATUS_VALUES:
        shape["api_status"] = envelope["status"]
    if "results" not in envelope:
        return shape

    results = envelope["results"]
    shape["results_type"] = _type_name(results)
    if isinstance(results, list):
        shape["item_count"] = len(results)
        item_types: dict[str, int] = {}
        for item in results:
            item_types[_type_name(item)] = item_types.get(_type_name(item), 0) + 1
        shape["item_types"] = item_types
        shape.update(
            _describe_objects([item for item in results if isinstance(item, dict)], counts_only)
        )
    elif isinstance(results, dict):
        if _keyed_by_name(results):
            shape["keyed_by_name"] = True
            shape["item_count"] = len(results)
            shape.update(_describe_objects(list(results.values()), counts_only))
        else:
            shape.update(_describe_objects([results], counts_only))
    return shape


def _parse_json(body) -> tuple[bool, object]:
    try:
        return True, json.loads(body.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return False, None


def probe(client, path: str) -> dict:
    """One read-only GET built from the client's URL, headers and TLS context.

    Returns the HTTP status and the parsed envelope, which `FortiGateClient`
    hides. Errors are reported by class name only: their text may carry
    device data or the request headers.
    """
    request = urllib.request.Request(f"{client.base_url}/{path}", headers=client.headers)
    if request.get_method() != "GET":
        raise RuntimeError("the diagnostic only issues GET requests")

    result = {"answered": False, "http_status": None, "error": None, "envelope": None}
    try:
        with _urlopen(request, context=client.ssl_context, timeout=REQUEST_TIMEOUT_S) as response:
            result["http_status"] = getattr(response, "status", None)
            body = response.read()
    except urllib.error.HTTPError as e:
        result["http_status"] = e.code
        result["error"] = "http_error"
        try:
            _, result["envelope"] = _parse_json(e.read())
        except Exception:
            result["envelope"] = None
        return result
    except urllib.error.URLError as e:
        reason = e.reason
        name = type(reason).__name__ if isinstance(reason, BaseException) else "URLError"
        result["error"] = f"network_error:{name}"
        return result
    except OSError as e:
        result["error"] = f"network_error:{type(e).__name__}"
        return result
    except Exception as e:
        result["error"] = f"unexpected:{type(e).__name__}"
        return result

    parsed, envelope = _parse_json(body)
    if not parsed:
        result["error"] = "invalid_json"
        return result
    result["answered"] = True
    result["envelope"] = envelope
    return result


def _fortios(envelope) -> dict | None:
    """Version and build from the envelope, only in the expected format."""
    if not isinstance(envelope, dict):
        return None
    version, build = envelope.get("version"), envelope.get("build")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        return None
    if isinstance(build, bool) or not isinstance(build, int):
        return None
    return {"version": version, "build": build}


def _entry(key: str, path: str, result: dict, counts_only: bool) -> dict:
    entry = {
        "key": key,
        "path": path,
        "requested": True,
        "answered": result["answered"],
        "http_status": result["http_status"],
        "error": result["error"],
    }
    entry.update(describe_envelope(result["envelope"], counts_only))
    return entry


def _not_requested(key: str, path: str) -> dict:
    entry = {
        "key": key,
        "path": path,
        "requested": False,
        "answered": False,
        "http_status": None,
        "error": "not_requested",
    }
    entry.update(describe_envelope(None))
    return entry


def _is_network_error(entry: dict) -> bool:
    return str(entry["error"] or "").startswith("network_error")


def _is_empty_list(entry: dict) -> bool:
    return entry["answered"] and entry["results_type"] == "list" and entry["item_count"] == 0


def _cell(value) -> str:
    return "-" if value is None else str(value)


def _note(entry: dict) -> str:
    if not entry["requested"]:
        return "not requested"
    if entry["error"]:
        return entry["error"]
    notes = []
    if _is_empty_list(entry):
        notes.append("empty list")
    if entry["results_type"] in ("absent", "null"):
        notes.append("no results")
    if entry["keyed_by_name"]:
        notes.append("keyed by name")
    if entry["unprintable_field_count"]:
        notes.append(f"{entry['unprintable_field_count']} key(s) not printed")
    if "scope_global" in entry:
        scoped = entry["scope_global"]
        notes.append(
            f"scope=global: http {_cell(scoped['http_status'])}, "
            f"items {_cell(scoped['item_count'])}"
        )
    return "; ".join(notes)


def _table(entries: list[dict]) -> list[str]:
    header = ("KEY", "PATH", "HTTP", "RESULTS", "ITEMS", "FIELDS", "NOTE")
    rows = [
        (
            entry["key"],
            entry["path"],
            _cell(entry["http_status"]),
            entry["results_type"] if entry["answered"] else "-",
            _cell(entry["item_count"]),
            _cell(entry["field_count"] if entry["answered"] else None),
            _note(entry),
        )
        for entry in entries
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header) - 1)]
    lines = []
    for row in [header, *rows]:
        cells = [row[i].ljust(widths[i]) for i in range(len(widths))]
        lines.append("  ".join([*cells, row[-1]]).rstrip())
    return lines


def _focus_lines(entries: list[dict]) -> list[str]:
    lines = []
    for entry in entries:
        if entry["key"] not in FOCUS_ENDPOINTS:
            continue
        variants = [(entry["path"], entry["fields"])]
        if "scope_global" in entry:
            variants.append((f"{entry['path']}?scope=global", entry["scope_global"]["fields"]))
        for path, fields in variants:
            if not fields:
                continue
            lines.append(f"{entry['key']} ({path}): " + ", ".join(sorted(fields)))
            for name, detail in sorted(fields.items()):
                if "item_fields" in detail:
                    lines.append(f"  {name}[]: " + ", ".join(detail["item_fields"]))
    return lines


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="diagnose_fortigate_local.py",
        description=(
            "Report the structure (never the content) of what each catalogue endpoint "
            "of the FortiGate REST API returns. Read-only: GET requests only."
        ),
        epilog="The FortiGate token is read from the FORTIGATE_TOKEN environment variable.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--only",
        help="comma-separated endpoint keys to check (default: the whole catalogue)",
    )
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="do not print or store field names, only counts",
    )
    parser.add_argument(
        "--probe-global-scope",
        action="store_true",
        help="repeat with ?scope=global every endpoint that answered an empty list",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"local directory for shapes.json (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args(argv)


def _load_settings(args: argparse.Namespace) -> dict:
    """Reads and checks every input before any request."""
    env = common.read_fortigate_env()
    common.require_env([("FORTIGATE_HOST", env["host"]), ("FORTIGATE_TOKEN", env["token"])])
    common.check_fortigate_env(env["host"], env["token"])

    catalogue = [(key, path) for path, key in ENDPOINTS]
    if args.only:
        wanted = [key.strip() for key in args.only.split(",") if key.strip()]
        known = {key for key, _ in catalogue}
        unknown = sorted(set(wanted) - known)
        if unknown or not wanted:
            raise common.ConfigError(
                "Unknown endpoint key(s) in --only: "
                + (", ".join(unknown) or "(none given)")
                + ". Valid keys: "
                + ", ".join(sorted(known))
                + "."
            )
        catalogue = [(key, path) for key, path in catalogue if key in wanted]

    return {**env, "endpoints": catalogue, "args": args}


def _run(settings: dict) -> int:
    args = settings["args"]
    token = settings["token"]
    try:
        client = FortiGateClient(
            host=settings["host"], token=token, verify_ssl=settings["verify_ssl"]
        )
    except Exception as e:
        raise common.ConfigError(
            f"Could not build the FortiGate client ({type(e).__name__})."
        ) from None

    entries: list[dict] = []
    fortios = None
    consecutive_network_failures = 0
    stopped = False
    for index, (key, path) in enumerate(settings["endpoints"]):
        if stopped:
            entries.append(_not_requested(key, path))
            continue

        result = probe(client, path)
        entry = _entry(key, path, result, args.counts_only)
        if index == 0 and not entry["answered"]:
            cause = f"HTTP {entry['http_status']}" if entry["http_status"] else entry["error"]
            _err(f"First request failed: GET {path} -> {cause}")
            _err(
                common.unreachable_message(
                    "ERROR: the FortiGate did not answer the first read-only GET. "
                    "No other request was sent and nothing was written.",
                    settings["verify_ssl"],
                )
            )
            return EXIT_FIRST_REQUEST

        if fortios is None and entry["answered"]:
            fortios = _fortios(result["envelope"])
        if args.probe_global_scope and _is_empty_list(entry):
            scoped = _entry(key, path, probe(client, f"{path}?scope=global"), args.counts_only)
            del scoped["key"], scoped["path"], scoped["requested"]
            entry["scope_global"] = scoped
        entries.append(entry)

        consecutive_network_failures = (
            consecutive_network_failures + 1 if _is_network_error(entry) else 0
        )
        if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
            stopped = True
            _err(
                f"Stopped after {MAX_CONSECUTIVE_NETWORK_FAILURES} consecutive network "
                "failures: the connection to the FortiGate seems to be down."
            )

    summary = {
        "total": len(entries),
        "answered": sum(1 for entry in entries if entry["answered"]),
        "empty_list": sum(1 for entry in entries if _is_empty_list(entry)),
        "failed": sum(1 for entry in entries if entry["requested"] and not entry["answered"]),
        "not_requested": sum(1 for entry in entries if not entry["requested"]),
    }
    shapes = common.redact(
        {
            "tool": "audit-engine/scripts/diagnose_fortigate_local.py",
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "contains_device_values": False,
            "fortios": fortios,
            "verify_ssl": settings["verify_ssl"],
            "counts_only": args.counts_only,
            "probe_global_scope": args.probe_global_scope,
            "summary": summary,
            "endpoints": entries,
        },
        token,
    )

    target = Path(args.output_dir) / _run_stamp()
    target.mkdir(parents=True, exist_ok=True)
    shapes_path = target / "shapes.json"
    shapes_path.write_text(json.dumps(shapes, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = []
    if fortios:
        lines.append(f"FortiOS {fortios['version']} build {fortios['build']}")
    lines.append("Structure only: no value read from the device is shown or stored.")
    lines.append("")
    lines.extend(_table(shapes["endpoints"]))
    focus = _focus_lines(shapes["endpoints"])
    if focus:
        lines.extend(["", "Field names (focus endpoints)", *focus])
    lines.extend(
        [
            "",
            f"Summary: answered {summary['answered']} of {summary['total']}; "
            f"empty list: {summary['empty_list']}; failed: {summary['failed']}; "
            f"not requested: {summary['not_requested']}",
            f"Shapes written to: {shapes_path}",
        ]
    )
    print(common.redact("\n".join(lines), token))

    complete = summary["failed"] == 0 and summary["not_requested"] == 0
    return EXIT_OK if complete else EXIT_INCOMPLETE


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = _load_settings(args)
    except common.ConfigError as e:
        _err(f"ERROR: {e}")
        return EXIT_CONFIG

    with common.redacted_logging(settings["token"]):
        try:
            return _run(settings)
        except common.ConfigError as e:
            _err(f"ERROR: {e}")
            return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
