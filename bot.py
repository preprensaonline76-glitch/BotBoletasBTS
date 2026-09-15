# ============================================================
# BOT BTS TICKETMASTER 24/7
# MONITOREO DE DISPONIBILIDAD + TELEGRAM
#
# NO REALIZA COMPRAS.
# NO HACE BYPASS DE CAPTCHA / ANTI-BOT.
#
# Detecta:
#   - AGOTADO
#   - DISPONIBLE
#   - DESCONOCIDO
#   - ERROR
#
# Compatible con Railway + Docker + Chromium + Selenium
# ============================================================

import os
import re
import json
import time
import traceback
import requests

from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
    NoSuchElementException
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

URLS = [
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre"
]

# ------------------------------------------------------------
# TIEMPOS
# ------------------------------------------------------------

INTERVALO_REVISION = 30
HEARTBEAT_HORAS = 5

PAGE_LOAD_TIMEOUT = 45
SCRIPT_TIMEOUT = 30

# Reintentos internos de carga
MAX_REINTENTOS_POR_URL = 2

# Cada cuánto comprobar que Chrome sigue vivo
WATCHDOG_SEGUNDOS = 60

# ------------------------------------------------------------
# ALERTAS DE DISPONIBILIDAD
# ------------------------------------------------------------

# Mientras esté disponible se repite cada 30 segundos.
REPETIR_DISPONIBILIDAD = True

# ------------------------------------------------------------
# ARCHIVO DE ESTADO
# ------------------------------------------------------------

STATE_FILE = "/tmp/ticketmaster_estado.json"

# ------------------------------------------------------------
# CAPTURAS DE DIAGNÓSTICO
# ------------------------------------------------------------

SCREENSHOT_DIR = "/tmp/ticketmaster_screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ============================================================
# VARIABLES GLOBALES
# ============================================================

driver = None

estado_anterior = {}

ultima_alerta_disponible = {}

ultimo_heartbeat = datetime.now()

inicio_bot = datetime.now()

ultima_revision_chrome = datetime.now()

# ------------------------------------------------------------
# ESTADÍSTICAS
# ------------------------------------------------------------

estadisticas = {
    "revisiones_totales": 0,
    "revisiones_correctas": 0,
    "revisiones_error": 0,
    "detecciones_agotado": 0,
    "detecciones_disponible": 0,
    "detecciones_desconocido": 0,
    "recuperaciones_chrome": 0,
}

# ------------------------------------------------------------
# CONTROL DE ERRORES TELEGRAM
# ------------------------------------------------------------

errores_consecutivos = 0
errores_telegram_en_racha = 0

MAX_ERRORES_TELEGRAM_POR_RACHA = 10


# ============================================================
# LOG
# ============================================================

def log(mensaje):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ahora}] {mensaje}", flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_url():
    return f"https://api.telegram.org/bot{TOKEN}"


def enviar_telegram(mensaje, silencioso=False):

    global errores_consecutivos
    global errores_telegram_en_racha

    if not TOKEN or not CHAT_ID:
        log("⚠️ TOKEN o CHAT_ID no configurados.")
        return False

    url = telegram_url() + "/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "disable_web_page_preview": True
    }

    try:

        respuesta = requests.post(
            url,
            json=payload,
            timeout=20
        )

        if respuesta.status_code == 200:

            errores_consecutivos = 0
            errores_telegram_en_racha = 0

            return True

        else:

            errores_consecutivos += 1

            if not silencioso:
                log(
                    f"❌ Telegram HTTP {respuesta.status_code}: "
                    f"{respuesta.text[:300]}"
                )

            return False

    except Exception as e:

        errores_consecutivos += 1

        if not silencioso:
            log(f"❌ Error Telegram: {e}")

        return False


def enviar_error_telegram(mensaje):

    global errores_telegram_en_racha

    if errores_telegram_en_racha >= MAX_ERRORES_TELEGRAM_POR_RACHA:

        log(
            "🔇 Límite de mensajes de error Telegram alcanzado "
            f"({MAX_ERRORES_TELEGRAM_POR_RACHA})."
        )

        return

    ok = enviar_telegram(
        "⚠️ ERROR BOT BTS\n\n" + mensaje,
        silencioso=True
    )

    if not ok:
        return

    errores_telegram_en_racha += 1


# ============================================================
# TELEGRAM - PRUEBA
# ============================================================

def probar_telegram():

    if not TOKEN:
        log("❌ TOKEN no encontrado.")
        return False

    if not CHAT_ID:
        log("❌ CHAT_ID no encontrado.")
        return False

    log("✅ TOKEN encontrado.")
    log("✅ CHAT_ID encontrado.")

    ok = enviar_telegram(
        "🚀 Bot BTS Ticketmaster iniciado correctamente.\n"
        "Monitoreo 24/7 activado.",
        silencioso=True
    )

    if ok:
        log("✅ Telegram funcionando.")
        return True

    log("❌ Telegram no respondió correctamente.")

    return False


