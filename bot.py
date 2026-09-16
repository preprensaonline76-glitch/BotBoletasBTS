import os
import time
import random
import sys
import re
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException


# ============================================================
# 🔐 VARIABLES DE RAILWAY
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


# ============================================================
# 🎫 URLS DE TICKETMASTER
# ============================================================

URLS = [
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre"
]

EVENTOS = {
    URLS[0]: "SÁBADO 3 DE OCTUBRE",
    URLS[1]: "VIERNES 2 DE OCTUBRE"
}


# ============================================================
# ⚙️ CONFIGURACIÓN
# ============================================================

MIN_ESPERA = 20
MAX_ESPERA = 30

# Heartbeat cada 5 horas
HEARTBEAT_INTERVAL = 5 * 60 * 60

# Tiempo máximo de carga
TIMEOUT_CARGA = 40

# Espera para contenido dinámico
ESPERA_RENDER_MIN = 2.0
ESPERA_RENDER_MAX = 4.0

# Repetición de alerta si continúa disponible
COOLDOWN_ALERTA = 30

# Máximo de errores consecutivos de Telegram
MAX_ERRORES_TELEGRAM = 10

# Esperas cuando Ticketmaster realmente devuelve protección
BLOQUEO_ESPERA_1 = 120
BLOQUEO_ESPERA_2 = 300
BLOQUEO_ESPERA_MAX = 600


# ============================================================
# 🧠 LOG
# ============================================================

def log(msg):
    print(msg)
    sys.stdout.flush()


# ============================================================
# ⏱️ TIEMPO ACTIVO
# ============================================================

inicio_bot = time.time()


def obtener_tiempo_activo():

    segundos = int(
        time.time() - inicio_bot
    )

    dias = segundos // 86400

    horas = (
        segundos % 86400
    ) // 3600

    minutos = (
        segundos % 3600
    ) // 60

    segundos_restantes = (
        segundos % 60
    )

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
            f"{segundos_restantes}s"
        )

    return (
        f"{segundos_restantes}s"
    )


def obtener_horas_activas():

    return (
        time.time() - inicio_bot
    ) / 3600


# ============================================================
# 📲 TELEGRAM
# ============================================================

errores_telegram = 0


def send_telegram(
    mensaje,
    contar_error=True
):

    global errores_telegram

    if not TOKEN:

        log(
            "❌ TOKEN no configurado"
        )

        return False

    if not CHAT_ID:

        log(
            "❌ CHAT_ID no configurado"
        )

        return False

    try:

        respuesta = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": mensaje
            },
            timeout=10
        )

        if respuesta.status_code == 200:

            errores_telegram = 0

            return True

        log(
            f"⚠️ Telegram respondió "
            f"{respuesta.status_code}"
        )

        if contar_error:

            errores_telegram += 1

            if (
                errores_telegram
                >= MAX_ERRORES_TELEGRAM
            ):

                log(
                    "⚠️ Se alcanzó el límite "
                    "de errores de Telegram."
                )

        return False

    except Exception as e:

        log(
            f"❌ Error Telegram: "
            f"{str(e)[:300]}"
        )

        if contar_error:

            errores_telegram += 1

        return False


# ============================================================
# 💓 HEARTBEAT
# ============================================================

ultima_heartbeat = time.time()


