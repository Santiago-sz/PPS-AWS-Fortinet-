"""Agentes de etapa registrados al importar el generador, sin I/O ni credenciales.

El orquestador conserva los presupuestos por ejecucion y los gates deterministas.
Las instrucciones son fuentes Python incluidas por el empaquetado Lambda existente.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from agent_prompts import MAP_SYSTEM_PROMPT, REDUCE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageAgent:
    agent_id: str
    version: str
    role: str
    input_contract: str
    output_contract: str
    default_call_budget: int
    max_output_tokens: int
    system_prompt: str = field(repr=False)

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()

    def run(self, user_prompt: str, api_key: str, *, transport: Callable[..., str]) -> str:
        """Una llamada al modelo; no ejecuta scripts ni dispone de tools propios.

        El transporte se inyecta en cada llamada: no almacena la clave y permite
        probar cada rol sin red. El orquestador decide si reintentar y cuando parar.
        """
        logger.info(
            "agent=%s version=%s prompt_sha256=%s",
            self.agent_id,
            self.version,
            self.prompt_sha256,
        )
        return transport(
            self.system_prompt, user_prompt, api_key, max_tokens=self.max_output_tokens
        )


_REGISTRY = MappingProxyType(
    {
        "policy_interpreter": StageAgent(
            agent_id="policy_interpreter",
            version="1.0.0",
            role="Extraer controles exigidos por la politica y verificables en FortiGate",
            input_contract="Chunks con referencias de origen y catalogo de endpoints",
            output_contract="JSON con checks; lista vacia si no hay controles verificables",
            default_call_budget=12,
            max_output_tokens=4096,
            system_prompt=MAP_SYSTEM_PROMPT,
        ),
        "audit_script_generator": StageAgent(
            agent_id="audit_script_generator",
            version="1.0.0",
            role="Generar un script de auditoria para los controles recibidos",
            input_contract="PolicyCheck con IDs, catalogo y feedback opcional del validador",
            output_contract="Codigo Python restringido; debe aprobar script_validator",
            default_call_budget=3,
            max_output_tokens=4096,
            system_prompt=REDUCE_SYSTEM_PROMPT,
        ),
    }
)


def load_agents() -> Mapping[str, StageAgent]:
    """Registro fijo e inmutable. Cargar no llama al modelo ni ejecuta codigo externo."""
    return _REGISTRY


def describe_agents() -> list[dict]:
    """Metadatos para inspeccion local, sin exponer prompts ni credenciales."""
    return [
        {
            "agent_id": agent.agent_id,
            "version": agent.version,
            "role": agent.role,
            "input_contract": agent.input_contract,
            "output_contract": agent.output_contract,
            "default_call_budget": agent.default_call_budget,
            "max_output_tokens": agent.max_output_tokens,
            "prompt_sha256": agent.prompt_sha256,
        }
        for agent in load_agents().values()
    ]


if __name__ == "__main__":
    print(json.dumps(describe_agents(), indent=2, ensure_ascii=False))
