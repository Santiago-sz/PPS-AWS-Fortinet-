import argparse
import json
from pathlib import Path

from .services import Service


def main():
    parser = argparse.ArgumentParser(description="API PPS de desarrollo (solo loopback)")
    parser.add_argument("--database", default=".pps-api/development.sqlite3")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    serve.add_argument(
        "--aws-bridge",
        action="store_true",
        help="Enviar a S3 y recuperar reportes en forma periódica (requiere credenciales AWS)",
    )
    serve.add_argument(
        "--aws-bridge-interval",
        type=float,
        default=15.0,
        metavar="SEGUNDOS",
        help="Espera entre ciclos del puente AWS (mínimo 5, por defecto 15)",
    )
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
    if args.command == "serve" and bool(args.tls_cert) != bool(args.tls_key):
        parser.error("HTTPS requiere --tls-cert y --tls-key juntos.")
    service = Service(args.database)
    if args.command == "serve":
        from . import server as http_server

        worker = None
        if args.aws_bridge:
            # El SDK de AWS se importa solo con esta opción; server/ no lo conoce.
            from .aws import worker as bridge_worker

            try:
                worker = bridge_worker.build_bridge_worker(
                    service, args.env_file, args.aws_bridge_interval
                )
            except ValueError as exc:
                parser.error(f"--aws-bridge: {exc}")
            service.automatic_dispatch = True
        server = http_server.create_server(
            service, args.port, tls_cert=args.tls_cert, tls_key=args.tls_key
        )
        print(
            f"API de desarrollo: {server.scheme}://127.0.0.1:{server.server_port} (sin OIDC)",
            flush=True,
        )
        if worker:
            print(
                f"Puente AWS activo: envío y recuperación cada {worker.interval:g} s.",
                flush=True,
            )
            worker.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if worker:
                worker.stop()
            server.server_close()
    elif args.command == "import-result":
        service.finish(
            args.audit_id,
            json.loads(args.manifest.read_text(encoding="utf-8")),
            json.loads(args.report.read_text(encoding="utf-8")),
        )
        print("Reporte asociado.")
    else:
        from .aws.cli import run

        run(args, service, parser)


if __name__ == "__main__":
    main()