# ============================================================
# GUARDAR ESTADO
# ============================================================

def guardar_estado():

    try:

        datos = {
            "estado_anterior": estado_anterior,
            "ultima_alerta_disponible": {
                k: v.isoformat()
                for k, v in ultima_alerta_disponible.items()
            },
            "estadisticas": estadisticas
        }

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as archivo:

            json.dump(
                datos,
                archivo,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        log(f"⚠️ No se pudo guardar estado: {e}")


# ============================================================
# CARGAR ESTADO
# ============================================================

def cargar_estado():

    global estado_anterior
    global ultima_alerta_disponible
    global estadisticas

    if not os.path.exists(STATE_FILE):
        log("ℹ️ No existe estado anterior. Inicio limpio.")
        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

        estado_anterior = datos.get(
            "estado_anterior",
            {}
        )

        fechas = datos.get(
            "ultima_alerta_disponible",
            {}
        )

        ultima_alerta_disponible = {}

        for url, fecha in fechas.items():

            try:
                ultima_alerta_disponible[url] = datetime.fromisoformat(
                    fecha
                )
            except Exception:
                pass

        estadisticas_guardadas = datos.get(
            "estadisticas",
            {}
        )

        for clave in estadisticas:

            if clave in estadisticas_guardadas:

                estadisticas[clave] = estadisticas_guardadas[clave]

        log("💾 Estado anterior recuperado.")

    except Exception as e:

        log(f"⚠️ No se pudo cargar estado anterior: {e}")


# ============================================================
# CONFIGURAR CHROME
# ============================================================

def crear_driver():

    log("🚀 Iniciando Chrome...")

    options = Options()

    # --------------------------------------------------------
    # HEADLESS
    # --------------------------------------------------------

    options.add_argument("--headless=new")

    # --------------------------------------------------------
    # ESTABILIDAD EN RAILWAY
    # --------------------------------------------------------

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    options.add_argument("--disable-software-rasterizer")

    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")

    options.add_argument("--disable-renderer-backgrounding")

    options.add_argument("--disable-features=Translate")

    options.add_argument("--disable-extensions")

    options.add_argument("--disable-popup-blocking")

    options.add_argument("--disable-notifications")

    options.add_argument("--mute-audio")

    options.add_argument("--window-size=1920,1080")

    options.add_argument("--lang=es-CO")

    # --------------------------------------------------------
    # USER AGENT NORMAL
    # --------------------------------------------------------

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )

    # --------------------------------------------------------
    # CARGA
    # --------------------------------------------------------

    options.page_load_strategy = "eager"

    # --------------------------------------------------------
    # DESACTIVAR LOGS EXCESIVOS
    # --------------------------------------------------------

    options.add_experimental_option(
        "excludeSwitches",
        [
            "enable-logging"
        ]
    )

    try:

        nuevo_driver = webdriver.Chrome(
            options=options
        )

        nuevo_driver.set_page_load_timeout(
            PAGE_LOAD_TIMEOUT
        )

        nuevo_driver.set_script_timeout(
            SCRIPT_TIMEOUT
        )

        log("✅ Selenium creado correctamente.")

        return nuevo_driver

    except Exception as e:

        log(
            "❌ No fue posible crear Selenium:\n"
            f"{traceback.format_exc()}"
        )

        return None


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global driver
    global ultima_revision_chrome

    log("🔄 Iniciando recuperación automática de Chrome...")

    try:

        if driver is not None:

            try:
                driver.quit()
            except Exception:
                pass

        driver = None

    except Exception:
        pass

    estadisticas["recuperaciones_chrome"] += 1

    time.sleep(3)

    driver = crear_driver()

    ultima_revision_chrome = datetime.now()

    if driver is None:

        log("❌ La recuperación de Chrome falló.")

        return False

    try:

        driver.get("https://www.ticketmaster.co/")

        time.sleep(3)

        log("✅ Chrome recuperado correctamente.")

        return True

    except Exception as e:

        log(f"❌ Chrome recuperado pero Ticketmaster falló: {e}")

        return False


# ============================================================
# OBTENER TEXTO DEL BODY
# ============================================================

def obtener_body_text(driver_actual):

    try:

        body = driver_actual.find_element(
            By.TAG_NAME,
            "body"
        )

        return body.text or ""

    except Exception:

        return ""


# ============================================================
# OBTENER TEXTO + ATRIBUTOS DEL DOM
# ============================================================