def enviar_heartbeat():

    agotados = sum(
        1
        for estado in ultimo_estado_valido.values()
        if estado == "agotado"
    )

    disponibles = sum(
        1
        for estado in ultimo_estado_valido.values()
        if estado == "disponible"
    )

    bloqueados = sum(
        1
        for estado in estado_actual.values()
        if estado == "bloqueado"
    )

    mensaje = (
        "💓 BOT SIGUE ACTIVO\n\n"

        "✅ Railway ejecutando correctamente\n"
        "🔎 Monitoreo de Ticketmaster activo\n"
        "📡 Telegram conectado\n\n"

        f"⏱️ Tiempo activo: "
        f"{obtener_tiempo_activo()}\n"

        f"🕐 Horas activas: "
        f"{obtener_horas_activas():.2f} h\n\n"

        f"🔁 Ciclos realizados: "
        f"{estadisticas['ciclos']}\n"

        f"❌ Detecciones AGOTADO: "
        f"{estadisticas['agotado']}\n"

        f"🚨 Detecciones DISPONIBLE: "
        f"{estadisticas['disponible']}\n"

        f"🛡️ Bloqueos detectados: "
        f"{estadisticas['bloqueado']}\n"

        f"❓ Desconocidos: "
        f"{estadisticas['desconocido']}\n"

        f"⚠️ Errores Selenium: "
        f"{estadisticas['error']}\n\n"

        f"📊 Estados válidos actuales:\n"

        f"❌ Agotados: "
        f"{agotados}\n"

        f"🚨 Disponibles: "
        f"{disponibles}\n"

        f"🛡️ Bloqueados ahora: "
        f"{bloqueados}"
    )

    if send_telegram(mensaje):

        log(
            "💓 Heartbeat enviado correctamente"
        )

    else:

        log(
            "⚠️ No se pudo enviar heartbeat"
        )


def comprobar_heartbeat():

    global ultima_heartbeat

    ahora = time.time()

    if (
        ahora - ultima_heartbeat
        >= HEARTBEAT_INTERVAL
    ):

        enviar_heartbeat()

        ultima_heartbeat = ahora


# ============================================================
# 🚨 ALERTA DE DISPONIBILIDAD
# ============================================================

def alerta_disponibilidad(url):

    evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    mensaje = (
        "🚨🚨 TICKET DISPONIBLE 🚨🚨\n\n"

        f"🎫 Evento: {evento}\n\n"

        "⚡ Posible disponibilidad detectada.\n\n"

        f"{url}\n\n"

        "🔎 Revisa Ticketmaster inmediatamente."
    )

    send_telegram(mensaje)


# ============================================================
# 🛡️ ALERTA DE BLOQUEO
# ============================================================

bloqueo_notificado = {
    url: False
    for url in URLS
}


def notificar_bloqueo(url):

    if bloqueo_notificado[url]:

        return

    evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    mensaje = (
        "🛡️ VERIFICACIÓN TEMPORALMENTE LIMITADA\n\n"

        f"🎫 Evento: {evento}\n\n"

        "Ticketmaster está mostrando una "
        "página de protección en lugar del "
        "contenido normal del evento.\n\n"

        "⚠️ El bot conservará el último estado "
        "válido de las entradas.\n\n"

        "🔄 El monitoreo continuará automáticamente."
    )

    if send_telegram(mensaje):

        bloqueo_notificado[url] = True

        log(
            f"🛡️ Bloqueo notificado: "
            f"{evento}"
        )


# ============================================================
# 🌐 CREAR CHROME
# ============================================================

def crear_driver():

    options = Options()

    options.binary_location = (
        "/usr/bin/chromium"
    )

    options.add_argument(
        "--headless=new"
    )

    options.add_argument(
        "--no-sandbox"
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
        "--disable-background-networking"
    )

    options.add_argument(
        "--disable-sync"
    )

    options.add_argument(
        "--metrics-recording-only"
    )

    options.add_argument(
        "--mute-audio"
    )

    options.add_argument(
        "--disable-notifications"
    )

    options.add_argument(
        "--disable-popup-blocking"
    )

    options.add_argument(
        "--window-size=1365,900"
    )

    options.add_argument(
        "--lang=es-CO"
    )

    options.add_argument(
        "--disable-background-timer-throttling"
    )

    options.add_argument(
        "--disable-backgrounding-occluded-windows"
    )

    options.add_argument(
        "--disable-renderer-backgrounding"
    )

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )

    options.page_load_strategy = (
        "eager"
    )

    service = Service(
        "/usr/bin/chromedriver"
    )

    nuevo_driver = webdriver.Chrome(
        service=service,
        options=options
    )

    nuevo_driver.set_page_load_timeout(
        TIMEOUT_CARGA
    )

    return nuevo_driver


