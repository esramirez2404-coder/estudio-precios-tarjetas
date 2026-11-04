# -*- coding: utf-8 -*-
"""Capa de acceso a datos para la app: credenciales, caché y catálogos vivos.

Aquí vive todo lo que depende de Streamlit. La lógica HTTP pura está en
:mod:`simbad.client`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import streamlit as st

from simbad import historial
from simbad.catalog import (
    AGGREGATE_MARKER,
    ENDPOINTS,
    TIPOS_ENTIDAD,
    requires_entity_filter,
)
from simbad.client import FetchReport, SimbadAPIError, SimbadAuthError, SimbadClient
from simbad.transform import drop_aggregates

#: Clave de sesión donde se guarda la API key escrita a mano.
_KEY_STATE = "simbad_api_key"

#: Parámetros de consulta. El OpenAPI declara los arreglos en formato form/explode
#: (``entidad=A&entidad=B``); el tope de páginas evita que un rango muy amplio
#: bloquee la app.
_ARRAY_STYLE = "repeat"
_PAGE_SIZE = 1000
_MAX_PAGES = 60

#: Todos los tipos de entidad, que es lo que hay que enviar cuando el usuario no
#: filtra: el API exige `entidad` o `tipoEntidad` en casi todos los endpoints.
_ALL_TIPOS = tuple(TIPOS_ENTIDAD)

#: Meses hacia atrás que se consultan al descubrir catálogos. Cada conjunto de datos
#: tiene su propio rezago y el API responde HTTP 403 si se pide un mes suelto que aún
#: no publicó; en cambio, un rango devuelve los meses que sí existan.
_DISCOVERY_WINDOW = 5

#: Meses hacia atrás que se sondean para dar con el último publicado de un
#: conjunto. Quince cubre de sobra el mayor rezago observado (unos seis meses).
_LATEST_LOOKBACK = 15

#: Meses por llamada. El gateway abandona la consulta a los ~60 s y responde HTTP
#: 504, y la latencia del API es muy variable, así que se trocea corto. Además, un mes
#: del tarifario son 18 páginas: con más de tres meses por llamada se pasaría del tope
#: de ``_MAX_PAGES`` y la respuesta llegaría cortada.
_MAX_MONTHS_PER_CALL = 3


def _window(periodo: str, months: int = _DISCOVERY_WINDOW) -> tuple[str, str]:
    """Rango ``(inicio, fin)`` que termina en ``periodo``."""
    fin = pd.Period(str(periodo)[:7], freq="M")
    return str(fin - months), str(fin)


# ----------------------------------------------------------- Credenciales


def stored_api_key() -> str:
    """API key configurada, buscando primero en ``st.secrets``.

    Orden de precedencia: la que el usuario escribió en esta sesión, luego
    ``.streamlit/secrets.toml``. Nunca se escribe la clave en disco desde la app.
    """
    manual = st.session_state.get(_KEY_STATE, "")
    if manual:
        return manual.strip()
    try:
        return str(st.secrets.get("simbad", {}).get("api_key", "")).strip()
    except Exception:
        # `st.secrets` lanza si no existe el archivo; se trata como "sin clave".
        return ""


def set_api_key(value: str) -> None:
    """Guarda la API key sólo en la sesión actual."""
    st.session_state[_KEY_STATE] = (value or "").strip()


def has_api_key() -> bool:
    """¿Hay una API key disponible?"""
    return bool(stored_api_key())


def _fingerprint(api_key: str) -> str:
    """Huella corta de la clave, para usarla como parte de las claves de caché.

    Evita que la clave viaje como argumento cacheado en texto plano.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------- Conexión


@st.cache_resource(show_spinner=False)
def _build_client(
    fingerprint: str,
    array_style: str,
    page_size: int,
    max_pages: int,
    _api_key: str,
) -> SimbadClient:
    """Construye (y reutiliza) el cliente HTTP para una configuración dada."""
    return SimbadClient(
        _api_key,
        array_style=array_style,
        page_size=page_size,
        max_pages=max_pages,
    )


def get_client() -> SimbadClient:
    """Cliente listo para usar con la API key vigente."""
    api_key = stored_api_key()
    if not api_key:
        raise SimbadAuthError(
            "No hay API key configurada. Pégala en el aviso de la página o guárdala "
            "en .streamlit/secrets.toml."
        )
    return _build_client(_fingerprint(api_key), _ARRAY_STYLE, _PAGE_SIZE, _MAX_PAGES, api_key)


