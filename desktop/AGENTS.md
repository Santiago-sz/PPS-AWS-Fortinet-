# Escritorio

- Leer `API_CONTRACT.md` y `docs/VALIDATION.md` al cambiar contratos o metricas.
- La GUI consume la API; no obtiene credenciales AWS ni llama a FortiGate/Lambda.
- Conservar separados demostracion, archivos locales y servicio conectado.
  No inventar fases, hallazgos, permisos ni resultados para completar la UI.
- Mantener denominadores, deteccion de duplicados y avisos de cobertura parcial.
- Ejecutar el perfil `desktop` (Qt offscreen); si cambia el contrato ejecutar `api`.
- Verificar en Windows para la plataforma soportada. Las pruebas offscreen no
  sustituyen accesibilidad, login institucional ni instalacion en equipo limpio.
