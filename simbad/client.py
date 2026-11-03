# -*- coding: utf-8 -*-
"""Cliente HTTP para el API de Estadísticas del Sistema Financiero (SIMBAD).

Sin dependencias de Streamlit a propósito: así se puede probar desde un script o
un notebook. La capa de caché para la app vive en :mod:`simbad.data`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlencode

import pandas as pd
import requests

from simbad.catalog import API_KEY_HEADER, BASE_URL
from simbad.catalog import get as get_endpoint

log = logging.getLogger(__name__)

#: Claves bajo las que el API podría envolver el arreglo de resultados.
_ENVELOPE_KEYS = ("data", "datos", "result", "results", "value", "items", "registros")

#: Cabeceras de paginación que el gateway suele devolver (para diagnóstico).
_PAGING_HEADERS = (
    "x-pagination",
    "x-total-count",
    "x-total-pages",
    "x-page",
    "total-count",
    "total-registros",
    "total-paginas",
)


#: Se inyecta una sola vez por proceso.
_system_certs_ready = False


def use_system_certificates() -> bool:
    """Valida TLS con el almacén de certificados del sistema operativo.

    En redes corporativas es habitual que un firewall (Fortinet, Zscaler y
    similares) re-firme el tráfico HTTPS con su propia CA. Esa CA está instalada en
    Windows —por eso el navegador funciona— pero no en el paquete `certifi` que usa
    `requests`, que falla con ``CERTIFICATE_VERIFY_FAILED``.

    `truststore` hace que Python use el almacén del sistema, de modo que la CA
    corporativa se acepta **sin desactivar la verificación**. Si el paquete no está
    instalado no pasa nada: se sigue con `certifi`.
    """
    global _system_certs_ready
    if _system_certs_ready:
        return True
    try:
        import truststore
    except ImportError:
        log.debug("truststore no está instalado; se usa el paquete de CA de certifi.")
        return False
    truststore.inject_into_ssl()
    _system_certs_ready = True
    log.info("Verificación TLS delegada al almacén de certificados del sistema.")
    return True


class SimbadAPIError(RuntimeError):
    """Error devuelto por el API o por la capa de transporte."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class SimbadAuthError(SimbadAPIError):
    """La suscripción (API key) falta, es inválida o no cubre este endpoint."""


@dataclass
class FetchReport:
    """Detalle de lo que ocurrió al traer un conjunto de datos.

    Se muestra en el panel de diagnóstico de la app para que sea evidente si una
    consulta quedó truncada por el tope de páginas.
    """

    endpoint: str = ""
    url: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    pages: int = 0
    rows: int = 0
    truncated: bool = False
    pagination_mode: str = ""
    elapsed_s: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)