# ------------------------------------------------------------ Consultas


#: Únicos filtros que el API aplica de verdad. El resto están declarados en el
#: OpenAPI pero el servidor responde HTTP 404 «No se ha encontrado resultados» aunque
#: el valor exista en los datos (comprobado con `indicador`: la misma consulta sin
#: ese filtro devuelve filas que contienen justamente ese indicador). Se piden al API
#: sólo los que funcionan y los demás se aplican sobre el resultado.
_API_FILTERS = ("entidad", "tipoEntidad")


def _split_filters(filters: Mapping[str, Any]) -> tuple[dict, dict]:
    """Separa los filtros que entiende el API de los que se aplican en pandas."""
    api = {k: v for k, v in filters.items() if k in _API_FILTERS}
    local = {k: v for k, v in filters.items() if k not in _API_FILTERS}
    return api, local


def _apply_local_filters(frame: pd.DataFrame, local: Mapping[str, Any]) -> pd.DataFrame:
    """Aplica sobre el ``DataFrame`` los filtros que el API no sabe resolver."""
    for columna, valores in local.items():
        if not valores or columna not in frame.columns:
            continue
        buscados = {str(v).strip() for v in valores}
        frame = frame[frame[columna].astype(str).str.strip().isin(buscados)]
    return frame


def _tidy(frame: pd.DataFrame, endpoint_id: str) -> tuple[pd.DataFrame, dict]:
    """Quita las filas agregadas antes de que los datos lleguen a la app.

    El API repite cada cifra con ``TODOS`` como comodín en cada dimensión. Se
    conservan sólo las filas de detalle, que son las que se pueden sumar sin duplicar.
    """
    notas: dict[str, Any] = {}
    if frame.empty:
        return frame, notas

    detalle = drop_aggregates(frame, endpoint_id)
    descartadas = len(frame) - len(detalle)
    if descartadas:
        notas["filas_agregadas_descartadas"] = descartadas
    return detalle.reset_index(drop=True), notas


@st.cache_data(ttl="30m", max_entries=128, show_spinner=False)
def _cached_fetch(
    fingerprint: str,
    array_style: str,
    page_size: int,
    max_pages: int,
    endpoint_id: str,
    periodo_inicial: str,
    periodo_final: str | None,
    filters_json: str,
    raw: bool,
    _client: SimbadClient,
) -> tuple[pd.DataFrame, dict]:
    """Consulta cacheada. Los argumentos escalares forman la clave de caché."""
    filters = json.loads(filters_json) if filters_json else {}
    api_filters, local_filters = _split_filters(filters)
    frame, report = _client.fetch(
        endpoint_id,
        periodo_inicial,
        periodo_final,
        filters=api_filters,
    )
    informe = report.__dict__
    if raw:
        return frame, informe

    limpio, notas = _tidy(frame, endpoint_id)
    if local_filters:
        antes = len(limpio)
        limpio = _apply_local_filters(limpio, local_filters).reset_index(drop=True)
        notas["filtrado_local"] = {
            "campos": sorted(local_filters),
            "filas": f"de {antes:,} a {len(limpio):,}",
        }
    informe["ajustes"] = notas
    informe["rows_detalle"] = len(limpio)
    return limpio, informe


@st.cache_data(ttl="6h", show_spinner=False)
def _discover_entity_types(
    fingerprint: str, endpoint_id: str, periodo: str, _client: SimbadClient
) -> list[str]:
    """Códigos de ``tipoEntidad`` que acepta este endpoint.

    Cada endpoint valida los códigos contra su propio vocabulario: los de
    intermediación **cambiaria** y los de subagentes rechazan la lista de las cinco
    entidades de intermediación financiera con un HTTP 400. En el caso normal basta
    una llamada; sólo si esa falla se prueban los códigos uno a uno.
    """
    completos = list(_ALL_TIPOS)
    try:
        inicio, fin = _window(periodo)
        _client.fetch_raw(
            endpoint_id, inicio, fin, filters={"tipoEntidad": completos}, page_size=5, max_pages=1
        )
        return completos
    except SimbadAuthError:
        # HTTP 403 es cuestión del plan o del período, no de los códigos enviados.
        return completos
    except SimbadAPIError:
        pass

    aceptados = []
    for codigo in completos + [AGGREGATE_MARKER]:
        try:
            _client.fetch_raw(
                endpoint_id, *_window(periodo), filters={"tipoEntidad": [codigo]}, page_size=5, max_pages=1
            )
        except SimbadAPIError:
            continue
        aceptados.append(codigo)
    return aceptados or completos


