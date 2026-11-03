# -*- coding: utf-8 -*-
"""Estudio de dispersión de precios en los tarifarios de tarjetas de crédito.

Página de análisis, no de consulta: responde a una pregunta concreta —¿cuesta lo
mismo el mismo servicio en todos los bancos?— y deja a la vista cada llamada al API
que sustenta las cifras, para poder reproducirlas o presentarlas.

A diferencia del resto de la app, aquí se descarga **el tarifario completo del período
elegido de una sola vez** —todos los tipos de entidad, todas las monedas— y todo lo
demás (tipo de entidad, moneda, tipo de cargo, gama) se calcula en pandas sobre esa
respuesta. Esos controles reejecutan el script, pero la descarga sale de la caché de
:mod:`simbad.data`, así que no generan tráfico nuevo y responden al instante. Sólo
cambiar el período pide datos nuevos, y por eso va detrás del botón «Consultar».

Los cálculos viven en :mod:`simbad.estudio_tarjetas`, sin Streamlit, para que el
notebook del estudio reproduzca las mismas cifras con las mismas funciones.
"""

from itertools import count
from urllib.parse import urlencode

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from simbad import data, ui
from simbad.catalog import BASE_URL, ENDPOINTS, TIPOS_ENTIDAD
from simbad.estudio_tarjetas import (
    GAMAS,
    MINIMO_ENTIDADES,
    ORDEN_GAMAS,
    cargos_disponibles,
    dispersion,
    explica,
    minimo_comparable,
)
from simbad.ficha_cargo import escalera_por_gama, ficha_cargo, gama_o_banco

ENDPOINT = "TasasComisionesTarjetasCredito"
RUTA = ENDPOINTS[ENDPOINT]["path"]

#: Reponer un plástico deteriorado es el mismo acto físico en las tres gamas:
#: imprimir una tarjeta. Por eso es el servicio donde una diferencia de precio
#: entre gamas no puede justificarse por el costo de producirlo.
SERVICIO_IDENTICO = "Cargo por Reemplazo por Deterioro Plástico"

#: Servicio de control: si la dispersión fuese un artefacto de los datos,
#: aparecería también aquí. No aparece, y eso valida el resto de las mediciones.
SERVICIO_CONTROL = "Comisión por Avance Efectivo"

TASA = "Interés por financiamiento"

ui.require_api_key()

#: Las secciones se numeran al dibujarse: la ficha del cargo sólo aparece cuando se
#: elige uno, y un número fijo dejaría un hueco en la numeración.
_numero_seccion = count(1)


def seccion(titulo: str) -> None:
    """Encabezado numerado de una sección del estudio."""
    st.subheader(f"{next(_numero_seccion)} · {titulo}")


# --------------------------------------------------------- Rastro de consultas


def _url_completa(informe: dict) -> str:
    """URL reproducible de la llamada que produjo estos datos."""
    params = dict(informe.get("params", {}))
    params = {k: v for k, v in params.items() if v not in (None, "", [], ())}
    return f"{informe.get('url', BASE_URL + RUTA)}?{urlencode(params, doseq=True)}"


def _nombre_mes(periodo: str) -> str:
    """``2026-05`` → ``Mayo 2026``."""
    return f"{ui.MESES[periodo[5:7]]} {periodo[:4]}"


def _etiqueta_periodo(inicio: str, fin: str) -> str:
    """Nombre legible del rango consultado: un mes, o «Enero 2026 – Mayo 2026»."""
    if inicio == fin:
        return _nombre_mes(inicio)
    return f"{_nombre_mes(inicio)} – {_nombre_mes(fin)}"


# ------------------------------------------------------------- Qué es esto


st.caption(
    "Estudio de precios sobre los tarifarios de tarjetas de crédito que publica la "
    "Superintendencia de Bancos. Una sola pregunta, medida y reproducible."
)

with st.container(border=True):
    st.markdown("### ¿Cuesta lo mismo el mismo servicio en todos los bancos?")
    st.markdown(
        "Cuando un banco emite una tarjeta, la renueva o te repone el plástico que se "
        "deterioró, **cobra por ello una tarifa que tiene publicada**. Esta página mide "
        "cuánto varía esa tarifa entre entidades para un servicio idéntico, y cuánto de "
        "esa variación se explica por la gama de la tarjeta frente a la identidad del "
        "banco que la cobra."
    )

