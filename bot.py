import os
import sys
import time
import random
import json
import signal
import traceback

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
    NoSuchWindowException,
    JavascriptException,
    StaleElementReferenceException
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


URLS = [
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre"
]


# ------------------------------------------------------------
# TIEMPOS
# ------------------------------------------------------------

MIN_ESPERA = 15
MAX_ESPERA = 25

HEARTBEAT_INTERVAL = 5 * 60 * 60

# Mientras haya disponibilidad, vuelve a avisar cada 30 segundos.
COOLDOWN_DISPONIBILIDAD = 30

PAGE_LOAD_TIMEOUT = 30
SCRIPT_TIMEOUT = 25

ESPERA_DESPUES_CARGA_MIN = 2
ESPERA_DESPUES_CARGA_MAX = 5


# ------------------------------------------------------------
# RECUPERACIÓN
# ------------------------------------------------------------

FALLOS_ANTES_REINICIO = 2

INTENTOS_RECUPERACION = 4

ESPERA_RECUPERACION_BASE = 3

MAX_ERRORES_TELEGRAM = 10

BACKOFF_MIN = 15
BACKOFF_MAX = 120


# ------------------------------------------------------------
# ARCHIVOS TEMPORALES
# ------------------------------------------------------------

ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"

CARPETA_DIAGNOSTICO = "/tmp/ticketmaster_diagnostico"

MAX_CAPTURAS = 3


# ============================================================
# VARIABLES GLOBALES
# ============================================================

driver = None

inicio_bot = time.time()

ultima_heartbeat = time.time()

errores_telegram_enviados = 0

fallos_consecutivos = 0

nivel_backoff = 0

recuperaciones_chrome = 0

revisiones_totales = 0

revisiones_correctas = 0

revisiones_error = 0

detecciones_agotado = 0

detecciones_disponible = 0

ultima_revision = None


estado_anterior = {
    url: None
    for url in URLS
}


ultima_alerta_disponibilidad = {
    url: 0
    for url in URLS
}


# ============================================================
# LOG
# ============================================================

def log(mensaje):
    print(mensaje)
    sys.stdout.flush()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(mensaje):

    if not TOKEN:
        log("❌ TOKEN no configurado.")
        return False

    if not CHAT_ID:
        log("❌ CHAT_ID no configurado.")
        return False

    try:

        respuesta = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": mensaje
            },
            timeout=15
        )

        if respuesta.status_code == 200:
            return True

        log(
            f"⚠️ Telegram HTTP {respuesta.status_code}: "
            f"{respuesta.text[:500]}"
        )

        return False

    except requests.RequestException as e:

        log(f"⚠️ Error de conexión con Telegram: {e}")

        return False

    except Exception as e:

        log(f"⚠️ Error Telegram: {e}")

        return False


# ============================================================
# ERRORES CONTROLADOS
# ============================================================

def enviar_error_controlado(mensaje):

    global errores_telegram_enviados

    if errores_telegram_enviados >= MAX_ERRORES_TELEGRAM:

        log(
            "🔇 Límite de errores Telegram alcanzado. "
            "Los siguientes errores solamente se registrarán en Railway."
        )

        return

    errores_telegram_enviados += 1

    mensaje_final = (
        "⚠️ ERROR DEL BOT\n\n"
        f"{mensaje}\n\n"
        f"Error {errores_telegram_enviados}/{MAX_ERRORES_TELEGRAM}"
    )

    send_telegram(mensaje_final)


# ============================================================
# RECUPERACIÓN DE ESTADO
# ============================================================

def registrar_recuperacion():

    global errores_telegram_enviados
    global fallos_consecutivos
    global nivel_backoff

    if fallos_consecutivos > 0:

        log("✅ Servicio recuperado correctamente.")

    errores_telegram_enviados = 0

    fallos_consecutivos = 0

    nivel_backoff = 0


# ============================================================
# FORMATO DE TIEMPO
# ============================================================

def formato_duracion(segundos):

    segundos = int(segundos)

    dias = segundos // 86400

    segundos %= 86400

    horas = segundos // 3600

    segundos %= 3600

    minutos = segundos // 60

    segundos %= 60

    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"

    if horas > 0:
        return f"{horas}h {minutos}m"

    if minutos > 0:
        return f"{minutos}m {segundos}s"

    return f"{segundos}s"