def accepted_entity_types(endpoint_id: str, periodo: str | None = None) -> list[str]:
    """Códigos de tipo de entidad utilizables con este endpoint."""
    try:
        client = get_client()
    except SimbadAPIError:
        return list(_ALL_TIPOS)
    return _discover_entity_types(
        _fingerprint(stored_api_key()), endpoint_id, periodo or latest_period(), client
    )


def default_entity_filter(
    endpoint_id: str, filters: Mapping[str, Any], *, periodo: str | None = None
) -> dict[str, Any]:
    """Completa el filtro de entidad cuando el endpoint lo exige y no viene ninguno.

    Casi todos los endpoints responden HTTP 400 si no se envía ``entidad`` ni
    ``tipoEntidad``, así que "sin filtrar" se traduce a "todos los tipos que este
    endpoint acepta".
    """
    limpio = dict(filters)
    if not requires_entity_filter(endpoint_id):
        return limpio
    if limpio.get("entidad"):
        # El API rechaza recibir entidad y tipoEntidad a la vez ("Se introdujo
        # entidad y tipo de entidad al mismo tiempo"). Gana el filtro más específico.
        limpio.pop("tipoEntidad", None)
    elif not limpio.get("tipoEntidad"):
        limpio["tipoEntidad"] = accepted_entity_types(endpoint_id, periodo)
    return limpio


def _tramos(inicio: str, fin: str, meses: int = _MAX_MONTHS_PER_CALL) -> list[tuple[str, str]]:
    """Parte un rango de períodos en bloques que el gateway sí aguanta."""
    actual = pd.Period(str(inicio)[:7], freq="M")
    ultimo = pd.Period(str(fin)[:7], freq="M")
    bloques = []
    while actual <= ultimo:
        corte = min(actual + meses - 1, ultimo)
        bloques.append((str(actual), str(corte)))
        actual = corte + 1
    return bloques


