# -*- coding: utf-8 -*-
"""Componentes de interfaz de la página de precios de tarjetas."""

from __future__ import annotations

import unicodedata
from typing import Any, Sequence

import pandas as pd
import streamlit as st

from simbad import data
from simbad.catalog import ENDPOINTS, TIPOS_ENTIDAD
from simbad.transform import (
    label,
    labels,
    measure_kind,
    number_format,
    to_excel_bytes,
)

#: Período más antiguo ofrecido en los selectores.
FIRST_PERIOD = "2012-01"

#: Nombres de los meses para los desplegables de período.
MESES = {
    "01": "Enero",
    "02": "Febrero",
    "03": "Marzo",
    "04": "Abril",
    "05": "Mayo",
    "06": "Junio",
    "07": "Julio",
    "08": "Agosto",
    "09": "Septiembre",
    "10": "Octubre",
    "11": "Noviembre",
    "12": "Diciembre",
}

#: Primer color de la escala categórica del tema (Sky Blue de marca). Se usa donde
#: hay una sola serie y el color no codifica identidad, como en los rankings.
SERIE_PRINCIPAL = "#009FE3"


# ------------------------------------------------------------- Acceso


def require_api_key() -> bool:
    """Pide la API key en la propia página y la detiene mientras no haya una."""
    if data.has_api_key():
        return True
    st.warning(
        "Esta página necesita tu API key del portal de desarrollador de la "
        "Superintendencia de Bancos: https://desarrollador.sb.gob.do → Perfil → "
        "Suscripciones → clave primaria.",
        icon=":material/key_off:",
    )
    with st.form("api_key_form"):
        clave = st.text_input(
            "API key",
            type="password",
            placeholder="Pega aquí tu clave primaria",
            help=(
                "Sólo vive en esta sesión del navegador. Para no escribirla cada vez, "
                "guárdala en `.streamlit/secrets.toml`."
            ),
        )
        if st.form_submit_button("Usar esta clave", icon=":material/key:", type="primary"):
            data.set_api_key(clave)
            st.rerun()
    st.stop()
    return False


# ------------------------------------------------------------ Filtros


def period_options(latest: str | None = None) -> list[str]:
    """Lista de períodos ``YYYY-MM`` desde :data:`FIRST_PERIOD` hasta el último."""
    end = latest or str(pd.Timestamp.today().to_period("M"))
    return [str(p) for p in pd.period_range(FIRST_PERIOD, end, freq="M")]


def _meses_del_anio(options: Sequence[str], anio: str) -> list[str]:
    """Meses con datos publicados dentro de un año."""
    return [p[5:7] for p in options if p[:4] == anio]


def _selector_mes_anio(
    host,
    *,
    etiqueta: str,
    options: Sequence[str],
    anios: Sequence[str],
    defecto: str,
    key: str,
    ultimo_mes: bool,
) -> str:
    """Par de desplegables año + mes que devuelve un período ``YYYY-MM``."""
    fila = host.container(horizontal=True, gap="small")
    anio = fila.selectbox(
        f"{etiqueta} — año",
        options=anios,
        index=anios.index(defecto[:4]) if defecto[:4] in anios else 0,
        key=f"{key}_anio",
    )
    meses = _meses_del_anio(options, anio) or ["01"]
    if defecto[:4] == anio and defecto[5:7] in meses:
        indice = meses.index(defecto[5:7])
    else:
        indice = len(meses) - 1 if ultimo_mes else 0
    mes = fila.selectbox(
        f"{etiqueta} — mes",
        options=meses,
        index=indice,
        format_func=lambda m: MESES[m],
        # El año forma parte de la clave: al cambiarlo, la lista de meses cambia y
        # el mes vuelve a un valor válido en lugar de arrastrar uno inexistente.
        key=f"{key}_mes_{anio}",
    )
    return f"{anio}-{mes}"