# ============================================================
# 🚀 DRIVER GLOBAL
# ============================================================

driver = None


def iniciar_driver(
    notificar=True
):

    global driver

    try:

        if driver:

            try:
                driver.quit()
            except Exception:
                pass

    except Exception:
        pass

    driver = None

    try:

        driver = crear_driver()

        driver.get(
            "https://www.ticketmaster.co"
        )

        time.sleep(2)

        log(
            "✅ Chrome iniciado correctamente"
        )

        if notificar:

            return True

        send_telegram(
            "🚀 BOT ACTIVO\n\n"
            "✅ Chrome iniciado correctamente\n"
            "🔎 Monitoreo iniciado\n"
            "📡 Telegram conectado"
        )

        return True

    except Exception as e:

        log(
            f"❌ Error iniciando Chrome: "
            f"{str(e)[:400]}"
        )

        send_telegram(
            "⚠️ ERROR DEL BOT\n\n"
            "Chrome/Selenium no pudo iniciarse.\n\n"
            "Revisa los logs de Railway."
        )

        return False


# ============================================================
# 🧠 ESTADOS
# ============================================================

# Último estado confirmado en una página normal
ultimo_estado_valido = {
    url: None
    for url in URLS
}


# Estado de la última consulta
estado_actual = {
    url: None
    for url in URLS
}


# Última alerta de disponibilidad
ultima_alerta = {
    url: 0
    for url in URLS
}


# Bloqueos consecutivos
racha_bloqueos = {
    url: 0
    for url in URLS
}


# ============================================================
# 📊 ESTADÍSTICAS
# ============================================================

estadisticas = {

    "ciclos": 0,

    "agotado": 0,

    "disponible": 0,

    "bloqueado": 0,

    "desconocido": 0,

    "error": 0
}


# ============================================================
# 🧹 NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:

        return ""

    texto = texto.lower()

    reemplazos = {

        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u"
    }

    for original, nuevo in reemplazos.items():

        texto = texto.replace(
            original,
            nuevo
        )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# 🛡️ DETECCIÓN DE PROTECCIÓN
# ============================================================
#
# MUY IMPORTANTE:
#
# Esta función NO busca frases de protección
# en todo el page_source.
#
# Solo utiliza el TEXTO VISIBLE.
#
# Esto evita el problema que tenía la versión
# anterior cuando encontraba frases dentro de
# scripts, SVG, JavaScript o contenido oculto.
# ============================================================

def detectar_proteccion(
    texto_visible
):

    texto = normalizar_texto(
        texto_visible
    )

    if not texto:

        return False

    frases_fuertes = [

        "your browsing activity has been paused",

        "we've detected unusual behavior",

        "we have detected unusual behavior",

        "unusual behavior on either your network or your browser",

        "browsing activity has been paused",

        "change your wi-fi or cellular network",

        "change your wifi or cellular network",

        "switch devices or move to a different location",

        "hemos detectado actividad inusual",

        "hemos detectado un comportamiento inusual",

        "actividad inusual en tu red",

        "comportamiento inusual"
    ]

    for frase in frases_fuertes:

        if frase in texto:

            return True

    # --------------------------------------------------------
    # Combinaciones que juntas sí son una señal fuerte
    # --------------------------------------------------------

    tiene_unusual = (
        "unusual behavior" in texto
        or
        "unusual activity" in texto
        or
        "actividad inusual" in texto
    )

    tiene_navegacion = (
        "browser" in texto
        or
        "browsing" in texto
        or
        "navegador" in texto
        or
        "red" in texto
    )

    if (
        tiene_unusual
        and tiene_navegacion
    ):

        return True

    return False


# ============================================================
# 🎫 PALABRAS AGOTADO
# ============================================================

PALABRAS_AGOTADO = [

    "entradas agotadas",

    "entrada agotada",

    "boletas agotadas",

    "boleta agotada",

    "tickets agotados",

    "ticket agotado",

    "agotado",

    "agotados",

    "sold out",

    "soldout",

    "no hay entradas",

    "no hay boletas",

    "no hay tickets",

    "no tickets available",

    "tickets are currently unavailable",

    "currently unavailable",

    "entradas no disponibles",

    "boletas no disponibles",

    "tickets no disponibles",

    "tickets unavailable",

    "entradas agotadas para este evento"
]