# ============================================================
# HEARTBEAT
# ============================================================

def comprobar_heartbeat():

    global ultima_heartbeat

    ahora = time.time()

    if ahora - ultima_heartbeat >= HEARTBEAT_INTERVAL:

        uptime = formato_duracion(
            ahora - inicio_bot
        )

        mensaje = (
            "💓 BOT ACTIVO\n\n"

            f"⏱️ Tiempo activo: {uptime}\n\n"

            f"🔎 Revisiones totales: {revisiones_totales}\n"

            f"✅ Revisiones correctas: {revisiones_correctas}\n"

            f"⚠️ Revisiones con error: {revisiones_error}\n\n"

            f"❌ Veces detectado AGOTADO: "
            f"{detecciones_agotado}\n"

            f"🚨 Veces detectado DISPONIBLE: "
            f"{detecciones_disponible}\n\n"

            f"♻️ Recuperaciones Chrome: "
            f"{recuperaciones_chrome}\n\n"

            "🎫 Ticketmaster monitoreado\n"
            "📡 Telegram conectado\n"
            "🟢 Monitoreo 24/7 activo"
        )

        if send_telegram(mensaje):

            log("💓 Heartbeat enviado.")

        ultima_heartbeat = ahora


# ============================================================
# ALERTAS
# ============================================================

def alerta_disponibilidad(url):

    mensaje = (
        "🚨🚨🚨 TICKET DISPONIBLE 🚨🚨🚨\n\n"

        "🎫 POSIBLE DISPONIBILIDAD DETECTADA\n\n"

        f"{url}\n\n"

        "⚡ REVISA TICKETMASTER INMEDIATAMENTE.\n\n"

        "⚠️ La disponibilidad puede ser temporal."
    )

    if send_telegram(mensaje):

        log("🚨 ALERTA DE DISPONIBILIDAD ENVIADA.")


def alerta_agotado(url):

    mensaje = (
        "❌ ENTRADAS AGOTADAS\n\n"
        f"{url}"
    )

    if send_telegram(mensaje):

        log("❌ Aviso de agotado enviado.")


def alerta_desconocido(url):

    mensaje = (
        "⚠️ ESTADO NO CONFIRMADO\n\n"

        f"{url}\n\n"

        "El bot no pudo confirmar disponibilidad "
        "ni agotado.\n\n"

        "🔎 El monitoreo continuará automáticamente."
    )

    if send_telegram(mensaje):

        log("⚠️ Aviso de estado desconocido enviado.")


# ============================================================
# ESTADO EN DISCO
# ============================================================