def load(
    endpoint_id: str,
    periodo_inicial: str,
    periodo_final: str | None = None,
    *,
    filters: Mapping[str, Any] | None = None,
    raw: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Trae un conjunto de datos del API, con caché de 30 minutos.

    Devuelve ``(DataFrame, informe)``. El informe se muestra en el panel de
    diagnóstico y advierte si la consulta quedó truncada. Con ``raw=True`` se
    devuelve la respuesta tal cual, sin los arreglos de :func:`_tidy`.

    Los rangos largos se piden por bloques. El gateway abandona una consulta a los
    sesenta segundos y devuelve HTTP 504: dieciocho meses de la cartera por entidad
    lo superan, mientras que doce responden. Trocear también mejora la caché, porque
    al mover un extremo del rango se reaprovechan los bloques que no cambiaron.
    """
    client = get_client()
    clean = {k: v for k, v in (filters or {}).items() if v not in (None, "", [], ())}
    clean = default_entity_filter(endpoint_id, clean)
    filtros_json = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    huella = _fingerprint(stored_api_key())

    bloques = _tramos(periodo_inicial, periodo_final or periodo_inicial)
    marcos: list[pd.DataFrame] = []
    informe: dict = {}
    for desde, hasta in bloques:
        marco, parcial = _cached_fetch(
            huella,
            client.array_style,
            client.page_size,
            client.max_pages,
            endpoint_id,
            desde,
            hasta,
            filtros_json,
            raw,
            client,
        )
        marcos.append(marco)
        if not informe:
            informe = dict(parcial)
            informe["params"] = {
                **parcial.get("params", {}),
                "periodoInicial": periodo_inicial,
                "periodoFinal": periodo_final,
            }
        else:
            informe["rows"] = informe.get("rows", 0) + parcial.get("rows", 0)
            informe["pages"] = informe.get("pages", 0) + parcial.get("pages", 0)
            informe["elapsed_s"] = informe.get("elapsed_s", 0.0) + parcial.get("elapsed_s", 0.0)
            informe["truncated"] = informe.get("truncated") or parcial.get("truncated")

    if len(bloques) > 1:
        informe["bloques"] = len(bloques)
    combinado = (
        marcos[0] if len(marcos) == 1 else pd.concat(marcos, ignore_index=True)
    )
    informe["rows_detalle"] = len(combinado)
    return combinado, informe


def tarifario_por_meses(
    meses: Sequence[str], al_avanzar: Callable[[int, int], None] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Tarifario de varios meses para la línea de tiempo. Ver :mod:`simbad.historial`."""
    return historial.descargar_meses(stored_api_key(), meses, al_avanzar=al_avanzar)


def load_safe(
    endpoint_id: str,
    periodo_inicial: str,
    periodo_final: str | None = None,
    *,
    filters: Mapping[str, Any] | None = None,
    quiet: bool = False,
    raw: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Como :func:`load`, pero muestra el error en la página en vez de romperla."""
    try:
        return load(endpoint_id, periodo_inicial, periodo_final, filters=filters, raw=raw)
    except SimbadAuthError as exc:
        if not quiet:
            st.error(str(exc), icon=":material/key_off:")
    except SimbadAPIError as exc:
        if not quiet:
            st.error(str(exc), icon=":material/cloud_off:")
    meta = ENDPOINTS.get(endpoint_id, {})
    empty = pd.DataFrame(columns=meta.get("dimensions", []) + meta.get("measures", []))
    return empty, FetchReport(endpoint=endpoint_id).__dict__


# ------------------------------------------------- Catálogos descubiertos


@st.cache_data(ttl="6h", show_spinner=False)
def _discover_latest_period(fingerprint: str, today: str, _client: SimbadClient) -> str | None:
    """Último período con datos publicados, buscando hacia atrás desde hoy.

    El API publica con rezago, así que se consulta una ventana amplia y se toma
    el período máximo devuelto.
    """
    end = pd.Period(today[:7], freq="M")
    start = end - 18
    try:
        rows, _ = _client.fetch_raw(
            "principalesIndicadoresSistema",
            str(start),
            str(end),
            page_size=500,
            max_pages=3,
        )
    except SimbadAPIError:
        return None
    periods = [str(r.get("periodo", ""))[:7] for r in rows if r.get("periodo")]
    return max(periods) if periods else None


def latest_period(default: str | None = None) -> str:
    """Período más reciente disponible en el API (con respaldo local)."""
    fallback = default or str(pd.Timestamp.today().to_period("M") - 3)
    try:
        client = get_client()
    except SimbadAPIError:
        return fallback
    found = _discover_latest_period(
        _fingerprint(stored_api_key()),
        str(pd.Timestamp.today().date()),
        client,
    )
    return found or fallback


@st.cache_data(ttl="6h", show_spinner=False)
def _discover_latest_for_endpoint(
    fingerprint: str, endpoint_id: str, today: str, _client: SimbadClient
) -> str | None:
    """Último período publicado de un conjunto de datos concreto.

    Cada conjunto lleva su propio rezago: en una misma fecha los principales
    indicadores llegaban a 2026-07, la cartera por entidad a 2026-05 y los
    indicadores financieros a 2026-03. Pedir un mes suelto que ese conjunto aún no
    publicó devuelve HTTP 403, así que conviene conocer su techo real.
    """
    fin = pd.Period(str(today)[:7], freq="M")
    filtros = default_entity_filter(endpoint_id, {}, periodo=str(fin))

    # Se prueba mes a mes hacia atrás en vez de pedir un rango largo: los conjuntos
    # grandes desbordan el tope de páginas y entonces sólo vuelven los meses más
    # antiguos del rango, que es justo lo contrario de lo que se busca. Cada sonda
    # pide cinco registros, así que es barata; el resultado se cachea seis horas.
    for atras in range(_LATEST_LOOKBACK):
        mes = str(fin - atras)
        try:
            rows, _ = _client.fetch_raw(
                endpoint_id, mes, mes, filters=filtros, page_size=5, max_pages=1
            )
        except SimbadAPIError:
            # Un mes que aún no se publica responde HTTP 403; se sigue hacia atrás.
            continue
        if rows:
            return mes
    return None


def latest_period_for(endpoint_id: str | None = None) -> str:
    """Último período disponible para un conjunto, con respaldo en el global."""
    global_ = latest_period()
    if not endpoint_id or endpoint_id == "principalesIndicadoresSistema":
        return global_
    try:
        client = get_client()
    except SimbadAPIError:
        return global_
    encontrado = _discover_latest_for_endpoint(
        _fingerprint(stored_api_key()),
        endpoint_id,
        str(pd.Timestamp.today().date()),
        client,
    )
    return encontrado or global_