def obtener_contenido_dom(driver_actual):

    partes = []

    # --------------------------------------------------------
    # BODY TEXT
    # --------------------------------------------------------

    try:

        texto_body = obtener_body_text(
            driver_actual
        )

        if texto_body:
            partes.append(texto_body)

    except Exception:
        pass

    # --------------------------------------------------------
    # PAGE SOURCE
    # --------------------------------------------------------

    try:

        source = driver_actual.page_source

        if source:
            partes.append(source)

    except Exception:
        pass

    # --------------------------------------------------------
    # ELEMENTOS
    # --------------------------------------------------------

    try:

        elementos = driver_actual.find_elements(
            By.XPATH,
            "//*"
        )

        for elemento in elementos:

            try:

                texto = elemento.text

                if texto:
                    partes.append(texto)

                aria = elemento.get_attribute(
                    "aria-label"
                )

                if aria:
                    partes.append(aria)

                title = elemento.get_attribute(
                    "title"
                )

                if title:
                    partes.append(title)

                value = elemento.get_attribute(
                    "value"
                )

                if value:
                    partes.append(value)

                data_testid = elemento.get_attribute(
                    "data-testid"
                )

                if data_testid:
                    partes.append(data_testid)

                data_label = elemento.get_attribute(
                    "data-label"
                )

                if data_label:
                    partes.append(data_label)

                data_status = elemento.get_attribute(
                    "data-status"
                )

                if data_status:
                    partes.append(data_status)

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error inspeccionando elementos DOM: {e}"
        )

    return "\n".join(partes)


# ============================================================
# SHADOW DOM
# ============================================================

def obtener_texto_shadow_dom(driver_actual):

    javascript = """
    function recorrer(root, resultados) {

        if (!root) {
            return;
        }

        try {

            if (root.nodeType === Node.TEXT_NODE) {

                const texto = root.textContent || "";

                if (texto.trim()) {
                    resultados.push(texto);
                }

                return;
            }

            if (root.nodeType === Node.ELEMENT_NODE) {

                const textoDirecto =
                    root.innerText || "";

                if (textoDirecto.trim()) {
                    resultados.push(textoDirecto);
                }

                const aria =
                    root.getAttribute("aria-label");

                if (aria) {
                    resultados.push(aria);
                }

                const title =
                    root.getAttribute("title");

                if (title) {
                    resultados.push(title);
                }

                if (root.shadowRoot) {

                    recorrer(
                        root.shadowRoot,
                        resultados
                    );
                }

                const hijos =
                    root.children || [];

                for (let i = 0; i < hijos.length; i++) {

                    recorrer(
                        hijos[i],
                        resultados
                    );
                }
            }

            if (
                root.nodeType === Node.DOCUMENT_FRAGMENT_NODE ||
                root.nodeType === Node.DOCUMENT_NODE
            ) {

                const hijos =
                    root.children || [];

                for (let i = 0; i < hijos.length; i++) {

                    recorrer(
                        hijos[i],
                        resultados
                    );
                }
            }

        } catch (e) {
            // Ignorar nodos problemáticos
        }
    }

    const resultados = [];

    recorrer(
        document.documentElement,
        resultados
    );

    return resultados.join("\\n");
    """

    try:

        resultado = driver_actual.execute_script(
            javascript
        )

        return resultado or ""

    except Exception as e:

        log(
            f"⚠️ Shadow DOM no disponible: {e}"
        )

        return ""


# ============================================================
# OBTENER CONTENIDO DE IFRAMES
# ============================================================

def obtener_contenido_iframes(driver_actual):

    contenidos = []

    try:

        iframes = driver_actual.find_elements(
            By.TAG_NAME,
            "iframe"
        )

        if not iframes:
            return ""

        log(
            f"🧩 Iframes encontrados: {len(iframes)}"
        )

        for indice in range(len(iframes)):

            try:

                # Volver al documento principal
                driver_actual.switch_to.default_content()

                iframes_actuales = driver_actual.find_elements(
                    By.TAG_NAME,
                    "iframe"
                )

                if indice >= len(iframes_actuales):
                    continue

                driver_actual.switch_to.frame(
                    iframes_actuales[indice]
                )

                texto = obtener_body_text(
                    driver_actual
                )

                if texto:
                    contenidos.append(texto)

                try:

                    source = driver_actual.page_source

                    if source:
                        contenidos.append(source)

                except Exception:
                    pass

            except Exception as e:

                log(
                    f"⚪ No se pudo inspeccionar iframe "
                    f"{indice}: {e}"
                )

            finally:

                try:
                    driver_actual.switch_to.default_content()
                except Exception:
                    pass

    except Exception as e:

        log(
            f"⚠️ Error buscando iframes: {e}"
        )

    return "\n".join(contenidos)


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    texto = texto.lower()

    # Normalización de espacios
    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# DETECTAR AGOTADO
# ============================================================

