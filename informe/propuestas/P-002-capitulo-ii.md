# P-002 · Relevamiento e investigación de mercado

Versión 6 · 21 de noviembre de 2026 · Aprobada y cargada en Google Docs. Destino: capítulo II, apartados II.I a II.VI, pestaña t.0 del [informe académico](https://docs.google.com/document/d/1Xe4F3dk1vfgj5ROYR11ACfVK3YQc-43Za8wE-QnbIDA/edit?tab=t.0).

## Estado de los requisitos

| Requisito | Google Docs al revisar · diagnóstico inicial | Cobertura en P-002 v6 | Resultado de la revisión y pendientes |
|---|---|---|---|
| R-02-01 Fuentes | Parcial. II.I identificaba la encuesta y las fuentes sobre seguridad en la nube. | Cubierto | Se vinculó el formulario original y se precisó qué aportó cada grupo de fuentes. |
| R-02-02 Instrumentos, dinámica y alcance | Parcial. II.II describía el instrumento y la muestra. Faltaban el período de aplicación y la convocatoria. | Cubierto | Se documentaron el período, la convocatoria, los límites de la muestra y el tratamiento de las respuestas múltiples. |
| R-02-03 Datos recabados | Parcial. II.III consignaba cuatro menciones para reducir el tiempo de corrección. | Cubierto | El formulario registra tres de diez. La tabla de resultados recoge la frecuencia comprobada. |
| R-02-04 Gráficos y variables | Parcial. II.IV presentaba seis figuras y atribuía un 40 % a la reducción del tiempo de corrección en el comentario de la figura 5. | Cubierto | Las seis leyendas identifican pregunta y base. La leyenda propuesta de la figura 5 ya consigna el 30 %. Se cotejaron las seis imágenes de Google Docs con sus leyendas y recuentos. |
| R-02-05 Análisis | Parcial. II.V presentaba AWS Security Hub como núcleo del producto. | Cubierto | Se contextualizó la comparación cloud en la etapa inicial y se incorporó la comparación aplicada a FortiGate. |
| R-02-06 Conclusiones | Parcial. II.VI extendía la predisposición a adoptar la herramienta cloud al prototipo actual. | Cubierto | El cierre delimita qué aporta la encuesta, identifica el perfil beneficiario y explicita qué falta evaluar con operadores. |

## Texto propuesto para revisión

**II.I. Fuentes de datos utilizadas.** En la etapa inicial del proyecto, el equipo relevó percepciones sobre seguridad de servicios en la nube mediante una encuesta anónima difundida en el ámbito universitario. Los resultados permiten reconstruir las necesidades exploradas cuando la propuesta se orientaba al monitoreo cloud y a la gestión de permisos. Para delimitar el problema de auditoría de FortiGate se tomó como antecedente la descripción del trabajo del personal de redes y ciberseguridad en la institución pública, presentada en I.III.

El equipo utilizó fuentes secundarias para interpretar las respuestas en el contexto de la seguridad en la nube. Los informes *The State of Cloud and AI Security 2025* y *Top Threats to Cloud Computing Survey Report 2026*, de Cloud Security Alliance, aportaron antecedentes sobre gestión de identidades, permisos y configuraciones. NIST SP 800-53 Rev. 5 e ISO/IEC 27001:2022 aportaron el marco conceptual para analizar el control de accesos, la trazabilidad y la gestión de la seguridad de la información (Cloud Security Alliance, 2025, 2026; Joint Task Force, 2020; International Organization for Standardization, 2022).

Para comparar las soluciones disponibles en la etapa inicial, el equipo consultó documentación oficial de AWS, Microsoft, Google Cloud, Wiz, Palo Alto Networks, Check Point, Orca Security y Fortinet. La comparación consideró el entorno cubierto por cada producto, los controles que evalúa y la forma en que presenta los hallazgos. Al delimitar la auditoría a FortiGate, se incorporó Security Rating como referencia para comparar qué criterio de verificación utiliza cada herramienta y qué resultado puede revisar el operador (Fortinet, s. f.).

Los casos publicados sobre la Universidad Católica de Salta, RMIT University y el Poder Judicial de San Luis documentan la adopción y administración de servicios en la nube en universidades y organismos públicos (Universidad Católica de Salta, 2024; Amazon Web Services, s. f.-e, s. f.-f). El procedimiento de revisión manual del firewall en la institución pública se describe en I.III.

**II.II. Instrumentos utilizados, dinámica y alcance.** El cuestionario autoadministrado «Framework automatizado para seguridad (CSPM/IAM)» se aplicó mediante Google Forms en agosto y septiembre de 2026. La convocatoria se realizó en charlas interuniversitarias con personal no docente y se extendió a docentes y a sus allegados en sus respectivas instituciones. La selección fue no probabilística.

El formulario recibió diez respuestas completas a diez preguntas cerradas de opción única, selección múltiple y valoración de 1 a 5. Respondieron personas de áreas técnicas y administrativas, entre ellas personal encargado de revisar configuraciones FortiGate. El cuestionario registró el área laboral de cada participante. Como esa categoría agrupa funciones distintas, los resultados se presentan para el conjunto de la muestra.

Las preguntas 5 y 9, sobre problemas prioritarios y beneficios esperados, indicaban seleccionar hasta tres opciones. En la pregunta 5, una persona marcó cuatro opciones. En la pregunta 9, una persona marcó cinco. Se conservaron todas las selecciones recibidas y se calculó el porcentaje de cada opción sobre las diez personas que respondieron.

La consulta documental sobre plataformas de seguridad en la nube se realizó en septiembre de 2026, durante la etapa inicial del proyecto.

**II.III. Presentación de datos recabados.** La siguiente síntesis reúne las frecuencias verificadas en las diez respuestas del formulario. Cada participante representa diez puntos porcentuales sobre el total de la muestra.

*Tabla 2.1. Resultados de la encuesta sobre seguridad institucional (n = 10).*

| Variable | Resultado sobre diez participantes |
|---|---|
| Área de trabajo | Infraestructura, gestión de TI y otras funciones, dos personas por categoría. Administración, ciberseguridad, desarrollo y dirección o coordinación de sistemas, una por categoría. |
| Uso laboral de servicios cloud | Nueve indicaron que los utilizan y una persona expresó incertidumbre. |
| Importancia de supervisar continuamente la seguridad | Diez asignaron 5 sobre 5. |
| Frecuencia percibida de problemas de configuración o acceso | Tres respondieron «muy frecuentemente», cuatro «frecuentemente» y tres «ocasionalmente». |
| Problemas relevantes (selección múltiple) | Siete mencionaron demoras de detección y siete, falta de visión centralizada. Cinco señalaron configuraciones inseguras. Cuatro eligieron cada una de estas opciones: permisos excesivos, accesos que siguen activos y dificultad para generar evidencia de auditoría. |
| Utilidad de un tablero centralizado | Ocho asignaron 5, una persona asignó 4 y otra asignó 3. Media de 4,7 sobre 5. |
| Utilidad de la detección automática con alertas | Diez asignaron 5 sobre 5. |
| Automatización preferida | Cinco eligieron corrección automática de bajo riesgo con aprobación para cambios sensibles, tres prefirieron aprobación para toda corrección y dos eligieron recibir únicamente recomendaciones. |
| Beneficios esperados (selección múltiple) | Nueve eligieron detección más rápida, seis facilitar auditorías y cinco centralizar la visión de seguridad. Cuatro eligieron reducir riesgos y tres reducir el tiempo de corrección. Dos eligieron mejorar el control de permisos y dos disminuir tareas manuales. |
| Adopción condicionada a seguridad y eficacia | Siete expresaron una opinión muy favorable, dos favorable y una neutral respecto de la herramienta descrita en la encuesta. |

**II.IV. Presentación de gráficos y variables de análisis.** Las seis figuras se elaboraron a partir del formulario «Framework automatizado para seguridad (CSPM/IAM)». En las preguntas de selección múltiple, el porcentaje de cada opción se calcula sobre las diez personas que respondieron y la suma puede superar el 100 %.

**Figura 1. Uso laboral de servicios en la nube.** Pregunta 2 (n = 10). Nueve personas indicaron que usaban estos servicios y una expresó incertidumbre.

**Figura 2. Frecuencia percibida de problemas de configuración, accesos o permisos.** Pregunta 4 (n = 10). Cuatro personas respondieron «frecuentemente», tres «muy frecuentemente» y tres «ocasionalmente».

**Figura 3. Problemas de seguridad relevantes para una universidad.** Pregunta 5 (selección múltiple, n = 10). Las demoras en la detección y la falta de una visión centralizada recibieron siete menciones cada una (70 %). Cuatro personas señalaron la dificultad para generar evidencia de auditoría (40 %).

**Figura 4. Nivel de automatización preferido.** Pregunta 8 (n = 10). Cinco personas eligieron correcciones automáticas de bajo riesgo con aprobación para cambios sensibles, tres prefirieron aprobar toda corrección y dos optaron por recibir únicamente recomendaciones.

**Figura 5. Beneficios esperados.** Pregunta 9 (selección múltiple, n = 10). Nueve personas eligieron detectar problemas con mayor rapidez y seis, facilitar auditorías. Reducir riesgos recibió cuatro menciones (40 %) y reducir el tiempo necesario para corregir incidentes, tres (30 %).

**Figura 6. Predisposición a adoptar la herramienta descrita en la encuesta.** Pregunta 10 (n = 10). Ante la condición de que la herramienta demostrara ser segura y efectiva, siete personas expresaron una opinión muy favorable, dos favorable y una neutral.

**II.V. Análisis de información.** Seis participantes incluyeron la posibilidad de facilitar auditorías entre los beneficios esperados y cuatro señalaron dificultades para generar evidencia. Estas dos preguntas ofrecen un punto de contacto con la tarea descrita en la institución pública. Allí, comprobar una condición puede exigir examinar varias reglas del firewall con nombres dispares. Para esa tarea, PostureGuard asocia cada verificación con una cláusula y conserva la evidencia que el operador puede revisar. Las dificultades de configuración y acceso relevadas en la encuesta también aparecen en los informes sectoriales de Cloud Security Alliance (2025, 2026). Esa coincidencia ayuda a interpretar qué preocupaciones comparten los participantes con el sector. Para evaluar cómo se comprueba una cláusula en un FortiGate, la comparación siguiente adopta como referencias el procedimiento institucional y la documentación técnica del fabricante.

La figura 4 muestra que las preferencias sobre la corrección se repartieron entre tres opciones. Solo dos participantes eligieron exclusivamente recomendaciones. La decisión de usar credenciales de solo lectura surge de la delimitación técnica e institucional del proyecto. Las preferencias expresadas ayudan a explicar por qué conviene comunicar al operador quién puede autorizar y aplicar cambios.

**Análisis competitivo**

El relevamiento documental de septiembre de 2026 comparó ocho alternativas para la propuesta inicial de seguridad en la nube. La tabla 2.2 sintetiza qué entorno examinaba cada alternativa y qué información ofrecía al equipo de seguridad, según la documentación de los proveedores citada en II.I.

*Tabla 2.2. Alternativas estudiadas en la etapa de seguridad en la nube.*

| Alternativa | Entorno considerado | Aporte identificado en el relevamiento | Fuente del relevamiento |
|---|---|---| --- |
| AWS Security Hub CSPM e IAM Access Analyzer | Cuentas y recursos de AWS | Consolidación de hallazgos de configuración y análisis de accesos. | Amazon Web Services (s. f.-b, s. f.-c), guías de IAM y Security Hub |
| Microsoft Defender for Cloud | Azure y entornos conectados de AWS y Google Cloud | Recomendaciones de postura y priorización de recursos que requieren atención. | Microsoft (2026), *Secure score in Defender for Cloud* |
| Google Security Command Center | Google Cloud y entornos adicionales según la edición | Concentración de hallazgos de postura, cumplimiento y detección. | Google Cloud (s. f.), *Security Command Center service tiers* |
| Wiz | Infraestructuras multicloud | Relación entre configuraciones, identidades y exposición para contextualizar un riesgo. | Wiz (s. f.), *Wiz Cloud: Manage security posture* |
| Cortex Cloud de Palo Alto Networks | Recursos y cargas de trabajo en la nube | Análisis conjunto de la postura y la actividad de las cargas de trabajo. | Palo Alto Networks (2025), presentación de Cortex Cloud |
| Check Point CloudGuard | Infraestructura en la nube | Evaluación de configuraciones mediante reglas de cumplimiento y consulta del riesgo por activo. | Check Point Software Technologies (2025), *Introduction to CloudGuard CNAPP* |
| Orca Security | Infraestructuras multicloud | Correlación de configuraciones, permisos y vulnerabilidades para priorizar hallazgos. | Orca Security (s. f.), *Cloud Security Posture Management (CSPM)* |
| Lacework FortiCNAPP | Infraestructuras y cargas de trabajo en la nube | Revisión de postura, permisos e infraestructura como código dentro del portafolio de Fortinet. | Fortinet (2024), ficha técnica de FortiCNAPP |

La concentración de hallazgos y su priorización eran criterios pertinentes cuando el proyecto abarcaba recursos cloud. Con el alcance definido en el capítulo I, la pregunta de comparación es más específica: ¿cómo pasa el personal de redes de una cláusula institucional a la configuración del firewall que permite verificarla? La tabla 2.3 compara tres formas de abordar esa tarea.

*Tabla 2.3. Criterio de verificación y resultado disponible en una revisión de FortiGate.*

| Método o herramienta | Punto de partida | Resultado que revisa el personal técnico |
|---|---|---|
| Revisión manual en la institución pública | Una condición que debe comprobarse y las políticas configuradas en el firewall | El personal identifica las reglas pertinentes y fundamenta su conclusión a partir de la configuración observada. |
| Fortinet Security Rating, documentado para FortiOS 7.4.9 | Comprobaciones de seguridad de Fortinet aplicables al entorno Security Fabric | Ofrece calificaciones, resultados detallados y recomendaciones (Fortinet, s. f.). |
| PostureGuard | Controles verificables extraídos de la normativa cargada por el operador | Entrega un reporte con la referencia a la cláusula, el resultado, la evidencia disponible y las remediaciones propuestas cuando corresponden. |

La descripción de la revisión manual procede del contexto institucional presentado en I.III. Para Security Rating se consultó la guía de administración de FortiOS 7.4.9 (Fortinet, s. f.). El recorrido de PostureGuard se describe en I.V y se desarrolla en el capítulo IX.

**Organizaciones que podrían beneficiarse**

El perfil de uso de PostureGuard reúne tres condiciones: la organización administra equipos FortiGate, cuenta con una normativa que contiene controles verificables y dispone de personal autorizado para consultar la configuración. El beneficio esperado consiste en que ese personal pueda localizar la evidencia y explicar el fundamento de un hallazgo durante una revisión. Su magnitud queda por medir.

*Tabla 2.4. Organizaciones que podrían beneficiarse de PostureGuard y posibles usos del reporte.*

| Segmento | Situación en la que el reporte podría resultar útil |
|---|---|
| Universidades y centros de investigación | Los equipos de redes podrían documentar si las reglas de acceso entre redes académicas, administrativas y de investigación cumplen la política institucional. |
| Organismos públicos | El responsable de redes podría entregar al área de auditoría la cláusula evaluada, la configuración observada y la recomendación asociada. La institución pública del capítulo I aporta el antecedente de uso en pruebas. |
| Salud, servicios profesionales, entidades financieras y aseguradoras | Cuando se exige separar redes que dan acceso a información sensible, el equipo podría revisar las reglas pertinentes y conservar la evidencia para una auditoría. |
| Empresas de software y tecnología | Tras un cambio de infraestructura, el equipo podría comprobar si las reglas consultables del firewall siguen satisfaciendo los controles internos. |
| PyMEs | Un equipo de TI reducido podría utilizar el reporte para organizar la revisión periódica y decidir qué recomendaciones atender primero. |
| Consultoras y proveedores de servicios administrados | Con autorización de cada cliente, el personal podría repetir el procedimiento de revisión y entregar los hallazgos vinculados con la normativa de esa organización. |

Los casos de UCASAL, RMIT University y el Poder Judicial de San Luis documentan la adopción de servicios cloud en educación superior y en el sector público (Universidad Católica de Salta, 2024; Amazon Web Services, s. f.-e, s. f.-f). La selección de estos segmentos como posibles beneficiarios de PostureGuard depende además de confirmar el uso de FortiGate y la necesidad de auditarlo frente a reglas propias. La encuesta universitaria tampoco permite estimar la demanda de los demás sectores.

**II.VI. Conclusiones.** Seis de las diez personas encuestadas incluyeron la posibilidad de facilitar auditorías entre los beneficios esperados. En la institución pública, esa necesidad se concreta al buscar la regla del firewall que permite comprobar una cláusula de la normativa. La comparación con la revisión manual y con Security Rating ayudó a precisar qué debe recibir el operador: un reporte de auditoría que reúne, para cada control, la cláusula evaluada, el resultado, la evidencia disponible y la propuesta de remediación cuando corresponde.

El perfil con mayor respaldo en el relevamiento es el de los equipos de redes y ciberseguridad que administran FortiGate y deben justificar sus verificaciones frente a una normativa propia. La institución pública aportó el contexto de pruebas. La aplicación en universidades, empresas y consultoras dependerá de que se confirmen esas condiciones en cada organización. Queda por evaluar con operadores si pueden reconstruir un hallazgo a partir del reporte, cuánto esfuerzo requiere hacerlo frente a la revisión manual y qué aceptación tiene el prototipo en esa tarea.

## Fuentes y decisiones

- [Ficha de requisitos](../requisitos/02-relevamiento-e-investigacion-de-mercado.md) y [contexto institucional de P-001](P-001-capitulo-i.md). Se cotejaron los recuentos de las diez preguntas con el [formulario original y sus respuestas](https://docs.google.com/forms/d/1t_hXOld-1IA-lGxUT2UiuVVCLhfyzSXygSk58r517so/edit#responses). Las fechas de creación de las respuestas en UTC abarcan del 31 de agosto al 7 de septiembre de 2026. La pregunta 9 registra tres selecciones para reducir el tiempo de corrección, frente a cuatro en II.III y en el comentario de la figura 5 del informe.
- Referencia incorporada en la bibliografía: Fortinet. (s. f.). *Security rating*. FortiOS 7.4.9 Administration Guide. [Documentación del fabricante](https://docs.fortinet.com/document/fortigate/7.4.9/administration-guide/292634/security-rating). Comparación documental, sin ensayo entre herramientas.
- Conservar las seis figuras con el detalle de II.IV al cargar las leyendas verificadas. El análisis competitivo y la segmentación del relevamiento original se incorporan al cuerpo de II.V.
- El autor confirmó el período de aplicación, la convocatoria y las consultas a personal que revisa FortiGate. El cuestionario carece de una variable que identifique ese rol. La figura 5 existente muestra 3 de 10 para reducir el tiempo de corrección y 4 de 10 para reducir riesgos.

## Aprobación y carga

El autor aprobó la carga de P-002 v6 y la incorporación de la referencia de Fortinet. Se verificaron el texto de II.I a II.VI, las cuatro tablas y las seis imágenes originales con sus respectivas leyendas en la pestaña t.0. La entrada de Fortinet y el enlace a la guía se verificaron en la bibliografía.