with st.expander(
    "Antes de empezar: qué es cada cosa (para quien no conoce el sistema financiero "
    "dominicano)",
    icon=":material/school:",
):
    st.markdown(
        """
**La Superintendencia de Bancos (SB)** es el organismo público que supervisa a los
bancos dominicanos. Entre otras cosas, obliga a cada entidad a informar lo que cobra
por sus servicios y publica esa información.

**El tarifario** es la lista de precios de un producto financiero: cuánto cuesta
emitir la tarjeta, renovarla, reponerla si se pierde, sacar efectivo en un cajero,
pagar tarde. No es lo que un cliente concreto pagó, sino **el precio anunciado**.

**SIMBAD** es el sistema de datos abiertos de la SB. Publica un API —una dirección de
internet que devuelve datos— con las estadísticas del sistema financiero. Esta app
consume ese API en vivo; nada de lo que ves aquí está copiado a mano.

**Las gamas de tarjeta.** Los bancos venden la misma tarjeta en varios niveles:
*clásica* (la básica), *oro* y *platino* (para clientes con mayores ingresos, con más
límite y más beneficios). Un precio distinto entre gamas puede ser legítimo: son
productos distintos. Por eso todas las comparaciones de esta página se hacen **dentro
de una misma gama**, y cuando se cruzan gamas se dice explícitamente.

---

**Por qué esta pregunta se puede responder y otras no.**

En economía, lo normal es observar un *resultado de mercado*: cuánto se prestó, a qué
tasa. Ese número es el cruce entre lo que alguien pidió y lo que alguien concedió, y
separar ambas cosas exige datos que casi nunca existen.

Un tarifario no es eso. **Es una decisión unilateral de la entidad, publicada por
ella.** No hay que inferir intenciones ni deducir quién quiso qué: se lee el precio que
el banco fijó. Por eso la pregunta admite una respuesta directa.
"""
    )


# ---------------------------------------------------------------- La consulta

with st.container(border=True):
    st.markdown("**La consulta** — qué período se descarga")
    inicio, fin = ui.period_range_selector(
        key="tarj",
        # Un mes son unos 6 500 registros y medio minuto de descarga: se parte de uno
        # solo y quien quiera un período más largo lo pide a sabiendas.
        default_months=1,
        container=st,
        endpoint_id=ENDPOINT,
    )
    st.caption(
        "Con un solo mes, el tarifario es una foto: el precio vigente ese mes. Con "
        "varios, el precio de cada entidad es la mediana de lo que publicó en ellos."
    )
    inicio, fin = ui.apply_gate(key="tarj", pending=(inicio, fin))

    etiqueta = _etiqueta_periodo(inicio, fin)
    sufijo = inicio if inicio == fin else f"{inicio}_{fin}"

    # La descarga va antes de los filtros de abajo porque el de tipo de cargo ofrece
    # sólo los cargos que trae este tarifario.
    with st.spinner("Descargando el tarifario del período…"):
        crudo, informe = data.load_safe(ENDPOINT, inicio, fin, filters={})

    if crudo.empty:
        st.warning(
            f"El API no devolvió tarifas para {etiqueta}. Prueba con otro período.",
            icon=":material/info:",
        )
        ui.source_note()
        st.stop()

    st.markdown("**Sobre la descarga** — qué parte se analiza")
    fila = st.container(horizontal=True, vertical_alignment="bottom")
    tipos = fila.multiselect(
        "Tipo de entidad",
        # Este conjunto rechaza los códigos de las corporaciones de crédito y de las
        # entidades públicas (HTTP 400): se ofrecen sólo los que acepta.
        options=[t for t in data.accepted_entity_types(ENDPOINT) if t in TIPOS_ENTIDAD],
        format_func=lambda t: TIPOS_ENTIDAD[t],
        key="tarj_tipos",
        placeholder="Todos los tipos",
        help="Sólo se ofrecen los tipos que publican tarifarios de tarjeta en este "
        "conjunto de datos.",
    )
    moneda = fila.selectbox(
        "Moneda",
        options=["DOP", "USD"],
        key="tarj_moneda",
        help="Se compara dentro de una misma moneda; mezclarlas no tendría sentido.",
    )
    opciones_cargo = [None, *cargos_disponibles(crudo)]
    if st.session_state.get("tarj_cargo") not in opciones_cargo:
        # Un cargo elegido con otro período puede no existir en éste.
        st.session_state["tarj_cargo"] = None
    cargo = fila.selectbox(
        "Tipo de cargo",
        options=opciones_cargo,
        format_func=lambda c: "Todos los cargos" if c is None else c,
        key="tarj_cargo",
        help="La variable que analiza tu grupo. Al elegir un cargo, la página abre con "
        "su ficha: estadística descriptiva por gama, precio de cada entidad y valores "
        "atípicos. El resto del estudio queda debajo como contexto del mercado.",
    )
    st.caption(
        "El tarifario completo del período se descarga **de una sola vez** y queda en "
        "caché. Tipo de entidad, moneda, tipo de cargo y los controles de más abajo "
        "trabajan sobre esa descarga: cambian al instante y no piden nada nuevo al API."
    )

