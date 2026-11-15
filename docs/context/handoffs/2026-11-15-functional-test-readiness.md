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

## Revisión del commit y preparación de CI (2026-11-15)

- Commit revisado: `c314de889de0e12d09ba5180cc517f1b99124dd6`; árbol limpio al iniciar.
- Revisión del agente sin hallazgos bloqueantes. Hash y AST siguen precediendo
  la preparación del cliente; no se modificaron validador, sandbox ni legacy.
- Control negativo de observabilidad: con `propagate=True` solo en memoria,
  el test falla como corresponde (una llamada al handler root); sin cambios en disco.
- Ubuntu WSL dispone de Python 3.14.4, no de 3.12. Docker no estaba iniciado.
  El test existente `TestWallClockBudgetViaSignalBackstop::test_real_signal_backstop_terminates_pure_cpu_spin_with_no_toolkit_calls`
  pasó allí: 1 aprobado. Se usó pytest puro del entorno local, sin instalar
  dependencias, con autoload de plugins y escritura de bytecode desactivados.
  Esta evidencia no sustituye CI Linux/Python 3.12.
- API GitHub Actions consultada por SHA: cero ejecuciones antes del push;
  `git ls-remote` confirmó que la rama todavía no existía en origin.
- El desarrollador autorizó explícitamente publicar esta rama, incluyendo el
  registro documental, y verificar CI. Merge sigue sin autorización.
- Próximo paso: push de `fix/functional-test-readiness`, consultar jobs del SHA
  publicado y revisar resultados y logs; no confundir Checkov soft-fail con
  ausencia de hallazgos.

### Primera ejecución remota

Push publicado en `43fb37e`. Run `43720460154`: API, GUI, evals e
infraestructura aprobaron; motor se detuvo antes de pytest por UP038 en
`tests/test_repository_layout.py:42`. Ruff 0.11.2 del CI exige unión de tipos
en `isinstance`; el Ruff local más nuevo no informó esa regla. Se ajustó
únicamente esa sintaxis preexistente; no cambia el contrato del test.
No corresponde nuevo test de comportamiento para este ajuste de lint.

### Resultado final de revisión y CI

- Commit de código final: `1eedd51d460f137a51d939acff8f647431a3dde3`, publicado.
- [Run 43720573002](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/actions/runs/43720573002): `completed/success`, Ubuntu 26.04, Python 3.12.16.
- Motor: 284 aprobados, sin skips; incluye SIGALRM real. Ruff 0.11.2 y formato correctos.
- API: 37 aprobados. GUI: 49 aprobados y Ruff correcto. Evals offline: job aprobado.
- Infraestructura: construcción del layer, fmt, init sin backend y validate aprobados.
  Checkov: 116 aprobados, 29 fallidos, 0 omitidos; job con soft-fail, no ausencia de hallazgos.
- Comprobación local del ajuste de lint: 3 tests de repository-layout aprobados,
  Ruff y formato correctos; diff sin errores de espacios.
- Revisión técnica del agente completa, sin hallazgos bloqueantes en el diff.
  Revisión del desarrollador y autorización de merge siguen pendientes.
- Este registro posterior solo modifica documentación; no invalida la evidencia
  del código probado en `1eedd51`. No se repitieron suites por agregar este registro.
- Próximo paso: prueba funcional local GUI/API. AWS/FortiGate real sigue pendiente.

### Regla de transición solicitada por el desarrollador

El 2026-11-15 se agregó a AGENTS.md §11 la obligación de integrar la tarea
actual en `main` antes de comenzar otra feature o fix, consultando y esperando
autorización explícita para el merge. La nueva rama parte de `main` actualizada.
No existe una rama local `main` al comprobar `git branch --list`; antes de un
merge deberá aclararse el destino sin asumir que `master` es equivalente.
Este pedido solo modifica la política, no autoriza un merge. Verificación
documental: lectura de la sección y `git diff --check`; sin suites de código.
