"""
Contratos IaC/código de la Knowledge Base administrada de Amazon Bedrock.

Mismo criterio que `test_handler.py::TestTerraformEnvVarsMatchHandler`: se lee
el HCL real (sin ejecutar Terraform ni tocar AWS) para que el contrato entre
la infraestructura y `knowledge_retriever.py` se verifique en CI y no recién
en un despliegue.

Cubre dos módulos:
  - `infrastructure/pipeline/`: variables nuevas, entorno del generador y
    permiso `bedrock:Retrieve` condicional y acotado.
  - `infrastructure/knowledge-base/`: módulo aislado con su propio provider.
"""

import re
from pathlib import Path

import knowledge_retriever

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").exists())
PIPELINE = ROOT / "infrastructure" / "pipeline"
KNOWLEDGE_BASE = ROOT / "infrastructure" / "knowledge-base"


def _strip_comments(text: str) -> str:
    """Quita comentarios `#` de línea completa o al final de una línea HCL."""
    return re.sub(r"(?m)(^|\s)#.*$", "", text)


def _read(path: Path) -> str:
    assert path.is_file(), f"Falta {path.relative_to(ROOT).as_posix()}"
    return _strip_comments(path.read_text(encoding="utf-8"))


def _read_module(directory: Path) -> str:
    assert directory.is_dir(), f"Falta el módulo {directory.relative_to(ROOT).as_posix()}"
    return "\n".join(_read(p) for p in sorted(directory.glob("*.tf")))


def _block(text: str, kind: str, *labels: str) -> str:
    """Cuerpo de un bloque de primer nivel (`resource "a" "b" { ... }`)."""
    header = r"\s+".join([kind, *[rf'"{re.escape(label)}"' for label in labels]])
    match = re.search(rf"(?m)^{header}\s*\{{(.*?)\n\}}", text, re.DOTALL)
    assert match, f"No se encontró el bloque {kind} {' '.join(labels)}"
    return match.group(1)


def _environment_variables(lambda_tf: str, function: str) -> str:
    block = _block(lambda_tf, "resource", "aws_lambda_function", function)
    match = re.search(r"variables\s*=\s*\{(.*?)\n\s*\}", block, re.DOTALL)
    assert match, f"aws_lambda_function.{function} no declara environment.variables"
    return match.group(1)


class TestPipelineVariables:
    def test_knowledge_base_id_defaults_to_disabled(self):
        block = _block(_read(PIPELINE / "variables.tf"), "variable", "knowledge_base_id")

        assert re.search(r"type\s*=\s*string", block)
        assert re.search(r'default\s*=\s*""', block)

    def test_knowledge_base_id_validation_rejects_wildcards_and_arns(self):
        """El id termina dentro de un ARN de IAM: solo se admite vacio o un id
        alfanumerico (patron `KnowledgeBaseId` del modelo de servicio), de modo
        que un `*` o un ARN completo nunca lleguen al Resource."""
        block = _block(_read(PIPELINE / "variables.tf"), "variable", "knowledge_base_id")

        assert re.search(r"validation\s*\{", block), "falta el bloque validation"
        pattern = re.search(r'regex\("([^"]+)",\s*var\.knowledge_base_id\)', block)
        assert pattern, "la validacion debe usar una expresion regular sobre el id"
        compiled = re.compile(pattern.group(1))
        assert compiled.fullmatch("")
        assert compiled.fullmatch("KBTEST0001")
        for rejected in ("*", "KB*", "kb/other", "arn:aws:bedrock:us-east-1::x", "ABCDEFGHIJK"):
            assert not compiled.fullmatch(rejected), rejected

    def test_knowledge_base_max_results_has_default_and_range_validation(self):
        block = _block(_read(PIPELINE / "variables.tf"), "variable", "knowledge_base_max_results")

        assert re.search(r"type\s*=\s*number", block)
        assert re.search(r"default\s*=\s*5\b", block)
        assert re.search(r"validation\s*\{", block), "falta el bloque validation"
        assert re.search(r"var\.knowledge_base_max_results\s*>=\s*1\b", block)
        assert re.search(r"var\.knowledge_base_max_results\s*<=\s*100\b", block)

    def test_example_tfvars_documents_both_variables_commented(self):
        example = (PIPELINE / "terraform.tfvars.example").read_text(encoding="utf-8")

        assert re.search(r"(?m)^#\s*knowledge_base_id\s*=", example)
        assert re.search(r"(?m)^#\s*knowledge_base_max_results\s*=", example)