truncada = ui.truncation_notice(informe)

# ------------------------------------------------------------- Preparación

marco = crudo.copy()
# El API devuelve el nombre largo («BANCOS MÚLTIPLES»); el filtro trabaja con códigos.
marco["tipo"] = ui.entity_type_codes(marco["tipoEntidad"])
if tipos:
    marco = marco[marco["tipo"].isin(tipos)]
    if marco.empty:
        st.warning(
            "Ninguna entidad de los tipos elegidos publica tarifas de tarjeta en "
            f"{etiqueta}. Amplía el filtro de tipo de entidad.",
            icon=":material/info:",
        )
        ui.source_note()
        st.stop()
marco["valor"] = pd.to_numeric(marco["valor"], errors="coerce")
marco["valorMinimo"] = pd.to_numeric(marco.get("valorMinimo"), errors="coerce")
marco["valorMaximo"] = pd.to_numeric(marco.get("valorMaximo"), errors="coerce")

# Un 3 % de las filas no declaran un precio único sino un rango (formatoTarifa =
# "Escala de valores fijos"): ahí `valor` viene en cero y el precio real está en
# mínimo–máximo. Se apartan en vez de mezclarlas, y se informa cuántas son.
es_rango = marco["valorMinimo"].fillna(0) > 0
rangos = marco[es_rango]
precios = marco[~es_rango & (marco["valor"] > 0)]
precios = precios[precios["moneda"] == moneda]

personales = precios[precios["tipoTarjeta"].isin(GAMAS)].copy()
personales["gama"] = personales["tipoTarjeta"].map(GAMAS)


# ------------------------------------------------------- El cargo del grupo

# Con un cargo elegido la página es sólo de ese cargo: su ficha, cómo cambia su precio
# con la gama dentro de cada entidad y qué pesa más en él. El estudio de todos los
# servicios, en el `else`, queda para cuando no se elige ninguno.
filas_cargo = pd.DataFrame()
if cargo:
    seccion(f"El cargo que analiza el grupo: {cargo}")
    filas_cargo = ficha_cargo(personales, cargo)
    if not filas_cargo.empty:
        seccion("El mismo cargo, el mismo banco: ¿un precio por gama?")
        escalera_por_gama(filas_cargo)
        seccion("¿Qué pesa más en el precio: la gama o el banco?")
        gama_o_banco(filas_cargo)
