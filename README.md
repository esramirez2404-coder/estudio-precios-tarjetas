# Estudio de precios de tarjetas de crédito

**EO4040 — Introducción a la Ciencia de Datos para Economía**

¿Cuesta lo mismo el mismo cargo de una tarjeta de crédito en todas las entidades? Y si
no, ¿la diferencia la explica la gama de la tarjeta (clásica, oro, platino) o el banco que
la cobra?

El proyecto responde con datos del API de **Estadísticas del Sistema Financiero v2
(SIMBAD)** de la Superintendencia de Bancos de la República Dominicana, en dos formatos:

- una **app de Streamlit** con la página *Precios de tarjetas*;
- un **notebook** que hace el mismo recorrido paso a paso, de la conexión al API al
  análisis del cargo, con el código a la vista.

La app consulta el API en vivo y se apoya en la caché de Streamlit (30 minutos para
consultas, 6 horas para el último mes publicado). Lo único que se guarda son los meses de
la línea de tiempo, en `.cache/tarifario/`: cada uno tarda unos 40 segundos en bajar y un
mes publicado no cambia. Esa carpeta no se sube al repositorio y se puede borrar sin riesgo.

## Requisitos

- Python 3.11 o superior.
- Una clave de suscripción del portal <https://desarrollador.sb.gob.do>.

## Instalación

El entorno virtual va **fuera de la carpeta del proyecto**. La ruta de esta carpeta es
larga y, dentro de ella, algunos archivos de numpy pasan del límite de 260 caracteres de
Windows (`WinError 206`). Además, fuera de OneDrive el entorno no se sincroniza roto a la
otra computadora.

```powershell
python -m venv $HOME\.venvs\estudio-precios-tarjetas
& $HOME\.venvs\estudio-precios-tarjetas\Scripts\Activate.ps1
pip install -r requirements-notebook.txt
```

`requirements-notebook.txt` instala la app y lo que necesita el notebook (scipy,
matplotlib, Jupyter). Si sólo vas a correr la app, basta con `requirements.txt`, que es
también lo que instala Streamlit Cloud.

En VS Code, elige ese intérprete con *Python: Select Interpreter → Enter interpreter
path* y apunta a `~\.venvs\estudio-precios-tarjetas\Scripts\python.exe`.

## Clave del API

La clave viaja en la cabecera `Ocp-Apim-Subscription-Key`. Hay dos formas de darla:

1. **Permanente** — copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml`
   y pega la clave primaria. Ese archivo está en `.gitignore`. El notebook también la lee
   de ahí, o de la variable de entorno `SIMBAD_API_KEY`.
2. **Sólo esta sesión** — si la app no encuentra clave, la pide en la propia página; se
   queda en la sesión del navegador y no se escribe en disco.

Para obtenerla: entra al portal, suscríbete a un producto que incluya *Estadísticas del
Sistema Financiero v2* y copia la clave primaria desde **Perfil → Suscripciones**.

## Ejecutar la app

```powershell
streamlit run streamlit_app.py
```

Para que otras personas de la red local puedan abrirla, añade `--server.address 0.0.0.0`
y comparte la **Network URL** que imprime Streamlit. Si no abre desde otro equipo, casi
siempre es el firewall de Windows: hay que permitir el puerto 8501 una vez, desde
PowerShell como administrador.

```powershell
New-NetFirewallRule -DisplayName "Streamlit SIMBAD 8501" -Direction Inbound `
  -Protocol TCP -LocalPort 8501 -Action Allow -Profile Private
```

## La página *Precios de tarjetas*

Abre con una tarjeta de crédito que lleva grabado el hallazgo: el número es cuántas veces
cobra la entidad más cara lo que cobra la más barata, el titular es el cargo, la vigencia
es el período y el metal es la gama (azul clásica, oro, plata platino). La tarjeta cambia
con el cargo y la gama elegidos. El cargo, la moneda, el tipo de entidad y el período se
eligen en el panel lateral, cuya pantalla resume lo que se está analizando.

La página abre con la variable del grupo, **Cargo por Renovación anual**. Un cargo puede
publicarse con varias periodicidades, y cada una se analiza por separado: cobrar 1,500 al
año no es cobrar 1,500 al mes, y en 2026 aparecen filas mensuales y por adelantado de este
cargo que en 2025 no existían.

**La línea de tiempo** sigue el cargo elegido mes a mes y compara dos trimestres, por
ejemplo T1 2025 y T1 2026: mediana por gama, cuántas entidades suben, bajan o no cambian, y
cada entidad con sus dos precios. Sólo entran en la comparación las entidades que publicaron
en ambos períodos, para que un banco nuevo no mueva la mediana. Con rangos de más de dos años
dibuja un mes de cada tres o de cada seis, siempre con los meses comparados. Los precios son
nominales: no descuentan la inflación.

