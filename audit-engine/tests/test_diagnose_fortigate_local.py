"""
Tests for scripts/diagnose_fortigate_local.py: the read-only shape diagnostic.

The diagnostic repeats, for every endpoint of the client's catalogue, the GET
the pipeline does and reports the STRUCTURE of each answer: HTTP status,
envelope keys, type of `results`, item count and field names. It must never
print or store a value read from the device, and never the token.

HTTP is faked at `urlopen`; no network, AWS or FortiGate call is ever made.
"""

import importlib.util
import io
import json
import logging
import urllib.error
from pathlib import Path

import pytest

import fortigate_client

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
DIAG_PATH = SCRIPTS_DIR / "diagnose_fortigate_local.py"

HOST = "192.0.2.10"
TOKEN = "tkn-SENTINEL-do-not-leak-7f3a9c"

# Every string below stands for a value read from the device. None of them may
# reach stdout, stderr, the log or the JSON file.
SECRET_VALUES = [
    "VALUE-admin-name",
    "VALUE-comment text",
    "198.51.100.77",
    "VALUE-SERIAL-FGT0000",
    "VALUE-hostname",
    "VALUE-vdom-name",
    "value-profile-one",
    "value-profile-two",
    "VALUE-nested",
    "VALUE-revision-hash",
    "VALUE key with spaces",
    "VALUE-error-detail",
]


def _envelope(results, **extra):
    envelope = {
        "http_method": "GET",
        "revision": "VALUE-revision-hash",
        "results": results,
        "vdom": "VALUE-vdom-name",
        "path": "system",
        "name": "admin",
        "status": "success",
        "http_status": 200,
        "serial": "VALUE-SERIAL-FGT0000",
        "version": "v7.6.8",
        "build": 3610,
    }
    envelope.update(extra)
    return envelope


ADMIN_ITEMS = [
    {
        "name": "VALUE-admin-name",
        "q_origin_key": "VALUE-admin-name",
        "accprofile": "value-profile-one",
        "comments": "VALUE-comment text",
        "trusthost1": "198.51.100.77 255.255.255.255",
        "vdom": [{"name": "VALUE-vdom-name", "q_origin_key": "VALUE-vdom-name"}],
        "VALUE key with spaces": 1,
    },
    {
        "name": "VALUE-admin-name",
        "accprofile": "value-profile-two",
        "two-factor": "disable",
        "vdom": [],
    },
]

SINGLETON = {
    "hostname": "VALUE-hostname",
    "admintimeout": 5,
    "admin-https-redirect": "enable",
    "ntpserver": [{"id": 1, "server": "198.51.100.77"}],
    "nested": {"inner-field": "VALUE-nested"},
}

# A mapping whose KEYS are user-defined names: they are values, not fields.
KEYED_BY_NAME = {
    "value-profile-one": {"status": "enable", "comment": "VALUE-comment text"},
    "value-profile-two": {"status": "disable", "extra-field": 3},
}


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """Replaces `urlopen`. Answers by path; records every request."""

    def __init__(self, responses=None, default=None):
        self.responses = responses or {}
        self.default = default if default is not None else _envelope([])
        self.requests: list[dict] = []

    def __call__(self, request, context=None, timeout=None):
        self.requests.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "headers": dict(request.header_items()),
                "data": request.data,
                "context": context,
                "timeout": timeout,
            }
        )
        suffix = request.full_url.split("/api/v2/cmdb/", 1)[1]
        answer = self.responses.get(suffix, self.default)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return FakeResponse(answer)
        return FakeResponse(json.dumps(answer).encode("utf-8"))


def _http_error(code, body=None):
    payload = json.dumps(
        body
        if body is not None
        else {"http_status": code, "status": "error", "detail": "VALUE-error-detail"}
    ).encode("utf-8")
    return urllib.error.HTTPError(
        f"https://{HOST}/x", code, "VALUE-error-detail", {}, io.BytesIO(payload)
    )