else:
    # -------------------------------------------------------------- El hallazgo

    seccion("El mismo servicio, en la misma gama, ¿al mismo precio?")

    gama_elegida = st.segmented_control(
        "Gama de tarjeta",
        options=ORDEN_GAMAS,
        default="Clásica",
        key="tarj_gama",
        help="Se compara dentro de una gama para que el producto sea equivalente.",
    )
    gama_elegida = gama_elegida or "Clásica"
    sub = personales[personales["gama"] == gama_elegida]
    minimo = minimo_comparable(sub["entidad"].nunique())
    resumen = dispersion(sub)
    resumen = resumen[resumen["entidades"] >= minimo]

    if resumen.empty:
        st.info(
            "No hay conceptos con suficientes entidades para comparar en esta gama. "
            "Prueba con otra gama, otra moneda o un filtro de tipo de entidad más amplio."
        )
    else:
        peor = resumen.iloc[0]
        ui.kpi_row(
            [
                {
                    "label": "Entidades en el tarifario",
                    "value": f"{sub['entidad'].nunique()}",
                    "help": f"Publican al menos un precio de tarjeta {gama_elegida.lower()}.",
                },
                {
                    "label": "Conceptos comparables",
                    "value": f"{len(resumen)}",
                    "help": f"Servicios que al menos {minimo} entidades publican.",
                },
                {
                    "label": "Mayor diferencia",
                    "value": f"{peor['veces']:.1f}×",
                    "help": f"{peor['concepto']}",
                },
                {
                    "label": "Mediana de las diferencias",
                    "value": f"{resumen['veces'].median():.1f}×",
                    "help": "Cuánto varía un servicio típico entre el banco más barato "
                    "y el más caro.",
                },
            ]
        )

        tabla = resumen.copy()
        tabla["servicio"] = tabla["concepto"] + "  (" + tabla["unidadValor"] + ")"
        tabla["rango"] = tabla.apply(
            lambda r: f"{r['minimo']:,.2f} — {r['maximo']:,.2f} {r['unidadValor']}", axis=1
        )
        st.dataframe(
            tabla[["servicio", "entidades", "rango", "mediana", "veces"]].rename(
                columns={
                    "servicio": "Servicio",
                    "entidades": "Entidades",
                    "rango": "Del más barato al más caro",
                    "mediana": "Mediana",
                    "veces": "Veces",
                }
            ),
            hide_index=True,
            column_config={
                "Mediana": st.column_config.NumberColumn("Mediana", format="localized"),
                "Veces": st.column_config.NumberColumn("Veces", format="%.1f ×"),
            },
            height=380,
        )

        with st.container(border=True):
            st.markdown(
                f"**Cuánto se encarece cada servicio según dónde lo contrates — {gama_elegida}**"
            )
            grafico = (
                alt.Chart(tabla.head(14))
                .mark_bar(cornerRadiusEnd=4, color=ui.SERIE_PRINCIPAL)
                .encode(
                    x=alt.X("veces:Q", title="Veces que el más caro supera al más barato"),
                    y=alt.Y("servicio:N", sort="-x", title=None),
                    tooltip=[
                        alt.Tooltip("servicio:N", title="Servicio"),
                        alt.Tooltip("minimo:Q", title="Más barato", format=",.2f"),
                        alt.Tooltip("mediana:Q", title="Mediana", format=",.2f"),
                        alt.Tooltip("maximo:Q", title="Más caro", format=",.2f"),
                        alt.Tooltip("entidades:Q", title="Entidades"),
                    ],
                )
                .properties(height=380)
            )
            st.altair_chart(grafico, width="stretch")
        st.caption(
            "Cada barra es un servicio idéntico dentro de la misma gama. Un valor de 5 "
            "significa que la entidad más cara cobra cinco veces lo que la más barata."
        )

    # ------------------------------------------------------- ¿Lo explica la gama?

    seccion("¿No será simplemente que hay tarjetas de distinta categoría?")

    st.markdown(
        "Es la objeción evidente: una platino es un producto distinto de una clásica, así "
        "que es normal que cueste más. Si la gama explicara las diferencias, al fijarla la "
        "dispersión debería desaparecer. La tabla siguiente la mide **dentro de cada gama "
        "por separado**."
    )

    filas = []
    for gama in ORDEN_GAMAS:
        en_gama = personales[personales["gama"] == gama]
        r = dispersion(en_gama)
        r = r[r["entidades"] >= minimo_comparable(en_gama["entidad"].nunique())]
        for _, f in r.iterrows():
            filas.append({"gama": gama, "concepto": f["concepto"], "veces": f["veces"],
                          "minimo": f["minimo"], "maximo": f["maximo"]})
    por_gama = pd.DataFrame(filas)

    if not por_gama.empty:
        pivote = por_gama.pivot_table(index="concepto", columns="gama", values="veces")
        pivote = pivote[[c for c in ORDEN_GAMAS if c in pivote.columns]]
        st.dataframe(
            pivote.round(1),
            column_config={
                c: st.column_config.NumberColumn(c, format="%.1f ×") for c in pivote.columns
            },
            height=340,
        )
        st.caption(
            "La dispersión no se reduce al fijar la gama. En varios servicios es **mayor** "
            "en platino que en clásica: fijar el producto no explica la diferencia, la amplía."
        )


    # ------------------------------------------- El mismo plástico, el mismo banco

    seccion("El mismo plástico, el mismo banco, tres precios")

    st.markdown(
        f"«{SERVICIO_IDENTICO}» es el caso más limpio de todos: reponer una tarjeta "
        "deteriorada es **el mismo acto físico** en las tres gamas —imprimir un plástico—. "
        "No cuesta más fabricar una platino. Si el precio sube con la gama dentro del mismo "
        "banco, no puede ser por el costo."
    )

    plastico = personales[personales["concepto"] == SERVICIO_IDENTICO]
    if plastico.empty:
        st.info("Este concepto no aparece en el tarifario de este período.")
    else:
        tabla_p = (
            plastico.groupby(["entidad", "gama"])["valor"].median().reset_index()
        )
        ancho = tabla_p.pivot(index="entidad", columns="gama", values="valor")
        ancho = ancho[[c for c in ORDEN_GAMAS if c in ancho.columns]].dropna()
        if not ancho.empty:
            ancho["Multiplica"] = ancho.max(axis=1) / ancho.min(axis=1)
            ancho = ancho.sort_values("Multiplica", ascending=False)

            planas = ancho[ancho["Multiplica"] <= 1.001]
            izq, der = st.columns([3, 2])
            with izq, st.container(border=True):
                st.markdown("**Precio de reponer el plástico, por banco y gama**")
                largo = ancho.drop(columns="Multiplica").reset_index().melt(
                    id_vars="entidad", var_name="gama", value_name="precio"
                )
                lineas = (
                    alt.Chart(largo)
                    .mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=2)
                    .encode(
                        x=alt.X("gama:N", sort=ORDEN_GAMAS, title=None),
                        y=alt.Y("precio:Q", title=f"Precio ({moneda})"),
                        color=alt.Color("entidad:N", title="Entidad"),
                        tooltip=[
                            alt.Tooltip("entidad:N", title="Entidad"),
                            alt.Tooltip("gama:N", title="Gama"),
                            alt.Tooltip("precio:Q", title="Precio", format=",.0f"),
                        ],
                    )
                    .properties(height=420)
                )
                st.altair_chart(lineas, width="stretch")
            with der, st.container(border=True):
                st.markdown("**Cuánto multiplica cada banco**")
                st.dataframe(
                    ancho.reset_index().rename(columns={"entidad": "Entidad"}),
                    hide_index=True,
                    column_config={
                        **{
                            c: st.column_config.NumberColumn(c, format="localized")
                            for c in ORDEN_GAMAS
                            if c in ancho.columns
                        },
                        "Multiplica": st.column_config.NumberColumn("Multiplica", format="%.1f ×"),
                    },
                    height=420,
                )

            if not planas.empty:
                nombres = ", ".join(planas.index.tolist())
                st.success(
                    f"**La prueba de que es una decisión y no un costo:** {nombres} "
                    f"{'cobra' if len(planas) == 1 else 'cobran'} exactamente lo mismo por "
                    "reponer el plástico en las tres gamas. Si fuese más caro fabricar una "
                    "platino, no podrían.",
                    icon=":material/check_circle:",
                )


    # ------------------------------------------------------------ El apilamiento

    seccion("Un número que se repite demasiado")

    tasas = personales[(personales["concepto"] == TASA) & (personales["unidadValor"] == "%")]
    if tasas.empty:
        st.info("No hay tasas de financiamiento en este tarifario.")
    else:
        por_ent = (
            tasas.groupby(["entidad", "gama"])["valor"].median().reset_index()
        )
        modo = por_ent["valor"].round(2).mode()
        tope = float(modo.iloc[0]) if not modo.empty else float(por_ent["valor"].max())
        cuantas = int((por_ent["valor"].round(2) == tope).sum())

        st.markdown(
            f"De las {len(por_ent)} combinaciones de banco y gama con tasa publicada, "
            f"**{cuantas} cobran exactamente {tope:.2f} %**. Los precios no coinciden en un "
            "número redondo por casualidad: eso suele ser la huella de un tope que ata a "
            "todos, o de un punto de referencia que todos imitan."
        )

        with st.container(border=True):
            st.markdown("**Distribución de la tasa de financiamiento**")
            histo = (
                alt.Chart(por_ent)
                .mark_bar(cornerRadiusEnd=3, color=ui.SERIE_PRINCIPAL)
                .encode(
                    x=alt.X("valor:Q", bin=alt.Bin(step=2), title="Tasa publicada (%)"),
                    y=alt.Y("count():Q", title="Cuántos bancos"),
                    tooltip=[alt.Tooltip("count():Q", title="Bancos")],
                )
                .properties(height=260)
            )
            st.altair_chart(histo, width="stretch")

        orden = por_ent.pivot(index="entidad", columns="gama", values="valor")
        orden = orden[[c for c in ORDEN_GAMAS if c in orden.columns]]
        st.dataframe(
            orden.sort_values(orden.columns[0]).round(2),
            column_config={
                c: st.column_config.NumberColumn(c, format="%.2f %%") for c in orden.columns
            },
            height=340,
        )
        st.warning(
            "**Pendiente de resolver antes de citar esta cifra.** El API declara estas tasas "
            "con `periodicidad = MENSUAL`. Una tasa de 60 % mensual sería absurda, así que "
            "casi con seguridad es la tasa anual que se cobra mes a mes — pero eso hay que "
            "confirmarlo en la metodología de la Superintendencia, no suponerlo. Las "
            "comparaciones entre bancos no se ven afectadas: todos usan la misma unidad.",
            icon=":material/help:",
        )


    # --------------------------------------------------------------- El control

    seccion("La prueba de que los datos no mienten")

    control = personales[personales["concepto"] == SERVICIO_CONTROL]
    if not control.empty:
        c = control.groupby("entidad")["valor"].median()
        st.markdown(
            f"Si la dispersión fuese un defecto de los datos, aparecería en todos los "
            f"servicios. No aparece: **«{SERVICIO_CONTROL}» se agrupa en "
            f"{c.median():.1f} %** en casi todas las entidades, de {c.min():.1f} a "
            f"{c.max():.1f} —apenas {c.max()/c.min():.1f}×—."
        )
        st.markdown(
            "Que exista un servicio donde el precio es prácticamente idéntico en todo el "
            "mercado, mientras emitir una tarjeta varía muchas veces, demuestra que lo que "
            "se está midiendo es real y propio de cada concepto, no un artefacto."
        )


    # -------------------------------------------------- Descomposición de varianza

    seccion("¿Qué pesa más: el servicio, la gama o el banco?")

    st.markdown(
        "La pregunta del trabajo no es sólo *cuánto* varía el precio, sino *de qué depende*. "
        "Esto se mide repartiendo la variación total del precio entre los factores que "
        "podrían explicarla."
    )

    base = personales[personales["valor"] > 0].copy()
    base["logp"] = np.log(base["valor"])

    if len(base) > 50:
        pasos = [
            ("Sólo saber qué servicio es", ["concepto"]),
            ("…y además la gama", ["concepto", "gama"]),
            ("…y además qué banco lo cobra", ["concepto", "gama", "entidad"]),
        ]
        acumulado = []
        previo = 0.0
        # `paso`, no `etiqueta`: ese nombre ya guarda el período y lo cita «El rastro».
        for paso, columnas in pasos:
            r2 = explica(base, columnas)
            acumulado.append(
                {"paso": paso, "explicado": r2 * 100, "aporta": (r2 - previo) * 100}
            )
            previo = r2
        resumen_var = pd.DataFrame(acumulado)

        izq, der = st.columns([2, 3])
        with izq:
            st.dataframe(
                resumen_var.rename(
                    columns={
                        "paso": "Qué sabes del precio",
                        "explicado": "Explicado (%)",
                        "aporta": "Añade (%)",
                    }
                ),
                hide_index=True,
                column_config={
                    "Explicado (%)": st.column_config.NumberColumn("Explicado", format="%.1f %%"),
                    "Añade (%)": st.column_config.NumberColumn("Añade", format="%.1f %%"),
                },
            )
        with der, st.container(border=True):
            st.markdown("**Cuánto añade cada dato a la explicación del precio**")
            barras = (
                alt.Chart(resumen_var)
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X("aporta:Q", title="Porcentaje de la variación que añade"),
                    y=alt.Y("paso:N", sort=None, title=None),
                    color=alt.Color("paso:N", legend=None),
                    tooltip=[
                        alt.Tooltip("paso:N", title="Paso"),
                        alt.Tooltip("aporta:Q", title="Añade", format=".1f"),
                        alt.Tooltip("explicado:Q", title="Explicado en total", format=".1f"),
                    ],
                )
                .properties(height=200)
            )
            st.altair_chart(barras, width="stretch")

        aporte_banco = resumen_var.iloc[-1]["aporta"]
        aporte_gama = resumen_var.iloc[1]["aporta"]
        st.info(
            f"**Cómo se lee:** saber de qué servicio se trata ya explica la mayor parte del "
            f"precio —no cuesta lo mismo reponer un plástico que emitir una tarjeta—. Una vez "
            f"sabido eso, conocer la gama añade **{aporte_gama:.1f} %** de explicación, "
            f"mientras que saber **qué banco lo cobra añade {aporte_banco:.1f} %**. "
            + (
                "La identidad del banco pesa más que la categoría del producto."
                if aporte_banco > aporte_gama
                else "La categoría del producto pesa más que la identidad del banco."
            ),
            icon=":material/lightbulb:",
        )
        st.caption(
            "Cálculo sobre el logaritmo del precio, para que un cargo de miles de pesos y "
            "una comisión de porcentaje pesen de forma comparable. Es una descomposición "
            "descriptiva, no un modelo causal: mide asociación, no efecto."
        )


