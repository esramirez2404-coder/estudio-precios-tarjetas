# -*- coding: utf-8 -*-
"""Descarga del tarifario mes a mes, para la línea de tiempo.

Sin dependencias de Streamlit: la usan la página y el notebook. Cada mes tarda unos
cuarenta segundos, así que se piden en paralelo y se guardan en ``.cache/tarifario``: un
mes ya publicado no cambia, y volver a compararlo no debe costar otra descarga.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from simbad.client import SimbadAPIError, SimbadClient
from simbad.transform import drop_aggregates

log = logging.getLogger(__name__)

ENDPOINT = "TasasComisionesTarjetasCredito"

#: Este conjunto rechaza los códigos de corporaciones y entidades públicas (HTTP 400).
TIPOS_ACEPTADOS = ("BM", "AAyP", "BAyC")

#: Descargas simultáneas. Con más, el gateway empieza a cortar conexiones.
HILOS = 4

CARPETA = Path(__file__).resolve().parent.parent / ".cache" / "tarifario"


def _ruta(mes: str) -> Path:
    return CARPETA / f"{mes}.parquet"


def _leer(mes: str) -> pd.DataFrame | None:
    """Mes guardado, o ``None`` si no está o el archivo no se puede leer."""
    try:
        return pd.read_parquet(_ruta(mes))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer %s del disco: %s", mes, exc)
        return None


def _guardar(mes: str, marco: pd.DataFrame) -> None:
    """Guarda un mes; si el disco falla, la app sigue y sólo pierde el atajo."""
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        temporal = _ruta(mes).with_suffix(".tmp")
        marco.to_parquet(temporal, index=False)
        temporal.replace(_ruta(mes))
    except OSError as exc:
        log.warning("No se pudo guardar %s en disco: %s", mes, exc)


def _bajar(api_key: str, mes: str) -> pd.DataFrame:
    # Un cliente por hilo: el cliente recuerda el modo de paginación que detectó.
    marco, _ = SimbadClient(api_key).fetch(
        ENDPOINT, mes, mes, filters={"tipoEntidad": list(TIPOS_ACEPTADOS)}
    )
    return drop_aggregates(marco, ENDPOINT)


def descargar_meses(
    api_key: str,
    meses: Sequence[str],
    *,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Tarifario de varios meses y lista de los que no se pudieron descargar.

    ``al_avanzar(hechos, total)`` se llama desde el hilo principal tras cada mes, para
    que quien llama pueda dibujar una barra de progreso.
    """
    guardados = {mes: _leer(mes) for mes in meses}
    marcos = [m for m in guardados.values() if m is not None]
    pendientes = [mes for mes, m in guardados.items() if m is None]
    fallidos: list[str] = []
    hechos = len(marcos)

    if pendientes:
        with ThreadPoolExecutor(max_workers=HILOS) as hilos:
            futuros = {hilos.submit(_bajar, api_key, mes): mes for mes in pendientes}
            for futuro in as_completed(futuros):
                mes = futuros[futuro]
                try:
                    marco = futuro.result()
                except SimbadAPIError as exc:
                    log.warning("No se pudo descargar %s: %s", mes, exc)
                    fallidos.append(mes)
                else:
                    if not marco.empty:
                        _guardar(mes, marco)
                        marcos.append(marco)
                hechos += 1
                if al_avanzar:
                    al_avanzar(hechos, len(guardados))

    unido = pd.concat(marcos, ignore_index=True) if marcos else pd.DataFrame()
    return unido, sorted(fallidos)