# ============================================================
# 🚨 PALABRAS DISPONIBLE
# ============================================================

PALABRAS_DISPONIBLE = [

    "entradas disponibles",

    "boletas disponibles",

    "tickets disponibles",

    "asientos disponibles",

    "seleccionar entradas",

    "seleccionar boletas",

    "seleccionar tickets",

    "select tickets",

    "select seats",

    "ver entradas",

    "ver boletas",

    "ver tickets",

    "ver asientos",

    "comprar entradas",

    "comprar boletas",

    "comprar tickets",

    "comprar asientos",

    "buy tickets",

    "available tickets",

    "tickets available",

    "available seats"
]


# ============================================================
# 🔍 CONTIENE PALABRA
# ============================================================

def contiene_alguna(
    texto,
    palabras
):

    for palabra in palabras:

        if palabra in texto:

            return True

    return False


# ============================================================
# 🎯 COMPROBAR QUE PARECE SER UNA PÁGINA DEL EVENTO
# ============================================================

def parece_pagina_evento(
    texto_visible,
    html
):

    texto = normalizar_texto(
        texto_visible
    )

    html_normalizado = normalizar_texto(
        html
    )

    señales = 0

    # --------------------------------------------------------
    # Nombre del artista/evento
    # --------------------------------------------------------

    if "bts" in texto:

        señales += 1

    elif "bts" in html_normalizado:

        señales += 1

    # --------------------------------------------------------
    # Ticketmaster
    # --------------------------------------------------------

    if "ticketmaster" in texto:

        señales += 1

    elif "ticketmaster" in html_normalizado:

        señales += 1

    # --------------------------------------------------------
    # Venta General
    # --------------------------------------------------------

    if "venta general" in texto:

        señales += 1

    # --------------------------------------------------------
    # Elementos típicos del evento
    # --------------------------------------------------------

    if (
        "octubre" in texto
        or
        "oct" in texto
    ):

        señales += 1

    if (
        "campin" in texto
        or
        "campín" in texto
    ):

        señales += 1

    return señales >= 2


# ============================================================
# 🔎 BOTONES DE COMPRA
# ============================================================

def detectar_botones_compra():

    try:

        elementos = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a"
        )

    except Exception:

        return False

    palabras = [

        "comprar",

        "buy",

        "tickets",

        "ticket",

        "entradas",

        "entrada",

        "boletas",

        "boleta",

        "select",

        "seleccionar",

        "ver entradas",

        "ver boletas",

        "ver tickets"
    ]

    for elemento in elementos:

        try:

            texto = normalizar_texto(
                elemento.text
            )

            if not texto:

                continue

            if contiene_alguna(
                texto,
                palabras
            ):

                return True

        except Exception:

            continue

    return False


# ============================================================
# 🔗 ENLACES DE COMPRA
# ============================================================

def detectar_enlaces_compra():

    try:

        enlaces = driver.find_elements(
            By.CSS_SELECTOR,
            "a"
        )

    except Exception:

        return False

    palabras = [

        "checkout",

        "purchase",

        "buy",

        "ticket",

        "tickets"
    ]

    for enlace in enlaces:

        try:

            href = enlace.get_attribute(
                "href"
            )

            if not href:

                continue

            href = normalizar_texto(
                href
            )

            if contiene_alguna(
                href,
                palabras
            ):

                return True

        except Exception:

            continue

    return False


# ============================================================
# 🔍 DETECCIÓN PRINCIPAL
# ============================================================