def period_range_selector(
    *,
    key: str,
    default_months: int = 24,
    container=None,
    endpoint_id: str | None = None,
) -> tuple[str, str]:
    """Selector de rango de períodos con desplegables de año y mes.

    Devuelve ``(periodoInicial, periodoFinal)``. Se usan desplegables en vez de un
    deslizador porque con más de diez años de historia el deslizador no permite
    elegir un mes concreto con precisión.

    Con ``endpoint_id`` la lista llega sólo hasta el último mes que ese conjunto
    tiene publicado. Cada conjunto lleva su propio rezago y elegir un mes posterior
    devolvía un HTTP 403 desconcertante.
    """
    host = container or st
    latest = data.latest_period_for(endpoint_id)
    options = period_options(latest)
    if not options:
        return latest, latest

    defecto_fin = options[-1]
    defecto_inicio = options[max(0, len(options) - default_months)]
    anios = sorted({p[:4] for p in options}, reverse=True)

    columnas = host.columns(2)
    inicio = _selector_mes_anio(
        columnas[0],
        etiqueta="Desde",
        options=options,
        anios=anios,
        defecto=defecto_inicio,
        key=f"{key}_desde",
        ultimo_mes=False,
    )
    fin = _selector_mes_anio(
        columnas[1],
        etiqueta="Hasta",
        options=options,
        anios=anios,
        defecto=defecto_fin,
        key=f"{key}_hasta",
        ultimo_mes=True,
    )

    if endpoint_id and latest < data.latest_period():
        host.caption(
            f"Este conjunto se publica con más rezago que el resto: el último mes "
            f"disponible es **{MESES[latest[5:7]]} {latest[:4]}**."
        )

    if inicio > fin:
        host.caption(
            f":orange[El mes inicial ({MESES[inicio[5:7]]} {inicio[:4]}) es posterior al "
            f"final; se consulta el rango al revés.]"
        )
        inicio, fin = fin, inicio
    return inicio, fin


def _sin_acentos(texto: Any) -> str:
    """Texto en mayúsculas y sin acentos, para comparar etiquetas del API."""
    normalizado = unicodedata.normalize("NFD", str(texto).upper())
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn").strip()


#: El API acepta códigos cortos (``BM``) pero devuelve el nombre completo
#: (``BANCOS MÚLTIPLES``), con mayúsculas y acentuación variables entre endpoints.
_NOMBRE_A_CODIGO = {_sin_acentos(v): k for k, v in TIPOS_ENTIDAD.items()}


def entity_type_codes(values: pd.Series) -> pd.Series:
    """Códigos cortos (``BM``, ``AAyP``…) a partir de los nombres largos del API.

    Sirve para filtrar una respuesta por tipo de entidad con los mismos códigos que
    aceptan los filtros. Un nombre que no figura en :data:`TIPOS_ENTIDAD` se
    devuelve tal cual.
    """
    return values.map(lambda t: _NOMBRE_A_CODIGO.get(_sin_acentos(t), t))


def apply_gate(*, key: str, pending: Any, container=None, label: str = "Consultar") -> Any:
    """Retiene los parámetros de la consulta hasta que se confirman.

    Streamlit reejecuta la página con cada clic en un filtro y cada ejecución lanza
    una consulta nueva. Con un API que tarda entre cuarenta y noventa segundos, tocar
    cuatro filtros seguidos costaba cuatro consultas de las que sólo interesaba la
    última, y las tres primeras bloqueaban la página mientras tanto.

    Los widgets siguen vivos —el tipo de entidad sigue acotando la lista de entidades
    al instante, sin esperar— porque lo que se aplaza es la llamada al API, no la
    interfaz. Por eso no se usa ``st.form``, que congelaría también esa relación.

    Devuelve los últimos parámetros confirmados, que son los que la página dibuja.
    """
    almacen = f"{key}__aplicado"
    if almacen not in st.session_state:
        # Primera visita: se consulta con los valores por defecto sin pedir el clic.
        st.session_state[almacen] = pending

    host = container or st
    fila = host.container(horizontal=True, vertical_alignment="center")
    hay_cambios = st.session_state[almacen] != pending
    if fila.button(
        label,
        key=f"{key}__consultar",
        type="primary" if hay_cambios else "secondary",
        disabled=not hay_cambios,
        icon=":material/search:",
    ):
        # Se vuelve a ejecutar en el acto: el botón ya se dibujó como «pendiente» en
        # esta pasada y quedaría encendido después de aplicar. Además así la consulta
        # se lanza una sola vez, en la pasada que ya trae los parámetros nuevos.
        st.session_state[almacen] = pending
        st.rerun()
    if hay_cambios:
        fila.markdown(":orange[Hay filtros sin aplicar. Abajo siguen los resultados anteriores.]")
    else:
        fila.caption("Los resultados de abajo corresponden a estos filtros.")
    return st.session_state[almacen]


# --------------------------------------------------------------- Tablas


def dataframe(
    frame: pd.DataFrame,
    *,
    endpoint_id: str | None = None,
    height: int | None = None,
    key: str | None = None,
) -> None:
    """Muestra un ``DataFrame`` con encabezados legibles y formato numérico."""
    if frame.empty:
        st.info("Sin registros que mostrar.", icon=":material/info:")
        return

    display = frame.rename(columns=labels(frame.columns))
    config: dict[str, Any] = {}
    if endpoint_id:
        for measure in ENDPOINTS[endpoint_id]["measures"]:
            if measure in frame.columns:
                kind = measure_kind(endpoint_id, measure)
                config[label(measure)] = st.column_config.NumberColumn(
                    label(measure), format=number_format(kind)
                )
    st.dataframe(
        display,
        hide_index=True,
        column_config=config,
        height=height or "auto",
        key=key,
    )


