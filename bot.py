import os
import re
import json
import time
import traceback
import requests

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException
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

INTERVALO_REVISION = 30
HEARTBEAT_HORAS = 5

PAGE_LOAD_TIMEOUT = 45
SCRIPT_TIMEOUT = 30

MAX_REINTENTOS = 2
MAX_ERRORES_TELEGRAM = 10

STATE_FILE = "/tmp/ticketmaster_estado.json"
SCREENSHOT_DIR = "/tmp/ticketmaster_screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ============================================================
# VARIABLES
# ============================================================

driver = None

estado_anterior = {}

ultima_alerta_disponible = {}

ultimo_heartbeat = datetime.now()

inicio_bot = datetime.now()

errores_telegram_en_racha = 0

estadisticas = {
    "revisiones_totales": 0,
    "revisiones_correctas": 0,
    "revisiones_error": 0,
    "detecciones_agotado": 0,
    "detecciones_disponible": 0,
    "detecciones_desconocido": 0,
    "recuperaciones_chrome": 0
}


# ============================================================
# LOG
# ============================================================

def log(mensaje):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ahora}] {mensaje}", flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje, silencioso=False):

    global errores_telegram_en_racha

    if not TOKEN or not CHAT_ID:
        log("❌ TOKEN o CHAT_ID no configurados.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    datos = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "disable_web_page_preview": True
    }

    try:

        respuesta = requests.post(
            url,
            json=datos,
            timeout=20
        )

        if respuesta.status_code == 200:

            errores_telegram_en_racha = 0
            return True

        if not silencioso:
            log(
                f"❌ Telegram HTTP {respuesta.status_code}: "
                f"{respuesta.text[:300]}"
            )

        return False

    except Exception as e:

        if not silencioso:
            log(f"❌ Error Telegram: {e}")

        return False


def enviar_error_telegram(mensaje):

    global errores_telegram_en_racha

    if errores_telegram_en_racha >= MAX_ERRORES_TELEGRAM:

        log(
            "🔇 Se alcanzó el máximo de "
            f"{MAX_ERRORES_TELEGRAM} errores Telegram."
        )

        return

    if enviar_telegram(
        "⚠️ ERROR BOT BTS\n\n" + mensaje,
        silencioso=True
    ):

        errores_telegram_en_racha += 1


# ============================================================
# ESTADO
# ============================================================

def guardar_estado():

    try:

        datos = {
            "estado_anterior": estado_anterior,
            "ultima_alerta_disponible": {
                url: fecha.isoformat()
                for url, fecha
                in ultima_alerta_disponible.items()
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

        log(f"⚠️ Error guardando estado: {e}")


def cargar_estado():

    global estado_anterior
    global ultima_alerta_disponible
    global estadisticas

    if not os.path.exists(STATE_FILE):
        log("ℹ️ No existe estado anterior.")
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

        for url, fecha in fechas.items():

            try:

                ultima_alerta_disponible[url] = (
                    datetime.fromisoformat(fecha)
                )

            except Exception:
                pass

        estadisticas_guardadas = datos.get(
            "estadisticas",
            {}
        )

        for clave in estadisticas:

            if clave in estadisticas_guardadas:

                estadisticas[clave] = (
                    estadisticas_guardadas[clave]
                )

        log("💾 Estado anterior cargado.")

    except Exception as e:

        log(f"⚠️ Error cargando estado: {e}")


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    log("🚀 Iniciando Chrome...")

    options = Options()

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--mute-audio")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=es-CO")

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )

    options.page_load_strategy = "eager"

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-logging"]
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

    except Exception:

        log(
            "❌ Error creando Selenium:\n"
            + traceback.format_exc()
        )

        return None


# ============================================================
# INICIALIZAR CHROME
# ============================================================