def detectar_disponibilidad(
    url
):

    global driver

    try:

        # ----------------------------------------------------
        # Comprobar driver
        # ----------------------------------------------------

        if driver is None:

            log(
                "⚠️ Driver inexistente."
            )

            if not iniciar_driver(
                notificar=False
            ):

                return "error"

        # ----------------------------------------------------
        # Cargar página
        # ----------------------------------------------------

        log(
            f"🌐 Consultando: "
            f"{EVENTOS.get(url, url)}"
        )

        driver.get(url)

        time.sleep(
            random.uniform(
                ESPERA_RENDER_MIN,
                ESPERA_RENDER_MAX
            )
        )

        # ----------------------------------------------------
        # Obtener HTML
        # ----------------------------------------------------

        try:

            page_source = (
                driver.page_source
                or ""
            )

        except Exception:

            page_source = ""

        # ----------------------------------------------------
        # Obtener texto visible
        # ----------------------------------------------------

        try:

            body = driver.find_element(
                By.TAG_NAME,
                "body"
            )

            texto_visible = (
                body.text
                or ""
            )

        except Exception:

            texto_visible = ""

        # ----------------------------------------------------
        # Normalizar
        # ----------------------------------------------------

        texto = normalizar_texto(
            texto_visible
        )

        html = normalizar_texto(
            page_source
        )

        # ----------------------------------------------------
        # Información básica
        # ----------------------------------------------------

        try:

            titulo = driver.title or ""

        except Exception:

            titulo = ""

        log(
            f"📄 {EVENTOS.get(url, url)}"
        )

        log(
            f"   Texto visible: "
            f"{len(texto_visible)} caracteres"
        )

        log(
            f"   HTML: "
            f"{len(page_source)} caracteres"
        )

        log(
            f"   Título: "
            f"{titulo[:150]}"
        )

        # ====================================================
        # 🛡️ PROTECCIÓN
        # ====================================================
        #
        # SOLO TEXTO VISIBLE.
        #
        # NO buscar protección en HTML.
        # ====================================================

        if detectar_proteccion(
            texto
        ):

            log(
                "🛡️ Protección detectada "
                "en texto visible"
            )

            return "bloqueado"

        # ====================================================
        # ❌ AGOTADO — TEXTO VISIBLE
        # ====================================================

        if contiene_alguna(
            texto,
            PALABRAS_AGOTADO
        ):

            log(
                "❌ AGOTADO detectado "
                "en texto visible"
            )

            return "agotado"

        # ====================================================
        # 🎫 PÁGINA DEL EVENTO
        # ====================================================

        es_evento = parece_pagina_evento(
            texto,
            html
        )

        log(
            f"   Página de evento: "
            f"{'SÍ' if es_evento else 'NO'}"
        )

        # ====================================================
        # ❌ AGOTADO — HTML
        # ====================================================
        #
        # Recuperamos la característica que hacía funcionar
        # al bot antiguo.
        #
        # Pero no se usa como primera comprobación.
        # Primero descartamos protección y comprobamos que
        # parece tratarse del evento.
        # ====================================================

        if es_evento:

            if contiene_alguna(
                html,
                PALABRAS_AGOTADO
            ):

                log(
                    "❌ AGOTADO detectado "
                    "en HTML de página de evento"
                )

                return "agotado"

        # ====================================================
        # 🚨 DISPONIBLE — TEXTO
        # ====================================================

        if contiene_alguna(
            texto,
            PALABRAS_DISPONIBLE
        ):

            log(
                "🚨 DISPONIBLE detectado "
                "en texto visible"
            )

            return "disponible"

        # ====================================================
        # 🚨 DISPONIBLE — BOTONES
        # ====================================================

        if detectar_botones_compra():

            log(
                "🚨 DISPONIBLE detectado "
                "mediante botón/enlace"
            )

            return "disponible"

        # ====================================================
        # 🚨 DISPONIBLE — ENLACES
        # ====================================================

        if detectar_enlaces_compra():

            log(
                "🚨 DISPONIBLE detectado "
                "mediante enlace de compra"
            )

            return "disponible"

        # ====================================================
        # ❓ DESCONOCIDO
        # ====================================================

        log(
            "❓ No se encontró una señal "
            "clara de disponibilidad "
            "o agotamiento"
        )

        return "desconocido"

    # ========================================================
    # 💥 ERROR
    # ========================================================

    except Exception as e:

        mensaje = str(e)

        log(
            f"⚠️ Error detectar: "
            f"{mensaje[:500]}"
        )

        estadisticas["error"] += 1

        mensaje_lower = (
            mensaje.lower()
        )

        errores_chrome = [

            "tab crashed",

            "session deleted",

            "invalid session",

            "chrome not reachable",

            "disconnected",

            "no such window",

            "web view not found",

            "chrome failed to start"
        ]

        if any(
            error in mensaje_lower
            for error in errores_chrome
        ):

            log(
                "🔄 Se detectó un problema "
                "real con Chrome."
            )

            iniciar_driver(
                notificar=False
            )

        return "error"


