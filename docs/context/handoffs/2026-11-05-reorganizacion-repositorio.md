# Handoff: reorganización del repositorio

- Fecha: 2026-11-05, America/Buenos_Aires.
- Estado: implementación y comprobaciones locales completadas; CI remoto pendiente.
- Rama: `feature/fase1-harness-bedrock`; commit de referencia `e5ca5a7`.
- Publicación autorizada posteriormente por el usuario: commit y push de los
  cambios realizados; merge no autorizado.

## Solicitud y alcance

El usuario autorizó implementar toda la estructura propuesta: GUI, API local,
motor de auditoría e infraestructura, con pruebas durante la migración. Dentro
de la API pidió separar puente AWS de servidor HTTPS. Se mantuvo HTTP loopback
compatible como se había anunciado, con HTTPS configurable por certificado/clave.

## Cambios previos

Ya existían el ajuste `.gitignore` para `.harness/` y `.venv-harness/`, y la
reorganización documental `docs/base/` + `docs/context/`. Se conservaron los
originales de `docs/base/`. Los manuales activos y su contexto se actualizaron
a las nuevas rutas.

## Implementación

- `desktop/` pasó a `gui/`; `audit-pipeline/api/` a `local-api/`.
- Motor separado en `audit-engine/{generator,executor,contracts,legacy}` con
  `tests/`, `evals/` y `scripts/`. Se preservan imports planos del runtime.
- Terraform del pipeline y laboratorio en `infrastructure/{pipeline,fortigate-lab}`.
- `archive_file` reúne únicamente los módulos Python del motor en un ZIP plano;
  conserva nombres de handlers y recursos, sin tests ni bytecode.
- API separada en `server/`, `aws/`, `services/`, `domain/` y `storage/`.
  Los imports públicos anteriores tienen adaptadores de compatibilidad.
- Servidor TLS 1.2+, certificado y clave obligatorios juntos. GUI con CA PEM
  opcional, validación de certificado/nombre y control de origen/esquema.
- SQLite, comandos de dispatch/sync/aprobación y carga sin AWS automático
  conservan su comportamiento. El servidor importa sin SDK AWS ni GUI.
- CI, instrucciones de rutas y manuales actualizados. El rediseño de reglas
  `AGENTS.md`, skills y hooks sigue pendiente; no se activaron hooks.

## Pruebas primero y resultados

Antes de implementar, los seis casos iniciales de API/TLS fallaron por falta
del soporte TLS, namespaces y control de downgrade. Dos pruebas de estructura
del motor fallaron por ausencia de los nuevos directorios y empaquetado. Luego
se implementó y se comprobó el flujo completo con carga DOCX sobre HTTPS.

Resultados finales locales:

| Comprobación | Resultado |
|---|---|
| Motor | 278 passed, 1 skipped (SIGALRM en Windows) |
| API | 37 passed |
| GUI, Qt offscreen | 49 passed |
| Ruff | Check y formato limpios en los archivos afectados |
| Evals offline | Tres normativas, todos los umbrales cumplidos |
| Build del layer | ZIP manylinux/CPython 3.12 construido en nueva ubicación |
| Terraform pipeline | fmt, init sin backend y validate correctos |
| Terraform laboratorio | Formato normalizado; init sin backend y validate correctos |
| Checkov 3.2.379 pipeline | 109 passed, 29 failed existentes, sin errores de parseo |
| Checkov laboratorio | 18 passed, 9 failed existentes, sin errores de parseo |
| ZIP plano de comprobación | Los tres handlers importan; executor no carga cliente Bedrock |
| Conservación | Validador, sandbox, código legacy, reporter y cliente FortiGate sin cambios de contenido; copias legacy de raíz intactas |
| Documentación | Base intacta, enlaces activos comprobados y YAML CI válido |
| Instalación editable | Paquetes reinstalados y `pps-api --help` / `serve --help` correctos |

Se usó `.venv-harness/`, preexistente. Checkov se instaló aisladamente en
`.harness/checkov-env/` para no alterar sus dependencias. Datos de Terraform
en directorios temporales externos. No se ejecutaron plan/apply ni AWS mutante.
Los escaneos Checkov devuelven fallo por los hallazgos documentados; no se deben
presentar como verificaciones de seguridad completamente aprobadas.

## Próximo paso y límites

Actualización de publicación: `ea6e63d` contiene la reorganización y HTTPS;
`988a1f3` contiene la documentación base y el contexto. El commit que incluye
esta actualización incorpora el contrato completo de `AGENTS.md`: TDD, contexto,
skills, handoffs, ramas, commits incrementales y revisión previa al merge.
Los hooks tienen política definida, pero todavía no están implementados.
Rama de publicación: `feature/fase1-harness-bedrock`; merge pendiente de revisión
y autorización explícita del desarrollador.

Revisar el diff con el usuario y definir las skills concretas y los hooks.
El CI remoto todavía debe ejecutarse. No se probó una auditoría live en AWS ni
se desplegó esta reorganización. Los certificados de las pruebas son temporales;
el operador debe proporcionar los certificados locales para usar HTTPS.

Consultar [arquitectura del repositorio](../repository-layout.md) y
[manual API](../../../local-api/README.md) antes de retomar. Revalidar Git y las
instrucciones actuales; el handoff no autoriza despliegues ni commits.