def detectar_agotado_en_texto(texto):

    if not texto:
        return False

    texto = normalizar_texto(texto)

    patrones_agotado = [

        # Español
        r"\bagotado\b",
        r"\bagotada\b",
        r"\bagotados\b",
        r"\bagotadas\b",

        r"entradas agotadas",
        r"boletas agotadas",
        r"tickets agotados",

        r"evento agotado",

        r"no hay entradas",
        r"no hay boletas",
        r"no hay tickets",

        r"entradas no disponibles",
        r"boletas no disponibles",
        r"tickets no disponibles",

        r"sin entradas disponibles",
        r"sin boletas disponibles",
        r"sin tickets disponibles",

        # Inglés
        r"\bsold out\b",
        r"\bsold-out\b",

        r"no tickets available",
        r"tickets unavailable",
        r"tickets are currently unavailable",
        r"tickets not available",

        r"no seats available",
        r"seats unavailable",
        r"no seats currently available",

        r"currently unavailable"
    ]

    for patron in patrones_agotado:

        try:

            if re.search(
                patron,
                texto,
                flags=re.IGNORECASE
            ):

                return True

        except Exception:
            continue

    return False


# ============================================================
# DETECTAR AGOTADO DIRECTAMENTE EN ELEMENTOS
# ============================================================

def detectar_agotado_en_elementos(driver_actual):

    patrones = [
        "agotado",
        "agotada",
        "agotados",
        "agotadas",
        "sold out",
        "sold-out"
    ]

    hallazgos = []

    try:

        elementos = driver_actual.find_elements(
            By.XPATH,
            "//*"
        )

        for elemento in elementos:

            try:

                textos = []

                texto = elemento.text

                if texto:
                    textos.append(texto)

                aria = elemento.get_attribute(
                    "aria-label"
                )

                if aria:
                    textos.append(aria)

                title = elemento.get_attribute(
                    "title"
                )

                if title:
                    textos.append(title)

                value = elemento.get_attribute(
                    "value"
                )

                if value:
                    textos.append(value)

                data_testid = elemento.get_attribute(
                    "data-testid"
                )

                if data_testid:
                    textos.append(data_testid)

                for valor in textos:

                    valor_normalizado = normalizar_texto(
                        valor
                    )

                    for patron in patrones:

                        if patron in valor_normalizado:

                            hallazgos.append(
                                (
                                    patron,
                                    valor_normalizado[:200]
                                )
                            )

                            # No necesitamos miles
                            # de coincidencias.
                            if len(hallazgos) >= 10:
                                return hallazgos

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error buscando agotado en elementos: {e}"
        )

    return hallazgos


# ============================================================
# DETECTAR AGOTADO CON XPATH DIRECTO
# ============================================================

def detectar_agotado_xpath(driver_actual):

    try:

        xpath = """
        //*[
            contains(
                translate(
                    normalize-space(.),
                    'ÁÉÍÓÚáéíóú',
                    'AEIOUaeiou'
                ),
                'agotado'
            )
            or
            contains(
                translate(
                    normalize-space(@aria-label),
                    'ÁÉÍÓÚáéíóú',
                    'AEIOUaeiou'
                ),
                'agotado'
            )
            or
            contains(
                translate(
                    normalize-space(@title),
                    'ÁÉÍÓÚáéíóú',
                    'AEIOUaeiou'
                ),
                'agotado'
            )
        ]
        """

        elementos = driver_actual.find_elements(
            By.XPATH,
            xpath
        )

        if elementos:

            for elemento in elementos[:10]:

                try:

                    texto = (
                        elemento.text
                        or
                        elemento.get_attribute(
                            "aria-label"
                        )
                        or
                        elemento.get_attribute(
                            "title"
                        )
                        or
                        ""
                    )

                    if texto.strip():

                        log(
                            "🔴 AGOTADO encontrado "
                            f"directamente en DOM: "
                            f"'{texto[:150]}'"
                        )

            return True

    except Exception as e:

        log(
            f"⚠️ Error en XPath agotado: {e}"
        )

    return False


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra(driver_actual):

    controles_fuertes = [

        "comprar boletas",
        "comprar entradas",
        "comprar tickets",

        "seleccionar localidad",
        "seleccionar asiento",
        "seleccionar asientos",

        "continuar compra",

        "buy tickets",
        "buy now",
        "purchase tickets",

        "select seats",
        "select tickets",
        "choose seats",
        "choose tickets",
        "get tickets",

        "checkout"
    ]

    # IMPORTANTE:
    # No usamos solamente "comprar", "purchase"
    # o "continuar", porque Ticketmaster puede tener
    # esos textos en componentes genéricos incluso
    # cuando el evento está agotado.

    encontrados = []

    try:

        elementos = driver_actual.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button'], input, "
            "[data-testid], [aria-label]"
        )

        for elemento in elementos:

            try:

                texto = (
                    elemento.text
                    or ""
                ).strip().lower()

                aria = (
                    elemento.get_attribute(
                        "aria-label"
                    )
                    or ""
                ).strip().lower()

                title = (
                    elemento.get_attribute(
                        "title"
                    )
                    or ""
                ).strip().lower()

                value = (
                    elemento.get_attribute(
                        "value"
                    )
                    or ""
                ).strip().lower()

                combinado = " ".join(
                    [
                        texto,
                        aria,
                        title,
                        value
                    ]
                )

                # --------------------------------------------
                # ¿ESTÁ DESHABILITADO?
                # --------------------------------------------

                disabled = elemento.get_attribute(
                    "disabled"
                )

                aria_disabled = (
                    elemento.get_attribute(
                        "aria-disabled"
                    )
                    or ""
                ).lower()

                clase = (
                    elemento.get_attribute(
                        "class"
                    )
                    or ""
                ).lower()

                if disabled is not None:
                    continue

                if aria_disabled == "true":
                    continue

                if "disabled" in clase:
                    continue

                # --------------------------------------------
                # BUSCAR CONTROLES FUERTES
                # --------------------------------------------

                for patron in controles_fuertes:

                    if patron in combinado:

                        encontrados.append(
                            {
                                "patron": patron,
                                "texto": combinado[:200]
                            }
                        )

                        break

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error buscando controles de compra: {e}"
        )

    if encontrados:

        log(
            f"🟢 Controles de compra activos: "
            f"{len(encontrados)}"
        )

        for encontrado in encontrados[:5]:

            log(
                "   🟢 "
                f"{encontrado['patron']} → "
                f"{encontrado['texto']}"
            )

        return True

    log(
        "⚪ No se detectaron controles de compra activos."
    )

    return False


