"""
Tests para field_catalog.py: la sección del prompt con el catálogo de campos
y la detección de nombres de campo que el catálogo no lista.

La detección es una ayuda para el ciclo de reintento, no una compuerta: debe
preferir no avisar antes que señalar código correcto. Por eso buena parte de
estos tests fija lo que NO se informa (diccionarios propios del script,
etiquetas de evidencia, búsquedas de texto, endpoints sin verificar).

El catálogo de estos tests es sintético.
"""

import field_catalog
import fortios_field_catalog

CATALOG = {
    "schema_version": 1,
    "fortios_version": "v7.6.8",
    "fortios_build": 3744,
    "endpoints": {
        "admins": {
            "status": "observed",
            "reason": None,
            "shape": "list",
            "fortios_version": "v7.6.8",
            "fields": {"accprofile": [], "name": [], "vdom": ["name", "q_origin_key"]},
            "unlisted_field_count": 0,
            "fields_truncated": False,
        },
        "dhcp_servers": {
            "status": "unknown",
            "reason": "not_answered",
            "shape": "unknown",
            "fortios_version": None,
            "fields": {},
            "unlisted_field_count": 0,
            "fields_truncated": False,
        },
        "interfaces": {
            "status": "observed",
            "reason": None,
            "shape": "list",
            "fortios_version": "v7.6.8",
            "fields": {"allowaccess": [], "name": [], "role": []},
            "unlisted_field_count": 1,
            "fields_truncated": False,
        },
        "log_settings": {
            "status": "observed",
            "reason": None,
            "shape": "object",
            "fortios_version": "v7.6.8",
            "fields": {"fwpolicy-implicit-log": [], "local-out": []},
            "unlisted_field_count": 0,
            "fields_truncated": False,
        },
        "ssl_ssh_profiles": {
            "status": "observed",
            "reason": None,
            "shape": "list",
            "fortios_version": "v7.6.8",
            "fields": {"https": ["min-allowed-ssl-version", "status"], "name": []},
            "unlisted_field_count": 0,
            "fields_truncated": False,
        },
        "system_global": {
            "status": "observed",
            "reason": None,
            "shape": "object",
            "fortios_version": "v7.6.8",
            "fields": {"admin-sport": [], "hostname": []},
            "unlisted_field_count": 0,
            "fields_truncated": True,
        },
    },
}


def _find(source: str) -> list[dict]:
    return field_catalog.find_unknown_field_references(source, CATALOG)


def _fields(source: str) -> list[str]:
    return [reference["field"] for reference in _find(source)]


class TestPromptSection:
    def test_it_states_the_fortios_version_of_the_catalogue(self):
        section = field_catalog.prompt_section(CATALOG)

        assert "FortiOS v7.6.8" in section
        assert "build 3744" in section

    def test_every_endpoint_is_listed_with_its_shape_and_field_names(self):
        section = field_catalog.prompt_section(CATALOG)

        assert "- log_settings (objeto): fwpolicy-implicit-log, local-out" in section
        assert "- admins (lista): accprofile, name, vdom{name, q_origin_key}" in section
        assert "- ssl_ssh_profiles (lista): https{min-allowed-ssl-version, status}, name" in section

    def test_unknown_endpoints_are_marked_and_list_no_field(self):
        section = field_catalog.prompt_section(CATALOG)

        assert "- dhcp_servers (sin verificar)" in section
        assert "- dhcp_servers (sin verificar):" not in section

    def test_it_carries_the_rules_for_the_model(self):
        section = field_catalog.prompt_section(CATALOG)

        assert "SOLO" in section
        assert "NO adivines" in section
        assert '"indeterminate"' in section
        assert "sin verificar" in section

    def test_it_is_deterministic(self):
        assert field_catalog.prompt_section(CATALOG) == field_catalog.prompt_section(CATALOG)

    def test_the_default_section_comes_from_the_versioned_catalogue(self):
        section = field_catalog.prompt_section()
        catalog = fortios_field_catalog.CATALOG

        assert section == field_catalog.prompt_section(catalog)
        assert catalog["fortios_version"] in section
        for key in catalog["endpoints"]:
            assert f"- {key} (" in section

    def test_the_versioned_section_only_uses_plain_ascii(self):
        # Los prompts del generador no llevan tildes ni otros caracteres fuera
        # de ASCII (salvo el "Respondé" histórico del prompt base).
        assert field_catalog.prompt_section().isascii()


