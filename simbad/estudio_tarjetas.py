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

#: La variable del grupo: la página abre con ella y el notebook la analiza.
CARGO_GRUPO = "Cargo por Renovación"

#: Meses de cada trimestre, para comparar períodos en la línea de tiempo.
TRIMESTRES = {"T1": (1, 2, 3), "T2": (4, 5, 6), "T3": (7, 8, 9), "T4": (10, 11, 12)}


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


# ------------------------------------------------------------ Línea de tiempo


def precios_personales(frame: pd.DataFrame, moneda: str) -> pd.DataFrame:
    """Precios únicos de las tres gamas personales en una moneda, con su ``gama``.

    Aparta las filas que declaran un rango en vez de un precio (``valorMinimo`` > 0,
    con ``valor`` en cero) y las de precio cero, igual en la foto de un mes que en la
    línea de tiempo.
    """
    marco = frame.reset_index(drop=True)
    valor = pd.to_numeric(marco["valor"], errors="coerce")
    minimo = pd.to_numeric(marco["valorMinimo"], errors="coerce").fillna(0)
    elegidas = (
        (minimo <= 0)
        & (valor > 0)
        & (marco["moneda"] == moneda)
        & marco["tipoTarjeta"].isin(GAMAS)
    )
    return marco[elegidas].assign(
        valor=valor[elegidas], gama=lambda d: d["tipoTarjeta"].map(GAMAS)
    )


def nombre_variable(cargo: str, periodicidad: str | None) -> str:
    """Nombre del cargo con su periodicidad: ``Cargo por Renovación anual``."""
    sufijo = {"ANUAL": "anual", "MENSUAL": "mensual"}.get(str(periodicidad))
    return f"{cargo} {sufijo}" if sufijo else cargo


def meses_del_trimestre(anio: int, trimestre: str) -> list[str]:
    """``(2025, "T1")`` → ``["2025-01", "2025-02", "2025-03"]``."""
    return [f"{anio}-{mes:02d}" for mes in TRIMESTRES[trimestre]]


def meses_de_la_linea(inicio: str, fin: str, obligatorios: list[str]) -> list[str]:
    """Meses que dibuja la línea de tiempo entre ``inicio`` y ``fin``.

    Cada mes tarda unos cuarenta segundos en descargarse. Hasta dos años se piden todos;
    con más, un mes de cada tres o de cada seis, siempre con los ``obligatorios``, que
    son los de los dos períodos que se comparan.
    """
    todos = pd.period_range(inicio, fin, freq="M").astype(str).tolist()
    paso = 1 if len(todos) <= 24 else 3 if len(todos) <= 60 else 6
    return sorted(set(todos[::paso]) | set(obligatorios))


def serie_mensual(filas: pd.DataFrame) -> pd.DataFrame:
    """Mediana y cuartiles del precio entre entidades, por mes y gama.

    Primero se toma la mediana por entidad, para que una entidad con varias marcas no
    cuente varias veces, igual que en :func:`precio_por_entidad`.
    """
    por_entidad = (
        filas.assign(mes=filas["periodo"].astype(str).str[:7])
        .groupby(["mes", "gama", "entidad"])["valor"]
        .median()
        .reset_index()
    )
    return (
        por_entidad.groupby(["mes", "gama"])["valor"]
        .agg(
            entidades="count",
            q1=lambda v: v.quantile(0.25),
            mediana="median",
            q3=lambda v: v.quantile(0.75),
        )
        .reset_index()
    )


def comparar_periodos(
    filas: pd.DataFrame, meses_a: list[str], meses_b: list[str]
) -> pd.DataFrame:
    """Precio de cada entidad y gama en dos períodos, sólo si publicó en ambos.

    Exigir las dos fechas evita un efecto de composición: si entra un banco caro, la
    mediana sube aunque nadie haya cambiado de precio.
    """
    mes = filas["periodo"].astype(str).str[:7]
    claves = ["gama", "entidad"]
    tabla = pd.concat(
        {
            "precio_a": filas[mes.isin(meses_a)].groupby(claves)["valor"].median(),
            "precio_b": filas[mes.isin(meses_b)].groupby(claves)["valor"].median(),
        },
        axis=1,
    ).dropna()
    return (
        tabla.assign(
            cambio=lambda d: d["precio_b"] - d["precio_a"],
            cambio_pct=lambda d: (d["precio_b"] / d["precio_a"] - 1) * 100,
        )
        .reset_index()
        .sort_values("cambio_pct", ascending=False, ignore_index=True)
    )


def resumen_comparacion(tabla: pd.DataFrame) -> pd.DataFrame:
    """Por gama: variación de la mediana, cuántas entidades cambiaron y la dispersión."""
    resumen = tabla.groupby("gama").agg(
        entidades=("entidad", "count"),
        mediana_a=("precio_a", "median"),
        mediana_b=("precio_b", "median"),
        suben=("cambio", lambda c: int((c > 0).sum())),
        bajan=("cambio", lambda c: int((c < 0).sum())),
        iguales=("cambio", lambda c: int((c == 0).sum())),
        min_a=("precio_a", "min"),
        max_a=("precio_a", "max"),
        min_b=("precio_b", "min"),
        max_b=("precio_b", "max"),
    )
    resumen["variacion_pct"] = (resumen["mediana_b"] / resumen["mediana_a"] - 1) * 100
    resumen["veces_a"] = resumen["max_a"] / resumen["min_a"]
    resumen["veces_b"] = resumen["max_b"] / resumen["min_b"]
    orden = [g for g in ORDEN_GAMAS if g in resumen.index]
    return resumen.loc[orden].drop(columns=["min_a", "max_a", "min_b", "max_b"]).reset_index()