# ============================================================
# 📊 PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    url,
    estado
):

    evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    estado_actual[url] = estado

    log(
        f"📊 {evento} → "
        f"{estado.upper()}"
    )

    # ========================================================
    # 🛡️ BLOQUEADO
    # ========================================================

    if estado == "bloqueado":

        estadisticas[
            "bloqueado"
        ] += 1

        racha_bloqueos[url] += 1

        notificar_bloqueo(
            url
        )

        log(
            f"🛡️ Bloqueo consecutivo: "
            f"{racha_bloqueos[url]}"
        )

        # NO cambiar último estado válido
        return

    # ========================================================
    # PÁGINA NORMAL RECUPERADA
    # ========================================================

    if racha_bloqueos[url] > 0:

        log(
            f"✅ Página normal recuperada: "
            f"{evento}"
        )

    racha_bloqueos[url] = 0

    bloqueo_notificado[url] = False

    # ========================================================
    # ❌ AGOTADO
    # ========================================================

    if estado == "agotado":

        estadisticas[
            "agotado"
        ] += 1

        anterior = (
            ultimo_estado_valido[url]
        )

        ultimo_estado_valido[url] = (
            "agotado"
        )

        # Solo avisar cuando:
        # - es la primera detección
        # - o cambió desde disponible

        if (
            anterior is None
            or
            anterior == "disponible"
        ):

            send_telegram(
                "❌ ENTRADAS AGOTADAS\n\n"
                f"🎫 Evento: {evento}\n\n"
                f"{url}"
            )

        return

    # ========================================================
    # 🚨 DISPONIBLE
    # ========================================================

    if estado == "disponible":

        estadisticas[
            "disponible"
        ] += 1

        ahora = time.time()

        anterior = (
            ultimo_estado_valido[url]
        )

        ultimo_estado_valido[url] = (
            "disponible"
        )

        # Alerta inmediata.
        #
        # Después puede volver a alertar
        # cada 30 segundos.

        if (
            ahora - ultima_alerta[url]
            >= COOLDOWN_ALERTA
        ):

            log(
                f"🚨 DISPONIBILIDAD DETECTADA: "
                f"{evento}"
            )

            alerta_disponibilidad(
                url
            )

            ultima_alerta[url] = ahora

        if anterior == "agotado":

            log(
                f"🚨 CAMBIO DE ESTADO: "
                f"{evento} "
                f"AGOTADO → DISPONIBLE"
            )

        return

    # ========================================================
    # ❓ DESCONOCIDO
    # ========================================================

    if estado == "desconocido":

        estadisticas[
            "desconocido"
        ] += 1

        log(
            f"❓ Estado no confirmado: "
            f"{evento}"
        )

        # NO modificar último estado válido
        return

    # ========================================================
    # ⚠️ ERROR
    # ========================================================

    if estado == "error":

        log(
            f"⚠️ Error temporal: "
            f"{evento}"
        )

        # NO modificar último estado válido
        return


# ============================================================
# ⏳ CALCULAR ESPERA POR BLOQUEO
# ============================================================

def calcular_espera_bloqueo():

    mayor_racha = max(
        racha_bloqueos.values()
    )

    if mayor_racha <= 1:

        return BLOQUEO_ESPERA_1

    if mayor_racha == 2:

        return BLOQUEO_ESPERA_2

    return BLOQUEO_ESPERA_MAX


