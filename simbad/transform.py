# -*- coding: utf-8 -*-
"""Transformaciones de datos y etiquetado legible para las series del SIMBAD.

Todas las funciones son puras (pandas, sin Streamlit) para poder probarlas
aisladamente.
"""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from simbad.catalog import AGGREGATE_MARKER, ENDPOINTS

#: Nombres legibles para columnas cuyo camelCase no basta o que llevan acento.
_LABELS: dict[str, str] = {
    "periodo": "Período",
    "tipoEntidad": "Tipo de entidad",
    "entidad": "Entidad",
    "tipoTarjeta": "Tipo de tarjeta",
    "nombreProducto": "Nombre del producto",
    "formatoTarifa": "Formato de tarifa",
    "unidadValor": "Unidad del valor",
}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def label(column: str) -> str:
    """Etiqueta legible para una columna del API."""
    if column in _LABELS:
        return _LABELS[column]
    words = _CAMEL.sub(" ", column).strip()
    return words[:1].upper() + words[1:]


def labels(columns: Iterable[str]) -> dict[str, str]:
    """Mapa ``columna -> etiqueta`` para renombrar un ``DataFrame``."""
    return {c: label(c) for c in columns}


def measure_kind(endpoint_id: str, measure: str) -> str:
    """Tipo de medida: ``monto``, ``porcentaje`` o ``conteo``."""
    meta = ENDPOINTS.get(endpoint_id, {})
    return meta.get("measure_kinds", {}).get(measure, "monto")


# --------------------------------------------------------------- Formateo


def number_format(kind: str) -> str:
    """Formato ``column_config.NumberColumn`` acorde al tipo de medida.

    Los montos van con separadores de miles y sin sufijos: en una tabla se busca la
    cifra exacta, y las abreviaturas compactas del inglés (K/M/B) se malinterpretan.
    """
    if kind == "porcentaje":
        return "%.2f %%"
    return "localized"


# ------------------------------------------------------ Filas agregadas


def _dimension_columns(frame: pd.DataFrame, endpoint_id: str | None) -> list[str]:
    """Columnas de dimensión presentes en el marco, salvo el período."""
    if endpoint_id:
        declaradas = ENDPOINTS.get(endpoint_id, {}).get("dimensions", [])
        return [c for c in declaradas if c != "periodo" and c in frame.columns]
    # pandas 3 infiere las columnas de texto como dtype `str`, no `object`; comparar
    # contra `object` las perdía todas y dejaba pasar las filas comodín TODOS.
    texto = frame.select_dtypes(include=["object", "string"]).columns
    return [c for c in texto if c != "periodo"]


def is_detail(frame: pd.DataFrame, endpoint_id: str | None = None) -> pd.Series:
    """Máscara de las filas de detalle: ninguna dimensión vale ``TODOS``.

    El API repite cada cifra en varios niveles de agregación usando ``TODOS`` como
    comodín. Sumar sin filtrar multiplica los totales.
    """
    if frame.empty:
        return pd.Series(dtype=bool)
    mascara = pd.Series(True, index=frame.index)
    for columna in _dimension_columns(frame, endpoint_id):
        mascara &= frame[columna].astype("string").str.upper().fillna("") != AGGREGATE_MARKER
    return mascara


def drop_aggregates(frame: pd.DataFrame, endpoint_id: str | None = None) -> pd.DataFrame:
    """Deja sólo las filas de detalle, que son las que se pueden sumar."""
    if frame.empty:
        return frame
    return frame[is_detail(frame, endpoint_id)]


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Serializa uno o más ``DataFrame`` a un libro de Excel en memoria."""
    import io

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            # Excel limita los nombres de hoja a 31 caracteres.
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()