Descarga el tarifario completo del período elegido —un rango de año y mes desde/hasta,
que por defecto es el último mes publicado (unos 9 000 registros, 40 segundos)— y
calcula todo lo demás en pandas sobre esa respuesta, que queda en caché: cambiar de tipo
de entidad, de gama o de moneda no genera tráfico nuevo. Sólo cambiar el período pide
datos nuevos, y por eso va detrás del botón *Consultar*. Con varios meses, el precio de
cada entidad es la mediana de lo que publicó en ellos. Este conjunto sólo acepta los
códigos `BM`, `AAyP` y `BAyC`; el API responde HTTP 400 a `CC` y `EP`.

**El filtro *Tipo de cargo*** (campo `concepto` del API: «Cargo por Renovación»,
«Comisión por Mora»…) sirve para que cada grupo elija la variable que le toca analizar.
Ofrece sólo los cargos que aparecen en las tarjetas personales del período descargado.
Con un cargo elegido, **toda la página se filtra a ese cargo** y no muestra ningún otro
servicio:

1. La ficha del cargo: entidades que lo publican, estadística descriptiva por gama
   (media, desviación, cuartiles, coeficiente de variación), diagrama de caja con un punto
   por entidad, precio de cada entidad y valores atípicos por la regla de Tukey.
2. El mismo cargo, el mismo banco: cómo cambia su precio de clásica a platino dentro de
   cada entidad, y cuánto multiplica cada una.
3. Qué parte de la variación de su precio explica la gama y cuál el banco.
4. El rastro de la consulta y las limitaciones, también acotados al cargo.

Si el cargo se publica en más de una unidad —porcentaje y monto fijo—, se elige cuál
analizar. Con «Todos los cargos» vuelve el estudio completo, que compara los servicios
entre sí: cuánto varía el precio del mismo servicio entre entidades, cuánto lo explica la
gama y cuánto la entidad, con la URL exacta de la consulta, el `curl` equivalente y el
detalle de cada decisión de limpieza.

Todas las tablas se pueden descargar en CSV y Excel.

## El notebook

`notebooks/estudio_precios_tarjetas.ipynb` hace el recorrido completo paso a paso: la
clave y la sesión HTTP, la primera llamada, los errores que devuelve el API, el sondeo del
último mes publicado, la descarga paginada, la exploración inicial, las filas repetidas,
la limpieza, el embudo de filtros hasta el cargo del grupo, su estadística descriptiva,
los atípicos, una prueba de Friedman entre gamas, la descomposición de la variación y la
línea de tiempo entre `PERIODO_A` y `PERIODO_B`. Una sección final comprueba con `assert`
que sus cifras coinciden con las de la app.

Se usa cambiando `CARGO` en la celda de parámetros y ejecutando todo de nuevo (*Restart
Kernel and Run All Cells*). La clave nunca se imprime. Los CSV que exporta quedan en
`notebooks/salidas/`, que no se sube al repositorio.

El notebook se genera con `notebooks/generar_notebook.py`. Si cambias su contenido,
edita el generador y vuelve a crearlo y ejecutarlo:

```powershell
python notebooks/generar_notebook.py
jupyter nbconvert --to notebook --execute --inplace notebooks/estudio_precios_tarjetas.ipynb
```

## Estructura

```
streamlit_app.py            Punto de entrada: configuración de página
app_pages/tarjetas.py       La página del estudio
simbad/
    catalog.py              Los dos endpoints que usa el estudio: rutas, filtros y columnas
    client.py               Cliente HTTP con reintentos y paginación (sin Streamlit)
    data.py                 Capa con caché: credenciales, consultas y último mes publicado
    estudio_tarjetas.py     Cálculos del estudio (sin Streamlit)
    ficha_cargo.py          Ficha del cargo que analiza cada grupo
    historial.py            Descarga del tarifario mes a mes, en paralelo (sin Streamlit)
    linea_tiempo.py         La línea de tiempo y la comparación entre períodos
    portada.py              La tarjeta de la portada y la pantalla del panel lateral
    estilo.css              Capa visual: degradados, animación y colores por función
    transform.py            Filas agregadas, etiquetas legibles y exportación (sin Streamlit)
    ui.py                   Componentes de interfaz: período, tablas, KPIs, descargas
notebooks/
    estudio_precios_tarjetas.ipynb   El estudio paso a paso, ya ejecutado
    generar_notebook.py              Genera el notebook
    salidas/                         CSV que exporta el notebook
.streamlit/config.toml      Tema oscuro con la escala de colores validada
```

`client.py`, `estudio_tarjetas.py` y `transform.py` no importan Streamlit a propósito: el
notebook los usa para comprobar que sus cifras coinciden con las de la app.

## Comportamientos del API que conviene conocer

Todo lo siguiente está verificado contra el API en producción. El panel *Detalle de la
consulta*, al pie de la página, indica qué correcciones se aplicaron.

**El API repite filas idénticas.** El tarifario de tarjetas de mayo de 2026 anuncia
16 362 registros, pero sólo 8 945 son distintos: hay filas iguales en todas sus columnas
repetidas hasta 17 veces. No es un efecto de la paginación: pedido en una sola página
(`registros=20000`), el mes devuelve las mismas 16 362 filas y las mismas 8 945 únicas.
El cliente se queda con una copia de cada fila, para que un producto repetido no pese más
en las medianas.