@pytest.fixture
def diag():
    spec = importlib.util.spec_from_file_location("diagnose_fortigate_local", DIAG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("FORTIGATE_HOST", HOST)
    monkeypatch.setenv("FORTIGATE_TOKEN", TOKEN)
    monkeypatch.delenv("FORTIGATE_VERIFY_SSL", raising=False)
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET"):
        monkeypatch.delenv(name, raising=False)


def _run(diag, monkeypatch, tmp_path, http, *extra_args):
    monkeypatch.setattr(diag, "_urlopen", http)
    return diag.main(["--output-dir", str(tmp_path), *extra_args])


def _shapes(tmp_path) -> dict:
    (path,) = list(tmp_path.rglob("shapes.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def _endpoint(shapes, key) -> dict:
    (entry,) = [e for e in shapes["endpoints"] if e["key"] == key]
    return entry


class TestDescribeEnvelope:
    def test_list_of_objects(self, diag):
        shape = diag.describe_envelope(_envelope(ADMIN_ITEMS))

        assert shape["results_type"] == "list"
        assert shape["item_count"] == 2
        assert shape["item_types"] == {"dict": 2}
        assert sorted(shape["fields"]) == [
            "accprofile",
            "comments",
            "name",
            "q_origin_key",
            "trusthost1",
            "two-factor",
            "vdom",
        ]
        assert shape["fields"]["name"] == {"present_in": 2, "types": ["str"]}
        assert shape["fields"]["two-factor"]["present_in"] == 1
        assert shape["unprintable_field_count"] == 1
        assert shape["fields_truncated"] is False

    def test_child_table_fields_and_lengths(self, diag):
        shape = diag.describe_envelope(_envelope(ADMIN_ITEMS))

        vdom = shape["fields"]["vdom"]
        assert vdom["types"] == ["list"]
        assert vdom["list_len_min"] == 0
        assert vdom["list_len_max"] == 1
        assert vdom["item_fields"] == ["name", "q_origin_key"]

    def test_singleton_dict(self, diag):
        shape = diag.describe_envelope(_envelope(SINGLETON))

        assert shape["results_type"] == "dict"
        assert shape["item_count"] is None
        assert shape["keyed_by_name"] is False
        assert sorted(shape["fields"]) == [
            "admin-https-redirect",
            "admintimeout",
            "hostname",
            "nested",
            "ntpserver",
        ]
        assert shape["fields"]["admintimeout"]["types"] == ["int"]
        assert shape["fields"]["ntpserver"]["item_fields"] == ["id", "server"]
        assert shape["fields"]["nested"]["item_fields"] == ["inner-field"]

    def test_dict_keyed_by_user_defined_names_prints_counts_only(self, diag):
        shape = diag.describe_envelope(_envelope(KEYED_BY_NAME))

        assert shape["results_type"] == "dict"
        assert shape["keyed_by_name"] is True
        assert shape["item_count"] == 2
        assert sorted(shape["fields"]) == ["comment", "extra-field", "status"]
        assert "value-profile-one" not in json.dumps(shape)

    def test_empty_list(self, diag):
        shape = diag.describe_envelope(_envelope([]))

        assert shape["results_type"] == "list"
        assert shape["item_count"] == 0
        assert shape["fields"] == {}

    def test_empty_dict(self, diag):
        shape = diag.describe_envelope(_envelope({}))

        assert shape["results_type"] == "dict"
        assert shape["fields"] == {}
        assert shape["keyed_by_name"] is False

    def test_absent_results(self, diag):
        envelope = _envelope(None)
        del envelope["results"]

        shape = diag.describe_envelope(envelope)

        assert shape["results_type"] == "absent"
        assert shape["item_count"] is None
        assert "results" not in shape["envelope_keys"]

    def test_null_and_scalar_results(self, diag):
        assert diag.describe_envelope(_envelope(None))["results_type"] == "null"
        assert diag.describe_envelope(_envelope("VALUE-nested"))["results_type"] == "str"

    def test_envelope_keys_are_names_only(self, diag):
        shape = diag.describe_envelope(_envelope([]))

        assert shape["envelope_keys"] == sorted(_envelope([]))
        assert shape["api_status"] == "success"

    def test_envelope_that_is_not_an_object(self, diag):
        shape = diag.describe_envelope(["VALUE-nested"])

        assert shape["results_type"] == "absent"
        assert shape["envelope_keys"] == []

    def test_envelope_counters_are_reported(self, diag):
        shape = diag.describe_envelope(_envelope([], size=4, matched_count=7))

        assert shape["envelope_counts"] == {"matched_count": 7, "size": 4}

    def test_field_names_are_capped(self, diag):
        item = {f"field-{i:04d}": i for i in range(diag.MAX_FIELD_NAMES + 25)}

        shape = diag.describe_envelope(_envelope([item]))

        assert len(shape["fields"]) == diag.MAX_FIELD_NAMES
        assert shape["fields_truncated"] is True
        assert shape["field_count"] == diag.MAX_FIELD_NAMES + 25

    def test_counts_only_omits_every_field_name(self, diag):
        shape = diag.describe_envelope(_envelope(ADMIN_ITEMS), counts_only=True)

        assert shape["fields"] == {}
        assert shape["field_count"] == 7
        assert shape["item_count"] == 2


class TestProbe:
    def _client(self, verify_ssl=True):
        return fortigate_client.FortiGateClient(host=HOST, token=TOKEN, verify_ssl=verify_ssl)

    def test_reuses_the_client_url_headers_and_tls_and_only_gets(self, diag, monkeypatch):
        http = FakeHttp({"system/admin": _envelope(ADMIN_ITEMS)})
        monkeypatch.setattr(diag, "_urlopen", http)
        client = self._client(verify_ssl=False)

        result = diag.probe(client, "system/admin")

        (request,) = http.requests
        assert request["url"] == f"{client.base_url}/system/admin"
        assert request["method"] == "GET"
        assert request["data"] is None
        assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert request["context"] is client.ssl_context
        assert request["timeout"] == diag.REQUEST_TIMEOUT_S == 15
        assert result["answered"] is True
        assert result["http_status"] == 200
        assert result["error"] is None

    def test_http_error_keeps_status_and_envelope_shape(self, diag, monkeypatch):
        monkeypatch.setattr(diag, "_urlopen", FakeHttp({"system/admin": _http_error(403)}))

        result = diag.probe(self._client(), "system/admin")

        assert result["answered"] is False
        assert result["http_status"] == 403
        assert result["error"] == "http_error"
        assert result["envelope"] == {
            "http_status": 403,
            "status": "error",
            "detail": "VALUE-error-detail",
        }

    def test_network_error_reports_only_the_error_class(self, diag, monkeypatch):
        error = urllib.error.URLError(TimeoutError("VALUE-error-detail"))
        monkeypatch.setattr(diag, "_urlopen", FakeHttp({"system/admin": error}))

        result = diag.probe(self._client(), "system/admin")

        assert result["answered"] is False
        assert result["http_status"] is None
        assert result["error"] == "network_error:TimeoutError"
        assert result["envelope"] is None

    def test_body_that_is_not_json(self, diag, monkeypatch):
        monkeypatch.setattr(diag, "_urlopen", FakeHttp({"system/admin": b"<html>VALUE-nested"}))

        result = diag.probe(self._client(), "system/admin")

        assert result["answered"] is False
        assert result["http_status"] == 200
        assert result["error"] == "invalid_json"

    def test_unexpected_exception_does_not_propagate(self, diag, monkeypatch):
        error = ValueError(f"Invalid header value b'Bearer {TOKEN}'")
        monkeypatch.setattr(diag, "_urlopen", FakeHttp({"system/admin": error}))

        result = diag.probe(self._client(), "system/admin")

        assert result["answered"] is False
        assert result["error"] == "unexpected:ValueError"
        assert TOKEN not in json.dumps(result)


class TestMain:
    def test_probes_every_catalogue_endpoint_once_with_get(self, diag, monkeypatch, tmp_path):
        http = FakeHttp()

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 0
        paths = [r["url"].split("/api/v2/cmdb/", 1)[1] for r in http.requests]
        assert sorted(paths) == sorted(path for path, _ in fortigate_client.ENDPOINTS)
        assert {r["method"] for r in http.requests} == {"GET"}
        shapes = _shapes(tmp_path)
        assert [e["key"] for e in shapes["endpoints"]] == [
            key for _, key in fortigate_client.ENDPOINTS
        ]

    def test_json_file_holds_the_shape_of_each_answer(self, diag, monkeypatch, tmp_path):
        http = FakeHttp(
            {
                "system/admin": _envelope(ADMIN_ITEMS),
                "system/global": _envelope(SINGLETON),
                "system/ntp": _http_error(403),
            }
        )

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 1
        shapes = _shapes(tmp_path)
        admins = _endpoint(shapes, "admins")
        assert admins["path"] == "system/admin"
        assert admins["answered"] is True
        assert admins["http_status"] == 200
        assert admins["results_type"] == "list"
        assert admins["item_count"] == 2
        assert "accprofile" in admins["fields"]
        ntp = _endpoint(shapes, "ntp")
        assert ntp["answered"] is False
        assert ntp["http_status"] == 403
        assert ntp["error"] == "http_error"
        assert ntp["envelope_keys"] == ["detail", "http_status", "status"]
        assert shapes["summary"] == {
            "total": len(fortigate_client.ENDPOINTS),
            "answered": len(fortigate_client.ENDPOINTS) - 1,
            "empty_list": len(fortigate_client.ENDPOINTS) - 3,
            "failed": 1,
            "not_requested": 0,
        }

    def test_stdout_has_a_table_and_a_summary(self, diag, monkeypatch, tmp_path, capsys):
        http = FakeHttp({"system/admin": _envelope(ADMIN_ITEMS), "system/ntp": _http_error(403)})

        _run(diag, monkeypatch, tmp_path, http)

        out = capsys.readouterr().out
        admins_line = next(line for line in out.splitlines() if line.startswith("admins "))
        assert "system/admin" in admins_line
        assert "200" in admins_line
        assert "list" in admins_line
        ntp_line = next(line for line in out.splitlines() if line.startswith("ntp "))
        assert "403" in ntp_line
        total = len(fortigate_client.ENDPOINTS)
        assert f"answered {total - 1} of {total}" in out
        assert f"empty list: {total - 2}" in out
        assert "failed: 1" in out
        assert "shapes.json" in out

    def test_field_names_of_the_focus_endpoints_are_printed(
        self, diag, monkeypatch, tmp_path, capsys
    ):
        http = FakeHttp(
            {"system/admin": _envelope(ADMIN_ITEMS), "system/global": _envelope(SINGLETON)}
        )

        _run(diag, monkeypatch, tmp_path, http)

        out = capsys.readouterr().out
        assert "two-factor" in out
        assert "trusthost1" in out
        assert "vdom[]: name, q_origin_key" in out
        assert "admintimeout" not in out
        for key in ("admins", "api_users", "admin_profiles", "ntp", "fortiguard", "log_settings"):
            assert key in diag.FOCUS_ENDPOINTS

    def test_fortios_version_and_build_are_reported_but_not_the_serial(
        self, diag, monkeypatch, tmp_path, capsys
    ):
        _run(diag, monkeypatch, tmp_path, FakeHttp())

        shapes = _shapes(tmp_path)
        assert shapes["fortios"] == {"version": "v7.6.8", "build": 3610}
        assert "v7.6.8" in capsys.readouterr().out
        assert "serial" not in shapes["fortios"]

    def test_unexpected_version_text_is_not_copied(self, diag, monkeypatch, tmp_path):
        http = FakeHttp(default=_envelope([], version="VALUE-hostname", build="VALUE-nested"))

        _run(diag, monkeypatch, tmp_path, http)

        assert _shapes(tmp_path)["fortios"] is None

    def test_only_selects_endpoints(self, diag, monkeypatch, tmp_path):
        http = FakeHttp()

        exit_code = _run(diag, monkeypatch, tmp_path, http, "--only", "admins,api_users")

        assert exit_code == 0
        assert [e["key"] for e in _shapes(tmp_path)["endpoints"]] == ["admins", "api_users"]
        assert len(http.requests) == 2

    def test_unknown_endpoint_in_only_is_a_config_error(self, diag, monkeypatch, tmp_path):
        http = FakeHttp()

        exit_code = _run(diag, monkeypatch, tmp_path, http, "--only", "admins,nope")

        assert exit_code == 2
        assert http.requests == []

    def test_counts_only_flag(self, diag, monkeypatch, tmp_path, capsys):
        http = FakeHttp({"system/admin": _envelope(ADMIN_ITEMS)})

        _run(diag, monkeypatch, tmp_path, http, "--counts-only")

        admins = _endpoint(_shapes(tmp_path), "admins")
        assert admins["fields"] == {}
        assert admins["field_count"] == 7
        out = capsys.readouterr().out
        assert "trusthost1" not in out
        assert "Field names" not in out

    def test_global_scope_probe_repeats_empty_lists_only(self, diag, monkeypatch, tmp_path):
        http = FakeHttp(
            {
                "system/admin": _envelope([]),
                "system/admin?scope=global": _envelope(ADMIN_ITEMS),
                "system/api-user": _envelope(ADMIN_ITEMS),
            }
        )

        _run(
            diag, monkeypatch, tmp_path, http, "--only", "admins,api_users", "--probe-global-scope"
        )

        urls = [r["url"].split("/api/v2/cmdb/", 1)[1] for r in http.requests]
        assert urls == ["system/admin", "system/admin?scope=global", "system/api-user"]
        assert {r["method"] for r in http.requests} == {"GET"}
        shapes = _shapes(tmp_path)
        assert _endpoint(shapes, "admins")["item_count"] == 0
        assert _endpoint(shapes, "admins")["scope_global"]["item_count"] == 2
        assert "scope_global" not in _endpoint(shapes, "api_users")

    def test_global_scope_field_names_are_printed_for_focus_endpoints(
        self, diag, monkeypatch, tmp_path, capsys
    ):
        http = FakeHttp(
            {
                "system/admin": _envelope([]),
                "system/admin?scope=global": _envelope(ADMIN_ITEMS),
            }
        )

        _run(diag, monkeypatch, tmp_path, http, "--only", "admins", "--probe-global-scope")

        out = capsys.readouterr().out
        assert "admins (system/admin?scope=global): " in out
        assert "trusthost1" in out
        assert "scope=global: http 200, items 2" in out

    def test_two_runs_do_not_overwrite_each_other(self, diag, monkeypatch, tmp_path):
        stamps = iter(["20261122T120000Z", "20261122T120500Z"])
        monkeypatch.setattr(diag, "_run_stamp", lambda: next(stamps))

        _run(diag, monkeypatch, tmp_path, FakeHttp())
        _run(diag, monkeypatch, tmp_path, FakeHttp())

        assert len(list(tmp_path.rglob("shapes.json"))) == 2

    def test_default_output_directory_is_git_ignored(self, diag):
        engine_dir = SCRIPTS_DIR.parent
        assert diag.DEFAULT_OUTPUT_DIR == engine_dir / "local-runs" / "diagnostics"
        root_ignore = (engine_dir.parent / ".gitignore").read_text(encoding="utf-8")
        assert "audit-engine/local-runs/" in root_ignore.splitlines()


class TestFailures:
    def test_first_request_failure_aborts_with_guidance(self, diag, monkeypatch, tmp_path, capsys):
        error = urllib.error.URLError(TimeoutError("VALUE-error-detail"))
        http = FakeHttp(default=error)

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 3
        assert len(http.requests) == 1
        assert list(tmp_path.rglob("shapes.json")) == []
        err = capsys.readouterr().err
        assert "VPN" in err
        assert "trusted host" in err.lower()
        assert "port" in err.lower()
        assert "FORTIGATE_VERIFY_SSL" in err

    def test_first_request_http_error_also_aborts(self, diag, monkeypatch, tmp_path, capsys):
        http = FakeHttp(default=_http_error(401))

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 3
        assert len(http.requests) == 1
        assert "401" in capsys.readouterr().err

    def test_later_failures_are_reported_and_exit_code_is_one(self, diag, monkeypatch, tmp_path):
        http = FakeHttp({"system/ntp": _http_error(403), "system/ha": _http_error(404)})

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 1
        assert _shapes(tmp_path)["summary"]["failed"] == 2
        assert len(http.requests) == len(fortigate_client.ENDPOINTS)

    def test_stops_after_consecutive_network_failures(self, diag, monkeypatch, tmp_path, capsys):
        first_path = fortigate_client.ENDPOINTS[0][0]
        error = urllib.error.URLError(TimeoutError("VALUE-error-detail"))
        http = FakeHttp({first_path: _envelope(SINGLETON)}, default=error)

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 1
        assert len(http.requests) == 1 + diag.MAX_CONSECUTIVE_NETWORK_FAILURES
        shapes = _shapes(tmp_path)
        assert shapes["summary"]["not_requested"] > 0
        assert "stopped" in capsys.readouterr().err.lower()

    @pytest.mark.parametrize("missing", ["FORTIGATE_HOST", "FORTIGATE_TOKEN"])
    def test_missing_env_var_fails_with_a_clear_message(
        self, diag, monkeypatch, tmp_path, capsys, missing
    ):
        monkeypatch.delenv(missing)
        http = FakeHttp()

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        assert exit_code == 2
        assert missing in capsys.readouterr().err
        assert http.requests == []

    def test_token_with_inner_whitespace_is_rejected_without_echo(
        self, diag, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("FORTIGATE_TOKEN", "abc\ndef-SECRETPART")
        http = FakeHttp()

        exit_code = _run(diag, monkeypatch, tmp_path, http)

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "SECRETPART" not in captured.out + captured.err
        assert http.requests == []

    def test_token_cannot_be_passed_as_an_argument(self, diag, monkeypatch, tmp_path):
        monkeypatch.setattr(diag, "_urlopen", FakeHttp())

        with pytest.raises(SystemExit) as excinfo:
            diag.main(["--output-dir", str(tmp_path), "--token", "x"])

        assert excinfo.value.code == 2


class TestNothingFromTheDeviceLeaks:
    def _responses(self):
        return {
            "system/global": _envelope(SINGLETON),
            "system/admin": _envelope(ADMIN_ITEMS),
            "system/api-user": _envelope(ADMIN_ITEMS),
            "system/accprofile": _envelope(KEYED_BY_NAME),
            "system/ntp": _envelope(SINGLETON),
            "system/fortiguard": _envelope("VALUE-nested"),
            "log/setting": _http_error(403),
            "system/ha": b"<html>VALUE-hostname</html>",
            "system/dns": ["VALUE-nested", {"VALUE key with spaces": "VALUE-nested"}],
        }

    def _everything_written(self, tmp_path, capsys, caplog) -> str:
        captured = capsys.readouterr()
        files = "".join(
            path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file()
        )
        records = "".join(record.getMessage() for record in caplog.records)
        return captured.out + captured.err + caplog.text + records + files

    @pytest.mark.parametrize("extra_args", [[], ["--counts-only"], ["--probe-global-scope"]])
    def test_no_device_value_reaches_stdout_log_or_file(
        self, diag, monkeypatch, tmp_path, capsys, caplog, extra_args
    ):
        caplog.set_level(logging.DEBUG)
        http = FakeHttp(self._responses(), default=_envelope(ADMIN_ITEMS))

        _run(diag, monkeypatch, tmp_path, http, *extra_args)

        written = self._everything_written(tmp_path, capsys, caplog)
        assert "shapes.json" in written
        for value in SECRET_VALUES:
            assert value not in written, value

    def test_token_and_host_never_reach_stdout_log_or_file(
        self, diag, monkeypatch, tmp_path, capsys, caplog
    ):
        caplog.set_level(logging.DEBUG)
        http = FakeHttp(self._responses())

        _run(diag, monkeypatch, tmp_path, http)

        written = self._everything_written(tmp_path, capsys, caplog)
        assert TOKEN not in written
        assert HOST not in written

    def test_token_in_an_exception_text_is_not_printed(
        self, diag, monkeypatch, tmp_path, capsys, caplog
    ):
        caplog.set_level(logging.DEBUG)
        error = ValueError(f"Invalid header value b'Bearer {TOKEN}'")
        http = FakeHttp({"system/admin": error})

        _run(diag, monkeypatch, tmp_path, http)

        assert TOKEN not in self._everything_written(tmp_path, capsys, caplog)

    def test_logging_setup_is_restored_after_the_run(self, diag, monkeypatch, tmp_path):
        root = logging.getLogger()
        handlers_before = list(root.handlers)
        filters_before = [list(h.filters) for h in handlers_before]

        _run(diag, monkeypatch, tmp_path, FakeHttp())

        assert list(root.handlers) == handlers_before
        assert [list(h.filters) for h in handlers_before] == filters_before


class TestPackagingAndDependencies:
    @pytest.mark.parametrize(
        "name", ["diagnose_fortigate_local.py", "local_run_common.py", "run_executor_local.py"]
    )
    def test_local_scripts_are_not_part_of_the_lambda_package(self, name):
        engine_dir = SCRIPTS_DIR.parent
        assert (SCRIPTS_DIR / name).is_file()
        for area in ("generator", "executor", "contracts", "legacy"):
            assert not (engine_dir / area / name).exists(), area
        terraform = (engine_dir.parent / "infrastructure/pipeline/lambda.tf").read_text(
            encoding="utf-8"
        )
        assert 'for area in ["generator", "executor", "contracts", "legacy"]' in terraform

    def test_diagnostic_needs_no_aws_sdk(self):
        for name in ("diagnose_fortigate_local.py", "local_run_common.py"):
            source = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("boto3", "botocore", "s3_io", "reporter", "handler_executor"):
                assert f"import {forbidden}" not in source, (name, forbidden)
                assert f"from {forbidden}" not in source, (name, forbidden)

    def test_diagnostic_only_issues_get_requests(self):
        source = DIAG_PATH.read_text(encoding="utf-8")
        for forbidden in ('method="POST"', 'method="PUT"', 'method="DELETE"', "data="):
            assert forbidden not in source, forbidden
