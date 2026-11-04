import argparse
import json
from pathlib import Path

from .service import Service


def main():
    parser = argparse.ArgumentParser(description="API PPS de desarrollo (solo loopback)")
    parser.add_argument("--database", default=".pps-api/development.sqlite3")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    ingest = commands.add_parser(
        "import-result", help="Adjuntar artefactos reales a una auditoría local"
    )
    ingest.add_argument("audit_id")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("report", type=Path)
    bridge = commands.add_parser(
        "aws", help="Enviar a S3 o recuperar reportes (requiere credenciales AWS)"
    )
    bridge.add_argument("action", choices=["dispatch", "sync", "list-pending", "approve"])
    bridge.add_argument("run_id", nargs="?", help="run_id a aprobar (solo para approve)")
    bridge.add_argument("--policies-bucket")
    bridge.add_argument("--reports-bucket")
    bridge.add_argument(
        "--executor-function",
        help="Nombre o ARN de la Lambda ejecutora (o PPS_EXECUTOR_FUNCTION en .env)",
    )
    args = parser.parse_args()
    service = Service(args.database)
    if args.command == "serve":
        from .server import create_server

        server = create_server(service, args.port)
        print(f"API de desarrollo: http://127.0.0.1:{server.server_port} (sin OIDC)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    elif args.command == "import-result":
        service.finish(
            args.audit_id,
            json.loads(args.manifest.read_text(encoding="utf-8")),
            json.loads(args.report.read_text(encoding="utf-8")),
        )
        print("Reporte asociado.")
    else:
        import boto3
        from botocore.config import Config

        from .aws_bridge import Bridge
        from .config import aws_options, load_settings

        try:
            if args.env_file != Path(".env") and not args.env_file.is_file():
                raise ValueError("No existe el archivo indicado en --env-file.")
            settings = load_settings(args.env_file)
            options, policies, reports = aws_options(
                settings, args.policies_bucket, args.reports_bucket
            )
            executor = args.executor_function or settings.get("PPS_EXECUTOR_FUNCTION")
            if args.action == "approve" and not args.run_id:
                raise ValueError("Indicá el run_id a aprobar: aws approve RUN_ID.")
            if args.action == "approve" and not executor:
                raise ValueError(
                    "Indicá --executor-function o completá PPS_EXECUTOR_FUNCTION en .env."
                )
            if args.action != "approve" and args.run_id:
                raise ValueError("run_id solo se acepta con la acción approve.")
        except ValueError as exc:
            parser.error(str(exc))
        session = boto3.Session(**options)
        no_retry = Config(retries={"total_max_attempts": 1})
        s3 = session.client("s3", config=no_retry)
        worker = Bridge(service, s3, policies, reports)
        if args.action == "approve":
            # Una sola invocación asíncrona; un reintento duplicaría la ejecución.
            executor_client = session.client("lambda", config=no_retry)
            status = worker.approve(args.run_id, executor, executor_client)
            print(f"Ejecutor invocado para {args.run_id} (StatusCode {status}). Luego: aws sync.")
        elif args.action == "list-pending":
            pending = worker.list_pending()
            print("\n".join(pending) if pending else "Sin ejecuciones pendientes.")
        else:
            print(f"Auditorías procesadas: {getattr(worker, args.action)()}")


if __name__ == "__main__":
    main()