class TestUnknownFieldReferences:
    def test_a_field_missing_from_an_object_endpoint_is_reported(self):
        source = (
            'settings = fgt.get("log_settings")\n'
            'value = settings["admin"] if "admin" in settings else None\n'
        )

        assert _find(source) == [{"field": "admin", "endpoints": ["log_settings"], "line": 2}]

    def test_a_listed_field_is_not_reported(self):
        source = 'settings = fgt.get("log_settings")\nvalue = settings["local-out"]\n'

        assert _find(source) == []

    def test_a_field_missing_from_the_items_of_a_list_endpoint_is_reported(self):
        source = (
            'for profile in fgt.get("ssl_ssh_profiles"):\n'
            '    version = profile["ssl-min-proto-ver"]\n'
        )

        assert _find(source) == [
            {"field": "ssl-min-proto-ver", "endpoints": ["ssl_ssh_profiles"], "line": 2}
        ]

    def test_an_index_before_the_key_keeps_the_origin(self):
        assert _fields('zone = fgt.get("interfaces")[0]["zone"]\n') == ["zone"]

    def test_a_nested_listed_field_is_not_reported(self):
        source = (
            'for profile in fgt.get("ssl_ssh_profiles"):\n'
            '    version = profile["https"]["min-allowed-ssl-version"]\n'
        )

        assert _find(source) == []

    def test_a_nested_field_missing_from_the_endpoint_is_reported(self):
        source = 'for p in fgt.get("ssl_ssh_profiles"):\n    v = p["https"]["tls-floor"]\n'

        assert _fields(source) == ["tls-floor"]

    def test_fields_read_inside_a_comprehension_are_checked(self):
        source = 'names = [a["name"] for a in fgt.get("admins") if a["super-user"] == "enable"]\n'

        assert _fields(source) == ["super-user"]

    def test_the_origin_follows_an_assignment_chain(self):
        source = (
            'admins = fgt.get("admins")\n'
            "ordered = sorted(admins)\n"
            "first = ordered[0]\n"
            'profile = first["profile-name"]\n'
        )

        assert _find(source) == [{"field": "profile-name", "endpoints": ["admins"], "line": 4}]

    def test_the_origin_follows_a_helper_parameter(self):
        source = (
            "def is_wan(iface):\n"
            '    return iface["zone"] == "wan"\n'
            "\n"
            'for iface in fgt.get("interfaces"):\n'
            "    flag = is_wan(iface)\n"
        )

        assert _find(source) == [{"field": "zone", "endpoints": ["interfaces"], "line": 2}]

    def test_the_origin_follows_a_helper_return_value(self):
        source = (
            "def admins():\n"
            '    return fgt.get("admins")\n'
            "\n"
            "for admin in admins():\n"
            '    value = admin["two-factor-status"]\n'
        )

        assert _fields(source) == ["two-factor-status"]

    def test_a_value_from_two_endpoints_accepts_a_field_of_either(self):
        source = (
            'rows = fgt.get("admins") + fgt.get("interfaces")\n'
            "for row in rows:\n"
            '    a = row["accprofile"]\n'
            '    b = row["role"]\n'
            '    c = row["nowhere"]\n'
        )

        assert _find(source) == [
            {"field": "nowhere", "endpoints": ["admins", "interfaces"], "line": 5}
        ]

    def test_each_field_is_reported_once_with_its_first_line(self):
        source = (
            'settings = fgt.get("log_settings")\n'
            'a = settings["event"]\n'
            'b = settings["event"]\n'
            'c = settings["admin"]\n'
        )

        assert _find(source) == [
            {"field": "event", "endpoints": ["log_settings"], "line": 2},
            {"field": "admin", "endpoints": ["log_settings"], "line": 4},
        ]


