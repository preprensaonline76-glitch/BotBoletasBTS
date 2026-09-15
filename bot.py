import os
import sys
import time
import random
import json
import signal
import traceback
import re

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


# ============================================================
# TIEMPOS
# ============================================================

MIN_ESPERA = 15
MAX_ESPERA = 25

# Heartbeat cada 5 horas
HEARTBEAT_INTERVAL = 5 * 60 * 60

# Si está disponible, repetir alerta cada 30 segundos
COOLDOWN_DISPONIBILIDAD = 30

# Selenium
PAGE_LOAD_TIMEOUT = 30
SCRIPT_TIMEOUT = 25

# Espera después de cargar Ticketmaster
ESPERA_DESPUES_CARGA_MIN = 2
ESPERA_DESPUES_CARGA_MAX = 5


# ============================================================
# RECUPERACIÓN AUTOMÁTICA
# ============================================================

FALLOS_ANTES_REINICIO = 2
INTENTOS_RECUPERACION = 4
ESPERA_RECUPERACION_BASE = 3

MAX_ERRORES_TELEGRAM = 10

BACKOFF_MIN = 15
BACKOFF_MAX = 120


# ============================================================
# DIAGNÓSTICO
# ============================================================

CARPETA_DIAGNOSTICO = "/tmp/ticketmaster_diagnostico"

MAX_CAPTURAS = 3
MAX_TEXTO_DIAGNOSTICO = 1500

ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"


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
            f"⚠️ Telegram HTTP "
            f"{respuesta.status_code}"
        )

        return False

    except requests.RequestException as e:

        log(
            f"⚠️ Error conexión Telegram: {e}"
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

    if errores_telegram_enviados >= MAX_ERRORES_TELEGRAM:

        log(
            "🔇 Límite de errores Telegram alcanzado."
        )

        return

    errores_telegram_enviados += 1

    mensaje_final = (
        "⚠️ ERROR DEL BOT\n\n"
        f"{mensaje}\n\n"
        f"Error "
        f"{errores_telegram_enviados}/"
        f"{MAX_ERRORES_TELEGRAM}"
    )

    send_telegram(mensaje_final)


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
# DURACIÓN
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
            f"{dias}d "
            f"{horas}h "
            f"{minutos}m"
        )

    if horas > 0:

        return (
            f"{horas}h "
            f"{minutos}m"
        )

    if minutos > 0:

        return (
            f"{minutos}m "
            f"{segundos}s"
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

            f"🔎 Revisiones totales: "
            f"{revisiones_totales}\n"

            f"✅ Revisiones correctas: "
            f"{revisiones_correctas}\n"

            f"⚠️ Revisiones con error: "
            f"{revisiones_error}\n\n"

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

        "⚠️ La disponibilidad puede ser temporal."
    )

    if send_telegram(mensaje):

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

    if send_telegram(mensaje):

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

        "El bot no pudo confirmar "
        "el estado de Ticketmaster.\n\n"

        "🔎 El monitoreo continuará."
    )

    if send_telegram(mensaje):

        log(
            "⚠️ Aviso de estado desconocido enviado."
        )


# ============================================================
# ESTADO
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

            datos = json.load(archivo)

        for url in URLS:

            estado = datos.get(url)

            if estado in (
                "disponible",
                "agotado",
                "desconocido"
            ):

                estado_anterior[url] = estado

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

        for _, ruta in archivos[
            MAX_CAPTURAS:
        ]:

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
            f"error_"
            f"{timestamp}_"
            f"{motivo}.png"
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
# CREAR CHROME
# ============================================================

def crear_driver():

    log(
        "🌐 Preparando Chromium..."
    )

    options = Options()

    options.binary_location = (
        "/usr/bin/chromium"
    )

    options.page_load_strategy = "eager"

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
        "--window-size=1365,768"
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

    navegador.implicitly_wait(1)

    log(
        "✅ Selenium creado correctamente."
    )

    return navegador


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

        return estado in (
            "loading",
            "interactive",
            "complete"
        )

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
                "Se continuará."
            )

        time.sleep(3)

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

        log(error)

        cerrar_driver()

        enviar_error_controlado(
            "Chrome/Selenium no pudo iniciarse.\n\n"
            f"{error[:1200]}"
        )

        return False