class TestGeneratorEnvironment:
    def test_generator_receives_the_env_vars_the_retriever_reads(self):
        env_block = _environment_variables(_read(PIPELINE / "lambda.tf"), "policy_generator")

        assert re.search(
            rf"\b{knowledge_retriever.KNOWLEDGE_BASE_ID_ENV}\b\s*=\s*var\.knowledge_base_id\b",
            env_block,
        )
        assert re.search(
            rf"\b{knowledge_retriever.KNOWLEDGE_BASE_MAX_RESULTS_ENV}\b\s*=\s*"
            r"(tostring\()?var\.knowledge_base_max_results\b",
            env_block,
        )

    def test_executor_and_assessor_do_not_receive_knowledge_base_env_vars(self):
        lambda_tf = _read(PIPELINE / "lambda.tf")

        for function in ("audit_executor", "assessor"):
            env_block = _environment_variables(lambda_tf, function)
            assert "KNOWLEDGE_BASE" not in env_block, function


class TestGeneratorRetrievePermission:
    EXACT_ARN = (
        '"arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}'
        ':knowledge-base/${var.knowledge_base_id}"'
    )

    def _policy(self, name: str) -> str:
        return _block(_read(PIPELINE / "iam.tf"), "resource", "aws_iam_role_policy", name)

    def test_generator_role_gets_retrieve_on_the_exact_knowledge_base(self):
        policy = self._policy("generator_knowledge_base")

        assert re.search(r"role\s*=\s*aws_iam_role\.generator\.id", policy)
        assert re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', policy) == ["bedrock:Retrieve"]
        assert re.search(r'Action\s*=\s*"bedrock:Retrieve"', policy)
        assert re.search(r'Effect\s*=\s*"Allow"', policy)
        resources = re.findall(r"(?m)^\s*Resource\s*=\s*(.+)$", policy)
        assert [r.strip() for r in resources] == [self.EXACT_ARN]

    def test_retrieve_permission_exists_only_when_the_id_is_set(self):
        """Con el id vacío el recurso no se crea: nunca hay un statement con
        Resource vacío o comodín, y la política principal no cambia."""
        policy = self._policy("generator_knowledge_base")

        assert re.search(r'count\s*=\s*var\.knowledge_base_id\s*!=\s*""\s*\?\s*1\s*:\s*0', policy)
        iam = _read(PIPELINE / "iam.tf")
        assert iam.count("bedrock:Retrieve") == 1, "el permiso solo vive en la política condicional"
        assert "bedrock:Retrieve" not in self._policy("generator_permissions")
        assert "knowledge" not in self._policy("generator_permissions").lower()

    def test_no_wildcard_knowledge_base_resource_in_the_pipeline(self):
        pipeline = _read_module(PIPELINE)

        assert not re.search(r"knowledge-base/\*", pipeline)
        assert not re.search(r'"bedrock:\*"', pipeline)

    def test_generator_keeps_its_existing_statements(self):
        policy = self._policy("generator_permissions")

        for sid in (
            "InvokeBedrockModel",
            "ReadPolicyUploads",
            "ListPolicyUploads",
            "WriteGeneratedArtifacts",
            "WriteFailureReports",
            "InvokeAuditExecutor",
            "SendToDeadLetterQueue",
            "WriteLogs",
        ):
            assert f'Sid = "{sid}"' in re.sub(r"[ \t]+", " ", policy), sid

    def test_executor_role_has_no_bedrock_permission(self):
        policy = self._policy("executor_permissions")

        assert "bedrock" not in policy.lower()
        assert "knowledge_base" not in policy

    def test_legacy_assessor_role_does_not_gain_retrieve(self):
        policy = self._policy("lambda_permissions")

        assert "bedrock:Retrieve" not in policy
        assert "knowledge" not in policy.lower()
        assert sorted(set(re.findall(r'"(bedrock:[A-Za-z*]+)"', policy))) == [
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
        ]

    def test_existing_resource_addresses_are_unchanged_and_only_one_is_added(self):
        iam = _read(PIPELINE / "iam.tf")

        addresses = re.findall(r'(?m)^resource\s+"([a-z_]+)"\s+"([a-z_]+)"', iam)
        assert addresses == [
            ("aws_iam_role", "lambda_execution"),
            ("aws_iam_role_policy", "lambda_permissions"),
            ("aws_iam_role", "generator"),
            ("aws_iam_role_policy", "generator_permissions"),
            ("aws_iam_role_policy", "generator_knowledge_base"),
            ("aws_iam_role", "executor"),
            ("aws_iam_role_policy", "executor_permissions"),
            ("aws_iam_role_policy_attachment", "executor_vpc_access"),
        ]
        assert 'name = "${local.prefix}-generator-policy"' in re.sub(r"[ \t]+", " ", iam)


