# Arquitectura y contratos

Fuente principal: [arquitectura base](../base/01-arquitectura-fase1.md).
Complementos: [capas de control](../base/03-harness-engineering.md) y
[conectividad FortiGate](../base/06-conexion-fortigate.md).
Síntesis documental: 2026-11-05; verificar la implementación antes de cambiarla.

## Recorrido de una auditoría

1. Desktop carga un PDF/DOCX mediante la API local, que valida el archivo y lo
   registra en SQLite. La carga local no invoca AWS.
2. `pps-api aws dispatch` sube la normativa a `policies/` en S3.
3. La notificación de S3 invoca `handler_generator.lambda_handler`.
4. El generador extrae texto, crea chunks por cláusula y llama a Bedrock:
   map produce controles y reduce produce un script. Los errores estáticos
   alimentan un ciclo acotado de corrección. Si hay una Knowledge Base
   configurada, entre map y reduce se consulta una vez por control y los
   fragmentos entran al prompt de reduce como referencia delimitada.
5. El generador guarda script y manifest en S3 con SHA-256. Con
   `AUTO_EXECUTE=false` queda pendiente de aprobación; con `true` invoca
   asincrónicamente al executor.
6. `handler_executor.lambda_handler` comprueba el hash contra manifest y payload,
   repite la validación y ejecuta mediante `sandbox.execute`.
7. El toolkit expone lecturas catalogadas del FortiGate y registro de hallazgos.
   El reporte se guarda en S3; el executor también notifica por SNS.
8. `pps-api aws sync` correlaciona reportes por `policy_key`, almacena manifest
   y reporte localmente y permite consultarlos desde desktop.

## Fronteras entre componentes

| Componente | Conoce o puede usar | Restricción de diseño |
|---|---|---|
| Generador | Normativa, Bedrock, artefactos S3, invocación del executor; consulta opcional a una Knowledge Base (`knowledge_retriever` y `reference_context`, deshabilitada por defecto; habilitada, aporta referencia al prompt de reduce) | Sin acceso al secret FortiGate; sus fallos se reportan a S3 sin SNS |
| Executor | Artefactos, secret FortiGate, GET catalogados, S3/SNS | Sin acceso a Bedrock; revalidación independiente |
| Script generado | Capacidades `fgt` y `report` y nombres seguros | Sin cliente HTTP general, imports, reflexión ni escritura en el firewall |
| Toolkit | Manifest y cliente FortiGate | Resuelve cita, remediación y documentos de referencia desde el manifest |
| Desktop | API local | Sin credenciales AWS |

El hash aporta una comprobación de integridad; no debe describirse como una
firma criptográfica de autoría. Una validación estática aprobada tampoco
demuestra por sí sola que la lógica de auditoría sea correcta.

La base documenta topes de 12 llamadas map, 3 intentos reduce, 4.000 nodos AST,
3 niveles de anidamiento y, en ejecución, 120 segundos, 40 llamadas y 500
hallazgos. Antes de depender de esos valores, consultar constantes, variables de
entorno y Terraform actuales. En Windows no está disponible el backstop SIGALRM.

## Artefactos y estados

```text
policies/{audit_id}.pdf|docx                  (bucket de entrada)
artifacts/{run_id}/script.py                 (bucket de resultados)
artifacts/{run_id}/manifest.json
reports/{run_id}/report.json
reports/{run_id}/report.md
```

El manifest relaciona `run_id`, `policy_key`, `policy_sha256`, `script_key`,
`script_sha256`, `checks`, `attempts`, `model` y `generated_at`. Cada control
lleva `check_id`, `clause_ref`, endpoints e intención. Los hallazgos incluyen
estado, evidencia, trazabilidad y remediación propuesta.

Solo cuando la recuperación desde la Knowledge Base estuvo habilitada, el
manifest suma el bloque `knowledge_base`: si estuvo habilitada, cuántos
controles obtuvieron referencia, cuántas consultas fallaron y, por
`check_id`, fuente y puntaje de cada fragmento usado (sin su texto). Cada
hallazgo lleva entonces `references`, resueltas por el executor desde ese
bloque. Un manifest sin el bloque significa recuperación deshabilitada y
sigue siendo válido. Ver
[la decisión 11](decisions/11-referencias-en-generacion.md).

| Estado | Significado documentado |
|---|---|
| `awaiting_approval` | Artefactos generados, sin invocar al executor |
| `invoked` | El generador invocó al executor; no significa que terminó |
| `completed` | El executor terminó normalmente; revisar evidencia y cobertura |
| `truncated` | Se agotó un presupuesto; se conservan hallazgos parciales |
| `could_not_audit` | Fallo explícito con `failure_reason` |

Los retornos del generador `generation_failed` y `no_verifiable_controls` se
representan en el reporte como `could_not_audit` con su motivo. No confundir
retorno de Lambda, estado de reporte y presentación de la API.

## Infraestructura y conectividad

El diseño usa S3, Lambdas, Bedrock, Secrets Manager, SNS, DLQ SQS y CloudWatch.
Desde el 2026-11-17 existe además, sin desplegar, el módulo opcional
`infrastructure/knowledge-base/` (Knowledge Base administrada de Bedrock); la
recuperación es aditiva y no sustituye el map/reduce sobre la normativa. Ver
[la decisión 10](decisions/10-bedrock-knowledge-base.md). El despliegue de ese
módulo estaba en curso el 2026-11-18 por fuera de esta documentación; su
estado no fue comprobado aquí.
El logging de invocaciones de Bedrock tiene alcance de cuenta/región y puede
contener texto sensible de las normativas. La región y el modelo documentados
son configuración histórica, no disponibilidad garantizada.

El executor necesita HTTPS al FortiGate y acceso a S3, Secrets Manager y SNS.
Su VPC es opcional. La base describe laboratorio FortiGate en `sa-east-1` y
pipeline en `us-east-1`: no asumir conectividad privada entre ambos. Consultar
el documento de conectividad antes de proponer cambios de red.
