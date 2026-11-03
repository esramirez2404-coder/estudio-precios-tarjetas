# -*- coding: utf-8 -*-
"""Cliente y utilidades para el API de Estadísticas del Sistema Financiero (SIMBAD).

Superintendencia de Bancos de la República Dominicana — Departamento de Estudios
Económicos. Portal: https://desarrollador.sb.gob.do
"""

from simbad.catalog import BASE_URL, ENDPOINTS, TIPOS_ENTIDAD
from simbad.client import SimbadAPIError, SimbadAuthError, SimbadClient

__all__ = [
    "BASE_URL",
    "ENDPOINTS",
    "TIPOS_ENTIDAD",
    "SimbadClient",
    "SimbadAPIError",
    "SimbadAuthError",
]
