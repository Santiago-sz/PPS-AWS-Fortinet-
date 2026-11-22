"""
Tests for scripts/stig_to_markdown.py: DISA XCCDF benchmark to Markdown.

The knowledge base ingests Markdown, not XCCDF. The converter must keep every
rule of the benchmark as one clearly delimited section (group id, rule id,
STIG id, severity, title, description, check text and fix text), keep the
source text verbatim, and refuse XML that declares a DTD or entities, because
the input is a downloaded file.

The fixture is synthetic: no DISA content is versioned in this repository.
"""

import importlib.util
from pathlib import Path

import pytest

CONVERTER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stig_to_markdown.py"

RULE_TEMPLATE = (
    '<Group id="{group}"><title>{srg}</title>'
    "<description>&lt;GroupDescription&gt;&lt;/GroupDescription&gt;</description>"
    '<Rule id="{rule}" weight="10.0" severity="{severity}">'
    "<version>{stig_id}</version><title>{title}</title>"
    "<description>&lt;VulnDiscussion&gt;{discussion}&lt;/VulnDiscussion&gt;"
    "&lt;FalsePositives&gt;&lt;/FalsePositives&gt;"
    "&lt;Documentable&gt;false&lt;/Documentable&gt;</description>"
    '<ident system="http://cyber.mil/cci">{cci}</ident>'
    '<fixtext fixref="F-1_fix">{fix}</fixtext><fix id="F-1_fix" />'
    '<check system="C-1_chk"><check-content>{check}</check-content></check>'
    "</Rule></Group>"
)

BENCHMARK_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Benchmark xmlns:dc="http://purl.org/dc/elements/1.1/" id="Sample_STIG" '
    'xmlns="http://checklists.nist.gov/xccdf/1.1">'
    '<status date="2026-08-24">accepted</status>'
    "<title>Sample Device Security Technical Implementation Guide</title>"
    "<description>Published as a tool to improve security.</description>"
    '<notice id="terms-of-use" xml:lang="en">{notice}</notice>'
    '<reference href="https://cyber.mil"><dc:publisher>DISA</dc:publisher></reference>'
    '<plain-text id="release-info">Release: 5 Benchmark Date: 30 Sep 2026</plain-text>'
    "<version>1</version>"
    '<Profile id="MAC-1_Public"><title>I - Public</title></Profile>'
    "{groups}</Benchmark>"
)

FIRST_RULE = {
    "group": "V-100001",
    "srg": "SRG-NET-000019-FW-000003",
    "rule": "SV-100001r1_rule",
    "severity": "high",
    "stig_id": "SMPL-FW-000005",
    "title": "The device must filter traffic by packet headers.",
    "discussion": "Information flow control regulates traffic.\n\nSecond paragraph.",
    "cci": "CCI-001414",
    "fix": "Run the following command:\n# config firewall policy\n#   set logtraffic all\n# end",
    "check": 'Verify no policy uses "any".\n\nIf one does, this is a finding.',
}

SECOND_RULE = {
    "group": "V-100002",
    "srg": "SRG-NET-000061-FW-000001",
    "rule": "SV-100002r2_rule",
    "severity": "low",
    "stig_id": "SMPL-FW-000010",
    "title": "The device must log to a central server &amp; keep local logs.",
    "discussion": "Central logging supports audits.",
    "cci": "CCI-000169",
    "fix": "Configure a syslog server.",
    "check": "Review the log settings.",
}


def build_benchmark(*rules, notice=""):
    groups = "".join(RULE_TEMPLATE.format(**rule) for rule in rules)
    return BENCHMARK_TEMPLATE.format(groups=groups, notice=notice).encode("utf-8")