# ============================================================
# 🔁 CICLO
# ============================================================

def ejecutar_ciclo():

    estadisticas[
        "ciclos"
    ] += 1

    numero = estadisticas[
        "ciclos"
    ]

    log(
        f"\n🔁 CICLO {numero}"
    )

    resultados = {}

    for url in URLS:

        estado = detectar_disponibilidad(
            url
        )

        resultados[url] = estado

        procesar_resultado(
            url,
            estado
        )

    return resultados


# ============================================================
# 📊 RESUMEN
# ============================================================

def mostrar_resumen():

    log(
        "\n📊 RESUMEN DEL CICLO"
    )

    for url in URLS:

        evento = EVENTOS.get(
            url,
            "EVENTO"
        )

        actual = (
            estado_actual[url]
        )

        valido = (
            ultimo_estado_valido[url]
        )

        log(
            f"   🎫 {evento}"
        )

        log(
            f"      Estado actual: "
            f"{actual}"
        )

        log(
            f"      Último válido: "
            f"{valido}"
        )


# ============================================================
# 🚀 ARRANQUE
# ============================================================

log(
    "🚀 MODO MONITOREO ACTIVADO"
)

log(
    "🔎 Monitoreo de Ticketmaster iniciado"
)


# ============================================================
# 🔐 VALIDAR TOKEN
# ============================================================

if not TOKEN:

    log(
        "❌ ERROR: TOKEN no configurado"
    )

    sys.exit(1)


if not CHAT_ID:

    log(
        "❌ ERROR: CHAT_ID no configurado"
    )

    sys.exit(1)


# ============================================================
# 📲 TELEGRAM
# ============================================================

if send_telegram(
    "🚀 BOT INICIANDO\n\n"
    "✅ Railway conectado\n"
    "📡 Telegram conectado\n"
    "🔎 Preparando monitoreo...\n\n"
    "🎫 Eventos configurados: 2"
):

    log(
        "✅ Telegram conectado correctamente"
    )

else:

    log(
        "⚠️ Telegram no confirmó conexión"
    )


# ============================================================
# 🌐 CHROME
# ============================================================

if not iniciar_driver():

    log(
        "❌ No fue posible iniciar Chrome."
    )

    sys.exit(1)


# ============================================================
# 🔄 LOOP PRINCIPAL
# ============================================================

while True:

    try:

        resultados = ejecutar_ciclo()

        mostrar_resumen()

        comprobar_heartbeat()

        # ----------------------------------------------------
        # ¿HAY BLOQUEO?
        # ----------------------------------------------------

        hay_bloqueo = any(
            estado == "bloqueado"
            for estado in resultados.values()
        )

        # ----------------------------------------------------
        # ESPERA NORMAL
        # ----------------------------------------------------

        if not hay_bloqueo:

            espera = random.randint(
                MIN_ESPERA,
                MAX_ESPERA
            )

            log(
                f"⏳ Esperando "
                f"{espera}s..."
            )

        # ----------------------------------------------------
        # ESPERA SI REALMENTE ESTÁ BLOQUEADO
        # ----------------------------------------------------

        else:

            espera = (
                calcular_espera_bloqueo()
            )

            log(
                "🛡️ Ticketmaster está "
                "limitando temporalmente "
                "la verificación."
            )

            log(
                f"⏳ Próxima comprobación "
                f"en {espera}s..."
            )

        time.sleep(
            espera
        )

    # ========================================================
    # 🛑 DETENCIÓN MANUAL
    # ========================================================

    except KeyboardInterrupt:

        log(
            "🛑 Bot detenido manualmente."
        )

        try:

            if driver:

                driver.quit()

        except Exception:

            pass

        break

    # ========================================================
    # 💥 ERROR GENERAL
    # ========================================================

    except Exception as e:

        log(
            f"❌ Error general: "
            f"{str(e)[:500]}"
        )

        estadisticas[
            "error"
        ] += 1

        try:

            if driver is None:

                iniciar_driver(
                    notificar=False
                )

        except Exception:

            pass

        time.sleep(30)
