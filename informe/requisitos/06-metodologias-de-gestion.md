# Capítulo VI — Metodologías de Gestión

Fecha de definición: 2026-11-21. Estado de cumplimiento: pendiente de revisión
integral del informe; esta ficha define requisitos, no certifica cumplimiento.

## Contenido exigido por el reglamento

Fuente: RR 97/23, arts. 22.4.6 y 24.3.6. La lista sintetiza
los temas del art. 24.3.6; consultar el original ante dudas de interpretación.

- [ ] R-06-01: Técnicas o prácticas de la ingeniería de software para el proyecto.
- [ ] R-06-02: Trazabilidad del proyecto.
- [ ] R-06-03: Gestión de la configuración del proyecto.
- [ ] R-06-04: Testing del proyecto.

## Aplicación a PostureGuard

Los siguientes son criterios de trabajo documental para este proyecto; no son
exigencias textuales adicionales del reglamento ni autorizan nuevas funciones.

- Describir prácticas efectivamente aplicadas y sus ejemplos: requerimientos, desarrollo incremental, revisión y TDD cuando exista evidencia.
- Relacionar necesidades y objetivos con cambios, pruebas y entregables; explicar versiones, ramas, revisión y configuración sin divulgar secretos.
- Documentar pruebas del motor, API, GUI, evals y validación de infraestructura que correspondan, con fecha, versión, entorno y resultado.
- Separar pruebas unitarias, integración local, fixtures, confirmación manual y E2E real; registrar fallos, exclusiones y pendientes.
- No reutilizar cantidades de tests ni estados de CI como actuales sin verificar su ejecución y procedencia.

## Evidencia para la revisión

Commits, requerimientos, registros de pruebas y revisión, configuración de CI y handoffs pertinentes; consultar el mapa de evidencia.

Registrar ubicación exacta en Google Docs, fuente y fecha o versión consultada.
Usar el [mapa de evidencia](../evidencia/README.md) a través del
[índice de requisitos](README.md) para localizar las fuentes del proyecto.

## Criterio de cierre

Las prácticas tienen ejemplos verificables y la sección de testing permite evaluar cobertura y límites. Un flujo con resultados sintéticos no acredita consultas reales a Bedrock/FortiGate.

Todos los requisitos se marcan como cumple, parcial, no cumple o pendiente de
verificación con evidencia. Si un punto no aplica, justificarlo y confirmarlo
con el autor; no eliminarlo de la lista. La redacción y carga siguen el circuito
de [propuestas](../propuestas/README.md) indicado desde el índice de requisitos.
