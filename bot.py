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
    JavascriptException
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

# CAMBIO: 30 segundos
COOLDOWN_DISPONIBILIDAD = 30

PAGE_LOAD_TIMEOUT = 25
SCRIPT_TIMEOUT = 20

ESPERA_DESPUES_CARGA = (1.5, 3.0)


# ------------------------------------------------------------
# RECUPERACIÓN
# ------------------------------------------------------------

FALLOS_ANTES_REINICIO = 2

INTENTOS_RECUPERACION = 3

ESPERA_RECUPERACION_BASE = 3

MAX_ERRORES_TELEGRAM = 10


# ------------------------------------------------------------
# BACKOFF
# ------------------------------------------------------------

BACKOFF_MIN = 15
BACKOFF_MAX = 120


# ------------------------------------------------------------
# ARCHIVOS
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

# ============================================================
# NUEVOS CONTADORES
# ============================================================

# Cuenta cada vez que una revisión detecta "agotado"
detecciones_agotado = 0

# Cuenta cada vez que una revisión detecta "disponible"
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
            f"⚠️ Telegram HTTP "
            f"{respuesta.status_code}"
        )

        return False

    except requests.RequestException as e:

        log(
            f"⚠️ Error de conexión con Telegram: {e}"
        )

        return False

    except Exception as e:

        log(
            f"⚠️ Error Telegram: {e}"
        )

        return False


# ============================================================
# ERRORES CONTROLADOS
# ============================================================

def enviar_error_controlado(mensaje):

    global errores_telegram_enviados

    if (
        errores_telegram_enviados
        >= MAX_ERRORES_TELEGRAM
    ):

        log(
            "🔇 Límite de errores Telegram "
            "alcanzado. Los siguientes errores "
            "se registrarán solamente en Railway."
        )

        return

    errores_telegram_enviados += 1

    mensaje_final = (
        "⚠️ ERROR DEL BOT\n\n"
        f"{mensaje}\n\n"
        f"Error {errores_telegram_enviados}/"
        f"{MAX_ERRORES_TELEGRAM}"
    )

    send_telegram(
        mensaje_final
    )


# ============================================================
# RECUPERACIÓN DE CONTADOR DE ERRORES
# ============================================================

def registrar_recuperacion():

    global errores_telegram_enviados
    global fallos_consecutivos
    global nivel_backoff

    if fallos_consecutivos > 0:

        log(
            "✅ Servicio recuperado correctamente."
        )

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

        return (
            f"{dias}d {horas}h "
            f"{minutos}m"
        )

    if horas > 0:

        return (
            f"{horas}h {minutos}m"
        )

    if minutos > 0:

        return (
            f"{minutos}m {segundos}s"
        )

    return f"{segundos}s"


# ============================================================
# HEARTBEAT
# ============================================================

def comprobar_heartbeat():

    global ultima_heartbeat

    ahora = time.time()

    if (
        ahora - ultima_heartbeat
        >= HEARTBEAT_INTERVAL
    ):

        uptime = formato_duracion(
            ahora - inicio_bot
        )

        mensaje = (
            "💓 BOT ACTIVO\n\n"

            f"⏱️ Tiempo activo: {uptime}\n\n"

            f"🔎 Revisiones: "
            f"{revisiones_totales}\n"

            f"✅ Revisiones correctas: "
            f"{revisiones_correctas}\n"

            f"⚠️ Revisiones con error: "
            f"{revisiones_error}\n\n"

            f"❌ Veces detectado agotado: "
            f"{detecciones_agotado}\n"

            f"🚨 Veces detectado disponible: "
            f"{detecciones_disponible}\n\n"

            f"♻️ Recuperaciones Chrome: "
            f"{recuperaciones_chrome}\n\n"

            "🎫 Ticketmaster monitoreado\n"

            "📡 Telegram conectado\n"

            "🟢 Monitoreo 24/7 activo"
        )

        if send_telegram(
            mensaje
        ):

            log(
                "💓 Heartbeat enviado."
            )

        ultima_heartbeat = ahora


# ============================================================
# ALERTA DISPONIBILIDAD
# ============================================================

def alerta_disponibilidad(url):

    mensaje = (
        "🚨🚨🚨 TICKET DISPONIBLE 🚨🚨🚨\n\n"

        "🎫 POSIBLE DISPONIBILIDAD DETECTADA\n\n"

        f"{url}\n\n"

        "⚡ REVISA TICKETMASTER INMEDIATAMENTE.\n\n"

        "⚠️ La detección puede ser temporal."
    )

    if send_telegram(
        mensaje
    ):

        log(
            "🚨 ALERTA DE DISPONIBILIDAD ENVIADA."
        )


