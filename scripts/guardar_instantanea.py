# -*- coding: utf-8 -*-
"""Guarda en notebooks/datos/ los datos del API que usa el notebook, para correrlo sin clave.

Quien tiene clave lo ejecuta una vez y sube la carpeta: el notebook, si no encuentra clave,
lee de ahí en lugar de llamar al API. Son estadísticas públicas de la Superintendencia;
la clave no se guarda en ningún archivo.

Desde la carpeta del proyecto:
    python scripts/guardar_instantanea.py
    python scripts/guardar_instantanea.py --desde 2025-01 --periodo 2026-05
"""

import argparse
import json
import os
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from simbad.historial import descargar_meses  # noqa: E402

URL = "https://apis.sb.gob.do/estadisticas/v2/tasas-comisiones/tarjetas-credito"
TIPOS_ACEPTADOS = ["BM", "AAyP", "BAyC"]
REGISTROS_POR_PAGINA = 1000
DESTINO = RAIZ / "notebooks" / "datos"

#: Meses hacia atrás que se sondean buscando el último publicado, como en el notebook.
MESES_SONDEO = 15


def leer_clave() -> str:
    """Clave del API: primero la variable de entorno, luego el secrets.toml de la app."""
    clave = os.environ.get("SIMBAD_API_KEY", "").strip()
    if clave:
        return clave
    secretos = RAIZ / ".streamlit" / "secrets.toml"
    if secretos.exists():
        with secretos.open("rb") as archivo:
            clave = str(tomllib.load(archivo).get("simbad", {}).get("api_key", "")).strip()
    if not clave:
        sys.exit("Falta la clave: define SIMBAD_API_KEY o crea .streamlit/secrets.toml")
    return clave


def nueva_sesion(clave: str) -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "Ocp-Apim-Subscription-Key": clave,
            "Accept": "application/json",
            # Sin User-Agent, el firewall delante del API bloquea la petición.
            "User-Agent": "simbad-instantanea/1.0",
        }
    )
    return sesion


def consultar(sesion, params, intentos: int = 3) -> requests.Response:
    """GET al endpoint de tarjetas, con reintentos ante cortes del gateway."""
    for intento in range(1, intentos + 1):
        try:
            respuesta = sesion.get(URL, params=params, timeout=120)
            if respuesta.status_code < 500:
                return respuesta
        except (requests.ConnectionError, requests.Timeout):
            if intento == intentos:
                raise
        time.sleep(2**intento)
    return respuesta


def parametros(periodo: str, pagina: int = 1, registros: int = REGISTROS_POR_PAGINA):
    return (
        [("periodoInicial", periodo), ("periodoFinal", periodo)]
        + [("tipoEntidad", t) for t in TIPOS_ACEPTADOS]
        + [("paginas", str(pagina)), ("registros", str(registros))]
    )


def primera_llamada(sesion, mes: str) -> dict:
    r = consultar(sesion, parametros(mes, registros=3))
    r.raise_for_status()
    return {
        "mes": mes,
        "url": r.url,
        "http": r.status_code,
        "segundos": r.elapsed.total_seconds(),
        "x_pagination": json.loads(r.headers.get("x-pagination", "{}")),
        "primer_registro": r.json()[0],
    }


def errores(sesion, mes: str) -> list[dict]:
    base = [("periodoInicial", mes), ("periodoFinal", mes)]
    casos = {
        "Sin tipoEntidad ni entidad": base + [("registros", "3")],
        "tipoEntidad=CC (corporaciones)": base + [("tipoEntidad", "CC"), ("registros", "3")],
        "tipoEntidad=BM,AAyP (con comas)": base + [("tipoEntidad", "BM,AAyP"), ("registros", "3")],
    }
    salida = []
    for caso, params in casos.items():
        r = consultar(sesion, params)
        salida.append({"caso": caso, "http": r.status_code, "texto": r.text[:110]})
    return salida


