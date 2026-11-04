"""Parseo HCL de las raices versionadas; no inicializa providers ni consulta AWS."""

import sys

import hcl2

from verify import IAC_ROOTS, ROOT


def main() -> int:
    failures = 0
    for directory in IAC_ROOTS:
        files = sorted((ROOT / directory).glob("*.tf"))
        if not files:
            print(f"FAIL: no hay archivos .tf en {directory}")
            failures += 1
        for path in files:
            try:
                with path.open(encoding="utf-8") as source:
                    hcl2.load(source)
                print(f"OK: {path.relative_to(ROOT)}")
            except Exception as error:
                print(f"FAIL: {path.relative_to(ROOT)}: {error}")
                failures += 1
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
