# Desarrollo y verificación

Fuentes: [runbook base](../base/02-paso-a-paso-despliegue-y-prueba.md),
[capas de control](../base/03-harness-engineering.md),
[mapa base](../base/04-estructura-del-repositorio.md) y
[TESTING.md](../../audit-engine/TESTING.md). Primera síntesis: 2026-11-05.

## Entorno y fuentes canónicas

Trabajar en un clon local fuera de carpetas sincronizadas por Drive. El entorno
documentado para Lambda y el layer es Python 3.12; API y desktop declaran sus
requisitos en sus propios `pyproject.toml`. El venv de referencia es `.venv/`
en la raíz. Su existencia y las dependencias instaladas deben comprobarse;
no asumir rutas personales del runbook.

Consultar los procedimientos completos en:

- [TESTING.md](../../audit-engine/TESTING.md): dependencias, tests, Ruff e IaC.
- [SECRETS.md](../../audit-engine/SECRETS.md): tratamiento de secretos e IAM.
- [Evals](../../audit-engine/evals/README.md): fixtures, modos y umbrales.
- [API](../../local-api/README.md): servidor y puente a AWS.
- [Desktop](../../gui/README.md) y [contrato API](../../gui/API_CONTRACT.md).
- [CI](../../.github/workflows/ci.yml): verificaciones automatizadas vigentes.

## Ciclo de trabajo acordado: tests primero

Para funcionalidad o corrección de errores: definir aceptación, escribir los
tests, ejecutarlos y comprobar que fallan por el comportamiento faltante,
implementar hasta que pasen y refactorizar con regresiones en verde. No debilitar
tests para acomodarlos a una implementación incorrecta. Registrar el fallo
inicial observado y el resultado final en la entrega y en el handoff.

Para una reorganización documental como esta, definir primero comprobaciones
de conservación de archivos y enlaces; no crear tests artificiales. Esta sección
recoge el acuerdo de la conversación y está incorporada al contrato vigente en
`AGENTS.md`. Ese contrato también exige rama por feature, commits pequeños por
incremento verificable y merge sujeto a revisión y autorización del desarrollador.

## Comandos de referencia

Desde `audit-engine/`, usando el intérprete del entorno elegido:

```powershell
../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
../.venv/Scripts/python.exe -m ruff check lambda/ evals/ scripts/build_layer.py
../.venv/Scripts/python.exe -m ruff format --check lambda/ evals/ scripts/build_layer.py
../.venv/Scripts/python.exe evals/run_evals.py --mode offline
```

API: instalar `local-api[dev]` y ejecutar pytest en ese directorio.
Desktop: instalar `desktop[dev]` y ejecutar pytest con `QT_QPA_PLATFORM=offscreen`.
No usar el antiguo runner `scripts/verify.py`: su implementación de desarrollo
fue retirada durante esta conversación.

Si se modifica IaC, seguir los comandos de `AGENTS.md` y `TESTING.md`: formato,
`init -backend=false`, `validate` y Checkov, con `TF_DATA_DIR` fuera del árbol.
El layer puede requerir construcción previa. No ejecutar plan/apply ni AWS
CLI mutante sin una solicitud explícita. Los ejemplos del runbook describen
procedimientos, no autorizan ejecutarlos.

## Cómo interpretar las verificaciones

Los números 275 tests de pipeline, 30 de API y 45 de desktop proceden del
registro base y de corridas anteriores; no son resultados nuevos de esta
reorganización. El skip de SIGALRM en Windows no prueba el backstop Linux.
Consultar [estado](status.md) para sus límites.

Los evals offline usan respuestas fijas: permiten detectar regresiones, pero
no prueban disponibilidad del modelo ni calidad live. Las fixtures actuales
documentadas fueron escritas a mano. Cambiar prompts, modelo o catálogo requiere
revisarlas y planificar la grabación live según el contrato del proyecto.

No guardar tokens ni credenciales en código, fixtures, documentación o handoffs.
El token FortiGate vive en Secrets Manager; las llamadas a Bedrock usan IAM.