def kpi_row(items: Sequence[dict]) -> None:
    """Fila de tarjetas KPI.

    Cada elemento admite ``label``, ``value``, ``delta``, ``help`` y ``chart_data``.
    """
    if not items:
        return
    with st.container(horizontal=True):
        for item in items:
            st.metric(
                item["label"],
                item["value"],
                item.get("delta"),
                border=True,
                help=item.get("help"),
                chart_data=item.get("chart_data"),
                chart_type=item.get("chart_type", "line"),
            )


# ------------------------------------------------------------ Descargas


def download_buttons(frame: pd.DataFrame, *, stem: str, key: str) -> None:
    """Botones para exportar la tabla mostrada a CSV y Excel."""
    if frame.empty:
        return
    with st.container(horizontal=True):
        st.download_button(
            "CSV",
            frame.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{stem}.csv",
            mime="text/csv",
            icon=":material/download:",
            key=f"{key}_csv",
        )
        st.download_button(
            "Excel",
            to_excel_bytes({stem[:31]: frame}),
            file_name=f"{stem}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/table:",
            key=f"{key}_xlsx",
        )


# ---------------------------------------------------------- Diagnóstico


def truncation_notice(report: dict | None) -> bool:
    """Avisa, junto a las cifras y no al pie, de que la respuesta vino a medias.

    Importa el sitio: el tope de páginas corta la respuesta sin que nada en los
    totales lo delate. La vista de detalle de la cartera devuelve sesenta mil
    registros para un solo mes y se corta ahí, de modo que la «cartera bruta» que se
    calcula encima es una fracción de la real y parece perfectamente creíble. Un
    aviso al final de la página llega tarde.

    Devuelve si hubo aviso, para que :func:`diagnostics` no lo repita abajo.
    """
    if not report or not report.get("truncated"):
        return False
    st.error(
        f"**Las cifras de abajo están incompletas.** El API devolvió "
        f"{report.get('rows', 0):,} registros y se cortó en el tope de "
        f"{report.get('pages', 0)} páginas, así que los totales sólo suman la parte "
        f"que llegó. Acota el ámbito a una entidad o reduce el rango de meses.",
        icon=":material/report:",
    )
    return True


def diagnostics(
    report: dict | None, *, endpoint_id: str = "", truncation_shown: bool = False
) -> None:
    """Panel plegable con el detalle de la consulta enviada al API.

    Con ``truncation_shown`` se omite el aviso de respuesta truncada porque la
    página ya lo dio arriba, junto a las cifras a las que afecta.
    """
    if not report:
        return
    if report.get("truncated") and not truncation_shown:
        st.warning(
            f"La consulta devolvió {report.get('rows', 0):,} registros y alcanzó el tope de "
            f"{report.get('pages', 0)} páginas. Acota el rango o los filtros para ver el total.",
            icon=":material/warning:",
        )

    with st.expander("Detalle de la consulta", icon=":material/terminal:"):
        meta = ENDPOINTS.get(endpoint_id or report.get("endpoint", ""), {})
        if meta.get("description"):
            st.caption(meta["description"])
        st.write(
            {
                "Endpoint": report.get("endpoint"),
                "URL": report.get("url"),
                "Parámetros": report.get("params"),
                "Registros devueltos": report.get("rows"),
                "Registros de detalle": report.get("rows_detalle", report.get("rows")),
                "Páginas leídas": report.get("pages"),
                "Modo de paginación": report.get("pagination_mode"),
                "Tiempo (s)": round(report.get("elapsed_s", 0.0), 2),
            }
        )
        ajustes = report.get("ajustes") or {}
        if ajustes:
            st.caption("Correcciones aplicadas a la respuesta del API")
            if ajustes.get("filas_agregadas_descartadas"):
                st.write(
                    f"- Se descartaron {ajustes['filas_agregadas_descartadas']:,} filas "
                    "agregadas (`TODOS`), que duplicarían los totales al sumar."
                )
        if report.get("headers"):
            st.caption("Cabeceras de paginación devueltas por el gateway")
            st.write(report["headers"])


def source_note() -> None:
    """Nota de fuente para el pie de las páginas."""
    st.caption(
        "Fuente: Superintendencia de Bancos de la República Dominicana — "
        "API de Estadísticas del Sistema Financiero v2 (SIMBAD). "
        "Datos consultados en línea."
    )