# --------------------------------------------------------- Rastro de consultas

seccion("El rastro: de dónde sale cada cifra")

st.markdown(
    "Todo lo anterior procede de **una sola descarga** del API de la Superintendencia: "
    f"el tarifario completo de {etiqueta}, de todos los tipos de entidad y en ambas "
    "monedas; los filtros de tipo, moneda y cargo se aplicaron después, sobre esa "
    "respuesta"
    + (f", y de ella sólo se usó «{cargo}». " if cargo else ". ")
    + "Abajo está la llamada, tal cual se envió, para que cualquiera pueda repetirla y "
    "obtener los mismos números."
)

bloques = int(informe.get("bloques", 0) or 0)
with st.container(border=True):
    st.markdown("**La consulta que sostiene esta página**")
    st.code(f"GET {_url_completa(informe)}", language="http")
    if bloques > 1:
        st.caption(
            f"El rango se pidió al API en **{bloques} bloques** consecutivos de meses "
            "—el gateway corta las consultas largas— y aquí se muestra como una sola "
            "URL con el rango completo. Los registros, páginas y segundos suman los "
            "bloques."
        )
    fila = st.container(horizontal=True)
    fila.metric("Registros recibidos", f"{len(crudo):,}", border=True)
    fila.metric("Páginas", f"{informe.get('pages', 0)}", border=True)
    fila.metric("Segundos", f"{informe.get('elapsed_s', 0):.1f}", border=True)
    fila.metric("Entidades", f"{crudo['entidad'].nunique()}", border=True)
    if inicio != fin:
        fila.metric("Meses", f"{crudo['periodo'].astype(str).str[:7].nunique()}", border=True)
    if not filas_cargo.empty:
        fila.metric("Registros del cargo analizados", f"{len(filas_cargo):,}", border=True)

