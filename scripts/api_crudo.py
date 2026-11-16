# -*- coding: utf-8 -*-
"""Muestra el tarifario de tarjetas tal cual lo devuelve el API, sin ningún tratamiento.

No usa el cliente de la app a propósito: aquí no se quitan filas repetidas, no se elige la
fila mayor y no se agrupa nada. Sirve para comprobar qué publica realmente el API.

Ejemplos, desde la carpeta del proyecto:
    python scripts/api_crudo.py
    python scripts/api_crudo.py --concepto "Cargo por Renovación"
    python scripts/api_crudo.py --entidad "LA NACIONAL" --desde 2026-01 --hasta 2026-05
"""

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

import requests

URL = "https://apis.sb.gob.do/estadisticas/v2/tasas-comisiones/tarjetas-credito"

#: Una sola página basta para una entidad; el API acepta este tamaño.
REGISTROS = 20000

#: El gateway corta hacia los 60 segundos; se le da margen.
ESPERA_SEGUNDOS = 120


def leer_clave() -> str:
    """Clave del API: primero la variable de entorno, luego el secrets.toml de la app."""
    clave = os.environ.get("SIMBAD_API_KEY", "").strip()
    if clave:
        return clave
    secretos = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if secretos.exists():
        with secretos.open("rb") as archivo:
            clave = str(tomllib.load(archivo).get("simbad", {}).get("api_key", "")).strip()
    if not clave:
        sys.exit("Falta la clave: define SIMBAD_API_KEY o crea .streamlit/secrets.toml")
    return clave


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    opciones = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opciones.add_argument("--entidad", default="LA NACIONAL")
    opciones.add_argument("--desde", default="2026-05", help="Mes inicial, AAAA-MM")
    opciones.add_argument("--hasta", default=None, help="Mes final; por defecto, igual a --desde")
    opciones.add_argument("--concepto", default=None, help="Deja sólo este cargo, nombre exacto")
    args = opciones.parse_args()

    try:
        # Valida TLS con el almacén de Windows, por si la red inspecciona HTTPS.
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    try:
        respuesta = requests.get(
            URL,
            params={
                "periodoInicial": args.desde,
                "periodoFinal": args.hasta or args.desde,
                "entidad": args.entidad,
                "paginas": 1,
                "registros": REGISTROS,
            },
            headers={
                "Ocp-Apim-Subscription-Key": leer_clave(),
                # Sin User-Agent, el firewall delante del API bloquea la petición.
                "User-Agent": "simbad-api-crudo/1.0",
            },
            timeout=ESPERA_SEGUNDOS,
        )
    except requests.RequestException as error:
        sys.exit(f"No se pudo conectar con el API: {error}")

    print(f"HTTP {respuesta.status_code} | {URL}", file=sys.stderr)
    if not respuesta.ok:
        sys.exit(f"El API respondió con error: {respuesta.text[:500]}")

    cuerpo = respuesta.json()
    filas = cuerpo if isinstance(cuerpo, list) else next(
        (v for v in cuerpo.values() if isinstance(v, list)), []
    )
    total = len(filas)
    if args.concepto:
        filas = [f for f in filas if str(f.get("concepto", "")).strip() == args.concepto]

    print(json.dumps(filas, ensure_ascii=False, indent=2))
    print(f"{len(filas)} filas mostradas de {total} recibidas.", file=sys.stderr)


if __name__ == "__main__":
    main()