class TestWhatIsNotReported:
    def test_keys_of_a_dict_built_by_the_script(self):
        source = (
            'counts = {"total": 0, "enabled": 0}\n'
            'for admin in fgt.get("admins"):\n'
            '    counts["total"] = counts["total"] + 1\n'
            'evidence = str(counts["enabled"])\n'
        )

        assert _find(source) == []

    def test_keys_of_a_dict_that_copies_device_values(self):
        source = (
            'for admin in fgt.get("admins"):\n'
            '    row = {"label": admin["name"], "profile": admin["accprofile"]}\n'
            '    text = row["label"] + row["profile"]\n'
        )

        assert _find(source) == []

    def test_rows_built_by_a_helper_that_returns_a_dict(self):
        source = (
            "def summarize(admin):\n"
            '    return {"label": admin["name"]}\n'
            "\n"
            "rows = []\n"
            'for admin in fgt.get("admins"):\n'
            "    rows = rows + [summarize(admin)]\n"
            "for row in rows:\n"
            '    text = row["label"]\n'
        )

        assert _find(source) == []

    def test_rows_built_by_a_dict_comprehension(self):
        source = (
            'by_name = {a["name"]: a for a in fgt.get("admins")}\n'
            'root = by_name["admin"]\n'
            'other = by_name["missing-admin"]\n'
        )

        assert _find(source) == []

    def test_a_dict_whose_keys_the_script_assigns(self):
        source = (
            'summary = fgt.get("log_settings")\n'
            'summary["checked"] = True\n'
            'flag = summary["checked"]\n'
        )

        assert _find(source) == []

    def test_a_text_search_inside_a_field_value(self):
        source = (
            'for iface in fgt.get("interfaces"):\n'
            '    exposed = "https" in iface["allowaccess"] or "telnet" in iface["allowaccess"]\n'
        )

        assert _find(source) == []

    def test_a_membership_test_alone_is_not_enough_to_report(self):
        # `"x" in d` es ambiguo: puede ser una clave o una búsqueda de texto.
        source = 'settings = fgt.get("log_settings")\nhas = "zone" in settings\n'

        assert _find(source) == []

    def test_evidence_labels_and_status_literals(self):
        source = (
            'settings = fgt.get("log_settings")\n'
            'evidence = "fwpolicy-implicit-log=" + str(settings["fwpolicy-implicit-log"])\n'
            'report.finding("chk-0001", "pass", evidence, ["log_settings"])\n'
        )

        assert _find(source) == []

    def test_a_key_that_is_not_a_string_literal(self):
        source = (
            "def value(data, key):\n"
            "    return data[key] if key in data else None\n"
            "\n"
            'x = value(fgt.get("log_settings"), "admin")\n'
        )

        assert _find(source) == []

    def test_an_unverified_endpoint(self):
        source = 'for server in fgt.get("dhcp_servers"):\n    lease = server["lease-time"]\n'

        assert _find(source) == []

    def test_a_value_that_may_come_from_an_unverified_endpoint(self):
        source = (
            'rows = fgt.get("admins") + fgt.get("dhcp_servers")\n'
            "for row in rows:\n"
            '    lease = row["lease-time"]\n'
        )

        assert _find(source) == []

    def test_an_endpoint_whose_field_list_was_truncated(self):
        assert _find('port = fgt.get("system_global")["admin-https-port"]\n') == []

    def test_an_endpoint_the_catalogue_does_not_have(self):
        assert _find('value = fgt.get("ntp")["ntpsync"]\n') == []

    def test_a_key_that_cannot_be_a_schema_field_name(self):
        # El diagnóstico no lista los nombres que no tienen forma de campo de
        # esquema (`unlisted_field_count`); una clave así no se puede juzgar.
        source = 'iface = fgt.get("interfaces")[0]\na = iface["Snmp-Index"]\nb = iface["a b"]\n'

        assert _find(source) == []

    def test_a_variable_with_no_known_origin(self):
        source = 'def read(item):\n    return item["zone"]\n'

        assert _find(source) == []

    def test_a_script_that_does_not_parse(self):
        assert _find("def broken(:\n") == []

    def test_a_script_too_deep_to_analyse(self):
        source = "x = " + "(" * 200 + 'fgt.get("admins")' + ")" * 200 + '[0]["nope"]\n'

        assert isinstance(_find(source), list)


class TestLimits:
    def test_the_number_of_reported_references_is_capped(self):
        lines = ['settings = fgt.get("log_settings")']
        lines += [f'v{i} = settings["invented-{i}"]' for i in range(60)]

        references = _find("\n".join(lines) + "\n")

        assert len(references) == 60
        assert len(field_catalog.summarize(references)["references"]) == (
            field_catalog.MAX_LISTED_REFERENCES
        )
        assert field_catalog.summarize(references)["unknown_field_references"] == 60

    def test_the_summary_states_the_catalogue_version(self):
        source = f'value = fgt.get("log_settings")["{"a" * 64}"]\n'

        summary = field_catalog.summarize(_find(source), CATALOG)

        assert summary["fortios_version"] == "v7.6.8"
        assert summary["unknown_field_references"] == 1
        assert summary["references"] == [
            {"field": "a" * 64, "endpoints": ["log_settings"], "line": 1}
        ]

    def test_the_summary_of_a_clean_script_is_empty(self):
        assert field_catalog.summarize([], CATALOG) == {
            "fortios_version": "v7.6.8",
            "unknown_field_references": 0,
            "references": [],
        }