# ============================================================
# RECUPERAR CHROME
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
            f"⏳ Esperando {espera}s..."
        )

        time.sleep(espera)

    log(
        "❌ Recuperación no completada."
    )

    return False


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    texto = texto.replace(
        "\u00a0",
        " "
    )

    texto = texto.replace(
        "\r",
        "\n"
    )

    return texto.lower()


# ============================================================
# BODY INNER TEXT
# ============================================================

def obtener_body_innertext():

    try:

        texto = driver.execute_script(
            """
            if (!document.body) {
                return "";
            }

            return document.body.innerText || "";
            """
        )

        return texto or ""

    except Exception as e:

        log(
            f"⚠️ body.innerText falló: {e}"
        )

        return ""


# ============================================================
# DOCUMENT INNER TEXT
# ============================================================

def obtener_document_innertext():

    try:

        texto = driver.execute_script(
            """
            if (!document.documentElement) {
                return "";
            }

            return document.documentElement.innerText || "";
            """
        )

        return texto or ""

    except Exception as e:

        log(
            f"⚠️ document.innerText falló: {e}"
        )

        return ""


# ============================================================
# HTML
# ============================================================

def obtener_html():

    try:

        html = driver.page_source

        return html or ""

    except Exception as e:

        log(
            f"⚠️ page_source falló: {e}"
        )

        return ""


# ============================================================
# TEXTOS DE ENLACES
# ============================================================

def obtener_textos_enlaces():

    resultados = []

    try:

        elementos = driver.find_elements(
            By.TAG_NAME,
            "a"
        )

    except Exception:

        return ""

    for elemento in elementos:

        try:

            texto = (
                elemento.text or ""
            ).strip()

            aria = (
                elemento.get_attribute(
                    "aria-label"
                )
                or ""
            ).strip()

            title = (
                elemento.get_attribute(
                    "title"
                )
                or ""
            ).strip()

            href = (
                elemento.get_attribute(
                    "href"
                )
                or ""
            ).strip()

            if texto:
                resultados.append(texto)

            if aria:
                resultados.append(aria)

            if title:
                resultados.append(title)

            if href:
                resultados.append(href)

        except (
            StaleElementReferenceException,
            WebDriverException
        ):

            continue

        except Exception:

            continue

    return "\n".join(resultados)


# ============================================================
# OBTENER TODO EL CONTENIDO
# ============================================================

def obtener_contenido_ticketmaster():

    partes = []

    body = obtener_body_innertext()

    if body:
        partes.append(body)

    document = obtener_document_innertext()

    if document:
        partes.append(document)

    html = obtener_html()

    if html:
        partes.append(html)

    enlaces = obtener_textos_enlaces()

    if enlaces:
        partes.append(enlaces)

    return normalizar_texto(
        "\n".join(partes)
    )


# ============================================================
# DETECTAR AGOTADO
# ============================================================

def detectar_agotado_en_texto(texto):

    if not texto:
        return False

    texto_normalizado = normalizar_texto(
        texto
    )

    patrones_agotado = [

        # ----------------------------------------------------
        # ESPAÑOL
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # INGLÉS
        # ----------------------------------------------------

        "sold out",
        "sold-out",

        "no tickets available",
        "tickets unavailable",

        "tickets are currently unavailable",
        "currently unavailable",

        "tickets not available",

        "no seats available",
        "seats unavailable",

        "no seats currently available"
    ]

    for patron in patrones_agotado:

        if patron in texto_normalizado:

            log("")
            log(
                "🔴🔴🔴 AGOTADO DETECTADO 🔴🔴🔴"
            )

            log(
                f"🎯 Señal encontrada: "
                f"'{patron}'"
            )

            posicion = (
                texto_normalizado.find(
                    patron
                )
            )

            inicio = max(
                0,
                posicion - 200
            )

            fin = min(
                len(texto_normalizado),
                posicion
                + len(patron)
                + 300
            )

            contexto = (
                texto_normalizado[
                    inicio:fin
                ]
            )

            contexto = re.sub(
                r"\s+",
                " ",
                contexto
            ).strip()

            log(
                "📌 Contexto:"
            )

            log(contexto)

            return True

    return False


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra():

    palabras = [

        # Español
        "comprar boletas",
        "comprar entradas",
        "comprar tickets",

        "comprar",

        "seleccionar localidad",
        "seleccionar asiento",
        "seleccionar asientos",

        "continuar compra",
        "continuar",

        # Inglés
        "buy tickets",
        "buy now",

        "purchase tickets",
        "purchase",

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
            """
            button,
            a,
            [role='button'],
            input,
            [data-testid],
            [aria-label]
            """
        )

    except Exception:

        return []

    for elemento in elementos:

        try:

            if not elemento.is_displayed():
                continue

            texto = normalizar_texto(
                elemento.text or ""
            )

            aria = normalizar_texto(
                elemento.get_attribute(
                    "aria-label"
                ) or ""
            )

            title = normalizar_texto(
                elemento.get_attribute(
                    "title"
                ) or ""
            )

            testid = normalizar_texto(
                elemento.get_attribute(
                    "data-testid"
                ) or ""
            )

            combinado = (
                f"{texto} "
                f"{aria} "
                f"{title} "
                f"{testid}"
            )

            for palabra in palabras:

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

    return encontrados


