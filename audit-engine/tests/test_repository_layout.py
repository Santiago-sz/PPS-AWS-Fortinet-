"""Contratos de ubicación y empaquetado después de separar componentes."""

import ast
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").exists())


def test_components_are_independent_roots():
    for directory in ("gui", "local-api", "audit-engine", "infrastructure/pipeline"):
        assert (ROOT / directory).is_dir(), directory
    assert not (ROOT / "audit-pipeline/api").exists()


def test_lambda_sources_are_flattenable_without_collisions():
    engine = ROOT / "audit-engine"
    modules = [
        p
        for area in ("generator", "executor", "contracts", "legacy")
        for p in (engine / area).glob("*.py")
    ]
    names = [p.name for p in modules]
    assert {"handler.py", "handler_generator.py", "handler_executor.py"} <= set(names)
    assert len(names) == len(set(names))
    available = {p.stem for p in modules}
    for module in modules:
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("handler", "llm_", "script_", "fortigate_")):
                        assert alias.name in available
    terraform = (ROOT / "infrastructure/pipeline/lambda.tf").read_text(encoding="utf-8")
    assert "filename = basename(source.value)" in terraform
    assert '"../../audit-engine/' in terraform


def test_executor_does_not_import_generator():
    for module in (ROOT / "audit-engine/executor").glob("*.py"):
        imports = [
            node
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in imports:
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            assert not {"llm_client", "bedrock_client"}.intersection(names)
