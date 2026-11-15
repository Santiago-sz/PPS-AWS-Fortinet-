# Preparación para pruebas funcionales

- Fecha e identificador: 2026-11-15, functional-test-readiness.
- Estado: implementación y verificaciones locales completas; revisión del desarrollador pendiente.
- Objetivo autorizado: corregir el test de observabilidad, reportar fallos de preparación del executor y decodificar claves de eventos S3.
- Rama: `fix/functional-test-readiness`, creada desde `feature/project-skills-hooks` en `a203948` (base y último commit previo a este incremento).
- Árbol inicial limpio; todos los cambios de esta tarea son propios.
- Restricciones: sin cambios en sandbox, validador, legacy, IAM ni infraestructura; sin AWS real, push o merge. Merge no autorizado.
- Skills: `pps-audit-engine`, `pps-review`, `pps-handoff`. Fuentes: arquitectura, TESTING, evals, tests y código; implementación local de captura de pytest 9.1.

## Decisiones y TDD

El fallo de observabilidad era una incompatibilidad del test con la captura de
pytest 9.1: captura loggers que no propagan. Se conserva la configuración de
producción y se comprueba directamente un handler del root.

Antes de implementar, cinco casos nuevos fallaron: tres claves S3 codificadas
y dos fallos de preparación (Secrets Manager y constructor del cliente).
Resultado inicial acotado: 5 fallidos y 34 aprobados. El fallo original de
observabilidad ya se había reproducido en la revisión previa.

El generador usa `unquote_plus` una sola vez; descarga y manifest conservan la
clave real. El executor reporta `preparation_error:<tipo>` sin incluir mensajes
de excepción en el reporte, emite evento terminal y no ejecuta el sandbox.
La entrega de reportes todavía depende de disponibilidad y permisos de S3/SNS.

## Evidencia

Entorno disponible: `.venv-gui`, Python 3.11, pytest 9.1.1; `.venv` ausente.
Comandos desde `audit-engine/` con `../.venv-gui/Scripts/python.exe`:

- `-m pytest -q -p no:cacheprovider`: 283 aprobados, 1 omitido (SIGALRM en Windows).
- `-m ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/build_layer.py`: correcto.
- `-m ruff format --check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/build_layer.py`: 43 archivos conformes.
- `evals/run_evals.py --mode offline`: tres políticas, todos los umbrales cumplidos.

No cambiaron prompt, modelo o catálogo; no corresponde regrabar fixtures.
No se repitieron suites de GUI/API porque no se modificaron esos componentes.
TESTING actualizado. Próximo paso: revisión del diff y CI Linux/Python 3.12;
después, verificar Bedrock y conectividad FortiGate para el E2E autorizado.
