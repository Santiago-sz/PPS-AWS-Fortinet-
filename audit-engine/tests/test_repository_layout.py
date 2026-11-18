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
            if isinstance(node, ast.Import | ast.ImportFrom)
        ]
        for node in imports:
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            assert not {"llm_client", "bedrock_client"}.intersection(names)


def test_knowledge_retriever_is_packaged_with_the_generator():
    engine = ROOT / "audit-engine"
    assert (engine / "generator/knowledge_retriever.py").is_file()
    owners = [
        area
        for area in ("generator", "executor", "contracts", "legacy")
        if (engine / area / "knowledge_retriever.py").exists()
    ]
    assert owners == ["generator"]
    terraform = (ROOT / "infrastructure/pipeline/lambda.tf").read_text(encoding="utf-8")
    assert 'for area in ["generator", "executor", "contracts", "legacy"]' in terraform
    assert 'fileset("${path.module}/../../audit-engine/${area}", "*.py")' in terraform


def test_executor_does_not_import_knowledge_retriever_or_bedrock_clients():
    for module in (ROOT / "audit-engine/executor").glob("*.py"):
        source = module.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert "knowledge_retriever" not in names, module.name
        assert "bedrock" not in source.lower(), module.name