def sondear(sesion) -> tuple[str, list[dict]]:
    hoy = pd.Timestamp.today().to_period("M")
    sondeo = []
    for atras in range(MESES_SONDEO):
        mes = str(hoy - atras)
        r = consultar(sesion, parametros(mes, registros=5))
        cuerpo = r.json() if r.status_code == 200 else []
        filas = len(cuerpo) if isinstance(cuerpo, list) else 0
        sondeo.append({"periodo": mes, "http": r.status_code, "registros": filas})
        if filas:
            return mes, sondeo
    sys.exit(f"Ningún mes con datos en los últimos {MESES_SONDEO} meses")


def descargar(sesion, periodo: str) -> tuple[pd.DataFrame, dict]:
    """Tarifario completo de un mes, página por página, sin quitar repetidas."""
    lotes, pagina = [], 1
    while True:
        r = consultar(sesion, parametros(periodo, pagina=pagina))
        r.raise_for_status()
        lote = r.json()
        info = json.loads(r.headers.get("x-pagination", "{}"))
        lotes.append(pd.DataFrame(lote))
        print(f"  página {pagina:>2} de {info.get('TotalPages', '?')}: {len(lote):>5} registros")
        if not info.get("HasNext") or not lote:
            break
        pagina += 1
    datos = pd.concat(lotes, ignore_index=True)
    return datos, {"paginas": pagina, "anunciados": info.get("TotalRecords"), "registros": len(datos)}


def filas_unicas(marco: pd.DataFrame) -> set:
    return set(map(tuple, marco.astype(str)[sorted(marco.columns)].drop_duplicates().to_numpy()))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    opciones = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opciones.add_argument("--desde", default="2025-01", help="Primer mes del tarifario, AAAA-MM")
    opciones.add_argument("--periodo", default=None, help="Mes del análisis; por defecto, el último")
    args = opciones.parse_args()

    try:
        # Valida TLS con el almacén de Windows, por si la red inspecciona HTTPS.
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    clave = leer_clave()
    sesion = nueva_sesion(clave)
    try:
        print("Sondeando el último mes publicado...")
        ultimo, sondeo = sondear(sesion)
        periodo = args.periodo or ultimo
        mes_prueba = str(pd.Timestamp.today().to_period("M") - 12)
        llamada = primera_llamada(sesion, mes_prueba)
        casos = errores(sesion, mes_prueba)

        print(f"Descargando {periodo} página a página...")
        crudo, paginacion = descargar(sesion, periodo)
        print(f"Pidiendo {periodo} en una sola página...")
        r = consultar(sesion, parametros(periodo, registros=20000))
        r.raise_for_status()
        una_pagina = pd.DataFrame(r.json())
    except requests.RequestException as error:
        sys.exit(f"No se pudo conectar con el API: {error}")

    meses = [str(m) for m in pd.period_range(args.desde, ultimo, freq="M")]
    print(f"Tarifario de {meses[0]} a {meses[-1]} (los meses ya guardados no se descargan)...")
    historia, fallidos = descargar_meses(clave, meses)
    if fallidos:
        sys.exit(f"No se pudieron descargar: {fallidos}. Vuelve a ejecutarlo.")

    (DESTINO / "tarifario").mkdir(parents=True, exist_ok=True)
    crudo.to_parquet(DESTINO / f"crudo_{periodo}.parquet", index=False)
    mes_de = historia["periodo"].astype(str).str[:7]
    for mes in meses:
        historia[mes_de == mes].to_parquet(DESTINO / "tarifario" / f"{mes}.parquet", index=False)

    llamadas = {
        "descargado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ultimo": ultimo,
        "periodo": periodo,
        "sondeo": sondeo,
        "primera_llamada": llamada,
        "errores": casos,
        "paginacion": paginacion,
        "una_pagina": {
            "filas": len(una_pagina),
            "unicas": len(una_pagina.drop_duplicates()),
            "segundos": r.elapsed.total_seconds(),
            "iguales": filas_unicas(una_pagina) == filas_unicas(crudo),
        },
    }
    texto = json.dumps(llamadas, ensure_ascii=False, indent=2, default=str)
    if clave in texto:
        sys.exit("La clave apareció en lo que se iba a guardar: no se escribe nada.")
    (DESTINO / "llamadas.json").write_text(texto, encoding="utf-8")

    print(f"Listo en {DESTINO}: crudo de {periodo} ({len(crudo):,} filas), {len(meses)} meses, llamadas.json")


if __name__ == "__main__":
    main()