# ============================================================
# ALERTA AGOTADO
# ============================================================

def alerta_agotado(url):

    mensaje = (
        "❌ ENTRADAS AGOTADAS\n\n"
        f"{url}"
    )

    if send_telegram(
        mensaje
    ):

        log(
            "❌ Aviso de agotado enviado."
        )


# ============================================================
# ALERTA DESCONOCIDO
# ============================================================

def alerta_desconocido(url):

    mensaje = (
        "⚠️ ESTADO NO CONFIRMADO\n\n"

        f"{url}\n\n"

        "El bot continuará monitoreando."
    )

    if send_telegram(
        mensaje
    ):

        log(
            "⚠️ Aviso de estado desconocido enviado."
        )


# ============================================================
# ESTADO PERSISTENTE
# ============================================================

def cargar_estado():

    global estado_anterior

    try:

        if not os.path.exists(
            ARCHIVO_ESTADO
        ):

            return

        with open(
            ARCHIVO_ESTADO,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(
                archivo
            )

        for url in URLS:

            estado = datos.get(
                url
            )

            if estado in (
                "disponible",
                "agotado",
                "desconocido"
            ):

                estado_anterior[url] = (
                    estado
                )

        log(
            "💾 Estado anterior cargado."
        )

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
# CREAR CARPETA DIAGNÓSTICO
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


# ============================================================
# CAPTURA DE DIAGNÓSTICO
# ============================================================

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

        driver.save_screenshot(
            ruta
        )

        log(
            f"📸 Captura guardada: {ruta}"
        )

        limpiar_capturas()

    except Exception as e:

        log(
            f"⚠️ No se pudo guardar captura: {e}"
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

            if os.path.isfile(
                ruta
            ):

                archivos.append(
                    (
                        os.path.getmtime(
                            ruta
                        ),
                        ruta
                    )
                )

        archivos.sort(
            key=lambda x: x[0],
            reverse=True
        )

        for _, ruta in archivos[
            MAX_CAPTURAS:
        ]:

            try:

                os.remove(
                    ruta
                )

            except Exception:

                pass

    except Exception:

        pass


# ============================================================
# CREAR DRIVER
# ============================================================

def crear_driver():

    log(
        "🌐 Preparando Chromium..."
    )

    options = Options()

    options.binary_location = (
        "/usr/bin/chromium"
    )

    options.page_load_strategy = (
        "eager"
    )

    options.add_argument(
        "--headless=new"
    )

    options.add_argument(
        "--no-sandbox"
    )

    options.add_argument(
        "--disable-setuid-sandbox"
    )

    options.add_argument(
        "--disable-dev-shm-usage"
    )

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

    options.add_argument(
        "--window-size=1280,720"
    )

    perfil = (
        f"/tmp/ticketmaster-profile-"
        f"{os.getpid()}-"
        f"{int(time.time())}"
    )

    options.add_argument(
        f"--user-data-dir={perfil}"
    )

    service = Service(
        executable_path="/usr/bin/chromedriver"
    )

    log(
        "🔎 Creando sesión Selenium..."
    )

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

    navegador.implicitly_wait(
        1
    )

    log(
        "✅ Selenium creado correctamente."
    )

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

    log(
        "🧹 Sesión Chrome cerrada."
    )


# ============================================================
# INICIAR DRIVER
# ============================================================

def iniciar_driver():

    global driver

    cerrar_driver()

    try:

        log(
            "🚀 Iniciando Chrome..."
        )

        driver = crear_driver()

        log(
            "🌐 Probando Ticketmaster..."
        )

        try:

            driver.get(
                "https://www.ticketmaster.co"
            )

        except TimeoutException:

            log(
                "⚠️ Timeout inicial. "
                "Se analizará lo cargado."
            )

        time.sleep(2)

        if not driver_vivo():

            raise WebDriverException(
                "Chrome dejó de responder "
                "después de iniciar."
            )

        try:

            titulo = driver.title

        except Exception:

            raise WebDriverException(
                "No fue posible obtener "
                "el título de Ticketmaster."
            )

        log(
            f"📄 Ticketmaster: "
            f"{titulo[:100]}"
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

        log(
            error
        )

        cerrar_driver()

        enviar_error_controlado(
            "Chrome/Selenium no pudo iniciarse.\n\n"
            f"{error[:1200]}"
        )

        return False


# ============================================================
# RECUPERACIÓN DE CHROME
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
            f"{intento}/"
            f"{INTENTOS_RECUPERACION}"
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

        time.sleep(
            espera
        )

    log(
        "❌ Recuperación no completada."
    )

    return False


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
# WATCHDOG REAL
# ============================================================

def watchdog():

    if not driver_vivo():

        log(
            "⚠️ WATCHDOG: Chrome no responde."
        )

        return False

    try:

        _ = driver.execute_script(
            "return document.readyState;"
        )

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
# TEXTO VISIBLE
# ============================================================

def obtener_texto_visible():

    try:

        elemento = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        return elemento.text.lower()

    except Exception:

        try:

            return driver.page_source.lower()

        except Exception:

            return ""


# ============================================================
# DETECCIÓN DE AGOTADO
# ============================================================

def detectar_agotado(texto):

    palabras_agotado = [

        "agotado",

        "sold out",

        "no hay entradas",

        "no tickets available",

        "tickets are currently unavailable",

        "currently unavailable",

        "entradas no disponibles",

        "evento agotado",

        "boletas agotadas",

        "tickets unavailable"

    ]

    for palabra in palabras_agotado:

        if palabra in texto:

            return True

    return False


# ============================================================
# DETECCIÓN DE CONTROLES
# ============================================================

def obtener_elementos_interactivos():

    try:

        return driver.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button'], input"
        )

    except Exception:

        return []


def detectar_controles_compra():

    palabras_fuertes = [

        "comprar boletas",

        "comprar entradas",

        "comprar",

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

        "tickets"

    ]

    elementos = (
        obtener_elementos_interactivos()
    )

    encontrados = []

    for elemento in elementos:

        try:

            if not elemento.is_displayed():

                continue

            texto = (
                elemento.text
                .strip()
                .lower()
            )

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

            combinado = (
                f"{texto} {aria} {title}"
            )

            for palabra in palabras_fuertes:

                if palabra in combinado:

                    encontrados.append(
                        palabra
                    )

                    break

        except Exception:

            continue

    palabras_href = [

        "checkout",

        "purchase",

        "buy",

        "select",

        "ticket"

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

                    encontrados.append(
                        f"href:{palabra}"
                    )

                    break

        except Exception:

            continue

    return encontrados


# ============================================================
# SISTEMA DE PUNTUACIÓN
# ============================================================

def calcular_puntuacion(
    texto,
    controles
):

    puntuacion = 0

    evidencias = []

    if controles:

        puntuacion += 3

        evidencias.append(
            "control interactivo"
        )

    palabras_compra = [

        "comprar boletas",

        "comprar entradas",

        "comprar",

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

            puntuacion += 2

            evidencias.append(
                f"texto:{palabra}"
            )

            break

    palabras_disponibles = [

        "disponible",

        "disponibles",

        "available",

        "availability",

        "selecciona tus entradas",

        "selecciona tus boletas",

        "select your tickets"

    ]

    for palabra in palabras_disponibles:

        if palabra in texto:

            puntuacion += 2

            evidencias.append(
                f"disponibilidad:{palabra}"
            )

            break

    if any(
        x.startswith("href:")
        for x in controles
    ):

        puntuacion += 2

        evidencias.append(
            "enlace de compra"
        )

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
                f"asientos:{palabra}"
            )

            break

    return (
        puntuacion,
        evidencias
    )


# ============================================================
# DETECCIÓN PRINCIPAL
# ============================================================

def detectar_disponibilidad(url):

    global driver

    if not driver_vivo():

        return "error"

    try:

        log(
            f"🔎 Revisando:\n{url}"
        )

        if not watchdog():

            log(
                "⚠️ Watchdog detectó renderer "
                "sin respuesta."
            )

            guardar_captura_error(
                "watchdog"
            )

            return "error"

        try:

            driver.get(
                url
            )

        except TimeoutException:

            log(
                "⚠️ Timeout de navegación. "
                "Continuando con lo cargado."
            )

        time.sleep(
            random.uniform(
                *ESPERA_DESPUES_CARGA
            )
        )

        if not driver_vivo():

            return "error"

        texto = obtener_texto_visible()

        if not texto:

            log(
                "⚠️ No se obtuvo texto "
                "de la página."
            )

            return "desconocido"

        if detectar_agotado(
            texto
        ):

            return "agotado"

        controles = (
            detectar_controles_compra()
        )

        puntuacion, evidencias = (
            calcular_puntuacion(
                texto,
                controles
            )
        )

        log(
            f"🧠 Puntuación: "
            f"{puntuacion}"
        )

        if evidencias:

            log(
                "🔍 Evidencias: "
                + ", ".join(
                    evidencias[:8]
                )
            )

        # ====================================================
        # SIN CONFIRMACIÓN DOBLE
        # ====================================================

        if puntuacion >= 3:

            return "disponible"

        return "desconocido"

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

        log(
            str(e)
        )

        guardar_captura_error(
            "webdriver"
        )

        return "error"

    except Exception as e:

        log(
            "⚠️ Error inesperado:"
        )

        log(
            str(e)
        )

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

        # -----------------------------------------------
        # CONTADOR DE DETECCIONES
        # -----------------------------------------------

        detecciones_disponible += 1

        ahora = time.time()

        # -----------------------------------------------
        # PRIMERA DETECCIÓN
        # -----------------------------------------------

        if anterior != "disponible":

            alerta_disponibilidad(
                url
            )

            ultima_alerta_disponibilidad[url] = (
                ahora
            )

        # -----------------------------------------------
        # REPETIR CADA 30 SEGUNDOS
        # -----------------------------------------------

        elif (
            ahora
            - ultima_alerta_disponibilidad[url]
            >= COOLDOWN_DISPONIBILIDAD
        ):

            alerta_disponibilidad(
                url
            )

            ultima_alerta_disponibilidad[url] = (
                ahora
            )

        estado_anterior[url] = (
            "disponible"
        )

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if estado == "agotado":

        # -----------------------------------------------
        # CONTADOR DE DETECCIONES
        # -----------------------------------------------

        detecciones_agotado += 1

        if anterior != "agotado":

            alerta_agotado(
                url
            )

        estado_anterior[url] = (
            "agotado"
        )

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if estado == "desconocido":

        if anterior != "desconocido":

            alerta_desconocido(
                url
            )

        estado_anterior[url] = (
            "desconocido"
        )

        guardar_estado()

        registrar_recuperacion()

        return

    # ========================================================
    # ERROR
    # ========================================================

    if estado == "error":

        log(
            "⚠️ Fallo temporal."
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
# CICLO
# ============================================================

def ciclo():

    global fallos_consecutivos

    global revisiones_totales

    global revisiones_correctas

    global revisiones_error

    global ultima_revision

    for url in URLS:

        if not driver_vivo():

            log(
                "⚠️ Chrome no está disponible."
            )

            if not recuperar_chrome():

                fallos_consecutivos += 1

                revisiones_error += 1

                return

        estado = detectar_disponibilidad(
            url
        )

        revisiones_totales += 1

        ultima_revision = time.time()

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

        revisiones_correctas += 1

        fallos_consecutivos = 0

        reset_backoff()

        procesar_resultado(
            url,
            estado
        )


# ============================================================
# VALIDACIÓN
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
# CIERRE LIMPIO
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


# ============================================================
# REGISTRAR SEÑALES
# ============================================================

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
        "🚀 BOT BTS TICKETMASTER 24/7 — MODO ÉLITE"
    )

    log(
        "============================================================"
    )

    log("")

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

    cargar_estado()

    preparar_diagnostico()

    if send_telegram(
        "🚀 BOT INICIANDO\n\n"

        "✅ Railway conectado\n"

        "📡 Telegram conectado\n"

        "🔎 Monitoreo Ticketmaster preparado\n"

        "🧠 Detección inteligente activada\n"

        "♻️ Recuperación automática activada\n"

        "🚨 Alertas de disponibilidad cada 30s\n"

        "🟢 Sistema 24/7 activado"
    ):

        log(
            "✅ Telegram funcionando."
        )

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
                        f"⏳ Backoff: "
                        f"{espera}s"
                    )

                    time.sleep(
                        espera
                    )

                    comprobar_heartbeat()

                    continue

            ciclo()

            comprobar_heartbeat()

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

        except KeyboardInterrupt:

            log(
                "🛑 Bot detenido manualmente."
            )

            cerrar_driver()

            break

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
                "♻️ Recuperación después "
                "de error general."
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
