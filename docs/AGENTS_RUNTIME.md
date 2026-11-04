# Agentes del pipeline de politicas

Se cargan dos agentes de etapa desde `audit-pipeline/lambda/audit_agents.py` al
importar `llm_client.py`. El registro y las definiciones son inmutables y no hacen
I/O al cargarse. No se requieren paquetes nuevos, comandos de activacion ni cambios
en Terraform: ambos modulos Python nuevos quedan dentro del `source_dir` existente.

| Agente | Entrada | Salida | Presupuesto por defecto |
| --- | --- | --- | --- |
| `policy_interpreter` v1.0.0 | Chunks de politica y catalogo de endpoints | JSON con controles y referencias de origen | 12 llamadas map |
| `audit_script_generator` v1.0.0 | Controles con IDs, catalogo y feedback del validador | Script Python para el sandbox | 3 intentos reduce |

Ambos tienen un limite de salida de 4096 tokens por llamada. Se conserva el modelo
configurado en `llm_client.CLAUDE_MODEL` y el transporte HTTP existente. Los
presupuestos de llamadas siguen controlados por el orquestador; los argumentos de
configuracion existentes pueden cambiarlos. El registro no es un contador global
ni mantiene memoria entre auditorias.

## Carga y uso

El flujo real `handler_generator -> llm_client.generate_audit_script` ahora usa
las instancias registradas para map y reduce. Las instrucciones anteriores se
trasladaron sin cambios a `agent_prompts.py`; el cambio formaliza sus roles y
permite inspeccionarlos. Los alias de prompts de `llm_client` se conservan.

Para inspeccionar IDs, versiones, contratos y hashes de instrucciones, sin llamar
al modelo ni cargar credenciales:

```powershell
.\.venv-harness\Scripts\python audit-pipeline/lambda/audit_agents.py
```

Cada llamada registra ID, version y SHA-256 del prompt de sistema. No registra
documentos, instrucciones de usuario ni claves desde la capa del agente. El
transporte previo conserva su manejo de errores; esta entrega no cambia esa capa.
Al modificar instrucciones, revisar y actualizar la version del agente.

## Controles y alcance

- Son agentes de etapa con una llamada al modelo por turno, no procesos autonomos
  ni subagentes del asistente de programacion. No leen AGENTS.md como prompts.
- No tienen herramientas propias para AWS, FortiGate, filesystem o ejecucion.
- El interprete debe devolver un objeto con una lista `checks` de objetos. Una
  respuesta mal formada falla explicitamente; solo `checks: []` representa una
  interpretacion sin controles verificables.
- Los IDs de controles siguen asignandose en codigo, no por el modelo.
- Reduce conserva validacion AST, feedback y reintentos acotados. Agotarlos no
  devuelve un script utilizable. Sin controles verificables no se llama a reduce.
- El ejecutor conserva hash, revalidacion independiente y presupuestos del sandbox.
  No se delegan permisos ni decisiones de seguridad en otro agente.

Las pruebas verifican carga sin red, enrutamiento real por roles, feedback,
agotamiento, respuestas mal formadas y metadatos sin secretos. Se ejecutan con:

```powershell
.\.venv-harness\Scripts\python scripts/verify.py pipeline
```

No demuestran calidad semantica, exactitud de citas ni resistencia a prompt
injection. La validacion de la forma de `checks` no es una validacion completa de
cada control. Esas evaluaciones siguen pendientes. Cargados en el codigo local
no significa desplegados o activos en AWS; no se ejecuto una auditoria real.

Verificacion local del 4 de noviembre de 2026: perfil `pipeline` aprobado con
218 pruebas aprobadas, 1 skip esperado de SIGALRM en Windows y Ruff aprobado.
El resumen y los logs estan en `.harness/reports-agents/`. Los prompts trasladados
se compararon con las fuentes anteriores y conservan exactamente su contenido.