def _coerce_rows(payload: Any) -> list[dict]:
    """Normaliza la respuesta a una lista de diccionarios.

    El API devuelve un arreglo JSON plano, pero se aceptan envolturas comunes por
    si una versión futura del gateway las introduce.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in _ENVELOPE_KEYS:
            if isinstance(payload.get(key), list):
                return [r for r in payload[key] if isinstance(r, dict)]
        # Un único registro devuelto como objeto.
        if payload and not any(isinstance(v, (list, dict)) for v in payload.values()):
            return [payload]
    return []


def _row_key(row: Mapping[str, Any]) -> tuple:
    """Clave estable para deduplicar registros entre páginas."""
    return tuple(sorted((k, str(v)) for k, v in row.items()))


class SimbadClient:
    """Cliente del API de estadísticas.

    Parameters
    ----------
    api_key:
        Clave de suscripción generada en https://desarrollador.sb.gob.do (se envía
        en la cabecera ``Ocp-Apim-Subscription-Key``).
    array_style:
        Cómo serializar los filtros de tipo arreglo. ``"repeat"`` (por defecto)
        envía ``entidad=A&entidad=B``, que es el formato ``form/explode`` que
        declara el OpenAPI del API. ``"csv"`` envía ``entidad=A,B``.
    page_size:
        Registros por página (parámetro ``registros``).
    max_pages:
        Tope de páginas por consulta, para no colgar la app con un rango enorme.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        array_style: str = "repeat",
        page_size: int = 1000,
        max_pages: int = 60,
        timeout: int = 90,
        max_retries: int = 3,
    ) -> None:
        if not api_key or not api_key.strip():
            raise SimbadAuthError("Falta el API key de suscripción.")
        if array_style not in ("repeat", "csv"):
            raise ValueError("array_style debe ser 'repeat' o 'csv'.")

        use_system_certificates()

        self.base_url = base_url.rstrip("/")
        self.array_style = array_style
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout = timeout
        self.max_retries = max_retries
        # Se descubre en la primera consulta con más de una página.
        self.pagination_mode: str | None = None

        self._session = requests.Session()
        self._session.headers.update(
            {
                API_KEY_HEADER: api_key.strip(),
                "Accept": "application/json",
                "User-Agent": "simbad-streamlit/1.0",
            }
        )

    # ------------------------------------------------------------------ HTTP

    def _build_params(self, raw: Mapping[str, Any]) -> list[tuple[str, str]]:
        """Aplana los parámetros respetando el estilo de arreglo configurado."""
        out: list[tuple[str, str]] = []
        for name, value in raw.items():
            if value is None or value == "" or value == []:
                continue
            if isinstance(value, (list, tuple, set)):
                values = [str(v) for v in value if v not in (None, "")]
                if not values:
                    continue
                if self.array_style == "csv":
                    out.append((name, ",".join(values)))
                else:
                    out.extend((name, v) for v in values)
            else:
                out.append((name, str(value)))
        return out

    def query_string(self, params: Mapping[str, Any]) -> str:
        """Cadena de consulta tal como se enviaría al API.

        Sirve para mostrar en la app la URL exacta de una consulta, o para
        reproducirla desde `curl` al reportar un problema al soporte del API.
        """
        return urlencode(self._build_params(params))

    def _request(self, path: str, params: Mapping[str, Any]) -> tuple[list[dict], dict]:
        """Ejecuta un GET con reintentos y devuelve (registros, cabeceras)."""
        url = f"{self.base_url}{path}"
        query = self._build_params(params)
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=query, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                # El gateway corta la conexión cuando está cargado: el mismo endpoint
                # que respondió hace un minuto devuelve `RemoteDisconnected` o agota
                # el tiempo de lectura. Se reintenta antes de darlo por caído.
                last_error = exc
                log.warning(
                    "Conexión interrumpida con %s (intento %s/%s): %s",
                    path,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt == self.max_retries:
                    raise SimbadAPIError(
                        f"No se pudo completar la consulta a {url} tras {self.max_retries} "
                        "intentos. El API cortó la conexión, que suele ser una sobrecarga "
                        "pasajera; reintenta en unos segundos o acorta el rango de "
                        f"períodos. Detalle: {exc}"
                    ) from exc
                time.sleep(min(2**attempt, 8))
                continue
            except requests.RequestException as exc:
                raise SimbadAPIError(
                    f"No se pudo conectar con {url}. Verifica tu conexión o el proxy "
                    f"corporativo. Detalle: {exc}"
                ) from exc

            if resp.status_code in (401, 403):
                # El gateway usa 403 tanto para una clave inválida como para pedir un
                # endpoint o un período que la suscripción no cubre. Se comprobó que un
                # mismo endpoint responde 200 para un mes y 403 para el siguiente.
                raise SimbadAuthError(
                    f"El API rechazó la consulta (HTTP {resp.status_code}). Tu suscripción "
                    "no cubre este endpoint o este período; también puede ser que la clave "
                    "sea incorrecta. Prueba con un período anterior.",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            if resp.status_code == 429:
                # Límite de llamadas del plan: respeta Retry-After si viene.
                wait = int(resp.headers.get("Retry-After", 0) or min(2**attempt, 30))
                log.warning("Límite de tasa alcanzado; esperando %ss", wait)
                if attempt == self.max_retries:
                    raise SimbadAPIError(
                        "Se alcanzó el límite de llamadas del plan (HTTP 429). Espera un "
                        "momento o reduce el rango de períodos.",
                        status=429,
                        body=resp.text[:500],
                    )
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                last_error = SimbadAPIError(
                    f"Error del servidor (HTTP {resp.status_code}).",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                if attempt == self.max_retries:
                    raise last_error
                time.sleep(min(2**attempt, 8))
                continue
            if resp.status_code >= 400:
                raise SimbadAPIError(
                    f"El API rechazó la consulta (HTTP {resp.status_code}). Revisa los "
                    f"filtros enviados. Respuesta: {resp.text[:300]}",
                    status=resp.status_code,
                    body=resp.text[:500],
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise SimbadAPIError(
                    f"La respuesta de {path} no es JSON válido: {resp.text[:200]}"
                ) from exc

            headers = {k: v for k, v in resp.headers.items() if k.lower() in _PAGING_HEADERS}
            return _coerce_rows(payload), headers

        raise SimbadAPIError(
            f"Sin respuesta de {url} tras {self.max_retries} intentos: {last_error}"
        )

    # ------------------------------------------------------------- Consultas

    def fetch_raw(
        self,
        endpoint_id: str,
        periodo_inicial: str,
        periodo_final: str | None = None,
        *,
        filters: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[dict], FetchReport]:
        """Trae todos los registros de un endpoint, paginando automáticamente."""
        meta = get_endpoint(endpoint_id)
        path = meta["path"]
        size = page_size or self.page_size
        cap = max_pages or self.max_pages
        allowed = set(meta["filters"])

        base_params: dict[str, Any] = {"periodoInicial": periodo_inicial}
        if periodo_final:
            base_params["periodoFinal"] = periodo_final
        for name, value in (filters or {}).items():
            if name not in allowed:
                log.debug("Filtro %r no aplica a %s; se omite.", name, endpoint_id)
                continue
            base_params[name] = value

        report = FetchReport(
            endpoint=endpoint_id,
            url=f"{self.base_url}{path}",
            params=dict(base_params),
        )
        started = time.perf_counter()

        rows: list[dict] = []
        seen: set[tuple] = set()
        previous_len = 0
        page = 1
        truncated = True

        while page <= cap:
            batch, headers = self._request(
                path, {**base_params, "paginas": page, "registros": size}
            )
            if headers:
                report.headers.update(headers)
            if not batch:
                truncated = False
                break

            # El significado de `paginas` no está documentado de forma inequívoca:
            # puede ser el índice de página o la cantidad de páginas a devolver
            # (respuesta acumulada). Se detecta al traer la segunda página.
            if page == 2 and self.pagination_mode is None:
                self.pagination_mode = "acumulado" if len(batch) > previous_len else "index"
                log.info("Modo de paginación detectado: %s", self.pagination_mode)

            if self.pagination_mode == "acumulado":
                # Cada llamada devuelve el acumulado desde el inicio: reemplaza.
                rows = list(batch)
                complete = len(batch) < size * page
            else:
                new = 0
                for row in batch:
                    key = _row_key(row)
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
                        new += 1
                complete = new == 0 or len(batch) < size

            previous_len = len(batch)
            report.pages = page
            if complete:
                truncated = False
                break
            page += 1

        report.truncated = truncated
        report.rows = len(rows)
        report.pagination_mode = self.pagination_mode or "página única"
        report.elapsed_s = time.perf_counter() - started
        if truncated:
            log.warning(
                "Consulta a %s truncada en %s páginas (%s registros).",
                endpoint_id,
                cap,
                len(rows),
            )
        return rows, report

    def fetch(
        self,
        endpoint_id: str,
        periodo_inicial: str,
        periodo_final: str | None = None,
        *,
        filters: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
    ) -> tuple[pd.DataFrame, FetchReport]:
        """Igual que :meth:`fetch_raw` pero devuelve un ``DataFrame`` tipado."""
        rows, report = self.fetch_raw(
            endpoint_id,
            periodo_inicial,
            periodo_final,
            filters=filters,
            page_size=page_size,
            max_pages=max_pages,
        )
        meta = get_endpoint(endpoint_id)

        if not rows:
            # Marco vacío pero con las columnas esperadas: simplifica las páginas.
            return pd.DataFrame(columns=meta["dimensions"] + meta["measures"]), report

        frame = pd.DataFrame(rows)
        for column in meta["measures"]:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        for column in meta["dimensions"]:
            if column in frame.columns and column != "periodo":
                frame[column] = frame[column].astype("string").str.strip()

        return frame, report