# ============================================================
# INDICADORES EXPLÍCITOS DE DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad(driver_actual):

    indicadores = [

        "selecciona tus entradas",
        "selecciona tus boletas",
        "selecciona tus tickets",

        "seleccione sus entradas",
        "seleccione sus boletas",
        "seleccione sus tickets",

        "entradas disponibles",
        "boletas disponibles",
        "tickets disponibles",

        "localidades disponibles",

        "seleccionar localidad",
        "seleccionar asiento",
        "seleccionar asientos",

        "elige tus entradas",
        "elige tus boletas",

        "select your tickets",
        "select your seats",

        "choose your seats",
        "choose your tickets",

        "available tickets",
        "tickets available",

        "available seats",
        "seats available"
    ]

    encontrados = []

    try:

        # ----------------------------------------------------
        # BODY + SOURCE + ATRIBUTOS
        # ----------------------------------------------------

        contenido = obtener_contenido_dom(
            driver_actual
        )

        texto = normalizar_texto(
            contenido
        )

        for indicador in indicadores:

            if indicador in texto:

                encontrados.append(
                    indicador
                )

        # ----------------------------------------------------
        # ELEMENTOS INDIVIDUALES
        # ----------------------------------------------------

        elementos = driver_actual.find_elements(
            By.XPATH,
            "//*"
        )

        for elemento in elementos:

            try:

                valores = [

                    elemento.text,

                    elemento.get_attribute(
                        "aria-label"
                    ),

                    elemento.get_attribute(
                        "title"
                    ),

                    elemento.get_attribute(
                        "value"
                    )
                ]

                combinado = normalizar_texto(
                    " ".join(
                        x or ""
                        for x in valores
                    )
                )

                for indicador in indicadores:

                    if indicador in combinado:

                        if indicador not in encontrados:

                            encontrados.append(
                                indicador
                            )

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error buscando indicadores: {e}"
        )

    if encontrados:

        log(
            "🟢 Indicadores explícitos de disponibilidad:"
        )

        for indicador in encontrados[:10]:

            log(
                f"   🟢 '{indicador}'"
            )

        return True

    log(
        "⚪ No se encontraron indicadores explícitos "
        "de disponibilidad."
    )

    return False


# ============================================================
# CAPTURA DE SCREENSHOT
# ============================================================

def guardar_screenshot(nombre):

    if driver is None:
        return

    try:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        ruta = os.path.join(
            SCREENSHOT_DIR,
            f"{nombre}_{timestamp}.png"
        )

        driver.save_screenshot(
            ruta
        )

        log(
            f"📸 Screenshot guardado: {ruta}"
        )

    except Exception as e:

        log(
            f"⚪ No se pudo guardar screenshot: {e}"
        )


# ============================================================
# ANALIZAR PÁGINA COMPLETA
# ============================================================

def analizar_pagina():

    contenido_principal = obtener_contenido_dom(
        driver
    )

    contenido_shadow = obtener_texto_shadow_dom(
        driver
    )

    contenido_iframes = obtener_contenido_iframes(
        driver
    )

    contenido_total = "\n".join(
        [
            contenido_principal,
            contenido_shadow,
            contenido_iframes
        ]
    )

    return contenido_total