**`TODOS` es un comodín de agregado, no un dato.** Una fila con `entidad = TODOS` es la
suma de todas las entidades. Sumar sin filtrar duplica cualquier total por entidad, así
que la app se queda sólo con las filas de detalle (ninguna dimensión en `TODOS`).

**Los filtros de entidad son obligatorios.** El endpoint responde
`HTTP 400 — "Se debe introducir entidad o tipo de entidad"` si no se envía `entidad` ni
`tipoEntidad`. «Sin filtrar» se traduce internamente a todos los tipos que acepta.

**Sólo funcionan de verdad los filtros de entidad.** El resto están declarados en el
OpenAPI, pero el servidor responde `HTTP 404 — "No se ha encontrado resultados"` aunque
el valor exista en los datos. Por eso al API se envían sólo `periodo`, `entidad` y
`tipoEntidad`, y los demás filtros se aplican sobre el resultado con pandas.

**El filtro por entidad y el filtro por tipo de entidad son excluyentes.** Enviar los
dos devuelve `HTTP 400 — "Se introdujo entidad y tipo de entidad al mismo tiempo"`.

**Los filtros de lista sólo funcionan repetidos** (`tipoEntidad=BM&tipoEntidad=AAyP`).
El formato separado por comas devuelve `HTTP 400`.

**Los códigos de tipo de entidad entran abreviados y salen completos.** Se envía `BM` y
la respuesta trae `BANCOS MÚLTIPLES`.

**`HTTP 403` no siempre es un problema de clave.** El plan también limita hasta qué
período se puede consultar, y pedir un mes que el conjunto aún no publicó devuelve 403.
Por eso el último mes se busca **sondeando mes a mes hacia atrás**, y los desplegables de
período se detienen ahí.

**El gateway abandona las consultas largas a los ~60 segundos** y responde `HTTP 504`.
La app pide los rangos largos en bloques de seis meses y los concatena; de paso, al mover
un extremo del rango se reaprovechan los bloques que no cambiaron.

**El gateway corta conexiones bajo carga** (`RemoteDisconnected`, tiempo de lectura
agotado). El cliente reintenta hasta tres veces con espera creciente.

**La paginación es ambigua.** El cliente detecta en la segunda página si el API devuelve
índices o resultados acumulados, y actúa en consecuencia.

**El WAF bloquea peticiones sin `User-Agent`.** Delante del API hay un firewall (Sucuri)
que responde con una página HTML de bloqueo. El cliente envía siempre un `User-Agent`
propio; conviene mantenerlo si se reutiliza el código desde un script.

## Cómo se escriben las cifras

Las magnitudes se rotulan con palabras y nunca con abreviaturas: en la práctica
financiera dominicana **«MM» significa millones**, de modo que rotular mil millones como
«MM» hace leer las cifras mil veces más pequeñas. En las tablas los montos van con la
cifra completa y separadores de miles, para poder auditarlos.

## Tema

El tema vive en `.streamlit/config.toml`: oscuro, sobre la paleta corporativa (navy
`#20397F`, gris `#E5E6E8`, Sky Blue `#009FE3`). La escala categórica de los gráficos está
validada contra ese fondo (separación bajo daltonismo y contraste ≥ 3:1); si cambias un
color, vuelve a validar la escala completa en lugar de ajustar un valor suelto. La
tipografía es Chivo; Chivo Mono queda para el código y el número grabado de la tarjeta.

Cada gama tiene su color en todos los gráficos que las separan (`ui.COLORES_GAMA`). Los
gráficos de precio por gama usan escala logarítmica: la misma distancia vertical es el
mismo múltiplo, y un solo banco muy caro no aplasta a los demás. En los de líneas, la
entidad bajo el puntero se enciende en amarillo con su nombre.

El título y la banda de portada se mueven despacio, la tarjeta se anima al dibujarse y se
endereza al señalarla; todo respeta la preferencia de movimiento reducido del sistema. El
panel lateral imita una terminal de pago con su pantalla. La tarjeta se dibuja con CSS y no con SVG porque `st.html` elimina los `<svg>`
al sanear el contenido. Si editas algo en `simbad/` y no ves el cambio, reinicia
`streamlit run`: el servidor puede conservar esos módulos en memoria.

## Redes corporativas

Si un firewall inspecciona el tráfico HTTPS (Fortinet, Zscaler y similares), Python
falla con `CERTIFICATE_VERIFY_FAILED` aunque el navegador funcione. Por eso el proyecto
incluye **`truststore`**, que delega la validación en el almacén de certificados de
Windows. **No desactiva la verificación de certificados.**

---

Fuente: Superintendencia de Bancos de la República Dominicana — API de Estadísticas del
Sistema Financiero v2. Soporte del API: soporteapis@sb.gob.do
