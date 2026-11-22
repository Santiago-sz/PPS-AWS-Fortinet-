"""
Converts a DISA XCCDF benchmark (a STIG "Manual-xccdf.xml") into Markdown.

The Bedrock knowledge base ingests Markdown but not XCCDF. This script writes
one clearly delimited section per rule, with the group id, rule id, STIG id,
severity, title, vulnerability discussion, check text and fix text. Check and
fix text are copied verbatim inside fenced blocks, so the FortiOS CLI lines
that start with "#" are not read as headings.

The input is a downloaded file and is treated as untrusted: a document that
declares a DTD or entities is rejected before parsing, and nothing from the
input is executed or resolved. Standard library only; this script is not part
of any Lambda package.

Usage:
    python scripts/stig_to_markdown.py <benchmark-xccdf.xml> <output.md>

The corpus procedure is in docs/context/rag/corpus.md.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

RULE_DELIMITER = "---"
MISSING_TEXT = "Not provided in the source benchmark."
EMPTY_NOTICE = "(empty in the source benchmark)"

# DISA severity category codes, as defined in the STIG overview documents.
SEVERITY_CATEGORIES = {"high": "CAT I", "medium": "CAT II", "low": "CAT III"}

_FORBIDDEN_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")
_DISCUSSION_PATTERN = re.compile(r"<VulnDiscussion>(.*?)</VulnDiscussion>", re.DOTALL)
_FENCE_PATTERN = re.compile(r"`{3,}")


def _local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def _children(element, name):
    return [child for child in element if _local_name(child) == name]


def _child_text(element, name):
    """Text of the first direct child with that local name, or an empty string."""
    for child in _children(element, name):
        return (child.text or "").strip()
    return ""


def _parse(xml_bytes):
    if any(declaration in xml_bytes for declaration in _FORBIDDEN_DECLARATIONS):
        raise ValueError("XML with a DTD or entity declarations is not accepted")
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as error:
        raise ValueError(f"The input is not well-formed XML: {error}") from None
    if _local_name(root) != "Benchmark":
        raise ValueError("The root element is not an XCCDF Benchmark")
    return root


def _vulnerability_discussion(description):
    """
    The rule description embeds a second, escaped XML fragment. Only the
    vulnerability discussion carries prose; the other fields are empty flags.
    """
    match = _DISCUSSION_PATTERN.search(description)
    return (match.group(1) if match else description).strip()


def _prose(text):
    """Keeps the text as is, except that a leading "#" must not open a heading."""
    if not text:
        return MISSING_TEXT
    return "\n".join("\\" + line if line.startswith("#") else line for line in text.splitlines())


def _fenced(text):
    if not text:
        return MISSING_TEXT
    longest = max((len(run) for run in _FENCE_PATTERN.findall(text)), default=2)
    fence = "`" * (longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _header(root, rule_count):
    status = _children(root, "status")
    status_text = ""
    if status:
        status_text = f"{(status[0].text or '').strip()} ({status[0].get('date', 'no date')})"
    reference = _children(root, "reference")
    publisher = _child_text(reference[0], "publisher") if reference else ""
    reference_url = reference[0].get("href", "") if reference else ""
    release = ""
    for plain_text in _children(root, "plain-text"):
        if plain_text.get("id") == "release-info":
            release = (plain_text.text or "").strip()

    lines = [
        f"# {_child_text(root, 'title')}",
        "",
        f"- Benchmark ID: {root.get('id', '')}",
        f"- Publisher: {publisher}",
        f"- Version: {_child_text(root, 'version')}",
        f"- Release information: {release}",
        f"- Status: {status_text}",
        f"- Reference: {reference_url}",
        f"- Rules: {rule_count}",
        f"- Terms-of-use notice: {_child_text(root, 'notice') or EMPTY_NOTICE}",
        "- Format: converted from the XCCDF benchmark to Markdown, one section per rule; "
        "titles, discussion, check text and fix text are the source text.",
        "",
        _prose(_child_text(root, "description")),
    ]
    return "\n".join(lines)


def _rule_section(group, rule):
    severity = rule.get("severity", "")
    category = SEVERITY_CATEGORIES.get(severity)
    severity_text = f"{severity} ({category})" if category else severity or "not stated"
    identifiers = [(ident.text or "").strip() for ident in _children(rule, "ident")]
    checks = _children(rule, "check")
    check_text = _child_text(checks[0], "check-content") if checks else ""

    lines = [
        f"## {group.get('id', '')} - {_child_text(rule, 'title')}",
        "",
        f"- Rule ID: {rule.get('id', '')}",
        f"- STIG ID: {_child_text(rule, 'version')}",
        f"- Severity: {severity_text}",
        f"- SRG: {_child_text(group, 'title')}",
        f"- CCI: {', '.join(identifiers) or 'not stated'}",
        "",
        "### Description",
        "",
        _prose(_vulnerability_discussion(_child_text(rule, "description"))),
        "",
        "### Check",
        "",
        _fenced(check_text),
        "",
        "### Fix",
        "",
        _fenced(_child_text(rule, "fixtext")),
    ]
    return "\n".join(lines)


def convert(xml_bytes):
    """Returns the Markdown document for an XCCDF benchmark given as bytes."""
    root = _parse(xml_bytes)
    rules = [
        (group, rule) for group in _children(root, "Group") for rule in _children(group, "Rule")
    ]
    if not rules:
        raise ValueError("The benchmark has no rules")
    parts = [_header(root, len(rules))]
    parts.extend(_rule_section(group, rule) for group, rule in rules)
    return f"\n\n{RULE_DELIMITER}\n\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("source", type=Path, help="XCCDF benchmark (Manual-xccdf.xml)")
    parser.add_argument("target", type=Path, help="Markdown file to create")
    arguments = parser.parse_args(argv)

    if arguments.target.exists():
        print(f"Refusing to overwrite {arguments.target}", file=sys.stderr)
        return 2
    try:
        markdown = convert(arguments.source.read_bytes())
    except ValueError as error:
        print(f"Cannot convert {arguments.source}: {error}", file=sys.stderr)
        return 1
    arguments.target.write_bytes(markdown.encode("utf-8"))
    print(f"{arguments.target}: {markdown.count(f'{chr(10)}{RULE_DELIMITER}{chr(10)}')} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