# ============================================================
# DETECTAR DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(url):

    global driver

    log("=" * 70)

    log("🔎 Revisando:")
    log(url)

    if driver is None:

        log(
            "❌ Driver inexistente."
        )

        return "error"

    for intento in range(
        1,
        MAX_REINTENTOS_POR_URL + 1
    ):

        try:

            # ------------------------------------------------
            # CARGAR URL
            # ------------------------------------------------

            log(
                f"🌐 Cargando página "
                f"(intento {intento}/"
                f"{MAX_REINTENTOS_POR_URL})..."
            )

            driver.get(url)

            # ------------------------------------------------
            # ESPERA PARA RENDERIZADO
            # ------------------------------------------------

            time.sleep(4)

            # ------------------------------------------------
            # OBTENER CONTENIDO
            # ------------------------------------------------

            contenido = analizar_pagina()

            log(
                f"📄 Contenido obtenido: "
                f"{len(contenido)} caracteres"
            )

            # ------------------------------------------------
            # 1. DETECCIÓN DIRECTA DE AGOTADO
            # ------------------------------------------------

            contiene_agotado_texto = (
                detectar_agotado_en_texto(
                    contenido
                )
            )

            log(
                "🔬 Contiene palabra "
                f"'agotado': "
                f"{contiene_agotado_texto}"
            )

            # ------------------------------------------------
            # 2. XPATH DIRECTO
            # ------------------------------------------------

            contiene_agotado_xpath = (
                detectar_agotado_xpath(
                    driver
                )
            )

            # ------------------------------------------------
            # 3. ELEMENTOS
            # ------------------------------------------------

            hallazgos_elementos = (
                detectar_agotado_en_elementos(
                    driver
                )
            )

            contiene_agotado_elementos = bool(
                hallazgos_elementos
            )

            if contiene_agotado_elementos:

                log(
                    "🔴 AGOTADO detectado "
                    "en elementos del DOM."
                )

                for patron, texto in (
                    hallazgos_elementos[:5]
                ):

                    log(
                        f"   🔴 {patron} → {texto}"
                    )

            # ------------------------------------------------
            # AGOTADO TIENE PRIORIDAD ABSOLUTA
            # ------------------------------------------------

            if (
                contiene_agotado_texto
                or contiene_agotado_xpath
                or contiene_agotado_elementos
            ):

                log(
                    "🔴🔴🔴 AGOTADO CONFIRMADO 🔴🔴🔴"
                )

                log(
                    "📊 RESULTADO FINAL: AGOTADO"
                )

                return "agotado"

            # ------------------------------------------------
            # 4. CONTROLES DE COMPRA
            # ------------------------------------------------

            hay_controles = (
                detectar_controles_compra(
                    driver
                )
            )

            # ------------------------------------------------
            # 5. INDICADORES
            # ------------------------------------------------

            hay_indicadores = (
                detectar_indicadores_disponibilidad(
                    driver
                )
            )

            # ------------------------------------------------
            # DISPONIBLE
            # ------------------------------------------------

            if (
                hay_controles
                or hay_indicadores
            ):

                log(
                    "🟢 SEÑAL DE DISPONIBILIDAD "
                    "CONFIRMADA."
                )

                log(
                    "📊 RESULTADO FINAL: DISPONIBLE"
                )

                return "disponible"

            # ------------------------------------------------
            # DESCONOCIDO
            # ------------------------------------------------

            log(
                "⚠️ No se encontró una señal clara "
                "de agotado ni disponibilidad."
            )

            log(
                "📊 RESULTADO FINAL: DESCONOCIDO"
            )

            return "desconocido"

        # ----------------------------------------------------
        # TIMEOUT
        # ----------------------------------------------------

        except TimeoutException as e:

            log(
                f"⏱️ Timeout cargando Ticketmaster: {e}"
            )

            if intento < MAX_REINTENTOS_POR_URL:

                time.sleep(3)
                continue

            return "error"

        # ----------------------------------------------------
        # ERROR SELENIUM
        # ----------------------------------------------------

        except WebDriverException as e:

            mensaje = str(e)

            log(
                "❌ Error Selenium:\n"
                f"{mensaje[:1000]}"
            )

            guardar_screenshot(
                "selenium_error"
            )

            if intento < MAX_REINTENTOS_POR_URL:

                time.sleep(3)
                continue

            return "error"

        # ----------------------------------------------------
        # ERROR GENERAL
        # ----------------------------------------------------

        except Exception as e:

            log(
                "❌ Error inesperado:\n"
                f"{traceback.format_exc()}"
            )

            if intento < MAX_REINTENTOS_POR_URL:

                time.sleep(3)
                continue

            return "error"

    return "error"


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(url, nuevo_estado):

    global estado_anterior
    global ultima_alerta_disponible

    anterior = estado_anterior.get(
        url
    )

    log(
        f"📊 {url} → {nuevo_estado}"
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if nuevo_estado == "error":

        estadisticas[
            "revisiones_error"
        ] += 1

        # IMPORTANTE:
        # NO cambiamos el estado anterior.
        #
        # Así, un fallo de Chrome no se interpreta
        # como agotado o disponible.

        enviar_error_telegram(
            "No fue posible revisar:\n"
            f"{url}\n\n"
            "El bot conservará el último estado conocido "
            "y seguirá intentando automáticamente."
        )

        guardar_estado()

        return

    # --------------------------------------------------------
    # REVISIÓN CORRECTA
    # --------------------------------------------------------

    estadisticas[
        "revisiones_correctas"
    ] += 1

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if nuevo_estado == "disponible":

        estadisticas[
            "detecciones_disponible"
        ] += 1

        ahora = datetime.now()

        debe_alertar = False

        # Primera detección
        if anterior != "disponible":

            debe_alertar = True

        # Repetición cada 30 segundos
        elif REPETIR_DISPONIBILIDAD:

            ultima = ultima_alerta_disponible.get(
                url
            )

            if ultima is None:

                debe_alertar = True

            else:

                diferencia = (
                    ahora - ultima
                ).total_seconds()

                if diferencia >= INTERVALO_REVISION:

                    debe_alertar = True

        if debe_alertar:

            log(
                "🚨🚨🚨 DISPONIBILIDAD DETECTADA 🚨🚨🚨"
            )

            mensaje = (
                "🚨🚨🚨 ¡BOLETAS DISPONIBLES! 🚨🚨🚨\n\n"
                "🎫 BTS WORLD TOUR\n"
                f"{url}\n\n"
                "🟢 Ticketmaster muestra señales "
                "de disponibilidad.\n\n"
                "⚡ REVISA AHORA."
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponible[
                url
            ] = ahora

        estado_anterior[
            url
        ] = "disponible"

    # --------------------------------------------------------
    # AGOTADO
    # --------------------------------------------------------

    elif nuevo_estado == "agotado":

        estadisticas[
            "detecciones_agotado"
        ] += 1

        if anterior != "agotado":

            log(
                "🔴 AGOTADO detectado."
            )

            enviar_telegram(
                "🔴 BTS TICKETMASTER\n\n"
                "⛔ ENTRADAS AGOTADAS\n\n"
                f"{url}"
            )

        estado_anterior[
            url
        ] = "agotado"

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    elif nuevo_estado == "desconocido":

        estadisticas[
            "detecciones_desconocido"
        ] += 1

        if anterior != "desconocido":

            log(
                "⚠️ Estado desconocido."
            )

            enviar_telegram(
                "⚠️ BTS TICKETMASTER\n\n"
                "❓ No se pudo determinar claramente "
                "la disponibilidad.\n\n"
                f"{url}"
            )

        estado_anterior[
            url
        ] = "desconocido"

    guardar_estado()


# ============================================================
# HEARTBEAT
# ============================================================

def enviar_heartbeat():

    global ultimo_heartbeat

    ahora = datetime.now()

    if (
        ahora - ultimo_heartbeat
    ).total_seconds() < HEARTBEAT_HORAS * 3600:

        return

    uptime = ahora - inicio_bot

    horas = int(
        uptime.total_seconds() // 3600
    )

    minutos = int(
        (
            uptime.total_seconds() % 3600
        ) // 60
    )

    mensaje = (
        "💓 BOT BTS — HEARTBEAT 24/7\n\n"

        "🟢 Bot operativo.\n\n"

        f"⏱️ Tiempo activo: "
        f"{horas} h {minutos} min\n\n"

        "📊 ESTADÍSTICAS\n"
        f"🔎 Revisiones totales: "
        f"{estadisticas['revisiones_totales']}\n"

        f"✅ Revisiones correctas: "
        f"{estadisticas['revisiones_correctas']}\n"

        f"❌ Revisiones con error: "
        f"{estadisticas['revisiones_error']}\n\n"

        f"🔴 Detecciones agotado: "
        f"{estadisticas['detecciones_agotado']}\n"

        f"🟢 Detecciones disponible: "
        f"{estadisticas['detecciones_disponible']}\n"

        f"⚪ Detecciones desconocido: "
        f"{estadisticas['detecciones_desconocido']}\n\n"

        f"🔄 Recuperaciones Chrome: "
        f"{estadisticas['recuperaciones_chrome']}\n\n"

        "🎫 URLs monitoreadas: "
        f"{len(URLS)}"
    )

    enviar_telegram(
        mensaje
    )

    ultimo_heartbeat = ahora

    guardar_estado()

    log(
        "💓 Heartbeat enviado."
    )


# ============================================================
# WATCHDOG CHROME
# ============================================================

def watchdog_chrome():

    global ultima_revision_chrome

    ahora = datetime.now()

    if (
        ahora - ultima_revision_chrome
    ).total_seconds() < WATCHDOG_SEGUNDOS:

        return True

    ultima_revision_chrome = ahora

    if driver is None:

        log(
            "⚠️ Watchdog: Chrome no existe."
        )

        return recuperar_chrome()

    try:

        # Una operación sencilla para verificar
        # que la sesión continúa viva.
        _ = driver.current_url

        return True

    except Exception as e:

        log(
            f"⚠️ Watchdog detectó Chrome caído: {e}"
        )

        return recuperar_chrome()


# ============================================================
# INICIALIZAR CHROME
# ============================================================

def inicializar_chrome():

    global driver

    log("🌐 Preparando Chromium...")

    driver = crear_driver()

    if driver is None:

        log(
            "❌ No fue posible iniciar Chrome."
        )

        return False

    try:

        log(
            "🌐 Probando Ticketmaster..."
        )

        driver.get(
            "https://www.ticketmaster.co/"
        )

        time.sleep(3)

        texto = obtener_body_text(
            driver
        )

        log(
            f"📄 Ticketmaster: "
            f"{texto[:300]}"
        )

        log(
            "✅ Chrome/Chromium operativo."
        )

        return True

    except Exception as e:

        log(
            f"❌ Prueba inicial fallida: {e}"
        )

        try:
            driver.quit()
        except Exception:
            pass

        driver = None

        return False


# ============================================================
# BUCLE PRINCIPAL
# ============================================================

def ejecutar_bot():

    global inicio_bot

    inicio_bot = datetime.now()

    log("=" * 60)
    log("🚀 BOT BTS TICKETMASTER 24/7")
    log("=" * 60)

    # --------------------------------------------------------
    # CONFIGURACIÓN
    # --------------------------------------------------------

    if not TOKEN:

        log(
            "❌ FALTA TOKEN."
        )

        return

    if not CHAT_ID:

        log(
            "❌ FALTA CHAT_ID."
        )

        return

    log(
        f"🎫 URLs monitoreadas: {len(URLS)}"
    )

    # --------------------------------------------------------
    # ESTADO
    # --------------------------------------------------------

    cargar_estado()

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if not probar_telegram():

        log(
            "⚠️ Telegram no pudo probarse, "
            "pero el bot continuará."
        )

    # --------------------------------------------------------
    # CHROME
    # --------------------------------------------------------

    while driver is None:

        if inicializar_chrome():

            break

        log(
            "🔄 Reintentando Chrome en 10 segundos..."
        )

        time.sleep(10)

    log(
        "✅ Chrome listo."
    )

    # --------------------------------------------------------
    # BUCLE 24/7
    # --------------------------------------------------------

    while True:

        inicio_ciclo = time.time()

        try:

            watchdog_chrome()

            # ------------------------------------------------
            # SI CHROME SIGUE CAÍDO
            # ------------------------------------------------

            if driver is None:

                log(
                    "⚠️ Chrome no disponible. "
                    "Intentando recuperar..."
                )

                recuperar_chrome()

                time.sleep(5)

                continue

            # ------------------------------------------------
            # REVISAR CADA URL
            # ------------------------------------------------

            for url in URLS:

                estadisticas[
                    "revisiones_totales"
                ] += 1

                resultado = detectar_disponibilidad(
                    url
                )

                procesar_resultado(
                    url,
                    resultado
                )

                # Pequeña pausa entre URLs
                time.sleep(2)

            # ------------------------------------------------
            # HEARTBEAT
            # ------------------------------------------------

            enviar_heartbeat()

            # ------------------------------------------------
            # ESPERA HASTA SIGUIENTE CICLO
            # ------------------------------------------------

            duracion = (
                time.time()
                - inicio_ciclo
            )

            espera = max(
                1,
                INTERVALO_REVISION - duracion
            )

            log(
                f"😴 Próxima revisión en "
                f"{espera:.1f} segundos."
            )

            time.sleep(
                espera
            )

        except KeyboardInterrupt:

            log(
                "🛑 Bot detenido manualmente."
            )

            break

        except Exception as e:

            log(
                "🔥 ERROR CRÍTICO EN BUCLE PRINCIPAL:\n"
                f"{traceback.format_exc()}"
            )

            enviar_error_telegram(
                "Error crítico en el bucle principal.\n\n"
                f"{str(e)[:1000]}\n\n"
                "El bot intentará continuar automáticamente."
            )

            # Intentar recuperar Chrome
            try:

                recuperar_chrome()

            except Exception:

                pass

            time.sleep(10)


# ============================================================
# CIERRE LIMPIO
# ============================================================

def cerrar():

    global driver

    log(
        "🧹 Cerrando recursos..."
    )

    try:

        guardar_estado()

    except Exception:
        pass

    try:

        if driver is not None:

            driver.quit()

    except Exception:
        pass

    driver = None

    log(
        "👋 Bot finalizado."
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        ejecutar_bot()

    except KeyboardInterrupt:

        log(
            "🛑 Interrupción manual."
        )

    except Exception:

        log(
            "🔥 ERROR FATAL:\n"
            f"{traceback.format_exc()}"
        )

    finally:

        cerrar()