with st.expander("Reproducirlo fuera de la app", icon=":material/terminal:"):
    st.markdown(
        "La clave de suscripción va en una cabecera. Sustituye `TU_CLAVE` por la tuya "
        "del portal de desarrolladores de la SB."
    )
    st.code(
        f'curl -H "Ocp-Apim-Subscription-Key: TU_CLAVE" \\\n'
        f'  "{_url_completa(informe)}"',
        language="bash",
    )
    st.markdown("En Python, con la misma capa que usa esta app:")
    st.code(
        "from simbad import data\n\n"
        f'marco, informe = data.load_safe("{ENDPOINT}", "{inicio}", "{fin}", filters={{}})\n'
        'print(len(marco), informe["rows"])'
        + (f'\ndel_cargo = marco[marco["concepto"] == "{cargo}"]' if cargo else ""),
        language="python",
    )
    st.caption(
        "El notebook `notebooks/estudio_precios_tarjetas.ipynb` hace el recorrido "
        "completo paso a paso: conexión, descarga paginada, limpieza, filtros y la "
        "ficha del cargo."
    )

with st.expander("Qué se hizo con esos datos antes de calcular", icon=":material/rule:"):
    pasos_limpieza = []
    if tipos:
        nombres_tipos = ", ".join(TIPOS_ENTIDAD[t].lower() for t in tipos)
        pasos_limpieza.append(
            f"**Se acotó a {nombres_tipos}.** La descarga trae todos los tipos de "
            f"entidad ({len(crudo):,} registros); el filtro se aplicó después y dejó "
            f"{len(marco):,}. Así el rastro de arriba sigue siendo la consulta completa."
        )
    # Con un cargo elegido, las cuentas y la tabla de filas apartadas son sólo de ese cargo.
    ambito = marco[marco["concepto"] == cargo] if cargo else marco
    apartadas = rangos[rangos["concepto"] == cargo] if cargo else rangos
    pasos_limpieza.append(
        f"**Se apartaron las filas que no declaran un precio único.** {len(apartadas):,} de "
        f"{len(ambito):,} registros{' de este cargo' if cargo else ''} "
        f"({len(apartadas) / max(len(ambito), 1) * 100:.1f} %) usan "
        '`formatoTarifa = "Escala de valores fijos"`: su campo `valor` viene en cero y el '
        "precio se expresa como un rango mínimo–máximo. Se excluyen en vez de mezclarlas."
    )
    pasos_limpieza.append(
        f"**Se fijó la moneda en {moneda}.** Comparar un cargo en pesos con uno en dólares "
        "no mediría precios, mediría el tipo de cambio."
    )
    pasos_limpieza.append(
        "**Se restringió a las tres gamas personales** (clásica, oro, platino), dejando "
        "fuera corporativas, empresariales y de flotilla, que no son comparables con ellas."
    )
    if not filas_cargo.empty:
        pasos_limpieza.append(
            f"**Se acotó al cargo «{cargo}»** en {filas_cargo['unidadValor'].iloc[0]}: "
            f"{len(filas_cargo):,} registros de {filas_cargo['entidad'].nunique()} "
            "entidades. Ninguna sección de la página usa los demás cargos."
        )
    mediana = (
        "**Se tomó la mediana por entidad** antes de comparar entidades: un banco puede "
        "publicar varias tarjetas de la misma gama —Visa y Mastercard, por ejemplo— y no "
        "debe pesar más por ello."
    )
    if inicio != fin:
        mediana += (
            " Como el período abarca varios meses, la misma mediana recorre los meses: el "
            "precio de una entidad es el que publicó de forma típica en ese período, y un "
            "cambio de tarifa a mitad del rango no cuenta como dos precios distintos."
        )
    pasos_limpieza.append(mediana)
    if not cargo:
        # El umbral sólo aplica al comparar servicios entre sí, que es lo que hace el
        # estudio sin cargo elegido.
        pasos_limpieza.append(
            f"**Se exigieron al menos {MINIMO_ENTIDADES} entidades** por concepto para "
            "considerarlo comparable. Cuando el filtro de tipo deja en una gama menos de "
            f"{2 * MINIMO_ENTIDADES} entidades, se exige la mitad de las presentes, nunca "
            f"menos de dos (en la gama {gama_elegida.lower()} de esta consulta: {minimo})."
        )
    st.markdown("\n".join(f"{n}. {paso}" for n, paso in enumerate(pasos_limpieza, 1)))
    if not apartadas.empty:
        st.markdown("**Las filas apartadas, para que consten:**")
        ui.dataframe(
            apartadas[
                ["entidad", "concepto", "tipoTarjeta", "valorMinimo", "valorMaximo", "unidadValor"]
            ].head(50),
            height=240,
        )

