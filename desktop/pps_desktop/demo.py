"""Explicit, deterministic demo. Never sends documents or simulates AWS jobs."""

from .domain import normalize


def snapshot():
    timestamp = "2026-09-28T12:42:00Z"
    device = {
        "id": "demo-fgt",
        "name": "FortiGate · Laboratorio",
        "type": "fortigate",
        "connector_status": "Datos de ejemplo",
        "last_checked_at": timestamp,
    }
    session = {
        "organization": {"id": "demo-org", "name": "Laboratorio PPS"},
        "user": {"id": "demo-user", "name": "Analista demo"},
        "role": "analyst",
        "environment": "DEMOSTRACIÓN",
        "devices": [device],
        "capabilities": {"reaudit": False, "follow_up": False},
        "max_upload_bytes": 20 * 1048576,
    }
    definitions = [
        (
            "Acceso administrativo",
            "Acceso e identidad",
            "fail",
            "system_global",
            "La administración debe limitarse a redes autorizadas.",
            "Se observó acceso HTTPS administrativo sin restricción de red.",
        ),
        (
            "Registro de eventos",
            "Registro y monitoreo",
            "pass",
            "log_setting",
            "Los eventos de seguridad deben registrarse.",
            "El registro de eventos está habilitado.",
        ),
        (
            "Sincronización de hora",
            "Registro y monitoreo",
            "pass",
            "system_ntp",
            "Los equipos deben sincronizar su reloj con una fuente NTP.",
            "NTP habilitado.",
        ),
        (
            "Perfil de contraseñas",
            "Acceso e identidad",
            "fail",
            "system_password_policy",
            "La longitud mínima de las contraseñas será de doce caracteres.",
            "La longitud mínima configurada es de ocho caracteres.",
        ),
        (
            "Administración cifrada",
            "Acceso e identidad",
            "pass",
            "system_interface",
            "La administración remota utilizará canales cifrados.",
            "HTTPS habilitado; HTTP deshabilitado.",
        ),
        (
            "Inspección de tráfico",
            "Protección de red",
            "indeterminate",
            "firewall_policy",
            "Se inspeccionará el tráfico de las redes incluidas en el alcance.",
            "El endpoint no respondió. No se pudo determinar el resultado.",
        ),
        (
            "Protección de aplicaciones",
            "Protección de red",
            "pass",
            "application_list",
            "Se aplicará control de aplicaciones.",
            "Existe un perfil de control asignado.",
        ),
        (
            "Registro remoto",
            "Registro y monitoreo",
            "pass",
            "log_syslogd_setting",
            "Se enviarán eventos al recolector central.",
            "Destino syslog configurado.",
        ),
        (
            "Túneles de terceros",
            "Protección de red",
            "not_applicable",
            "vpn_ipsec_phase1_interface",
            "Los túneles con terceros requieren revisión.",
            "No hay túneles de terceros en el alcance.",
        ),
        (
            "Revisión de reglas",
            "Protección de red",
            None,
            "firewall_policy",
            "Las reglas deberán revisarse periódicamente.",
            "",
        ),
        (
            "Interfaces de gestión",
            "Acceso e identidad",
            None,
            "system_interface",
            "Se separarán las interfaces de gestión.",
            "",
        ),
        (
            "Retención de eventos",
            "Registro y monitoreo",
            None,
            "log_setting",
            "Se conservarán los registros por el plazo institucional.",
            "",
        ),
    ]
    checks, findings = [], []
    for index, (title, group, status, endpoint, clause, evidence) in enumerate(definitions, 1):
        cid = f"CHK-{index:03d}"
        ref = {"heading_path": [group], "page": 2 + index // 3, "quote": clause}
        checks.append(
            {
                "check_id": cid,
                "title": title,
                "clause_ref": ref,
                "endpoints": [endpoint],
                "intent": clause,
            }
        )
        if status:
            findings.append(
                {
                    "check_id": cid,
                    "status": status,
                    "evidence": evidence,
                    "traceable": True,
                    "clause_ref": ref,
                    "endpoints_used": [endpoint],
                }
            )
    manifest = {"run_id": "demo-run-20260928", "checks": checks, "policy_sha256": "a" * 64}
    report = {
        "run_id": manifest["run_id"],
        "status": "truncated",
        "truncated": True,
        "timestamp": timestamp,
        "findings": findings,
        "notes": [],
        "failure_reason": "Se alcanzó el límite de tiempo; 3 controles no fueron evaluados.",
    }
    result = normalize(
        manifest,
        report,
        {
            "audit_id": "demo-audit",
            "source": "demo",
            "policy_name": "Política de seguridad institucional",
            "policy_version": "2.1",
            "policy_version_id": "demo-version",
            "device": device,
        },
    )
    policies = [
        {
            "id": "demo-policy",
            "name": result["policy_name"],
            "version_label": "2.1",
            "version_id": "demo-version",
            "status": "lista",
            "scope": "FortiGate de laboratorio",
            "description": "Controles de acceso, protección de red y registro de eventos.",
            "uploaded_by": "Analista demo",
            "uploaded_at": "2026-09-28T12:30:00Z",
            "mime_type": "application/pdf",
            "size": 248320,
            "sha256": "a" * 64,
            "review_status": "Propuesta IA · sin aprobación humana",
            "checks": checks,
            "device_id": device["id"],
            "last_audit_id": "demo-audit",
        }
    ]
    audit = {
        "id": "demo-audit",
        "run_id": manifest["run_id"],
        "policy_version_id": "demo-version",
        "policy_name": result["policy_name"],
        "policy_version": "2.1",
        "device": device,
        "status": "truncated",
        "phase": "elaborando reporte",
        "started_at": "2026-09-28T12:38:00Z",
        "finished_at": timestamp,
        "failure_reason": report["failure_reason"],
        "events": [
            {
                "phase": phase,
                "timestamp": f"2026-09-28T12:{minute}:00Z",
                "message": "Evento de ejemplo",
            }
            for phase, minute in [
                ("recibido", "38"),
                ("extrayendo", "38"),
                ("generando controles", "39"),
                ("validando", "40"),
                ("recopilando evidencia", "40"),
                ("elaborando reporte", "42"),
            ]
        ],
    }
    return {
        "session": session,
        "policies": policies,
        "audits": [audit],
        "results": {"demo-audit": result},
    }