def inicializar_chrome():

    global driver

    driver = crear_driver()

    if driver is None:
        return False

    try:

        log("🌐 Probando Ticketmaster...")

        driver.get(
            "https://www.ticketmaster.co/"
        )

        time.sleep(3)

        texto = obtener_body_text()

        log(
            f"📄 Ticketmaster: "
            f"{texto[:300]}"
        )

        log("✅ Chrome/Chromium operativo.")
        log("✅ Chrome listo.")

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
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global driver

    log("🔄 Recuperando Chrome...")

    try:

        if driver is not None:
            driver.quit()

    except Exception:
        pass

    driver = None

    estadisticas["recuperaciones_chrome"] += 1

    time.sleep(3)

    if inicializar_chrome():

        log("✅ Chrome recuperado correctamente.")

        return True

    log("❌ No se pudo recuperar Chrome.")

    return False


# ============================================================
# BODY TEXT
# ============================================================

def obtener_body_text():

    try:

        body = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        return body.text or ""

    except Exception:

        return ""


# ============================================================
# CONTENIDO DEL DOM
# ============================================================

def obtener_contenido_dom():

    partes = []

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    try:

        texto = obtener_body_text()

        if texto:
            partes.append(texto)

    except Exception:
        pass

    # --------------------------------------------------------
    # PAGE SOURCE
    # --------------------------------------------------------

    try:

        source = driver.page_source

        if source:
            partes.append(source)

    except Exception:
        pass

    # --------------------------------------------------------
    # ELEMENTOS
    # --------------------------------------------------------

    try:

        elementos = driver.find_elements(
            By.XPATH,
            "//*"
        )

        for elemento in elementos:

            try:

                valores = [
                    elemento.text,
                    elemento.get_attribute("aria-label"),
                    elemento.get_attribute("title"),
                    elemento.get_attribute("value"),
                    elemento.get_attribute("data-testid"),
                    elemento.get_attribute("data-label"),
                    elemento.get_attribute("data-status")
                ]

                for valor in valores:

                    if valor:
                        partes.append(valor)

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error inspeccionando DOM: {e}"
        )

    return "\n".join(partes)


# ============================================================
# SHADOW DOM
# ============================================================

def obtener_shadow_dom():

    javascript = """
    function recorrer(elemento, salida) {

        if (!elemento) {
            return;
        }

        try {

            if (elemento.nodeType === Node.TEXT_NODE) {

                if (elemento.textContent.trim()) {
                    salida.push(elemento.textContent);
                }

                return;
            }

            if (
                elemento.nodeType === Node.ELEMENT_NODE
            ) {

                if (elemento.innerText) {
                    salida.push(elemento.innerText);
                }

                const aria =
                    elemento.getAttribute("aria-label");

                if (aria) {
                    salida.push(aria);
                }

                const title =
                    elemento.getAttribute("title");

                if (title) {
                    salida.push(title);
                }

                if (elemento.shadowRoot) {

                    recorrer(
                        elemento.shadowRoot,
                        salida
                    );
                }

                for (
                    const hijo of elemento.children
                ) {

                    recorrer(
                        hijo,
                        salida
                    );
                }
            }

        } catch (e) {
        }
    }

    const salida = [];

    recorrer(
        document.documentElement,
        salida
    );

    return salida.join("\\n");
    """

    try:

        resultado = driver.execute_script(
            javascript
        )

        return resultado or ""

    except Exception as e:

        log(
            f"⚪ Shadow DOM no disponible: {e}"
        )

        return ""


# ============================================================
# IFRAME
# ============================================================

def obtener_iframes():

    contenidos = []

    try:

        cantidad = len(
            driver.find_elements(
                By.TAG_NAME,
                "iframe"
            )
        )

        if cantidad == 0:
            return ""

        log(
            f"🧩 Iframes encontrados: {cantidad}"
        )

        for indice in range(cantidad):

            try:

                driver.switch_to.default_content()

                iframes = driver.find_elements(
                    By.TAG_NAME,
                    "iframe"
                )

                if indice >= len(iframes):
                    continue

                driver.switch_to.frame(
                    iframes[indice]
                )

                texto = obtener_body_text()

                if texto:
                    contenidos.append(texto)

                try:

                    source = driver.page_source

                    if source:
                        contenidos.append(source)

                except Exception:
                    pass

            except Exception as e:

                log(
                    f"⚪ No se pudo revisar iframe "
                    f"{indice}: {e}"
                )

            finally:

                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

    except Exception as e:

        log(
            f"⚠️ Error buscando iframes: {e}"
        )

    return "\n".join(contenidos)