# ============================================================
# DETECTAR INDICADORES DE DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad(
    texto
):

    indicadores = [

        # Español
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

        # Inglés
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

    texto = normalizar_texto(
        texto
    )

    for indicador in indicadores:

        if indicador in texto:

            encontrados.append(
                indicador
            )

    return encontrados


# ============================================================
# MOSTRAR DIAGNÓSTICO
# ============================================================

def mostrar_diagnostico_contenido(
    contenido
):

    longitud = len(contenido)

    log(
        f"📄 Contenido obtenido: "
        f"{longitud} caracteres"
    )

    if not contenido:

        log(
            "⚠️ CONTENIDO VACÍO."
        )

        return

    contiene_agotado = (
        "agotado" in contenido
    )

    log(
        "🔬 Contiene palabra "
        f"'agotado': "
        f"{contiene_agotado}"
    )

    if longitud <= 1000:

        limpio = re.sub(
            r"\s+",
            " ",
            contenido
        ).strip()

        log(
            "🔬 DIAGNÓSTICO DEL CONTENIDO:"
        )

        log(
            limpio[
                :MAX_TEXTO_DIAGNOSTICO
            ]
        )

        log(
            "🔬 FIN DEL DIAGNÓSTICO."
        )


# ============================================================
# DETECTAR ESTADO
#
# PRIORIDAD:
#
# 1. AGOTADO
# 2. CONTROLES / INDICADORES
# 3. DESCONOCIDO
# 4. ERROR SI SELENIUM FALLA
# ============================================================

def detectar_disponibilidad(url):

    if not driver_vivo():

        return "error"

    try:

        log("")
        log("🔎 Revisando:")
        log(url)

        # ====================================================
        # WATCHDOG
        # ====================================================

        if not watchdog():

            log(
                "⚠️ WATCHDOG: "
                "renderer sin respuesta."
            )

            guardar_captura_error(
                "watchdog"
            )

            return "error"

        # ====================================================
        # CARGAR URL
        # ====================================================

        try:

            driver.get(url)

        except TimeoutException:

            log(
                "⚠️ Timeout de navegación."
            )

            log(
                "➡️ Se analizará "
                "lo que alcanzó a cargar."
            )

        except WebDriverException as e:

            log(
                f"⚠️ Error navegando: {e}"
            )

            guardar_captura_error(
                "navegacion"
            )

            return "error"

        # ====================================================
        # ESPERAR
        # ====================================================

        time.sleep(
            random.uniform(
                ESPERA_DESPUES_CARGA_MIN,
                ESPERA_DESPUES_CARGA_MAX
            )
        )

        if not driver_vivo():

            return "error"

        # ====================================================
        # OBTENER CONTENIDO
        # ====================================================

        contenido = (
            obtener_contenido_ticketmaster()
        )

        mostrar_diagnostico_contenido(
            contenido
        )

        if not contenido:

            log(
                "⚠️ No se obtuvo contenido "
                "de Ticketmaster."
            )

            return "desconocido"

        # ====================================================
        # 1. AGOTADO
        # ====================================================
        #
        # AGOTADO SIEMPRE TIENE PRIORIDAD.
        #
        # Aunque la página contenga "purchase",
        # "buy", etc., si también dice "Agotado",
        # el resultado es AGOTADO.
        # ====================================================

        if detectar_agotado_en_texto(
            contenido
        ):

            log(
                "❌ AGOTADO CONFIRMADO."
            )

            log(
                "📊 RESULTADO FINAL: AGOTADO"
            )

            return "agotado"

        # ====================================================
        # 2. CONTROLES DE COMPRA
        # ====================================================

        controles = (
            detectar_controles_compra()
        )

        if controles:

            log(
                "🟢 CONTROLES DE COMPRA DETECTADOS:"
            )

            log(
                "🔘 "
                + ", ".join(
                    controles[:10]
                )
            )

        else:

            log(
                "⚪ No se detectaron "
                "controles de compra."
            )

        # ====================================================
        # 3. INDICADORES DE DISPONIBILIDAD
        # ====================================================

        indicadores = (
            detectar_indicadores_disponibilidad(
                contenido
            )
        )

        if indicadores:

            log(
                "🟢 INDICADORES DE DISPONIBILIDAD:"
            )

            log(
                "🎫 "
                + ", ".join(
                    indicadores[:10]
                )
            )

        else:

            log(
                "⚪ No se encontraron "
                "indicadores explícitos "
                "de disponibilidad."
            )

        # ====================================================
        # 4. DISPONIBLE
        # ====================================================

        if controles or indicadores:

            log("")
            log(
                "🚨🚨🚨 DISPONIBILIDAD DETECTADA 🚨🚨🚨"
            )

            log(
                "📊 RESULTADO FINAL: DISPONIBLE"
            )

            return "disponible"

        # ====================================================
        # 5. DESCONOCIDO
        # ====================================================

        log(
            "⚠️ No se encontró una señal clara "
            "de agotado ni disponibilidad."
        )

        log(
            "📊 RESULTADO FINAL: DESCONOCIDO"
        )

        return "desconocido"

    # ========================================================
    # SESIÓN SELENIUM
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

    # ========================================================
    # WEBDRIVER
    # ========================================================

    except WebDriverException as e:

        log(
            "⚠️ WebDriverException:"
        )

        log(str(e))

        guardar_captura_error(
            "webdriver"
        )

        return "error"

    # ========================================================
    # ERROR GENERAL
    # ========================================================

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

        # ----------------------------------------------------
        # CAMBIO A DISPONIBLE
        # ----------------------------------------------------

        if anterior != "disponible":

            log("")
            log(
                "🚨🚨🚨 CAMBIO A DISPONIBLE 🚨🚨🚨"
            )

            alerta_disponibilidad(
                url
            )

            ultima_alerta_disponibilidad[
                url
            ] = ahora

        # ----------------------------------------------------
        # CONTINÚA DISPONIBLE
        # ----------------------------------------------------

        elif (
            ahora
            - ultima_alerta_disponibilidad[url]
            >= COOLDOWN_DISPONIBILIDAD
        ):

            alerta_disponibilidad(
                url
            )

            ultima_alerta_disponibilidad[
                url
            ] = ahora

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

        detecciones_agotado += 1

        # ----------------------------------------------------
        # SOLO AVISAR AL CAMBIAR A AGOTADO
        # ----------------------------------------------------

        if anterior != "agotado":

            log("")
            log(
                "❌ CAMBIO A AGOTADO"
            )

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

        return

    # ========================================================
    # ERROR
    # ========================================================

    if estado == "error":

        log(
            "⚠️ Fallo temporal."
        )

        log(
            "ℹ️ Se conserva "
            "el último estado conocido."
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
            2
            ** (
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

        # ----------------------------------------------------
        # COMPROBAR CHROME
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

        estado = (
            detectar_disponibilidad(url)
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
        # CORRECTA
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
            "No hay URLs."
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
# SEÑALES
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
        "🧹 Cerrando Selenium..."
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
        f"🎫 URLs monitoreadas: "
        f"{len(URLS)}"
    )

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

        "♻️ Recuperación automática de Chrome activada\n"

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
            "♻️ Se intentará recuperar "
            "automáticamente."
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
                        f"⏳ Backoff: "
                        f"{espera}s"
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

            time.sleep(espera)

        # ----------------------------------------------------
        # INTERRUPCIÓN
        # ----------------------------------------------------

        except KeyboardInterrupt:

            log(
                "🛑 Bot detenido manualmente."
            )

            cerrar_driver()

            break

        # ----------------------------------------------------
        # ERROR GENERAL
        # ----------------------------------------------------

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
                f"de error en {espera}s."
            )

            time.sleep(espera)

            recuperar_chrome()

            time.sleep(3)


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":

    main()