def cargar_estado():

    global estado_anterior

    try:

        if not os.path.exists(ARCHIVO_ESTADO):

            return

        with open(
            ARCHIVO_ESTADO,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

        for url in URLS:

            estado = datos.get(url)

            if estado in (
                "disponible",
                "agotado",
                "desconocido"
            ):

                estado_anterior[url] = estado

        log("💾 Estado anterior cargado.")

    except Exception as e:

        log(
            f"⚠️ No se pudo cargar estado: {e}"
        )


def guardar_estado():

    try:

        with open(
            ARCHIVO_ESTADO,
            "w",
            encoding="utf-8"
        ) as archivo:

            json.dump(
                estado_anterior,
                archivo,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        log(
            f"⚠️ No se pudo guardar estado: {e}"
        )


# ============================================================
# DIAGNÓSTICO
# ============================================================

def preparar_diagnostico():

    try:

        os.makedirs(
            CARPETA_DIAGNOSTICO,
            exist_ok=True
        )

    except Exception as e:

        log(
            f"⚠️ No se pudo crear diagnóstico: {e}"
        )


def limpiar_capturas():

    try:

        archivos = []

        for nombre in os.listdir(
            CARPETA_DIAGNOSTICO
        ):

            ruta = os.path.join(
                CARPETA_DIAGNOSTICO,
                nombre
            )

            if os.path.isfile(ruta):

                archivos.append(
                    (
                        os.path.getmtime(ruta),
                        ruta
                    )
                )

        archivos.sort(
            key=lambda x: x[0],
            reverse=True
        )

        for _, ruta in archivos[MAX_CAPTURAS:]:

            try:
                os.remove(ruta)
            except Exception:
                pass

    except Exception:
        pass


def guardar_captura_error(motivo):

    if not driver_vivo():

        return

    try:

        preparar_diagnostico()

        timestamp = time.strftime(
            "%Y%m%d_%H%M%S"
        )

        nombre = (
            f"error_{timestamp}_{motivo}.png"
        )

        ruta = os.path.join(
            CARPETA_DIAGNOSTICO,
            nombre
        )

        driver.save_screenshot(ruta)

        log(
            f"📸 Captura guardada: {ruta}"
        )

        limpiar_capturas()

    except Exception as e:

        log(
            f"⚠️ No se pudo guardar captura: {e}"
        )


# ============================================================
# DRIVER
# ============================================================

def crear_driver():

    log("🌐 Preparando Chromium...")

    options = Options()

    options.binary_location = "/usr/bin/chromium"

    # --------------------------------------------------------
    # Estrategia de carga
    # --------------------------------------------------------

    options.page_load_strategy = "eager"

    # --------------------------------------------------------
    # Headless
    # --------------------------------------------------------

    options.add_argument("--headless=new")

    # --------------------------------------------------------
    # Railway / Docker
    # --------------------------------------------------------

    options.add_argument("--no-sandbox")

    options.add_argument(
        "--disable-setuid-sandbox"
    )

    options.add_argument(
        "--disable-dev-shm-usage"
    )

    # --------------------------------------------------------
    # Estabilidad
    # --------------------------------------------------------

    options.add_argument(
        "--disable-gpu"
    )

    options.add_argument(
        "--disable-software-rasterizer"
    )

    options.add_argument(
        "--disable-extensions"
    )

    options.add_argument(
        "--disable-notifications"
    )

    options.add_argument(
        "--disable-popup-blocking"
    )

    options.add_argument(
        "--disable-sync"
    )

    options.add_argument(
        "--disable-background-networking"
    )

    options.add_argument(
        "--disable-background-timer-throttling"
    )

    options.add_argument(
        "--disable-renderer-backgrounding"
    )

    options.add_argument(
        "--disable-backgrounding-occluded-windows"
    )

    options.add_argument(
        "--disable-features=Translate"
    )

    options.add_argument(
        "--no-first-run"
    )

    options.add_argument(
        "--no-default-browser-check"
    )

    options.add_argument(
        "--mute-audio"
    )

    # --------------------------------------------------------
    # Tamaño
    # --------------------------------------------------------

    options.add_argument(
        "--window-size=1365,768"
    )

    # --------------------------------------------------------
    # User profile independiente
    # --------------------------------------------------------

    perfil = (
        f"/tmp/ticketmaster-profile-"
        f"{os.getpid()}-"
        f"{int(time.time())}"
    )

    options.add_argument(
        f"--user-data-dir={perfil}"
    )

    # --------------------------------------------------------
    # Driver
    # --------------------------------------------------------

    service = Service(
        executable_path="/usr/bin/chromedriver"
    )

    log("🔎 Creando sesión Selenium...")

    navegador = webdriver.Chrome(
        service=service,
        options=options
    )

    navegador.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    navegador.set_script_timeout(
        SCRIPT_TIMEOUT
    )

    navegador.implicitly_wait(1)

    log("✅ Selenium creado correctamente.")

    return navegador


# ============================================================
# CERRAR DRIVER
# ============================================================

def cerrar_driver():

    global driver

    if driver is None:

        return

    try:

        driver.quit()

    except Exception:

        pass

    driver = None

    log("🧹 Sesión Chrome cerrada.")


# ============================================================
# DRIVER VIVO
# ============================================================

def driver_vivo():

    global driver

    if driver is None:

        return False

    try:

        _ = driver.current_url

        return True

    except (
        InvalidSessionIdException,
        NoSuchWindowException,
        WebDriverException
    ):

        return False

    except Exception:

        return False


# ============================================================
# WATCHDOG
# ============================================================

def watchdog():

    if not driver_vivo():

        log(
            "⚠️ WATCHDOG: Chrome no responde."
        )

        return False

    try:

        estado = driver.execute_script(
            "return document.readyState;"
        )

        if estado not in (
            "loading",
            "interactive",
            "complete"
        ):

            return False

        return True

    except (
        JavascriptException,
        WebDriverException,
        InvalidSessionIdException
    ):

        log(
            "⚠️ WATCHDOG: Renderer no responde."
        )

        return False

    except Exception:

        return False


# ============================================================
# INICIAR DRIVER
# ============================================================

def iniciar_driver():

    global driver

    cerrar_driver()

    try:

        log("🚀 Iniciando Chrome...")

        driver = crear_driver()

        log("🌐 Probando conexión con Ticketmaster...")

        try:

            driver.get(
                "https://www.ticketmaster.co"
            )

        except TimeoutException:

            log(
                "⚠️ Timeout inicial. "
                "Se analizará el contenido cargado."
            )

        time.sleep(3)

        if not driver_vivo():

            raise WebDriverException(
                "Chrome dejó de responder después de iniciar."
            )

        try:

            titulo = driver.title

        except Exception:

            raise WebDriverException(
                "No fue posible obtener el título."
            )

        log(
            f"📄 Ticketmaster: {titulo[:100]}"
        )

        log(
            "✅ Chrome/Chromium operativo."
        )

        return True

    except Exception as e:

        error = str(e)

        log(
            "❌ No se pudo iniciar Chrome:"
        )

        log(error)

        cerrar_driver()

        enviar_error_controlado(
            "Chrome/Selenium no pudo iniciarse.\n\n"
            f"{error[:1200]}"
        )

        return False


# ============================================================
# RECUPERACIÓN AUTOMÁTICA
# ============================================================

def recuperar_chrome():

    global recuperaciones_chrome

    log(
        "♻️ INICIANDO RECUPERACIÓN AUTOMÁTICA..."
    )

    cerrar_driver()

    time.sleep(2)

    for intento in range(
        1,
        INTENTOS_RECUPERACION + 1
    ):

        log(
            f"🔄 Recuperación "
            f"{intento}/{INTENTOS_RECUPERACION}"
        )

        if iniciar_driver():

            recuperaciones_chrome += 1

            log(
                "✅ Chrome recuperado."
            )

            return True

        espera = (
            ESPERA_RECUPERACION_BASE
            * intento
        )

        log(
            f"⏳ Esperando {espera}s "
            "antes del siguiente intento..."
        )

        time.sleep(espera)

    log(
        "❌ Recuperación no completada."
    )

    return False


# ============================================================
# TEXTO DE LA PÁGINA
# ============================================================

def obtener_texto_visible():

    try:

        elemento = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        texto = elemento.text

        if texto:

            return texto.lower()

    except Exception:

        pass

    try:

        return driver.page_source.lower()

    except Exception:

        return ""


# ============================================================
# TEXTO COMPLETO PARA DIAGNÓSTICO
# ============================================================

def obtener_texto_completo():

    try:

        html = driver.page_source

        if html:

            return html.lower()

    except Exception:

        pass

    return ""


# ============================================================
# DETECCIÓN DE AGOTADO
# ============================================================

def detectar_agotado(texto):

    palabras_agotado = [

        "agotado",

        "agotada",

        "agotados",

        "agotadas",

        "sold out",

        "no hay entradas",

        "no hay boletas",

        "no tickets available",

        "tickets are currently unavailable",

        "currently unavailable",

        "entradas no disponibles",

        "boletas no disponibles",

        "evento agotado",

        "entradas agotadas",

        "boletas agotadas",

        "tickets unavailable"
    ]

    for palabra in palabras_agotado:

        if palabra in texto:

            log(
                f"❌ Señal explícita de agotado: "
                f"'{palabra}'"
            )

            return True

    return False


# ============================================================
# ELEMENTOS INTERACTIVOS
# ============================================================

def obtener_elementos_interactivos():

    try:

        return driver.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button'], "
            "input, [data-testid], "
            "[aria-label]"
        )

    except Exception:

        return []


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra():

    palabras_fuertes = [

        "comprar boletas",

        "comprar entradas",

        "comprar tickets",

        "buy tickets",

        "buy now",

        "purchase tickets",

        "purchase",

        "seleccionar localidad",

        "seleccionar asiento",

        "seleccionar asientos",

        "select seats",

        "select tickets",

        "choose seats",

        "choose tickets",

        "get tickets",

        "ver boletos",

        "ver boletas",

        "seleccionar boletos"
    ]

    elementos = obtener_elementos_interactivos()

    encontrados = []

    for elemento in elementos:

        try:

            if not elemento.is_displayed():

                continue

            texto = (
                elemento.text
                or ""
            ).strip().lower()

            aria = (
                elemento.get_attribute(
                    "aria-label"
                )
                or ""
            ).lower()

            title = (
                elemento.get_attribute(
                    "title"
                )
                or ""
            ).lower()

            data_testid = (
                elemento.get_attribute(
                    "data-testid"
                )
                or ""
            ).lower()

            combinado = (
                f"{texto} "
                f"{aria} "
                f"{title} "
                f"{data_testid}"
            )

            for palabra in palabras_fuertes:

                if palabra in combinado:

                    if palabra not in encontrados:

                        encontrados.append(
                            palabra
                        )

                    break

        except (
            StaleElementReferenceException,
            WebDriverException
        ):

            continue

        except Exception:

            continue

    # --------------------------------------------------------
    # HREFS
    # --------------------------------------------------------

    palabras_href = [

        "checkout",

        "purchase",

        "buy",

        "select",

        "ticket",

        "tickets"
    ]

    for elemento in elementos:

        try:

            href = (
                elemento.get_attribute(
                    "href"
                )
                or ""
            ).lower()

            if not href:

                continue

            for palabra in palabras_href:

                if palabra in href:

                    marcador = f"href:{palabra}"

                    if marcador not in encontrados:

                        encontrados.append(
                            marcador
                        )

                    break

        except Exception:

            continue

    return encontrados


# ============================================================
# DETECCIÓN DE INDICADORES DE DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad(texto):

    indicadores = [

        "selecciona tus entradas",

        "selecciona tus boletas",

        "selecciona tus tickets",

        "seleccione sus entradas",

        "seleccione sus boletas",

        "select your tickets",

        "select your seats",

        "choose your seats",

        "choose your tickets",

        "available tickets",

        "tickets available",

        "boletas disponibles",

        "entradas disponibles",

        "localidades disponibles",

        "seleccionar localidad",

        "seleccionar asiento",

        "seleccionar asientos"
    ]

    encontrados = []

    for indicador in indicadores:

        if indicador in texto:

            encontrados.append(
                indicador
            )

    return encontrados


# ============================================================
# PUNTUACIÓN
# ============================================================

def calcular_puntuacion(
    texto,
    controles
):

    puntuacion = 0

    evidencias = []

    # --------------------------------------------------------
    # CONTROLES REALES
    # --------------------------------------------------------

    if controles:

        puntuacion += 4

        evidencias.append(
            "control interactivo de compra"
        )

    # --------------------------------------------------------
    # TEXTO FUERTE DE COMPRA
    # --------------------------------------------------------

    palabras_compra = [

        "comprar boletas",

        "comprar entradas",

        "comprar tickets",

        "buy tickets",

        "buy now",

        "purchase tickets",

        "purchase",

        "seleccionar localidad",

        "seleccionar asiento",

        "seleccionar asientos",

        "select seats",

        "select tickets",

        "choose seats",

        "choose tickets"
    ]

    for palabra in palabras_compra:

        if palabra in texto:

            puntuacion += 3

            evidencias.append(
                f"texto:{palabra}"
            )

            break

    # --------------------------------------------------------
    # INDICADORES DE DISPONIBILIDAD
    # --------------------------------------------------------

    indicadores = (
        detectar_indicadores_disponibilidad(
            texto
        )
    )

    if indicadores:

        puntuacion += 3

        evidencias.append(
            "disponibilidad:"
            + indicadores[0]
        )

    # --------------------------------------------------------
    # ENLACES DE COMPRA
    # --------------------------------------------------------

    if any(
        x.startswith("href:")
        for x in controles
    ):

        puntuacion += 3

        evidencias.append(
            "enlace relacionado con compra"
        )

    # --------------------------------------------------------
    # ASIENTOS / LOCALIDADES
    # --------------------------------------------------------

    palabras_asientos = [

        "asiento",

        "asientos",

        "seat",

        "seats",

        "localidad",

        "localidades"
    ]

    for palabra in palabras_asientos:

        if palabra in texto:

            puntuacion += 1

            evidencias.append(
                f"contexto:{palabra}"
            )

            break

    return puntuacion, evidencias


# ============================================================
# DETECTAR DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(url):

    global driver

    if not driver_vivo():

        return "error"

    try:

        log("")
        log("🔎 Revisando:")
        log(url)

        # ----------------------------------------------------
        # WATCHDOG
        # ----------------------------------------------------

        if not watchdog():

            log(
                "⚠️ Watchdog detectó "
                "renderer sin respuesta."
            )

            guardar_captura_error(
                "watchdog"
            )

            return "error"

        # ----------------------------------------------------
        # CARGAR URL
        # ----------------------------------------------------

        try:

            driver.get(url)

        except TimeoutException:

            log(
                "⚠️ Timeout de navegación. "
                "Continuando con lo cargado."
            )

        except WebDriverException as e:

            log(
                f"⚠️ Error navegando: {e}"
            )

            guardar_captura_error(
                "navegacion"
            )

            return "error"

        # ----------------------------------------------------
        # ESPERA PARA JAVASCRIPT
        # ----------------------------------------------------

        espera = random.uniform(
            ESPERA_DESPUES_CARGA_MIN,
            ESPERA_DESPUES_CARGA_MAX
        )

        time.sleep(espera)

        # ----------------------------------------------------
        # VERIFICAR DRIVER
        # ----------------------------------------------------

        if not driver_vivo():

            return "error"

        # ----------------------------------------------------
        # OBTENER TEXTO
        # ----------------------------------------------------

        texto = obtener_texto_visible()

        if not texto:

            log(
                "⚠️ No se obtuvo texto visible."
            )

            return "desconocido"

        # ----------------------------------------------------
        # DIAGNÓSTICO LOCAL
        # ----------------------------------------------------

        log(
            f"📄 Texto obtenido: "
            f"{len(texto)} caracteres"
        )

        # ----------------------------------------------------
        # AGOTADO
        # ----------------------------------------------------

        if detectar_agotado(texto):

            return "agotado"

        # ----------------------------------------------------
        # CONTROLES
        # ----------------------------------------------------

        controles = (
            detectar_controles_compra()
        )

        # ----------------------------------------------------
        # PUNTUACIÓN
        # ----------------------------------------------------

        puntuacion, evidencias = (
            calcular_puntuacion(
                texto,
                controles
            )
        )

        log(
            f"🧠 Puntuación: {puntuacion}"
        )

        if evidencias:

            log(
                "🔍 Evidencias: "
                + ", ".join(
                    evidencias[:10]
                )
            )

        # ----------------------------------------------------
        # DECISIÓN
        # ----------------------------------------------------

        # La disponibilidad requiere señales
        # suficientemente fuertes.

        if puntuacion >= 6:

            log(
                "🚨 Señales suficientes "
                "para DISPONIBLE."
            )

            return "disponible"

        # ----------------------------------------------------
        # SIN SEÑAL CLARA
        # ----------------------------------------------------

        log(
            "⚠️ No se encontró una señal "
            "clara de agotado o disponibilidad."
        )

        return "desconocido"

    # ========================================================
    # ERRORES SELENIUM
    # ========================================================

    except (
        InvalidSessionIdException,
        NoSuchWindowException
    ) as e:

        log(
            f"❌ Sesión Selenium inválida: {e}"
        )

        guardar_captura_error(
            "sesion"
        )

        return "error"

    except WebDriverException as e:

        log(
            "⚠️ WebDriverException:"
        )

        log(str(e))

        guardar_captura_error(
            "webdriver"
        )

        return "error"

    except Exception as e:

        log(
            "⚠️ Error inesperado:"
        )

        log(str(e))

        guardar_captura_error(
            "inesperado"
        )

        return "error"


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    url,
    estado
):

    global estado_anterior

    global ultima_alerta_disponibilidad

    global detecciones_agotado

    global detecciones_disponible

    anterior = estado_anterior[url]

    log(
        f"📊 {url} → {estado}"
    )

    # ========================================================
    # DISPONIBLE
    # ========================================================

    if estado == "disponible":

        detecciones_disponible += 1

        ahora = time.time()

        # Primera detección
        if anterior != "disponible":

            alerta_disponibilidad(url)

            ultima_alerta_disponibilidad[url] = ahora

        # Sigue disponible:
        # alerta nuevamente cada 30 segundos.
        elif (
            ahora
            - ultima_alerta_disponibilidad[url]
            >= COOLDOWN_DISPONIBILIDAD
        ):

            alerta_disponibilidad(url)

            ultima_alerta_disponibilidad[url] = ahora

        estado_anterior[url] = "disponible"

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if estado == "agotado":

        detecciones_agotado += 1

        # Solo enviar cuando cambia a agotado.
        if anterior != "agotado":

            alerta_agotado(url)

        estado_anterior[url] = "agotado"

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if estado == "desconocido":

        # Solo avisar cuando cambia a desconocido.
        if anterior != "desconocido":

            alerta_desconocido(url)

        estado_anterior[url] = "desconocido"

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # ERROR
    # ========================================================

    if estado == "error":

        log(
            "⚠️ Fallo temporal. "
            "No se cambia el estado anterior."
        )

        return