# ============================================================
# NORMALIZAR
# ============================================================

def normalizar(texto):

    if not texto:
        return ""

    texto = texto.lower()

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# DETECTAR AGOTADO EN TEXTO
# ============================================================

def detectar_agotado_en_texto(texto):

    texto = normalizar(texto)

    patrones = [

        "agotado",
        "agotada",
        "agotados",
        "agotadas",

        "entradas agotadas",
        "boletas agotadas",
        "tickets agotados",

        "evento agotado",

        "no hay entradas",
        "no hay boletas",
        "no hay tickets",

        "entradas no disponibles",
        "boletas no disponibles",
        "tickets no disponibles",

        "sin entradas disponibles",
        "sin boletas disponibles",
        "sin tickets disponibles",

        "sold out",
        "sold-out",

        "no tickets available",
        "tickets unavailable",
        "tickets are currently unavailable",
        "tickets not available",

        "no seats available",
        "seats unavailable",
        "no seats currently available",

        "currently unavailable"
    ]

    for patron in patrones:

        if patron in texto:
            return True

    return False


# ============================================================
# DETECTAR AGOTADO EN ELEMENTOS
# ============================================================

def detectar_agotado_elementos():

    patrones = [
        "agotado",
        "agotada",
        "agotados",
        "agotadas",
        "sold out",
        "sold-out"
    ]

    try:

        elementos = driver.find_elements(
            By.XPATH,
            "//*"
        )

        for elemento in elementos:

            try:

                valores = [
                    elemento.text,
                    elemento.get_attribute("aria-label"),
                    elemento.get_attribute("title"),
                    elemento.get_attribute("value"),
                    elemento.get_attribute("data-testid")
                ]

                for valor in valores:

                    texto = normalizar(
                        valor or ""
                    )

                    for patron in patrones:

                        if patron in texto:

                            log(
                                "🔴 AGOTADO encontrado "
                                f"en elemento: "
                                f"'{texto[:200]}'"
                            )

                            return True

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error detectando agotado "
            f"en elementos: {e}"
        )

    return False


# ============================================================
# DETECTAR AGOTADO CON XPATH
# ============================================================

def detectar_agotado_xpath():

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

    try:

        elementos = driver.find_elements(
            By.XPATH,
            xpath
        )

        if elementos:

            log(
                "🔴 XPath encontró elementos "
                "relacionados con AGOTADO."
            )

            return True

    except Exception as e:

        log(
            f"⚪ XPath agotado no disponible: {e}"
        )

    return False


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra():

    patrones = [

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

    encontrados = []

    try:

        elementos = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button'], input, "
            "[data-testid], [aria-label]"
        )

        for elemento in elementos:

            try:

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

                texto = normalizar(
                    " ".join(
                        x or ""
                        for x in valores
                    )
                )

                for patron in patrones:

                    if patron in texto:

                        encontrados.append(
                            patron
                        )

                        break

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error controles compra: {e}"
        )

    if encontrados:

        log(
            "🟢 Controles de compra activos:"
        )

        for patron in encontrados[:5]:

            log(
                f"   🟢 {patron}"
            )

        return True

    log(
        "⚪ No se detectaron controles "
        "de compra activos."
    )

    return False


# ============================================================
# INDICADORES DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad():

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

    try:

        contenido = obtener_contenido_dom()

        contenido += "\n"
        contenido += obtener_shadow_dom()

        contenido += "\n"
        contenido += obtener_iframes()

        texto = normalizar(
            contenido
        )

        encontrados = []

        for indicador in indicadores:

            if indicador in texto:

                encontrados.append(
                    indicador
                )

        if encontrados:

            log(
                "🟢 Indicadores explícitos "
                "de disponibilidad:"
            )

            for indicador in encontrados[:10]:

                log(
                    f"   🟢 {indicador}"
                )

            return True

    except Exception as e:

        log(
            f"⚠️ Error indicadores "
            f"disponibilidad: {e}"
        )

    log(
        "⚪ No se encontraron indicadores "
        "explícitos de disponibilidad."
    )

    return False


