# Trabajo en este repositorio

Leer [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) antes de elegir un componente.
La guia de preparacion y verificacion es [docs/HARNESS.md](docs/HARNESS.md).

- El flujo de politicas vive en `audit-pipeline/lambda/` y se empaqueta desde
  `audit-pipeline/terraform/`. `lambda/` y `terraform/` en la raiz son un flujo
  anterior independiente; no copiar cambios entre ambos automaticamente.
- No se conoce el despliegue activo a partir del codigo. No afirmar que un cambio
  esta desplegado por haberlo escrito o probado.
- Mantener la GUI desacoplada de AWS/FortiGate y respetar `desktop/API_CONTRACT.md`.
- No leer ni mostrar `.env`, credenciales, documentos privados, tfstate ni SQLite
  local para verificar cambios. Usar fixtures sinteticos y directorios temporales.
- La verificacion no requiere credenciales reales. No ejecutar `aws dispatch`,
  `aws sync`, Terraform plan/apply/destroy ni llamadas al modelo como parte de ella.
- Ejecutar `python scripts/verify.py <perfil>` usando el Python del entorno dev.
  Perfiles: `harness`, `pipeline`, `api`, `desktop`, `iac`; sin argumentos corre todos.
  Cambios transversales requieren los perfiles afectados. No instalar dependencias
  automaticamente dentro del runner ni modificar codigo para ocultar un fallo.
- Reportar controles ejecutados, fallos, skips y limites de la evidencia. Un control
  no disponible no es un control aprobado. Los logs/JSON quedan en `.harness/reports/`.
- No editar ZIPs, ejecutables, caches, providers ni artefactos generados como fuentes.
- Los archivos de `P-Terraform-Forti-AWS/` no estan versionados por este repositorio;
  no incorporarlos ni tratarlos como parte de la verificacion reproducible.
