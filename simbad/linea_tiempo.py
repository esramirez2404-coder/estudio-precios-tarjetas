# -*- coding: utf-8 -*-
"""Línea de tiempo del cargo: cómo evoluciona su precio y comparación entre dos períodos.

Es un fragmento de Streamlit: cambiar los períodos o la gama sólo vuelve a dibujar esta
sección, no toda la página. Los cálculos salen de :mod:`simbad.estudio_tarjetas`, que el
notebook del estudio usa también.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from simbad import data, historial, ui
from simbad.estudio_tarjetas import (
    ORDEN_GAMAS,
    TRIMESTRES,
    comparar_periodos,
    meses_de_la_linea,
    meses_del_trimestre,
    precios_personales,
    resumen_comparacion,
    serie_mensual,
)
from simbad.ficha_cargo import ESCALA_GAMAS, eje_precio

#: El mismo color marca cada período en la banda de la línea y en los puntos por entidad.
COLOR_A = "#FF2E93"
COLOR_B = "#00E5FF"

#: Primer año que publica el API para este conjunto.
PRIMER_ANIO = 2018

#: Vega escribe los meses en inglés; esto los pone en español en el eje.
_MES_EN_ESPANOL = (
    "['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']"
    "[month(datum.value)] + ' ' + timeFormat(datum.value, '%y')"
)

_NOMBRES_TRIMESTRE = {
    "T1": "T1 (ene–mar)",
    "T2": "T2 (abr–jun)",
    "T3": "T3 (jul–sep)",
    "T4": "T4 (oct–dic)",
}


def _selector_periodo(letra: str, anios: list[int], anio_defecto: int) -> tuple[int, str]:
    """Año y trimestre de uno de los dos períodos."""
    with st.container(border=True, key=f"linea_periodo_{letra}"):
        st.markdown(f"**Período {letra}**")
        anio = st.selectbox(
            f"Año del período {letra}",
            options=anios,
            index=anios.index(anio_defecto),
            key=f"linea_anio_{letra}",
        )
        trimestre = st.segmented_control(
            f"Trimestre del período {letra}",
            options=list(TRIMESTRES),
            default="T1",
            required=True,
            format_func=lambda t: _NOMBRES_TRIMESTRE[t],
            key=f"linea_trimestre_{letra}",
        )
    return anio, trimestre


def _filas_de_la_variable(
    marco: pd.DataFrame,
    *,
    cargo: str,
    periodicidad: str,
    unidad: str,
    moneda: str,
    tipos: list[str],
) -> pd.DataFrame:
    """Sólo la variable analizada, con los mismos filtros que el resto de la página."""
    filas = precios_personales(marco, moneda)
    if tipos:
        filas = filas[ui.entity_type_codes(filas["tipoEntidad"]).isin(tipos)]
    return filas[
        (filas["concepto"] == cargo)
        & (filas["periodicidad"] == periodicidad)
        & (filas["unidadValor"] == unidad)
    ]


def _banda(meses: list[str], color: str, nombre: str) -> alt.LayerChart:
    """Franja vertical que marca un período, con su nombre arriba."""
    inicio = pd.Timestamp(f"{meses[0]}-01") - pd.Timedelta(days=15)
    fin = pd.Timestamp(f"{meses[-1]}-01") + pd.Timedelta(days=15)
    fila = pd.DataFrame(
        {"inicio": [inicio], "fin": [fin], "medio": [inicio + (fin - inicio) / 2], "nombre": [nombre]}
    )
    franja = alt.Chart(fila).mark_rect(color=color, opacity=0.2).encode(x="inicio:T", x2="fin:T")
    rotulo = (
        alt.Chart(fila)
        .mark_text(color=color, fontWeight="bold", fontSize=13, dy=-4)
        .encode(x="medio:T", y=alt.value(12), text="nombre:N")
    )
    return franja + rotulo


def _grafico_linea(
    serie: pd.DataFrame,
    *,
    meses_a: list[str],
    meses_b: list[str],
    nombre_a: str,
    nombre_b: str,
    unidad: str,
) -> None:
    """Mediana por gama a lo largo del tiempo, con su rango intercuartílico."""
    datos = serie.assign(fecha=lambda d: pd.to_datetime(d["mes"] + "-01"))
    foco = alt.selection_point(
        fields=["fecha"], on="pointerover", nearest=True, empty=False, clear="pointerout"
    )
    eje_x = alt.X(
        "fecha:T",
        title=None,
        axis=alt.Axis(
            labelExpr=_MES_EN_ESPANOL,
            grid=False,
            labelAngle=0,
            labelOverlap="greedy",
            tickCount={"interval": "month", "step": 1},
        ),
    )
    base = alt.Chart(datos).encode(x=eje_x)
    color = alt.Color("gama:N", scale=ESCALA_GAMAS, title="Gama", sort=ORDEN_GAMAS)
    rango = base.mark_area(opacity=0.14).encode(
        y=alt.Y("q1:Q", title=None, scale=alt.Scale(type="log", nice=False)),
        y2="q3:Q",
        color=alt.Color("gama:N", scale=ESCALA_GAMAS, legend=None),
    )
    lineas = base.mark_line(strokeWidth=3).encode(
        y=eje_precio("mediana", f"Precio mediano ({unidad})"), color=color
    )
    puntos = base.mark_circle(size=70).encode(
        y=eje_precio("mediana", f"Precio mediano ({unidad})"),
        color=alt.Color("gama:N", scale=ESCALA_GAMAS, legend=None),
        opacity=alt.condition(foco, alt.value(1.0), alt.value(0.55)),
        tooltip=[
            alt.Tooltip("mes:N", title="Mes"),
            alt.Tooltip("gama:N", title="Gama"),
            alt.Tooltip("mediana:Q", title="Mediana", format=",.2f"),
            alt.Tooltip("q1:Q", title="Q1", format=",.2f"),
            alt.Tooltip("q3:Q", title="Q3", format=",.2f"),
            alt.Tooltip("entidades:Q", title="Entidades"),
        ],
    ).add_params(foco)
    regla = (
        base.mark_rule(color="#FFFFFF", opacity=0.55, strokeDash=[4, 4])
        .transform_filter(foco)
    )
    grafico = alt.layer(
        _banda(meses_a, COLOR_A, nombre_a),
        _banda(meses_b, COLOR_B, nombre_b),
        rango,
        lineas,
        regla,
        puntos,
    ).properties(height=420)
    st.altair_chart(grafico, width="stretch")


def _grafico_por_entidad(tabla: pd.DataFrame, nombre_a: str, nombre_b: str, unidad: str) -> None:
    """Cada entidad con sus dos precios, unidos: la longitud del tramo es el cambio."""
    orden = tabla["entidad"].tolist()
    largo = tabla.melt(
        id_vars=["entidad", "cambio_pct"],
        value_vars=["precio_a", "precio_b"],
        var_name="columna",
        value_name="precio",
    ).assign(periodo=lambda d: d["columna"].map({"precio_a": nombre_a, "precio_b": nombre_b}))
    eje_y = alt.Y("entidad:N", sort=orden, title=None)
    escala_x = alt.Scale(type="log", nice=False)
    tramo = (
        alt.Chart(tabla)
        .mark_rule(color="#AEBBDD", strokeWidth=2)
        .encode(
            y=eje_y,
            x=alt.X(
                "precio_a:Q",
                scale=escala_x,
                title=f"Precio ({unidad}), escala logarítmica",
                axis=alt.Axis(format=",.3~r", tickCount=6),
            ),
            x2="precio_b:Q",
        )
    )
    puntos = (
        alt.Chart(largo)
        .mark_circle(size=120, opacity=1)
        .encode(
            y=eje_y,
            x=alt.X("precio:Q", scale=escala_x),
            color=alt.Color(
                "periodo:N",
                scale=alt.Scale(domain=[nombre_a, nombre_b], range=[COLOR_A, COLOR_B]),
                title=None,
                legend=alt.Legend(orient="top"),
            ),
            tooltip=[
                alt.Tooltip("entidad:N", title="Entidad"),
                alt.Tooltip("periodo:N", title="Período"),
                alt.Tooltip("precio:Q", title="Precio", format=",.2f"),
                alt.Tooltip("cambio_pct:Q", title="Cambio (%)", format="+.1f"),
            ],
        )
    )
    alto = max(260, 26 * len(tabla) + 70)
    st.altair_chart((tramo + puntos).properties(height=alto), width="stretch")


def _cambio_del_indicador(variacion: float, nombre_a: str) -> dict:
    """Variación del indicador. Subir va en rojo: un cargo más caro es peor para quien paga."""
    if abs(variacion) < 0.05:
        return {
            "delta": f"Sin cambio frente a {nombre_a}",
            "delta_color": "off",
            "delta_arrow": "off",
        }
    return {"delta": f"{variacion:+.1f} % frente a {nombre_a}", "delta_color": "inverse"}


def _lectura(resumen: pd.DataFrame, nombre_a: str, nombre_b: str) -> str:
    """El resultado de la comparación, en palabras."""
    partes = [
        f"en {f.gama.lower()}, {f.variacion_pct:+.1f} % ({f.suben} suben, {f.bajan} bajan, "
        f"{f.iguales} igual)"
        for f in resumen.itertuples()
    ]
    mayor = resumen.loc[(resumen["veces_b"] - resumen["veces_a"]).abs().idxmax()]
    return (
        f"**De {nombre_a} a {nombre_b}** la mediana cambia así, contando sólo las entidades "
        f"que publicaron en ambos períodos: {'; '.join(partes)}. La distancia entre la más "
        f"cara y la más barata de {mayor['gama'].lower()} pasa de {mayor['veces_a']:.1f} a "
        f"{mayor['veces_b']:.1f} veces."
    )


@st.fragment
def linea_de_tiempo(
    *, cargo: str, periodicidad: str, unidad: str, moneda: str, tipos: list[str]
) -> None:
    """Sección completa: elegir dos trimestres, ver la línea y comparar entidad por entidad."""
    ultimo = data.latest_period_for(historial.ENDPOINT)
    ultimo_anio = int(ultimo[:4])
    anios = list(range(ultimo_anio, PRIMER_ANIO - 1, -1))

    izq, der = st.columns(2)
    with izq:
        anio_a, trimestre_a = _selector_periodo("A", anios, ultimo_anio - 1)
    with der:
        anio_b, trimestre_b = _selector_periodo("B", anios, ultimo_anio)
    anio_a, trimestre_a, anio_b, trimestre_b = ui.apply_gate(
        key="linea", pending=(anio_a, trimestre_a, anio_b, trimestre_b), label="Comparar"
    )

    nombre_a, nombre_b = f"{trimestre_a} {anio_a}", f"{trimestre_b} {anio_b}"
    meses_a = [m for m in meses_del_trimestre(anio_a, trimestre_a) if m <= ultimo]
    meses_b = [m for m in meses_del_trimestre(anio_b, trimestre_b) if m <= ultimo]
    if not meses_a or not meses_b:
        st.info(
            f"El API publica este tarifario hasta {ultimo}: elige un trimestre con datos.",
            icon=":material/event_busy:",
        )
        return
    if meses_a == meses_b:
        st.info("Elige dos trimestres distintos para compararlos.", icon=":material/compare_arrows:")
        return
    if meses_b[0] < meses_a[0]:
        meses_a, meses_b = meses_b, meses_a
        nombre_a, nombre_b = nombre_b, nombre_a

    meses = meses_de_la_linea(meses_a[0], meses_b[-1], meses_a + meses_b)
    barra = st.progress(0.0, text=f"Preparando {len(meses)} meses del tarifario…")
    marco, fallidos = data.tarifario_por_meses(
        meses,
        al_avanzar=lambda hechos, total: barra.progress(
            hechos / total, text=f"Descargados {hechos} de {total} meses del tarifario…"
        ),
    )
    barra.empty()
    if fallidos:
        st.warning(
            f"No se pudieron descargar {', '.join(fallidos)}: la línea queda sin esos meses. "
            "Pulsa «Comparar» más tarde para reintentarlo.",
            icon=":material/cloud_off:",
        )
    if marco.empty:
        st.info("El API no devolvió tarifas para estos meses.", icon=":material/info:")
        return

    filas = _filas_de_la_variable(
        marco, cargo=cargo, periodicidad=periodicidad, unidad=unidad, moneda=moneda, tipos=tipos
    )
    tabla = comparar_periodos(filas, meses_a, meses_b)
    if tabla.empty:
        st.info(
            f"Ninguna entidad publica este cargo en {nombre_a} y en {nombre_b} a la vez, con "
            "estos filtros. Prueba con otros trimestres o amplía el tipo de entidad.",
            icon=":material/info:",
        )
        return

    resumen = resumen_comparacion(tabla)
    serie = serie_mensual(filas)
    ui.kpi_row(
        [
            {
                "label": f"{f.gama}: mediana en {nombre_b}",
                "value": f"{f.mediana_b:,.0f} {unidad}",
                **_cambio_del_indicador(f.variacion_pct, nombre_a),
                "help": f"Mediana de las {f.entidades} entidades que publicaron en ambos "
                f"períodos. En {nombre_a} era {f.mediana_a:,.0f} {unidad}.",
                "chart_data": serie.loc[serie["gama"] == f.gama, "mediana"].tolist(),
            }
            for f in resumen.itertuples()
        ]
    )

    with st.container(border=True):
        st.markdown("**El precio mediano, mes a mes**")
        _grafico_linea(
            serie,
            meses_a=meses_a,
            meses_b=meses_b,
            nombre_a=nombre_a,
            nombre_b=nombre_b,
            unidad=unidad,
        )
        st.caption(
            "La línea es la mediana entre entidades de cada gama y la franja suave va de su "
            "primer a su tercer cuartil."
            + (" Con un rango tan largo se muestra sólo una parte de los meses." if len(meses)
               < len(pd.period_range(meses_a[0], meses_b[-1], freq="M")) else "")
        )

    st.info(_lectura(resumen, nombre_a, nombre_b), icon=":material/insights:")

    gamas = resumen["gama"].tolist()
    gama = st.segmented_control(
        "Gama que se compara entidad por entidad",
        options=gamas,
        default=gamas[0],
        required=True,
        key="linea_gama",
    ) or gamas[0]
    de_la_gama = tabla[tabla["gama"] == gama]
    izq, der = st.columns([3, 2])
    with izq, st.container(border=True):
        st.markdown(f"**Cada entidad en {nombre_a} y en {nombre_b}: {gama.lower()}**")
        _grafico_por_entidad(de_la_gama, nombre_a, nombre_b, unidad)
    with der, st.container(border=True):
        st.markdown("**Cuánto cambió cada entidad**")
        st.dataframe(
            de_la_gama[["entidad", "precio_a", "precio_b", "cambio_pct"]].rename(
                columns={
                    "entidad": "Entidad",
                    "precio_a": nombre_a,
                    "precio_b": nombre_b,
                    "cambio_pct": "Cambio",
                }
            ),
            hide_index=True,
            column_config={
                nombre_a: st.column_config.NumberColumn(nombre_a, format="localized"),
                nombre_b: st.column_config.NumberColumn(nombre_b, format="localized"),
                "Cambio": st.column_config.NumberColumn("Cambio", format="%+.1f %%"),
            },
            height=min(520, 36 * len(de_la_gama) + 40),
        )

    st.caption(
        "Precios de lista nominales: no descuentan la inflación. Cada precio es la mediana de "
        "lo que la entidad publicó en el trimestre. Una entidad sólo entra en la comparación "
        "si publicó en los dos períodos, para que un banco nuevo no mueva la mediana."
    )