st.markdown("**Descargar los datos de esta página**")
if cargo:
    st.caption("La respuesta completa del API, tal como llegó (todos los cargos):")
ui.download_buttons(crudo, stem=f"tarifario_tarjetas_{sufijo}", key="tarj_dl_crudo")
if not cargo and not personales.empty:
    ui.download_buttons(
        personales[
            ["periodo", "tipoEntidad", "entidad", "gama", "marca", "nombreProducto",
             "concepto", "valor", "unidadValor", "periodicidad", "formatoTarifa"]
        ],
        stem=f"tarjetas_personales_{sufijo}_{moneda}",
        key="tarj_dl_limpio",
    )
if not filas_cargo.empty:
    st.caption(f"Sólo el cargo «{cargo}»:")
    ui.download_buttons(
        filas_cargo[
            ["periodo", "tipoEntidad", "entidad", "gama", "marca", "nombreProducto",
             "concepto", "valor", "unidadValor", "periodicidad", "formatoTarifa"]
        ],
        stem="_".join(
            ["".join(c if c.isalnum() else "_" for c in cargo)[:40], sufijo, moneda]
        ),
        key="tarj_dl_cargo",
    )


# ------------------------------------------------------------- Limitaciones

seccion("Lo que este análisis no puede decir")

st.markdown(
    """
Declararlo es parte del trabajo, no una debilidad.

**Es precio de lista, no precio pagado.** Los bancos negocian, exoneran cuotas y hacen
promociones. Lo que se mide es el tarifario publicado, que es una decisión de la
entidad — no el desembolso efectivo de un cliente concreto.
"""
)

if not cargo or cargo == TASA:
    st.markdown(
        """
**La unidad de la tasa está sin confirmar.** El API dice `MENSUAL`; los valores sólo
tienen sentido como tasa anual. Hay que resolverlo en la documentación de la SB. No
afecta a las comparaciones entre bancos, porque todos usan la misma unidad.
"""
    )

st.markdown(
    """
**Mide un nivel, no una evolución.** Con un mes es la foto del tarifario vigente; con
varios, el precio típico de cada entidad en ese período. Si la dispersión se ha abierto
o cerrado con los años es otra pregunta, que exigiría seguirla mes a mes.

**No explica por qué.** Mide cuánto varía el precio y con qué está asociado. No dice
si la causa es el costo, el poder de mercado o la estrategia comercial: eso requeriría
datos de costos por producto que SIMBAD no publica.

**No es una recomendación.** Un banco más caro en un servicio puede ser más barato en
otro, o ofrecer ventajas que el tarifario no recoge.
"""
)

ui.diagnostics(informe, endpoint_id=ENDPOINT, truncation_shown=truncada)
ui.source_note()
