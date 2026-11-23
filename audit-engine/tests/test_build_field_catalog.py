"""
Tests for scripts/build_field_catalog.py and for the versioned catalogue it
writes (generator/fortios_field_catalog.py).

The catalogue lists, per endpoint key, the field NAMES seen in the answers of
one device. It is built from the output of the shape diagnostic, which holds
structure only. These tests pin three properties:

  - the builder merges diagnostics, never invents a name and marks as
    "unknown" every endpoint it could not observe;
  - the committed catalogue holds names only, is sorted and is exactly what
    the builder renders (so it can be regenerated without a noisy diff);
  - the catalogue travels in the Lambda package and the builder does not.

Every diagnostic used here is synthetic.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

import fortigate_client
import fortios_field_catalog

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = next(p for p in ENGINE_DIR.parents if (p / "AGENTS.md").exists())
BUILDER_PATH = ENGINE_DIR / "scripts" / "build_field_catalog.py"
CATALOG_PATH = ENGINE_DIR / "generator" / "fortios_field_catalog.py"

FIELD_NAME = re.compile(r"[a-z][a-z0-9_\-]{0,63}")
ENDPOINT_KEYS = [label for _, label in fortigate_client.ENDPOINTS]


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_field_catalog", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _field(types=("str",), item_fields=None) -> dict:
    entry = {"present_in": 1, "types": list(types)}
    if item_fields is not None:
        entry["item_fields"] = list(item_fields)
    return entry


def _endpoint(key: str, results_type: str = "dict", fields: dict | None = None, **extra) -> dict:
    entry = {
        "key": key,
        "path": "x/y",
        "requested": True,
        "answered": True,
        "http_status": 200,
        "error": None,
        "results_type": results_type,
        "item_count": None,
        "keyed_by_name": False,
        "field_count": len(fields or {}),
        "fields": fields or {},
        "fields_truncated": False,
        "unprintable_field_count": 0,
    }
    entry.update(extra)
    return entry


def _shapes(endpoints: list[dict], version: str = "v7.6.8", build: int = 3744, **extra) -> dict:
    shapes = {
        "tool": "audit-engine/scripts/diagnose_fortigate_local.py",
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "contains_device_values": False,
        "fortios": {"version": version, "build": build},
        "counts_only": False,
        "endpoints": endpoints,
    }
    shapes.update(extra)
    return shapes


class TestBuildCatalog:
    def test_object_and_list_endpoints_keep_their_shape_and_field_names(self, builder):
        shapes = _shapes(
            [
                _endpoint("log_settings", "dict", {"resolve-ip": _field(), "local-out": _field()}),
                _endpoint(
                    "interfaces",
                    "list",
                    {"name": _field(), "ipv6": _field(("dict",), ["ip6-mode", "autoconf"])},
                    item_count=2,
                ),
            ]
        )

        catalog = builder.build_catalog([shapes])

        assert catalog["fortios_version"] == "v7.6.8"
        assert catalog["fortios_build"] == 3744
        log_settings = catalog["endpoints"]["log_settings"]
        assert log_settings["status"] == "observed"
        assert log_settings["shape"] == "object"
        assert log_settings["fortios_version"] == "v7.6.8"
        assert log_settings["fields"] == {"local-out": [], "resolve-ip": []}
        interfaces = catalog["endpoints"]["interfaces"]
        assert interfaces["shape"] == "list"
        assert interfaces["fields"] == {"ipv6": ["autoconf", "ip6-mode"], "name": []}

    def test_every_endpoint_of_the_client_is_present(self, builder):
        catalog = builder.build_catalog(
            [_shapes([_endpoint("dns", "dict", {"primary": _field()})])]
        )

        assert sorted(catalog["endpoints"]) == sorted(ENDPOINT_KEYS)

    def test_an_endpoint_that_did_not_answer_is_unknown_with_no_fields(self, builder):
        failed = _endpoint(
            "dhcp_servers", "absent", {}, answered=False, http_status=400, error="http_error"
        )

        catalog = builder.build_catalog([_shapes([failed])])

        entry = catalog["endpoints"]["dhcp_servers"]
        assert entry == {
            "status": "unknown",
            "reason": "not_answered",
            "shape": "unknown",
            "fortios_version": None,
            "fields": {},
            "unlisted_field_count": 0,
            "fields_truncated": False,
        }

    def test_an_empty_list_is_unknown_but_keeps_the_list_shape(self, builder):
        empty = _endpoint("vpn_ipsec", "list", {}, item_count=0)

        entry = builder.build_catalog([_shapes([empty])])["endpoints"]["vpn_ipsec"]

        assert entry["status"] == "unknown"
        assert entry["reason"] == "empty_list"
        assert entry["shape"] == "list"
        assert entry["fields"] == {}

    def test_an_endpoint_missing_from_every_diagnostic_is_unknown(self, builder):
        entry = builder.build_catalog([_shapes([])])["endpoints"]["snmp_sysinfo"]

        assert entry["status"] == "unknown"
        assert entry["reason"] == "not_in_diagnostic"

    def test_a_later_diagnostic_fills_an_endpoint_the_first_one_saw_empty(self, builder):
        first = _shapes([_endpoint("admins", "list", {}, item_count=0)])
        second = _shapes(
            [_endpoint("admins", "list", {"name": _field(), "accprofile": _field()}, item_count=1)]
        )

        for order in ([first, second], [second, first]):
            entry = builder.build_catalog(order)["endpoints"]["admins"]
            assert entry["status"] == "observed"
            assert entry["fields"] == {"accprofile": [], "name": []}

    def test_two_observations_of_one_endpoint_are_merged_by_union(self, builder):
        first = _shapes(
            [_endpoint("admins", "list", {"name": _field(), "vdom": _field(("list",), ["name"])})]
        )
        second = _shapes(
            [
                _endpoint(
                    "admins",
                    "list",
                    {"trusthost1": _field(), "vdom": _field(("list",), ["q_origin_key"])},
                )
            ]
        )

        entry = builder.build_catalog([first, second])["endpoints"]["admins"]

        assert entry["fields"] == {
            "name": [],
            "trusthost1": [],
            "vdom": ["name", "q_origin_key"],
        }

    def test_the_global_scope_probe_is_used_when_the_default_scope_is_empty(self, builder):
        entry = _endpoint(
            "admins",
            "list",
            {},
            item_count=0,
            scope_global=_endpoint("admins", "list", {"name": _field()}, item_count=1),
        )

        result = builder.build_catalog([_shapes([entry])])["endpoints"]["admins"]

        assert result["status"] == "observed"
        assert result["fields"] == {"name": []}

    def test_unlisted_and_truncated_field_markers_are_kept(self, builder):
        entry = _endpoint(
            "fortiguard",
            "dict",
            {"port": _field()},
            unprintable_field_count=2,
            fields_truncated=True,
        )

        result = builder.build_catalog([_shapes([entry])])["endpoints"]["fortiguard"]

        assert result["unlisted_field_count"] == 2
        assert result["fields_truncated"] is True

    def test_a_name_that_is_not_a_schema_field_name_is_dropped(self, builder):
        entry = _endpoint(
            "dns",
            "dict",
            {
                "primary": _field(),
                "Oficina Central": _field(),
                "ok": _field(("dict",), ["good-name", "10.0.0.1"]),
            },
        )

        result = builder.build_catalog([_shapes([entry])])["endpoints"]["dns"]

        assert result["fields"] == {"ok": ["good-name"], "primary": []}

    def test_an_endpoint_key_outside_the_client_catalogue_is_ignored(self, builder):
        catalog = builder.build_catalog(
            [_shapes([_endpoint("not_an_endpoint", "dict", {"a": _field()})])]
        )

        assert "not_an_endpoint" not in catalog["endpoints"]


class TestBuildCatalogRefusesUnsafeInput:
    def test_a_diagnostic_that_may_hold_device_values_is_refused(self, builder):
        with pytest.raises(builder.CatalogInputError, match="contains_device_values"):
            builder.build_catalog([_shapes([], contains_device_values=True)])

    def test_a_diagnostic_without_the_values_flag_is_refused(self, builder):
        shapes = _shapes([])
        del shapes["contains_device_values"]

        with pytest.raises(builder.CatalogInputError, match="contains_device_values"):
            builder.build_catalog([shapes])

    def test_an_unknown_schema_version_is_refused(self, builder):
        with pytest.raises(builder.CatalogInputError, match="schema_version"):
            builder.build_catalog([_shapes([], schema_version=2)])

    def test_a_counts_only_diagnostic_is_refused(self, builder):
        with pytest.raises(builder.CatalogInputError, match="counts"):
            builder.build_catalog([_shapes([], counts_only=True)])

    def test_diagnostics_of_different_fortios_versions_are_refused(self, builder):
        with pytest.raises(builder.CatalogInputError, match="FortiOS"):
            builder.build_catalog([_shapes([]), _shapes([], version="v7.4.5", build=2702)])

    def test_a_diagnostic_without_the_fortios_version_is_refused(self, builder):
        with pytest.raises(builder.CatalogInputError, match="FortiOS"):
            builder.build_catalog([_shapes([], fortios=None)])

    def test_no_diagnostic_is_refused(self, builder):
        with pytest.raises(builder.CatalogInputError):
            builder.build_catalog([])


class TestRenderModule:
    def test_rendering_is_deterministic_and_independent_of_input_order(self, builder):
        a = _endpoint("dns", "dict", {"secondary": _field(), "primary": _field()})
        b = _endpoint("ntp", "dict", {"type": _field(), "ntpserver": _field(("list",), ["id"])})

        first = builder.render_module(builder.build_catalog([_shapes([a, b])]))
        second = builder.render_module(builder.build_catalog([_shapes([b, a])]))

        assert first == second

    def test_the_rendered_module_loads_back_to_the_same_catalogue(self, builder, tmp_path):
        catalog = builder.build_catalog(
            [_shapes([_endpoint("dns", "dict", {"primary": _field()})])]
        )
        target = tmp_path / "rendered_catalog.py"
        target.write_text(builder.render_module(catalog), encoding="utf-8")

        spec = importlib.util.spec_from_file_location("rendered_catalog", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.CATALOG == catalog

    def test_main_writes_the_module_from_diagnostic_files(self, builder, tmp_path, capsys):
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        first.write_text(
            json.dumps(_shapes([_endpoint("admins", "list", {}, item_count=0)])), encoding="utf-8"
        )
        second.write_text(
            json.dumps(_shapes([_endpoint("admins", "list", {"name": _field()}, item_count=1)])),
            encoding="utf-8",
        )
        output = tmp_path / "out.py"

        code = builder.main([str(first), str(second), "--output", str(output)])

        assert code == 0
        assert '"name"' in output.read_text(encoding="utf-8")
        assert "observed" in capsys.readouterr().out

    def test_main_reports_an_unsafe_diagnostic_and_writes_nothing(self, builder, tmp_path, capsys):
        source = tmp_path / "a.json"
        source.write_text(json.dumps(_shapes([], contains_device_values=True)), encoding="utf-8")
        output = tmp_path / "out.py"

        code = builder.main([str(source), "--output", str(output)])

        assert code == 2
        assert not output.exists()
        assert "contains_device_values" in capsys.readouterr().err


class TestCommittedCatalog:
    """El catálogo versionado: solo nombres, ordenado y regenerable."""

    def test_it_covers_exactly_the_endpoints_of_the_client(self):
        assert sorted(fortios_field_catalog.CATALOG["endpoints"]) == sorted(ENDPOINT_KEYS)

    def test_it_states_the_fortios_version_it_was_observed_on(self):
        catalog = fortios_field_catalog.CATALOG

        assert re.fullmatch(r"v\d+\.\d+\.\d+", catalog["fortios_version"])
        assert isinstance(catalog["fortios_build"], int)
        for entry in catalog["endpoints"].values():
            expected = catalog["fortios_version"] if entry["status"] == "observed" else None
            assert entry["fortios_version"] == expected

    def test_it_holds_field_names_only(self):
        catalog = fortios_field_catalog.CATALOG

        assert set(catalog) == {"schema_version", "fortios_version", "fortios_build", "endpoints"}
        for key, entry in catalog["endpoints"].items():
            assert set(entry) == {
                "status",
                "reason",
                "shape",
                "fortios_version",
                "fields",
                "unlisted_field_count",
                "fields_truncated",
            }, key
            assert entry["status"] in ("observed", "unknown"), key
            assert entry["shape"] in ("object", "list", "unknown"), key
            assert entry["reason"] in (
                None,
                "not_answered",
                "empty_list",
                "no_fields",
                "not_in_diagnostic",
            ), key
            assert isinstance(entry["unlisted_field_count"], int), key
            assert isinstance(entry["fields_truncated"], bool), key
            for name, children in entry["fields"].items():
                assert FIELD_NAME.fullmatch(name), (key, name)
                assert isinstance(children, list), (key, name)
                for child in children:
                    assert FIELD_NAME.fullmatch(child), (key, name, child)

    def test_observed_endpoints_list_fields_and_unknown_ones_list_none(self):
        for key, entry in fortios_field_catalog.CATALOG["endpoints"].items():
            if entry["status"] == "observed":
                assert entry["fields"], key
                assert entry["reason"] is None, key
                assert entry["shape"] in ("object", "list"), key
            else:
                assert entry["fields"] == {}, key
                assert entry["reason"] is not None, key

    def test_the_endpoints_not_read_by_the_diagnostic_are_unknown(self):
        endpoints = fortios_field_catalog.CATALOG["endpoints"]

        for key in ("dhcp_servers", "snmp_sysinfo"):
            assert endpoints[key]["status"] == "unknown"
            assert endpoints[key]["fields"] == {}

    def test_it_is_sorted(self):
        endpoints = fortios_field_catalog.CATALOG["endpoints"]

        assert list(endpoints) == sorted(endpoints)
        for entry in endpoints.values():
            assert list(entry["fields"]) == sorted(entry["fields"])
            for children in entry["fields"].values():
                assert children == sorted(set(children))

    def test_the_committed_file_is_exactly_what_the_builder_renders(self, builder):
        rendered = builder.render_module(fortios_field_catalog.CATALOG)

        assert CATALOG_PATH.read_text(encoding="utf-8") == rendered

    def test_it_knows_the_fields_behind_the_findings_that_motivated_it(self):
        endpoints = fortios_field_catalog.CATALOG["endpoints"]

        # Nombres que los scripts pidieron y el equipo no trae.
        assert "ssl-min-proto-ver" not in endpoints["ssl_ssh_profiles"]["fields"]
        assert "zone" not in endpoints["interfaces"]["fields"]
        assert "update-schedule" not in endpoints["fortiguard"]["fields"]
        # Nombres que el equipo sí trae.
        assert "min-allowed-ssl-version" in endpoints["ssl_ssh_profiles"]["fields"]["https"]
        assert "fwpolicy-implicit-log" in endpoints["log_settings"]["fields"]
        assert "accprofile" in endpoints["admins"]["fields"]


class TestPackaging:
    def test_the_catalogue_module_is_part_of_the_lambda_package(self):
        terraform = (ROOT / "infrastructure/pipeline/lambda.tf").read_text(encoding="utf-8")

        assert CATALOG_PATH.is_file()
        assert CATALOG_PATH.parent.name == "generator"
        assert 'for area in ["generator", "executor", "contracts", "legacy"]' in terraform
        assert 'fileset("${path.module}/../../audit-engine/${area}", "*.py")' in terraform

    def test_the_catalogue_module_needs_nothing_but_the_standard_library(self):
        source = CATALOG_PATH.read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]

        assert imports == ["import json"]

    def test_the_builder_is_not_part_of_the_lambda_package(self):
        assert BUILDER_PATH.is_file()
        for area in ("generator", "executor", "contracts", "legacy"):
            assert not (ENGINE_DIR / area / BUILDER_PATH.name).exists()

    def test_the_executor_does_not_import_the_catalogue(self):
        for module in (ENGINE_DIR / "executor").glob("*.py"):
            assert "fortios_field_catalog" not in module.read_text(encoding="utf-8"), module.name
