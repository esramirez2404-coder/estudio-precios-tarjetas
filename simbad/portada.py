# -*- coding: utf-8 -*-
"""Portada del estudio: una tarjeta de crédito con el hallazgo grabado.

Es el único elemento de la página hecho con HTML propio, porque Streamlit no tiene un
componente que dibuje una tarjeta. Cada parte de la tarjeta lleva un dato: el número
grabado es la cifra que resume el estudio (cuántas veces cobra la entidad más cara lo
que cobra la más barata), el titular es el cargo, la vigencia es el período del
tarifario y el metal es la gama.
"""

from __future__ import annotations

from html import escape

import streamlit as st

#: Metal de cada gama: tres paradas del degradado y la tinta del grabado. Clásica es
#: oscura con tinta clara; oro y platino son claros con tinta oscura. Así el texto
#: conserva el contraste en toda la superficie de la tarjeta.
TINTA_CLARA = "#FFFFFF"
METALES = {
    "Clásica": ("#0B2FA8", "#0B6BE0", "#0A8FD6", TINTA_CLARA),
    "Oro": ("#FFE27A", "#F2BE2C", "#C9920F", "#2A1C00"),
    "Platino": ("#FFFFFF", "#D5DCE8", "#A4AFC2", "#121A2B"),
}

_ESTILO = """
<style>
.tj-escena { display: flex; justify-content: center; padding: .5rem 0 1rem; perspective: 1100px; }
.tj-tarjeta {
  position: relative; box-sizing: border-box; display: flex; flex-direction: column;
  width: 100%; max-width: 430px; aspect-ratio: 1.586 / 1; padding: 1.1rem 1.35rem;
  border-radius: 18px; overflow: hidden; color: var(--tj-tinta);
  background: linear-gradient(135deg, var(--tj-a) 0%, var(--tj-b) 58%, var(--tj-c) 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 0 0 1px rgba(255,255,255,.08),
              0 28px 50px -22px rgba(0,0,0,.75), 0 10px 18px -12px rgba(0,0,0,.6);
  transform: rotateX(7deg) rotateY(-11deg);
  animation: tj-emision .9s cubic-bezier(.2,.75,.25,1) backwards;
  transition: transform .45s cubic-bezier(.2,.75,.25,1);
}
/* Al señalarla, la tarjeta se endereza para leerla de frente. */
.tj-tarjeta:hover { transform: none; }
/* Fondo de seguridad: anillos finos como los de la impresión de una tarjeta real. */
.tj-tarjeta::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: repeating-radial-gradient(circle at 92% 118%, rgba(255,255,255,.08) 0 1px, transparent 1px 7px);
}
/* Un solo destello metálico al emitirse la tarjeta. */
.tj-tarjeta::after {
  content: ""; position: absolute; top: -50%; bottom: -50%; left: -60%; width: 45%;
  pointer-events: none;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,.32), transparent);
  transform: translateX(-120%) skewX(-12deg);
  animation: tj-brillo 1.5s .45s ease-out both;
}
@keyframes tj-emision {
  from { opacity: 0; transform: rotateX(22deg) rotateY(-32deg) translateY(18px); }
  to   { opacity: 1; transform: rotateX(7deg) rotateY(-11deg); }
}
@keyframes tj-brillo { to { transform: translateX(420%) skewX(-12deg); } }
.tj-sup { display: flex; justify-content: space-between; align-items: baseline; font-size: .82rem; }
.tj-emisor { font-weight: 500; opacity: .9; }
.tj-gama { font-size: 1.05rem; font-weight: 800; }
.tj-medio { display: flex; align-items: center; gap: .7rem; margin-top: .85rem; }
.tj-chip {
  position: relative; width: 44px; height: 33px; border-radius: 7px;
  background: linear-gradient(135deg, #F4E2A1 0%, #C79D3E 48%, #EED48A 100%);
  box-shadow: inset 0 0 0 1px rgba(60,40,0,.35);
}
.tj-chip::before { content: ""; position: absolute; inset: 7px 12px; border: 1px solid rgba(60,40,0,.4); border-radius: 4px; }
.tj-chip::after { content: ""; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px solid rgba(60,40,0,.4); }
.tj-ondas { display: flex; align-items: center; gap: 1px; opacity: .85; }
.tj-ondas i { display: block; width: 8px; border-right: 2px solid currentColor; border-radius: 50%; }
.tj-ondas i:nth-child(1) { height: 9px; }
.tj-ondas i:nth-child(2) { height: 15px; }
.tj-ondas i:nth-child(3) { height: 21px; }
.tj-numero {
  margin-top: .65rem; font-family: 'Chivo Mono', ui-monospace, monospace; font-weight: 600;
  font-size: clamp(2.2rem, 7vw, 3.1rem); line-height: 1; letter-spacing: .03em;
}
.tj-leyenda { margin-top: .35rem; max-width: 34ch; font-size: .8rem; line-height: 1.3; opacity: .92; }
.tj-inf { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; margin-top: auto; }
.tj-titular {
  font-family: 'Chivo Mono', ui-monospace, monospace; font-size: .76rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.tj-vigencia { text-align: right; white-space: nowrap; font-size: .62rem; opacity: .92; }
.tj-vigencia b { display: block; font-family: 'Chivo Mono', ui-monospace, monospace; font-size: .9rem; font-weight: 600; letter-spacing: .04em; }
.tj-tinta-clara .tj-numero, .tj-tinta-clara .tj-titular { text-shadow: 0 1px 0 rgba(0,0,0,.45), 0 -1px 0 rgba(255,255,255,.22); }
.tj-tinta-oscura .tj-numero, .tj-tinta-oscura .tj-titular { text-shadow: 0 1px 0 rgba(255,255,255,.7), 0 -1px 0 rgba(0,0,0,.18); }
@media (prefers-reduced-motion: reduce) {
  .tj-tarjeta { animation: none; }
  .tj-tarjeta::after { display: none; }
}
</style>
"""