# ============================================================
# BACKOFF
# ============================================================

def obtener_espera_backoff():

    global nivel_backoff

    nivel_backoff = min(
        nivel_backoff + 1,
        6
    )

    espera = min(
        BACKOFF_MIN
        * (
            2 ** (
                nivel_backoff - 1
            )
        ),
        BACKOFF_MAX
    )

    espera += random.randint(
        0,
        10
    )

    return espera


def reset_backoff():

    global nivel_backoff

    nivel_backoff = 0


# ============================================================
# CICLO DE MONITOREO
# ============================================================

def ciclo():

    global fallos_consecutivos

    global revisiones_totales

    global revisiones_correctas

    global revisiones_error

    global ultima_revision

    for url in URLS:

        # ----------------------------------------------------
        # VERIFICAR CHROME
        # ----------------------------------------------------

        if not driver_vivo():

            log(
                "⚠️ Chrome no está disponible."
            )

            if not recuperar_chrome():

                fallos_consecutivos += 1

                revisiones_error += 1

                return

        # ----------------------------------------------------
        # REVISAR URL
        # ----------------------------------------------------

        estado = detectar_disponibilidad(
            url
        )

        revisiones_totales += 1

        ultima_revision = time.time()

        # ----------------------------------------------------
        # ERROR
        # ----------------------------------------------------

        if estado == "error":

            revisiones_error += 1

            fallos_consecutivos += 1

            log(
                f"⚠️ Fallo consecutivo: "
                f"{fallos_consecutivos}"
            )

            if (
                fallos_consecutivos
                >= FALLOS_ANTES_REINICIO
            ):

                if recuperar_chrome():

                    fallos_consecutivos = 0

                    reset_backoff()

                else:

                    return

            continue

        # ----------------------------------------------------
        # CORRECTO
        # ----------------------------------------------------

        revisiones_correctas += 1

        fallos_consecutivos = 0

        reset_backoff()

        procesar_resultado(
            url,
            estado
        )