class TestPipelineProviderIsUntouched:
    def test_pipeline_keeps_the_aws_provider_5_constraint_and_lock(self):
        main = _read(PIPELINE / "main.tf")
        lock = (PIPELINE / ".terraform.lock.hcl").read_text(encoding="utf-8")

        assert re.search(r'version\s*=\s*"~> 5\.0"', main)
        aws = _block(lock, "provider", "registry.terraform.io/hashicorp/aws")
        assert re.search(r'version\s*=\s*"5\.100\.0"', aws)
        assert "aws_bedrockagent_knowledge_base" not in _read_module(PIPELINE)


class TestKnowledgeBaseModule:
    def test_module_declares_its_own_provider_and_lock_file(self):
        module = _read_module(KNOWLEDGE_BASE)
        pipeline_main = _read(PIPELINE / "main.tf")

        assert re.search(r'source\s*=\s*"hashicorp/aws"', module)
        constraint = re.search(r'source\s*=\s*"hashicorp/aws"\s*version\s*=\s*"([^"]+)"', module)
        assert constraint, "el módulo debe fijar la versión del provider aws"
        assert constraint.group(1) != "~> 5.0", "el provider 5.x no soporta KB administradas"
        required = re.search(r'required_version\s*=\s*"([^"]+)"', module)
        assert required
        assert required.group(1) == re.search(
            r'required_version\s*=\s*"([^"]+)"', pipeline_main
        ).group(1)
        assert (KNOWLEDGE_BASE / ".terraform.lock.hcl").is_file()
        assert not re.search(r"(?m)^\s*backend\s+\"", module), "estado propio, sin backend remoto"

    def test_variables_mirror_the_pipeline_naming(self):
        variables = _read(KNOWLEDGE_BASE / "variables.tf")

        for name, default in (
            ("aws_region", "us-east-1"),
            ("project_name", "pps"),
            ("environment", "prod"),
        ):
            block = _block(variables, "variable", name)
            assert re.search(rf'default\s*=\s*"{default}"', block), name
        module = _read_module(KNOWLEDGE_BASE)
        assert 'prefix = "${var.project_name}-${var.environment}"' in re.sub(r"[ \t]+", " ", module)
        for tag in ("Project", "Environment", "ManagedBy"):
            assert re.search(rf"\b{tag}\s*=", module), tag

    def test_knowledge_base_is_managed_without_storage_configuration(self):
        block = _block(
            _read_module(KNOWLEDGE_BASE), "resource", "aws_bedrockagent_knowledge_base", "this"
        )

        assert re.search(r'type\s*=\s*"MANAGED"', block)
        assert re.search(r"managed_knowledge_base_configuration\s*\{", block)
        assert re.search(r'embedding_model_type\s*=\s*"MANAGED"', block)
        assert "storage_configuration" not in block
        assert re.search(r"role_arn\s*=\s*aws_iam_role\.knowledge_base\.arn", block)

    def test_data_source_uses_the_managed_s3_connector_on_the_module_bucket(self):
        block = _block(
            _read_module(KNOWLEDGE_BASE), "resource", "aws_bedrockagent_data_source", "documents"
        )

        assert re.search(r'type\s*=\s*"MANAGED_KNOWLEDGE_BASE_CONNECTOR"', block)
        assert re.search(r"managed_knowledge_base_connector_configuration\s*\{", block)
        assert re.search(
            r"knowledge_base_id\s*=\s*aws_bedrockagent_knowledge_base\.this\.id", block
        )
        assert "aws_s3_bucket.knowledge" in block

    def test_service_role_trust_policy_has_confused_deputy_conditions(self):
        block = _block(_read_module(KNOWLEDGE_BASE), "resource", "aws_iam_role", "knowledge_base")

        assert re.search(r'Service\s*=\s*"bedrock\.amazonaws\.com"', block)
        assert re.search(r'Action\s*=\s*"sts:AssumeRole"', block)
        equals = re.search(r"StringEquals\s*=\s*\{(.*?)\}", block, re.DOTALL)
        assert equals
        assert re.search(
            r'"aws:SourceAccount"\s*=\s*data\.aws_caller_identity\.current\.account_id',
            equals.group(1),
        )
        like = re.search(r"ArnLike\s*=\s*\{(.*?)\n\s*\}", block, re.DOTALL)
        assert like
        assert (
            '"arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}'
            ':knowledge-base/*"'
        ) in like.group(1)
        assert '"aws:SourceArn"' in like.group(1)

    def test_service_role_policy_is_read_only_on_the_bucket_without_wildcards(self):
        block = _block(
            _read_module(KNOWLEDGE_BASE), "resource", "aws_iam_role_policy", "knowledge_base"
        )

        assert sorted(re.findall(r'"([a-z0-9]+:[A-Za-z*]+)"', block)) == [
            "s3:GetObject",
            "s3:ListBucket",
        ]
        resources = re.findall(r"Resource\s*=\s*(.+)", block)
        assert sorted(r.strip() for r in resources) == [
            '"${aws_s3_bucket.knowledge.arn}/*"',
            "aws_s3_bucket.knowledge.arn",
        ]
        assert not re.search(r'Resource\s*=\s*"\*"', block)
        assert re.search(
            r'Action\s*=\s*"s3:ListBucket"\s*Resource\s*=\s*aws_s3_bucket\.knowledge\.arn\s',
            block,
        )

    def test_module_has_no_wildcard_resource_or_action(self):
        module = _read_module(KNOWLEDGE_BASE)

        assert not re.search(r'Resource\s*=\s*"\*"', module)
        assert not re.search(r'"[a-z0-9-]+:\*"', module)
        assert not re.search(r'Action\s*=\s*"\*"', module)

    def test_documents_bucket_follows_the_pipeline_naming_and_hardening(self):
        module = _read_module(KNOWLEDGE_BASE)
        bucket = _block(module, "resource", "aws_s3_bucket", "knowledge")

        assert (
            'bucket = "${local.prefix}-knowledge-${data.aws_caller_identity.current.account_id}"'
            in re.sub(r"[ \t]+", " ", bucket)
        )
        versioning = _block(module, "resource", "aws_s3_bucket_versioning", "knowledge")
        assert re.search(r'status\s*=\s*"Enabled"', versioning)
        public = _block(module, "resource", "aws_s3_bucket_public_access_block", "knowledge")
        for flag in (
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        ):
            assert re.search(rf"{flag}\s*=\s*true", public), flag
        encryption = _block(
            module, "resource", "aws_s3_bucket_server_side_encryption_configuration", "knowledge"
        )
        assert re.search(r'sse_algorithm\s*=\s*"AES256"', encryption)
        lifecycle = _block(module, "resource", "aws_s3_bucket_lifecycle_configuration", "knowledge")
        assert "noncurrent_version_expiration" in lifecycle
        assert "abort_incomplete_multipart_upload" in lifecycle

    def test_outputs_expose_what_the_pipeline_and_the_operator_need(self):
        outputs = _read(KNOWLEDGE_BASE / "outputs.tf")

        expected = {
            "knowledge_base_id": r"aws_bedrockagent_knowledge_base\.this\.id",
            "knowledge_base_arn": r"aws_bedrockagent_knowledge_base\.this\.arn",
            "data_source_id": r"aws_bedrockagent_data_source\.documents\.data_source_id",
            "knowledge_bucket": r"aws_s3_bucket\.knowledge\.bucket",
        }
        for name, value in expected.items():
            assert re.search(rf"value\s*=\s*{value}", _block(outputs, "output", name)), name

    def test_module_contains_no_account_ids_or_literal_arns(self):
        for path in sorted(KNOWLEDGE_BASE.glob("*")):
            if path.suffix not in {".tf", ".md", ".example"}:
                continue
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"(?<!\d)\d{12}(?!\d)", text.replace("123456789012", "")), path
