# -*- coding: utf-8 -*-
"""Cálculos del estudio de precios de tarjetas de crédito.

Sin dependencias de Streamlit a propósito, como :mod:`simbad.client`: la página
``app_pages/tarjetas.py`` y el notebook ``notebooks/estudio_precios_tarjetas.ipynb``
usan estas mismas funciones, así que cualquier cifra de la página se puede reproducir
—y comprobar— desde el notebook.
"""

from __future__ import annotations

import pandas as pd

#: Las tres gamas de tarjeta personal, de menor a mayor. El API las nombra en
#: mayúsculas y con barras; aquí se usan nombres cortos para las etiquetas.
GAMAS = {
    "TARJETA DE CREDITO PERSONAL CLASICA/STANDARD": "Clásica",
    "TARJETA DE CREDITO PERSONAL ORO/GOLD": "Oro",
    "TARJETA DE CREDITO PERSONAL PLATINO/PLATINUM (O SUPERIOR)": "Platino",
}
ORDEN_GAMAS = ["Clásica", "Oro", "Platino"]

#: Entidades que deben publicar un servicio para que tenga sentido compararlo. Es el
#: umbral con todo el mercado (unas veintitrés entidades). Cuando el filtro de tipo
#: deja un universo pequeño —siete asociaciones, dos bancos de ahorro y crédito— se
#: exige la mitad de las presentes, nunca menos de dos, para no vaciar la página.
MINIMO_ENTIDADES = 6

#: Factor de las vallas de Tukey para marcar un precio como atípico.
FACTOR_ATIPICO = 1.5


def minimo_comparable(universo: int) -> int:
    """Entidades exigidas por concepto según cuántas hay en el universo comparado."""
    return max(2, min(MINIMO_ENTIDADES, universo // 2))


def cargos_disponibles(frame: pd.DataFrame) -> list[str]:
    """Tipos de cargo (campo ``concepto``) publicados en alguna tarjeta personal.

    Son las opciones del filtro «Tipo de cargo»: sólo se ofrecen los que aparecen en
    las tres gamas que analiza el estudio, para que ninguna opción deje la página vacía.
    """
    personales = frame[frame["tipoTarjeta"].isin(GAMAS)]
    return sorted(personales["concepto"].dropna().astype(str).str.strip().unique())


def dispersion(frame: pd.DataFrame) -> pd.DataFrame:
    """Precio mínimo, mediano y máximo de cada concepto, una fila por entidad.

    Se toma la mediana por entidad antes de comparar: un banco puede publicar varias
    tarjetas de la misma gama (distintas marcas) y no debe pesar más por ello. Si el
    período abarca varios meses, la misma mediana recorre los meses: el precio de la
    entidad es el que publicó de forma típica en ese período.
    """
    if frame.empty:
        return pd.DataFrame()
    por_entidad = (
        frame.groupby(["concepto", "unidadValor", "entidad"])["valor"].median().reset_index()
    )
    resumen = (
        por_entidad.groupby(["concepto", "unidadValor"])["valor"]
        .agg(entidades="count", minimo="min", mediana="median", maximo="max")
        .reset_index()
    )
    resumen["veces"] = resumen["maximo"] / resumen["minimo"]
    return resumen.sort_values("veces", ascending=False)


def precio_por_entidad(frame: pd.DataFrame) -> pd.DataFrame:
    """Precio de cada entidad en cada gama: la mediana de lo que publicó.

    Es la misma regla que :func:`dispersion`, una observación por entidad y gama,
    para que una entidad con varias marcas no cuente varias veces.
    """
    return (
        frame.groupby(["tipoEntidad", "entidad", "gama"])["valor"].median().reset_index()
    )


def estadistica_por_gama(precios: pd.DataFrame) -> pd.DataFrame:
    """Estadística descriptiva del precio en cada gama, sobre una fila por entidad.

    Además de lo que da ``describe()``, añade el coeficiente de variación (desviación
    entre media, en %) y cuántas veces el precio más alto supera al más bajo.
    """
    tabla = (
        precios.groupby("gama")["valor"]
        .describe()
        .rename(
            columns={
                "count": "entidades",
                "mean": "media",
                "std": "desviacion",
                "min": "minimo",
                "25%": "q1",
                "50%": "mediana",
                "75%": "q3",
                "max": "maximo",
            }
        )
    )
    tabla["entidades"] = tabla["entidades"].astype(int)
    tabla["cv"] = tabla["desviacion"] / tabla["media"] * 100
    tabla["veces"] = tabla["maximo"] / tabla["minimo"]
    orden = [g for g in ORDEN_GAMAS if g in tabla.index]
    return tabla.loc[orden].reset_index()


def atipicos(precios: pd.DataFrame, factor: float = FACTOR_ATIPICO) -> pd.DataFrame:
    """Precios fuera de las vallas de Tukey de su gama.

    Una valla es ``Q1 − factor·RIC`` y la otra ``Q3 + factor·RIC``, con RIC el rango
    intercuartílico. Es la misma regla que dibuja los bigotes de un diagrama de caja.
    """
    cuartiles = precios.groupby("gama")["valor"].quantile([0.25, 0.75]).unstack()
    ric = cuartiles[0.75] - cuartiles[0.25]
    vallas = pd.DataFrame(
        {
            "valla_inferior": cuartiles[0.25] - factor * ric,
            "valla_superior": cuartiles[0.75] + factor * ric,
        }
    )
    marcado = precios.join(vallas, on="gama")
    fuera = marcado[
        (marcado["valor"] < marcado["valla_inferior"])
        | (marcado["valor"] > marcado["valla_superior"])
    ]
    posicion = {g: i for i, g in enumerate(ORDEN_GAMAS)}
    return fuera.sort_values(
        ["gama", "valor"], key=lambda s: s.map(posicion) if s.name == "gama" else s
    ).reset_index(drop=True)


def explica(frame: pd.DataFrame, por: list[str], columna: str = "logp") -> float:
    """Parte de la variación del precio que queda explicada al conocer ``por``.

    Es la proporción de varianza que desaparece al sustituir cada precio por la media
    de su grupo. Cero significa que ese dato no dice nada; uno, que lo determina.
    """
    y = frame[columna]
    total = float(((y - y.mean()) ** 2).sum())
    if total <= 0:
        return 0.0
    medias = frame.groupby(por, observed=True)[columna].transform("mean")
    residual = float(((y - medias) ** 2).sum())
    return 1.0 - residual / total