@pytest.fixture(scope="module")
def converter():
    spec = importlib.util.spec_from_file_location("stig_to_markdown", CONVERTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def markdown(converter):
    return converter.convert(build_benchmark(FIRST_RULE, SECOND_RULE))


def rule_sections(markdown):
    """Splits the document on the rule delimiter; the first part is the header."""
    return markdown.split("\n---\n")


class TestHeader:
    def test_title_is_the_benchmark_title(self, markdown):
        assert markdown.startswith("# Sample Device Security Technical Implementation Guide\n")

    def test_header_keeps_identification_and_release(self, markdown):
        header = rule_sections(markdown)[0]
        assert "Sample_STIG" in header
        assert "DISA" in header
        assert "Release: 5 Benchmark Date: 30 Sep 2026" in header
        assert "2026-08-24" in header
        assert "Rules: 2" in header

    def test_empty_notice_is_reported_as_empty(self, markdown):
        assert "Terms-of-use notice: (empty in the source benchmark)" in rule_sections(markdown)[0]

    def test_notice_text_is_kept_when_present(self, converter):
        result = converter.convert(build_benchmark(FIRST_RULE, notice="Approved for release."))
        assert "Terms-of-use notice: Approved for release." in rule_sections(result)[0]


class TestRuleSections:
    def test_one_section_per_rule_in_document_order(self, markdown):
        sections = rule_sections(markdown)
        assert len(sections) == 3
        assert sections[1].lstrip().startswith("## V-100001 ")
        assert sections[2].lstrip().startswith("## V-100002 ")

    def test_section_carries_every_identifier(self, markdown):
        section = rule_sections(markdown)[1]
        assert "The device must filter traffic by packet headers." in section
        assert "- Rule ID: SV-100001r1_rule" in section
        assert "- STIG ID: SMPL-FW-000005" in section
        assert "- SRG: SRG-NET-000019-FW-000003" in section
        assert "- CCI: CCI-001414" in section

    @pytest.mark.parametrize(
        ("severity", "expected"),
        [("high", "high (CAT I)"), ("medium", "medium (CAT II)"), ("low", "low (CAT III)")],
    )
    def test_severity_names_the_disa_category(self, converter, severity, expected):
        rule = dict(FIRST_RULE, severity=severity)
        section = rule_sections(converter.convert(build_benchmark(rule)))[1]
        assert f"- Severity: {expected}" in section

    def test_description_is_only_the_vulnerability_discussion(self, markdown):
        section = rule_sections(markdown)[1]
        assert "Information flow control regulates traffic.\n\nSecond paragraph." in section
        assert "VulnDiscussion" not in section
        assert "Documentable" not in section
        assert "false" not in section

    def test_check_and_fix_text_are_verbatim_in_their_own_blocks(self, markdown):
        section = rule_sections(markdown)[1]
        description, check, fix = (
            section.index("### Description"),
            section.index("### Check"),
            section.index("### Fix"),
        )
        assert description < check < fix
        assert (
            'Verify no policy uses "any".\n\nIf one does, this is a finding.' in section[check:fix]
        )
        assert "# config firewall policy\n#   set logtraffic all\n# end" in section[fix:]

    def test_cli_comment_lines_do_not_become_headings(self, markdown):
        headings = [line for line in markdown.splitlines() if line.startswith("#")]
        outside_fences = []
        fenced = False
        for line in markdown.splitlines():
            if line.startswith("```"):
                fenced = not fenced
            elif line.startswith("#") and not fenced:
                outside_fences.append(line)
        assert "# config firewall policy" in headings
        assert all(line.startswith(("# Sample", "## V-", "### ")) for line in outside_fences)

    def test_xml_entities_are_decoded(self, markdown):
        assert "central server & keep local logs" in rule_sections(markdown)[2]

    def test_fence_grows_when_the_text_contains_a_fence(self, converter):
        rule = dict(FIRST_RULE, fix="Example:\n```\nset x\n```\nDone.")
        section = rule_sections(converter.convert(build_benchmark(rule)))[1]
        assert "````text\nExample:\n```\nset x\n```\nDone.\n````" in section

    def test_missing_fix_text_is_stated_not_hidden(self, converter):
        source = build_benchmark(FIRST_RULE).replace(
            b'<fixtext fixref="F-1_fix">' + FIRST_RULE["fix"].encode() + b"</fixtext>", b""
        )
        section = rule_sections(converter.convert(source))[1]
        assert "### Fix\n\nNot provided in the source benchmark." in section


class TestUntrustedInput:
    @pytest.mark.parametrize(
        "declaration",
        [
            b'<!DOCTYPE Benchmark SYSTEM "http://example.invalid/x.dtd">',
            b'<!DOCTYPE b [<!ENTITY a "aaaa">]>',
        ],
    )
    def test_dtd_and_entity_declarations_are_rejected(self, converter, declaration):
        source = build_benchmark(FIRST_RULE).replace(b"?>", b"?>" + declaration, 1)
        with pytest.raises(ValueError, match="DTD"):
            converter.convert(source)

    def test_document_that_is_not_a_benchmark_is_rejected(self, converter):
        with pytest.raises(ValueError, match="Benchmark"):
            converter.convert(b'<?xml version="1.0"?><html><body/></html>')

    def test_benchmark_without_rules_is_rejected(self, converter):
        with pytest.raises(ValueError, match="no rules"):
            converter.convert(build_benchmark())


class TestCommandLine:
    def test_writes_utf8_markdown_with_unix_newlines(self, converter, tmp_path):
        source = tmp_path / "in" / "sample-xccdf.xml"
        source.parent.mkdir()
        source.write_bytes(build_benchmark(dict(FIRST_RULE, title="Regla con acentuación ñ")))
        target = tmp_path / "out" / "sample.md"
        target.parent.mkdir()

        assert converter.main([str(source), str(target)]) == 0

        written = target.read_bytes()
        assert b"\r\n" not in written
        assert "Regla con acentuación ñ" in written.decode("utf-8")
        assert written.endswith(b"\n")

    def test_does_not_overwrite_an_existing_file(self, converter, tmp_path):
        source = tmp_path / "sample-xccdf.xml"
        source.write_bytes(build_benchmark(FIRST_RULE))
        target = tmp_path / "sample.md"
        target.write_text("keep", encoding="utf-8")

        assert converter.main([str(source), str(target)]) == 2
        assert target.read_text(encoding="utf-8") == "keep"
