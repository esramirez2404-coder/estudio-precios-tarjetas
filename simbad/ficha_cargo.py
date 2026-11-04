# -*- coding: utf-8 -*-
"""Ficha del cargo que analiza cada grupo en el estudio de precios de tarjetas.

Es la sección que abre ``app_pages/tarjetas.py`` cuando se elige un tipo de cargo. Vive
aparte porque es un bloque autocontenido de la página: recibe las filas de las tarjetas
personales ya filtradas y dibuja KPIs, estadística descriptiva, distribución, precio por
entidad y atípicos. Los cálculos salen de :mod:`simbad.estudio_tarjetas`, que el notebook
del estudio usa también.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from simbad import ui
from simbad.estudio_tarjetas import (
    ORDEN_GAMAS,
    atipicos,
    estadistica_por_gama,
    explica,
    precio_por_entidad,
)

#: Escala de color de las gamas, la misma en todos los gráficos de la página.
ESCALA_GAMAS = alt.Scale(domain=ORDEN_GAMAS, range=[ui.COLORES_GAMA[g] for g in ORDEN_GAMAS])

#: Eje de las gamas, en su orden y con las etiquetas en horizontal.
EJE_GAMAS = alt.X("gama:N", sort=ORDEN_GAMAS, title=None, axis=alt.Axis(labelAngle=0))


def eje_precio(campo: str, titulo: str) -> alt.Y:
    """Eje de precios en escala logarítmica.

    Un solo banco caro aplastaba las cajas de las otras gamas. En escala logarítmica la
    misma distancia vertical es el mismo múltiplo, que es de lo que trata el estudio.
    """
    return alt.Y(
        f"{campo}:Q",
        title=f"{titulo}, escala logarítmica",
        scale=alt.Scale(type="log", nice=False),
        axis=alt.Axis(format=",.3~r", tickCount=6),
    )


def _con_unidad(valor: float, unidad: str) -> str:
    """Precio con su unidad: ``3.50 %`` o ``1,200.00 DOP``."""
    return f"{valor:,.2f} %" if unidad == "%" else f"{valor:,.2f} {unidad}"


def _cargo_en_una_periodicidad(filas: pd.DataFrame) -> pd.DataFrame:
    """Filas del cargo con una sola periodicidad, por defecto la más frecuente.

    Cobrar 1,500 al año no es el mismo precio que cobrar 1,500 al mes, y mezclarlos
    contaminaría la comparación entre períodos: «Cargo por Renovación» es anual en casi
    todas sus filas, pero en 2026 aparecen filas mensuales que en 2025 no existían.
    """
    periodicidades = filas["periodicidad"].value_counts().index.tolist()
    if len(periodicidades) == 1:
        return filas
    periodicidad = st.segmented_control(
        "Periodicidad del cargo",
        options=periodicidades,
        default=periodicidades[0],
        required=True,
        format_func=lambda p: str(p).capitalize(),
        key=f"tarj_periodicidad_{filas['concepto'].iloc[0]}",
        help="Este cargo se publica con más de una periodicidad; cada una se analiza por "
        "separado.",
    )
    return filas[filas["periodicidad"] == (periodicidad or periodicidades[0])]


def _cargo_en_una_unidad(filas: pd.DataFrame) -> pd.DataFrame:
    """Filas del cargo en una sola unidad, preguntando cuál cuando hay varias.

    Un mismo cargo puede publicarse como porcentaje o como monto fijo —«Comisión por
    Mora» tiene las dos formas— y promediar una con otra no mediría nada.
    """
    unidades = filas["unidadValor"].value_counts().index.tolist()
    if len(unidades) == 1:
        return filas
    unidad = st.segmented_control(
        "Unidad del cargo",
        options=unidades,
        default=unidades[0],
        key=f"tarj_unidad_{filas['concepto'].iloc[0]}",
        help="Este cargo se publica de más de una forma; cada una se analiza por separado.",
    )
    return filas[filas["unidadValor"] == (unidad or unidades[0])]


def _resumen_cargo(
    filas: pd.DataFrame, por_entidad: pd.DataFrame, descriptiva: pd.DataFrame, unidad: str
) -> None:
    """KPIs del cargo: alcance, nivel, dispersión y qué parte explica la gama.

    La dispersión se mide dentro de cada gama, como en el resto del estudio: comparar
    una clásica barata con una platino cara mediría la gama, no al banco.
    """
    con_log = filas.assign(logp=np.log(filas["valor"]))
    r2_gama = explica(con_log, ["gama"])
    r2_banco = explica(con_log, ["gama", "entidad"])
    mas_dispersa = descriptiva.loc[descriptiva["veces"].idxmax()]
    ui.kpi_row(
        [
            {
                "label": "Entidades que lo publican",
                "value": f"{por_entidad['entidad'].nunique()}",
                "help": "En alguna de las tres gamas personales, con la moneda y los "
                "tipos de entidad elegidos.",
            },
            {
                "label": "Precio mediano",
                "value": _con_unidad(por_entidad["valor"].median(), unidad),
                "help": "Mediana del precio de cada entidad en cada gama, con las tres "
                "gamas juntas. La tabla de abajo lo da gama por gama.",
            },
            {
                "label": "Mayor diferencia en una gama",
                "value": f"{mas_dispersa['veces']:.1f}×",
                "help": f"En la gama {mas_dispersa['gama'].lower()}, la entidad más cara "
                f"cobra {mas_dispersa['veces']:.1f} veces lo que la más barata.",
            },
            {
                "label": "Lo explica la gama",
                "value": f"{r2_gama * 100:.1f} %",
                "help": "Parte de la variación del precio (en logaritmo) que desaparece "
                "al conocer la gama de la tarjeta.",
            },
            {
                "label": "Añade saber el banco",
                "value": f"{(r2_banco - r2_gama) * 100:.1f} %",
                "help": "Lo que se explica de más al conocer, además de la gama, qué "
                "entidad cobra el cargo.",
            },
        ]
    )


def _descriptiva_cargo(descriptiva: pd.DataFrame) -> None:
    """Tabla de estadística descriptiva por gama."""
    nombres = {
        "gama": "Gama",
        "entidades": "Entidades",
        "media": "Media",
        "desviacion": "Desv. estándar",
        "minimo": "Mínimo",
        "q1": "Q1",
        "mediana": "Mediana",
        "q3": "Q3",
        "maximo": "Máximo",
        "cv": "CV",
        "veces": "Veces",
    }
    montos = ["Media", "Desv. estándar", "Mínimo", "Q1", "Mediana", "Q3", "Máximo"]
    st.dataframe(
        descriptiva.rename(columns=nombres),
        hide_index=True,
        column_config={
            **{c: st.column_config.NumberColumn(c, format="localized") for c in montos},
            "CV": st.column_config.NumberColumn("CV", format="%.1f %%"),
            "Veces": st.column_config.NumberColumn("Veces", format="%.1f ×"),
        },
    )


def _distribucion_cargo(por_entidad: pd.DataFrame, unidad: str) -> None:
    """Diagrama de caja por gama, con un punto por entidad encima."""
    eje_y = eje_precio("valor", f"Precio ({unidad})")
    base = alt.Chart(por_entidad).encode(x=EJE_GAMAS)
    caja = base.mark_boxplot(
        size=70, outliers=False, opacity=0.55, median={"color": "#FFFFFF", "strokeWidth": 2}
    ).encode(y=eje_y, color=alt.Color("gama:N", scale=ESCALA_GAMAS, legend=None))
    puntos = base.mark_circle(
        size=60, color="#E5E6E8", opacity=0.9, stroke="#0A142F", strokeWidth=1
    ).encode(
        y=eje_y,
        tooltip=[
            alt.Tooltip("entidad:N", title="Entidad"),
            alt.Tooltip("tipoEntidad:N", title="Tipo de entidad"),
            alt.Tooltip("gama:N", title="Gama"),
            alt.Tooltip("valor:Q", title="Precio", format=",.2f"),
        ],
    )
    st.altair_chart((caja + puntos).properties(height=380), width="stretch")


def _ranking_cargo(por_entidad: pd.DataFrame) -> None:
    """Precio de cada entidad en cada gama, de la más barata a la más cara."""
    tabla = por_entidad.pivot_table(
        index=["entidad", "tipoEntidad"], columns="gama", values="valor"
    ).reset_index()
    gamas = [g for g in ORDEN_GAMAS if g in tabla.columns]
    st.dataframe(
        tabla[["entidad", "tipoEntidad", *gamas]]
        .sort_values(gamas[0])
        .rename(columns={"entidad": "Entidad", "tipoEntidad": "Tipo de entidad"}),
        hide_index=True,
        column_config={g: st.column_config.NumberColumn(g, format="localized") for g in gamas},
        height=380,
    )


def ficha_cargo(frame: pd.DataFrame, cargo: str) -> pd.DataFrame:
    """Ficha del cargo que analiza el grupo. Devuelve las filas que se analizaron."""
    filas = frame[frame["concepto"] == cargo]
    if filas.empty:
        st.info(
            f"Ninguna entidad publica «{cargo}» en tarjetas personales con la moneda y "
            "los tipos de entidad elegidos. Prueba con la otra moneda o amplía el tipo "
            "de entidad.",
            icon=":material/info:",
        )
        return filas
    filas = _cargo_en_una_periodicidad(filas)
    filas = _cargo_en_una_unidad(filas)
    unidad = filas["unidadValor"].iloc[0]
    por_entidad = precio_por_entidad(filas)
    descriptiva = estadistica_por_gama(por_entidad)

    st.markdown(
        "Cada entidad cuenta **una vez por gama**: su precio es la mediana de lo que "
        "publicó en esa gama, aunque tenga varias marcas o productos."
    )
    _resumen_cargo(filas, por_entidad, descriptiva, unidad)
    st.markdown(
        "**Estadística descriptiva por gama** — el coeficiente de variación (CV) es la "
        "desviación estándar entre la media: cuánto se separan los precios de su "
        "promedio, sin depender de la escala."
    )
    _descriptiva_cargo(descriptiva)

    izq, der = st.columns([3, 2])
    with izq, st.container(border=True):
        st.markdown("**Distribución del precio por gama**")
        _distribucion_cargo(por_entidad, unidad)
    with der, st.container(border=True):
        st.markdown("**Precio de cada entidad**")
        _ranking_cargo(por_entidad)

    fuera = atipicos(por_entidad)
    if fuera.empty:
        st.caption(
            "Ningún precio cae fuera de las vallas de Tukey de su gama (Q1 − 1.5·RIC y "
            "Q3 + 1.5·RIC): no hay valores atípicos."
        )
    else:
        lista = "; ".join(
            f"{f.entidad} en {f.gama.lower()}: {_con_unidad(f.valor, unidad)}"
            for f in fuera.itertuples()
        )
        st.warning(
            f"**Valores atípicos** —fuera de Q1 − 1.5·RIC y Q3 + 1.5·RIC de su gama—: "
            f"{lista}.",
            icon=":material/scatter_plot:",
        )
    return filas


def grafico_escalera(largo: pd.DataFrame, titulo_y: str, formato: str = ",.2f") -> None:
    """Una línea por entidad a través de las gamas; la que está bajo el puntero se enciende.

    Con veinte entidades, una leyenda de colores no se puede leer. Todas las líneas van
    en un tono apagado, la del banco que se señala se resalta con su nombre al final, y
    los puntos llevan el color de su gama. ``largo`` trae ``entidad``, ``gama`` y
    ``precio``.
    """
    foco = alt.selection_point(
        fields=["entidad"], on="pointerover", nearest=True, empty=False, clear="pointerout"
    )
    ultima = [g for g in ORDEN_GAMAS if g in set(largo["gama"])][-1]
    base = alt.Chart(largo).encode(
        x=EJE_GAMAS,
        y=eje_precio("precio", titulo_y),
        detail="entidad:N",
    )
    lineas = base.mark_line().encode(
        color=alt.condition(foco, alt.value(ui.SERIE_RESALTADA), alt.value(ui.SERIE_APAGADA)),
        opacity=alt.condition(foco, alt.value(1.0), alt.value(0.6)),
        strokeWidth=alt.condition(foco, alt.value(3.5), alt.value(1.6)),
    )
    puntos = base.mark_circle(size=60).encode(
        color=alt.Color("gama:N", scale=ESCALA_GAMAS, legend=None),
        tooltip=[
            alt.Tooltip("entidad:N", title="Entidad"),
            alt.Tooltip("gama:N", title="Gama"),
            alt.Tooltip("precio:Q", title="Precio", format=formato),
        ],
    ).add_params(foco)
    nombre = (
        base.mark_text(align="left", dx=10, fontSize=13, fontWeight="bold", color=ui.SERIE_RESALTADA)
        .encode(text="entidad:N")
        .transform_filter(foco)
        .transform_filter(alt.datum.gama == ultima)
    )
    st.altair_chart(alt.layer(lineas, puntos, nombre).properties(height=420), width="stretch")
    st.caption(
        "Cuanto más empinada la línea, más multiplica esa entidad el precio. Pasa el "
        "puntero sobre un punto para seguir su línea."
    )


def _lineas_por_entidad(ancho: pd.DataFrame, unidad: str) -> None:
    """Una línea por entidad, de su gama más baja a la más alta."""
    largo = (
        ancho.drop(columns="Multiplica")
        .reset_index()
        .melt(id_vars="entidad", var_name="gama", value_name="precio")
    )
    grafico_escalera(largo, f"Precio ({unidad})")


def escalera_por_gama(filas: pd.DataFrame) -> None:
    """Precio del cargo en cada gama, dentro de cada entidad.

    Es la misma comparación que el estudio general hace con el reemplazo del plástico:
    fijada la entidad, ¿cuánto sube el precio al pasar de clásica a platino? Sólo
    entran las entidades que publican el cargo en todas las gamas presentes.
    """
    unidad = filas["unidadValor"].iloc[0]
    ancho = precio_por_entidad(filas).pivot_table(index="entidad", columns="gama", values="valor")
    gamas = [g for g in ORDEN_GAMAS if g in ancho.columns]
    ancho = ancho[gamas].dropna()
    if len(gamas) < 2 or ancho.empty:
        st.info(
            "Ninguna entidad publica este cargo en más de una gama: no hay forma de ver "
            "cómo cambia su precio con la gama.",
            icon=":material/info:",
        )
        return
    ancho["Multiplica"] = ancho.max(axis=1) / ancho.min(axis=1)
    ancho = ancho.sort_values("Multiplica", ascending=False)

    st.markdown(
        f"Las **{len(ancho)} entidades** que publican el cargo en "
        f"{'las tres gamas' if len(gamas) == 3 else 'todas las gamas presentes'}. Cada "
        "línea es una entidad: si el precio dependiera sólo del servicio, serían planas."
    )
    izq, der = st.columns([3, 2])
    with izq, st.container(border=True):
        st.markdown("**Precio del cargo por entidad y gama**")
        _lineas_por_entidad(ancho, unidad)
    with der, st.container(border=True):
        st.markdown("**Cuánto multiplica cada entidad**")
        st.dataframe(
            ancho.reset_index().rename(columns={"entidad": "Entidad"}),
            hide_index=True,
            column_config={
                **{g: st.column_config.NumberColumn(g, format="localized") for g in gamas},
                "Multiplica": ui.columna_veces("Multiplica", ancho["Multiplica"].max()),
            },
            height=420,
        )

    planas = ancho[ancho["Multiplica"] <= 1.001]
    st.caption(
        f"La entidad típica cobra **{ancho['Multiplica'].median():.1f} veces más** en su "
        f"gama más cara que en la más barata; la que más multiplica, "
        f"{ancho.index[0]}, llega a {ancho['Multiplica'].iloc[0]:.1f} veces."
    )
    if not planas.empty:
        st.success(
            f"**{', '.join(planas.index)}** {'cobra' if len(planas) == 1 else 'cobran'} "
            "exactamente lo mismo en todas las gamas.",
            icon=":material/check_circle:",
        )


def gama_o_banco(filas: pd.DataFrame) -> None:
    """Qué parte de la variación del precio del cargo explica la gama y cuál el banco."""
    con_log = filas.assign(logp=np.log(filas["valor"]))
    r2_gama = explica(con_log, ["gama"])
    r2_ambos = explica(con_log, ["gama", "entidad"])
    reparto = pd.DataFrame(
        {
            "paso": ["Saber la gama", "…y además qué banco lo cobra", "Sin explicar"],
            "porcentaje": [r2_gama * 100, (r2_ambos - r2_gama) * 100, (1 - r2_ambos) * 100],
        }
    )

    st.markdown(
        "Se reparte la variación del precio del cargo entre los dos factores que podrían "
        "explicarla. Cada porcentaje es la parte de la varianza que desaparece al "
        "sustituir cada precio por la media de su grupo."
    )
    izq, der = st.columns([2, 3])
    with izq:
        st.dataframe(
            reparto.rename(columns={"paso": "Qué sabes del precio", "porcentaje": "Explica"}),
            hide_index=True,
            column_config={"Explica": st.column_config.NumberColumn("Explica", format="%.1f %%")},
        )
    with der, st.container(border=True):
        barras = (
            alt.Chart(reparto)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("porcentaje:Q", title="Porcentaje de la variación del precio"),
                y=alt.Y("paso:N", sort=None, title=None),
                color=alt.Color("paso:N", legend=None),
                tooltip=[
                    alt.Tooltip("paso:N", title="Paso"),
                    alt.Tooltip("porcentaje:Q", title="Explica", format=".1f"),
                ],
            )
            .properties(height=180)
        )
        st.altair_chart(barras, width="stretch")

    banco = r2_ambos - r2_gama
    st.info(
        f"**Cómo se lee:** conocer la gama explica **{r2_gama * 100:.1f} %** de la "
        f"variación del precio, y saber además qué banco lo cobra añade "
        f"**{banco * 100:.1f} %**. "
        + (
            "La categoría de la tarjeta pesa más que la identidad del banco."
            if r2_gama > banco
            else "La identidad del banco pesa más que la categoría de la tarjeta."
        ),
        icon=":material/lightbulb:",
    )
    st.caption(
        "Cálculo sobre el logaritmo del precio, para que las diferencias sean relativas. "
        "«Sin explicar» es lo que varía entre tarjetas del mismo banco y la misma gama "
        "—distintas marcas o productos—. Es una descomposición descriptiva, no un "
        "modelo causal: mide asociación, no efecto."
    )