# ============================================================
# VALIDAR CONFIGURACIÓN
# ============================================================

def validar_configuracion():

    errores = []

    if not TOKEN:

        errores.append(
            "TOKEN no está configurado."
        )

    if not CHAT_ID:

        errores.append(
            "CHAT_ID no está configurado."
        )

    if not URLS:

        errores.append(
            "No hay URLs para monitorear."
        )

    if errores:

        log(
            "❌ CONFIGURACIÓN INVÁLIDA:"
        )

        for error in errores:

            log(
                f"   • {error}"
            )

        return False

    return True


# ============================================================
# SEÑALES DE APAGADO
# ============================================================

def manejar_senal(
    signum,
    frame
):

    log("")

    log(
        "🛑 Señal de apagado recibida."
    )

    log(
        "🧹 Cerrando Selenium correctamente..."
    )

    cerrar_driver()

    log(
        "👋 Bot finalizado correctamente."
    )

    sys.exit(0)


signal.signal(
    signal.SIGTERM,
    manejar_senal
)

signal.signal(
    signal.SIGINT,
    manejar_senal
)


# ============================================================
# MAIN
# ============================================================

def main():

    global driver

    log("")

    log(
        "============================================================"
    )

    log(
        "🚀 BOT BTS TICKETMASTER 24/7"
    )

    log(
        "============================================================"
    )

    log("")

    # --------------------------------------------------------
    # CONFIGURACIÓN
    # --------------------------------------------------------

    if not validar_configuracion():

        return

    log(
        "✅ TOKEN encontrado."
    )

    log(
        "✅ CHAT_ID encontrado."
    )

    log(
        f"🎫 URLs monitoreadas: {len(URLS)}"
    )

    log("")

    # --------------------------------------------------------
    # ESTADO
    # --------------------------------------------------------

    cargar_estado()

    preparar_diagnostico()

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if send_telegram(

        "🚀 BOT INICIANDO\n\n"

        "✅ Railway conectado\n"

        "📡 Telegram conectado\n"

        "🔎 Monitoreo Ticketmaster preparado\n"

        "♻️ Recuperación automática activada\n"

        "🚨 Alertas de disponibilidad cada 30s\n"

        "💓 Heartbeat cada 5 horas\n"

        "🟢 Sistema 24/7 activado"

    ):

        log(
            "✅ Telegram funcionando."
        )

    # --------------------------------------------------------
    # CHROME
    # --------------------------------------------------------

    if iniciar_driver():

        log(
            "✅ Chrome listo."
        )

    else:

        log(
            "⚠️ Chrome no pudo iniciar."
        )

        log(
            "♻️ Se intentará recuperar automáticamente."
        )

    # ========================================================
    # BUCLE INFINITO
    # ========================================================

    while True:

        try:

            # ------------------------------------------------
            # WATCHDOG
            # ------------------------------------------------

            if not watchdog():

                log(
                    "⚠️ WATCHDOG: "
                    "Chrome/Renderer no responde."
                )

                if not recuperar_chrome():

                    espera = (
                        obtener_espera_backoff()
                    )

                    log(
                        f"⏳ Backoff: {espera}s"
                    )

                    time.sleep(
                        espera
                    )

                    comprobar_heartbeat()

                    continue

            # ------------------------------------------------
            # CICLO
            # ------------------------------------------------

            ciclo()

            # ------------------------------------------------
            # HEARTBEAT
            # ------------------------------------------------

            comprobar_heartbeat()

            # ------------------------------------------------
            # ESPERA
            # ------------------------------------------------

            if nivel_backoff == 0:

                espera = random.randint(
                    MIN_ESPERA,
                    MAX_ESPERA
                )

            else:

                espera = (
                    obtener_espera_backoff()
                )

            log(
                f"⏳ Próximo ciclo en "
                f"{espera}s."
            )

            time.sleep(
                espera
            )

        # ====================================================
        # CTRL+C
        # ====================================================

        except KeyboardInterrupt:

            log(
                "🛑 Bot detenido manualmente."
            )

            cerrar_driver()

            break

        # ====================================================
        # ERROR GENERAL
        # ====================================================

        except Exception as e:

            log(
                "❌ ERROR GENERAL CONTROLADO:"
            )

            log(
                str(e)
            )

            log(
                traceback.format_exc()
            )

            enviar_error_controlado(

                "Error general del proceso:\n\n"
                f"{str(e)[:1200]}"

            )

            cerrar_driver()

            fallos_consecutivos += 1

            espera = (
                obtener_espera_backoff()
            )

            log(
                f"♻️ Recuperación después "
                f"de error general en {espera}s."
            )

            time.sleep(
                espera
            )

            recuperar_chrome()

            time.sleep(3)


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    main()