# ============================================================
# SCREENSHOT
# ============================================================

def guardar_screenshot(nombre):

    if driver is None:
        return

    try:

        fecha = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        ruta = os.path.join(
            SCREENSHOT_DIR,
            f"{nombre}_{fecha}.png"
        )

        driver.save_screenshot(
            ruta
        )

        log(
            f"📸 Screenshot: {ruta}"
        )

    except Exception as e:

        log(
            f"⚪ No se pudo guardar screenshot: {e}"
        )


# ============================================================
# DETECCIÓN PRINCIPAL
# ============================================================

def detectar_disponibilidad(url):

    log("=" * 65)

    log("🔎 Revisando:")
    log(url)

    if driver is None:

        log("❌ Driver inexistente.")

        return "error"

    for intento in range(
        1,
        MAX_REINTENTOS + 1
    ):

        try:

            log(
                f"🌐 Cargando página "
                f"(intento {intento}/{MAX_REINTENTOS})..."
            )

            driver.switch_to.default_content()

            driver.get(url)

            time.sleep(4)

            # ------------------------------------------------
            # CONTENIDO COMPLETO
            # ------------------------------------------------

            contenido = obtener_contenido_dom()

            contenido += "\n"
            contenido += obtener_shadow_dom()

            contenido += "\n"
            contenido += obtener_iframes()

            log(
                f"📄 Contenido obtenido: "
                f"{len(contenido)} caracteres"
            )

            # ------------------------------------------------
            # AGOTADO - MÉTODO 1
            # ------------------------------------------------

            agotado_texto = (
                detectar_agotado_en_texto(
                    contenido
                )
            )

            log(
                "🔬 Contiene palabra "
                f"'agotado': {agotado_texto}"
            )

            # ------------------------------------------------
            # AGOTADO - MÉTODO 2
            # ------------------------------------------------

            agotado_elementos = (
                detectar_agotado_elementos()
            )

            # ------------------------------------------------
            # AGOTADO - MÉTODO 3
            # ------------------------------------------------

            agotado_xpath = (
                detectar_agotado_xpath()
            )

            # ------------------------------------------------
            # PRIORIDAD ABSOLUTA
            # ------------------------------------------------

            if (
                agotado_texto
                or agotado_elementos
                or agotado_xpath
            ):

                log(
                    "🔴🔴🔴 AGOTADO CONFIRMADO 🔴🔴🔴"
                )

                log(
                    "📊 RESULTADO FINAL: AGOTADO"
                )

                return "agotado"

            # ------------------------------------------------
            # DISPONIBILIDAD
            # ------------------------------------------------

            controles = (
                detectar_controles_compra()
            )

            indicadores = (
                detectar_indicadores_disponibilidad()
            )

            if controles or indicadores:

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

        except TimeoutException as e:

            log(
                f"⏱️ Timeout: {e}"
            )

            if intento < MAX_REINTENTOS:

                time.sleep(3)
                continue

            return "error"

        except WebDriverException as e:

            log(
                f"❌ Selenium: {str(e)[:1000]}"
            )

            guardar_screenshot(
                "selenium_error"
            )

            if intento < MAX_REINTENTOS:

                time.sleep(3)
                continue

            return "error"

        except Exception as e:

            log(
                "❌ Error inesperado:\n"
                + traceback.format_exc()
            )

            if intento < MAX_REINTENTOS:

                time.sleep(3)
                continue

            return "error"

    return "error"


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    url,
    nuevo_estado
):

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

        enviar_error_telegram(
            "No fue posible revisar:\n"
            f"{url}\n\n"
            "Se conservará el último estado conocido."
        )

        guardar_estado()

        return

    # --------------------------------------------------------
    # CORRECTA
    # --------------------------------------------------------

    estadisticas[
        "revisiones_correctas"
    ] += 1

    # --------------------------------------------------------
    # AGOTADO
    # --------------------------------------------------------

    if nuevo_estado == "agotado":

        estadisticas[
            "detecciones_agotado"
        ] += 1

        if anterior != "agotado":

            enviar_telegram(
                "🔴 BTS TICKETMASTER\n\n"
                "⛔ ENTRADAS AGOTADAS\n\n"
                f"{url}"
            )

        estado_anterior[
            url
        ] = "agotado"

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    elif nuevo_estado == "disponible":

        estadisticas[
            "detecciones_disponible"
        ] += 1

        ahora = datetime.now()

        ultima = (
            ultima_alerta_disponible.get(
                url
            )
        )

        enviar = False

        if anterior != "disponible":

            enviar = True

        elif ultima is None:

            enviar = True

        else:

            segundos = (
                ahora - ultima
            ).total_seconds()

            if segundos >= INTERVALO_REVISION:

                enviar = True

        if enviar:

            log(
                "🚨🚨🚨 DISPONIBILIDAD DETECTADA 🚨🚨🚨"
            )

            enviar_telegram(
                "🚨🚨🚨 ¡BOLETAS DISPONIBLES! 🚨🚨🚨\n\n"
                "🎫 BTS WORLD TOUR\n\n"
                f"{url}\n\n"
                "🟢 Ticketmaster muestra señales "
                "de disponibilidad.\n\n"
                "⚡ REVISA AHORA."
            )

            ultima_alerta_disponible[
                url
            ] = ahora

        estado_anterior[
            url
        ] = "disponible"

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    elif nuevo_estado == "desconocido":

        estadisticas[
            "detecciones_desconocido"
        ] += 1

        if anterior != "desconocido":

            enviar_telegram(
                "⚠️ BTS TICKETMASTER\n\n"
                "❓ Estado desconocido.\n\n"
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

    segundos = (
        ahora - ultimo_heartbeat
    ).total_seconds()

    if segundos < HEARTBEAT_HORAS * 3600:

        return

    uptime = (
        ahora - inicio_bot
    )

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

        f"🎫 URLs monitoreadas: "
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
# WATCHDOG
# ============================================================

def verificar_chrome():

    global driver

    if driver is None:
        return recuperar_chrome()

    try:

        _ = driver.current_url

        return True

    except Exception as e:

        log(
            f"⚠️ Chrome dejó de responder: {e}"
        )

        return recuperar_chrome()


# ============================================================
# BOT PRINCIPAL
# ============================================================

def ejecutar_bot():

    global inicio_bot

    inicio_bot = datetime.now()

    log("=" * 60)
    log("🚀 BOT BTS TICKETMASTER 24/7")
    log("=" * 60)

    if not TOKEN:

        log("❌ TOKEN no encontrado.")
        return

    if not CHAT_ID:

        log("❌ CHAT_ID no encontrado.")
        return

    log("✅ TOKEN encontrado.")
    log("✅ CHAT_ID encontrado.")

    log(
        f"🎫 URLs monitoreadas: {len(URLS)}"
    )

    cargar_estado()

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if enviar_telegram(
        "🚀 Bot BTS Ticketmaster iniciado.\n"
        "🟢 Monitoreo 24/7 activo.",
        silencioso=True
    ):

        log("✅ Telegram funcionando.")

    else:

        log(
            "⚠️ Telegram no respondió."
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

    # --------------------------------------------------------
    # BUCLE
    # --------------------------------------------------------

    while True:

        inicio_ciclo = time.time()

        try:

            verificar_chrome()

            if driver is None:

                time.sleep(5)
                continue

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

                time.sleep(2)

            enviar_heartbeat()

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
                "🔥 ERROR EN BUCLE PRINCIPAL:\n"
                + traceback.format_exc()
            )

            enviar_error_telegram(
                "Error en el bucle principal:\n"
                f"{str(e)[:1000]}"
            )

            try:
                recuperar_chrome()
            except Exception:
                pass

            time.sleep(10)


# ============================================================
# CIERRE
# ============================================================

def cerrar():

    global driver

    log("🧹 Cerrando recursos...")

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

    log("👋 Bot finalizado.")


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
            + traceback.format_exc()
        )

    finally:

        cerrar()
