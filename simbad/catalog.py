# -*- coding: utf-8 -*-
"""Catálogo de endpoints del API de Estadísticas del Sistema Financiero (SIMBAD).

Generado a partir de los metadatos publicados por el portal de desarrollador de la
Superintendencia de Bancos (Azure API Management), API
``estad-sticas-del-sistema-financiero-con-paginacion`` v2.

No editar a mano salvo para ajustar etiquetas: las dimensiones y medidas provienen
del esquema OpenAPI real de cada respuesta.

El API publica una treintena de endpoints; aquí sólo están los dos que usa el estudio
de tarjetas.
"""

from __future__ import annotations

BASE_URL = "https://apis.sb.gob.do/estadisticas/v2"
API_KEY_HEADER = "Ocp-Apim-Subscription-Key"

#: Tipos de entidad de intermediación financiera (nombres cortos del API).
TIPOS_ENTIDAD = {
    "BM": "Bancos múltiples",
    "AAyP": "Asociaciones de ahorros y préstamos",
    "BAyC": "Bancos de ahorro y crédito",
    "CC": "Corporaciones de crédito",
    "EP": "Entidades públicas de intermediación financiera",
}

#: Valor que el API usa como comodín de "agregado" en cualquier dimensión: una fila
#: con ``TODOS`` en una columna es la suma sobre esa dimensión, no un dato más. Sumar
#: sin excluirlas multiplica los totales (un estado de situación de tres niveles se
#: triplica).
AGGREGATE_MARKER = "TODOS"

#: Endpoints cuyos filtros de entidad son obligatorios: el API responde HTTP 400
#: ("Se debe introducir entidad o tipo de entidad") si no se envía ninguno.
def requires_entity_filter(endpoint_id: str) -> bool:
    """¿Este endpoint exige que se envíe ``entidad`` o ``tipoEntidad``?"""
    filtros = ENDPOINTS.get(endpoint_id, {}).get("filters", [])
    return "entidad" in filtros or "tipoEntidad" in filtros


#: ``TasasComisionesTarjetasCredito`` es el tarifario que se estudia. Los principales
#: indicadores sólo se consultan para averiguar el último mes publicado por el API.
ENDPOINTS = {
    "principalesIndicadoresSistema": {
        "label": "Principales indicadores del sistema",
        "path": "/indicadores/principales",
        "group": "Indicadores y solvencia",
        "description": "Variables e indicadores que suministran informaciones sobre la rentabilidad de los activos, solvencia y morosidad.",
        "filters": [],
        "dimensions": [
            "periodo"
        ],
        "measures": [
            "activos",
            "solvencia",
            "montoCarteraCredito",
            "morosidad",
            "roa",
            "tasaActiva",
            "tasaPasiva",
            "margen"
        ],
        "measure_kinds": {
            "activos": "monto",
            "solvencia": "porcentaje",
            "montoCarteraCredito": "monto",
            "morosidad": "porcentaje",
            "roa": "porcentaje",
            "tasaActiva": "porcentaje",
            "tasaPasiva": "porcentaje",
            "margen": "porcentaje"
        }
    },
    "TasasComisionesTarjetasCredito": {
        "label": "Tasas y comisiones de Tarjetas de crédito",
        "path": "/tasas-comisiones/tarjetas-credito",
        "group": "Acceso y otros",
        "description": "Variables e indicadores que suministran informaciones de los distintos tipos de tarjetas de créditos, marca, denominación de la moneda, marca, formato de tarifa, montos mínimos y máximos, tasas y comisiones.",
        "filters": [
            "entidad",
            "tipoEntidad"
        ],
        "dimensions": [
            "periodo",
            "tipoEntidad",
            "entidad",
            "nombreProducto",
            "marca",
            "tipoTarjeta",
            "moneda",
            "concepto",
            "periodicidad",
            "formatoTarifa",
            "unidadValor"
        ],
        "measures": [
            "valor",
            "valorMinimo",
            "valorMaximo"
        ],
        "measure_kinds": {
            "valor": "monto",
            "valorMinimo": "monto",
            "valorMaximo": "monto"
        }
    }
}


def get(endpoint_id: str) -> dict:
    """Devuelve los metadatos de un endpoint por su identificador."""
    try:
        return ENDPOINTS[endpoint_id]
    except KeyError:
        raise KeyError(
            f"Endpoint desconocido: {endpoint_id!r}. "
            f"Opciones: {', '.join(sorted(ENDPOINTS))}"
        ) from None
