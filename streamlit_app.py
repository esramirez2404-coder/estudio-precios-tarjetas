# -*- coding: utf-8 -*-
"""Estudio de precios de tarjetas de crédito en el sistema financiero dominicano.

Consume en línea el API de Estadísticas del Sistema Financiero v2 de la
Superintendencia de Bancos (SIMBAD) para comparar lo que cobra cada entidad por el
mismo cargo de una tarjeta de crédito.
"""

import streamlit as st

st.set_page_config(
    page_title="Precios de tarjetas — SIMBAD",
    page_icon=":material/credit_card:",
    layout="wide",
)

page = st.navigation(
    [
        st.Page(
            "app_pages/tarjetas.py",
            title="Precios de tarjetas",
            icon=":material/credit_card:",
            default=True,
        ),
    ],
)

st.title(page.title, icon=page.icon)
page.run()