#: Símbolo de pago sin contacto: tres arcos hechos con CSS, porque ``st.html`` elimina
#: los ``<svg>`` al sanear el contenido.
_ONDAS = '<span class="tj-ondas" aria-hidden="true"><i></i><i></i><i></i></span>'


def _mes_corto(periodo: str) -> str:
    """``2026-05`` → ``05/26``, como la fecha de vencimiento de una tarjeta."""
    return f"{periodo[5:7]}/{periodo[2:4]}"


def _vigencia(inicio: str, fin: str) -> str:
    """Un mes (``05/26``) o un rango (``01/26–05/26``)."""
    return _mes_corto(inicio) if inicio == fin else f"{_mes_corto(inicio)}–{_mes_corto(fin)}"


def pantalla_terminal(*, titulo: str, filas: dict[str, str]) -> None:
    """Pantalla del panel lateral: lo que la página está analizando, a la vista."""
    lineas = "".join(
        f'<div class="tj-pantalla-fila"><span>{escape(nombre)}</span><span>{escape(valor)}</span></div>'
        for nombre, valor in filas.items()
    )
    st.html(
        f'<div class="tj-pantalla" role="status"><div class="tj-pantalla-titulo">{escape(titulo)}'
        f'<span class="tj-cursor" aria-hidden="true"></span></div>{lineas}</div>'
    )


def tarjeta(
    *, gama: str, cifra: str, leyenda: str, titular: str, inicio: str, fin: str
) -> None:
    """Dibuja la tarjeta de la portada con el metal de ``gama``.

    ``titular`` y ``leyenda`` pueden traer texto del API (nombres de cargos), así que
    todo se escapa antes de entrar en el HTML.
    """
    a, b, c, tinta = METALES.get(gama, METALES["Clásica"])
    tono = "tj-tinta-clara" if tinta == TINTA_CLARA else "tj-tinta-oscura"
    vigencia = _vigencia(inicio, fin)
    descripcion = f"Tarjeta {gama}: {cifra}, {leyenda}. {titular}. Vigencia {vigencia}."
    st.html(
        f"""{_ESTILO}
<div class="tj-escena">
  <div class="tj-tarjeta {tono}" role="img" aria-label="{escape(descripcion)}"
       style="--tj-a:{a};--tj-b:{b};--tj-c:{c};--tj-tinta:{tinta}">
    <div class="tj-sup"><span class="tj-emisor">Tarifario SIMBAD</span>
      <span class="tj-gama">{escape(gama)}</span></div>
    <div class="tj-medio"><span class="tj-chip"></span>{_ONDAS}</div>
    <div class="tj-numero">{escape(cifra)}</div>
    <div class="tj-leyenda">{escape(leyenda)}</div>
    <div class="tj-inf">
      <div class="tj-titular">{escape(titular)}</div>
      <div class="tj-vigencia">Vigencia<b>{vigencia}</b></div>
    </div>
  </div>
</div>"""
    )
