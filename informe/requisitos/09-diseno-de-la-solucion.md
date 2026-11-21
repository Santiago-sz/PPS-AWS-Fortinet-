# Capítulo IX — Diseño de la Solución

Fecha de definición: 2026-11-21. Estado de cumplimiento: pendiente de revisión
integral del informe; esta ficha define requisitos, no certifica cumplimiento.

## Contenido exigido por el reglamento

Fuente: RR 97/23, arts. 22.4.9 y 24.3.9. La lista sintetiza
los temas del art. 24.3.9; consultar el original ante dudas de interpretación.

- [ ] R-09-01: Arquitectura del sistema de información.
- [ ] R-09-02: Diseño de solución.
- [ ] R-09-03: Modelo de datos.
- [ ] R-09-04: Infraestructura de comunicaciones y servidores.
- [ ] R-09-05: Entornos de trabajo.
- [ ] R-09-06: Solución.

## Aplicación a PostureGuard

Los siguientes son criterios de trabajo documental para este proyecto; no son
exigencias textuales adicionales del reglamento ni autorizan nuevas funciones.

- Explicar el recorrido normativa → generación Bedrock → artefactos → revalidación y sandbox → FortiGate GET → reporte → API/GUI.
- Documentar separación de responsabilidades y permisos de generador y ejecutor, catálogo autorizado, presupuestos e integridad del script.
- Relacionar controles, manifest, ejecuciones y hallazgos con persistencia, artefactos y contratos vigentes.
- Describir comunicaciones y entornos locales, pruebas y AWS, distinguiendo diseño Terraform de despliegue comprobado y conectividad pendiente.
- Usar diagramas y capturas con versión, fuente y explicación; identificar cada evidencia sintética.
- Explicar funcionamiento, decisiones y limitaciones de lo construido sin copiar código extenso ni presentar remediaciones como ejecutadas.

## Evidencia para la revisión

Código y contratos actuales, Terraform, diagramas, manuales, modelo de datos, capturas y resultados fechados de las verificaciones disponibles.

Registrar ubicación exacta en Google Docs, fuente y fecha o versión consultada.
Usar el [mapa de evidencia](../evidencia/README.md) a través del
[índice de requisitos](README.md) para localizar las fuentes del proyecto.

## Criterio de cierre

Diagramas, texto y contratos son coherentes con la versión documentada. Cada capacidad se identifica como implementada, verificada o pendiente; el diseño no se confunde con validación E2E.

Todos los requisitos se marcan como cumple, parcial, no cumple o pendiente de
verificación con evidencia. Si un punto no aplica, justificarlo y confirmarlo
con el autor; no eliminarlo de la lista. La redacción y carga siguen el circuito
de [propuestas](../propuestas/README.md) indicado desde el índice de requisitos.
