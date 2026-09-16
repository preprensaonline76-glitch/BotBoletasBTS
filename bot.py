import os
import re
import sys
import time
import random
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
# ⚙️ CONFIGURACIÓN GENERAL
# ============================================================

MIN_ESPERA = 20
MAX_ESPERA = 30

# Heartbeat cada 5 horas
HEARTBEAT_INTERVAL = 5 * 60 * 60

# Tiempo máximo de carga
TIMEOUT_CARGA = 40

# Espera después de cargar
ESPERA_RENDER = 3

# Alerta de disponibilidad cada 30 segundos
COOLDOWN_ALERTA = 30

# Máximo de errores consecutivos enviados por Telegram
MAX_ERRORES_TELEGRAM = 10

# Backoff cuando Ticketmaster está bloqueando
ESPERA_BLOQUEO_1 = 120       # 2 minutos
ESPERA_BLOQUEO_2 = 300       # 5 minutos
ESPERA_BLOQUEO_MAX = 600     # 10 minutos


# ============================================================
# 🧠 LOG
# ============================================================

def log(msg):
    print(msg)
    sys.stdout.flush()


# ============================================================
# ⏱️ TIEMPO DE ACTIVIDAD
# ============================================================

inicio_bot = time.time()


def tiempo_activo():
    segundos = int(time.time() - inicio_bot)

    dias = segundos // 86400
    horas = (segundos % 86400) // 3600
    minutos = (segundos % 3600) // 60
    seg = segundos % 60

    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"

    if horas > 0:
        return f"{horas}h {minutos}m"

    if minutos > 0:
        return f"{minutos}m {seg}s"

    return f"{seg}s"


def horas_activas_decimal():
    return (time.time() - inicio_bot) / 3600


# ============================================================
# 📲 TELEGRAM
# ============================================================

errores_telegram_consecutivos = 0


def send_telegram(msg, contar_error=True):

    global errores_telegram_consecutivos

    if not TOKEN or not CHAT_ID:
        log("❌ Faltan TOKEN o CHAT_ID")
        return False

    try:

        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

        if response.status_code == 200:

            errores_telegram_consecutivos = 0

            return True

        log(
            f"⚠️ Telegram respondió HTTP "
            f"{response.status_code}"
        )

        if contar_error:
            errores_telegram_consecutivos += 1

        return False

    except Exception as e:

        log(f"❌ Error Telegram: {e}")

        if contar_error:
            errores_telegram_consecutivos += 1

        return False


# ============================================================
# 💓 HEARTBEAT
# ============================================================

ultima_heartbeat = time.time()


def enviar_heartbeat():

    agotados = sum(
        1 for estado in ultimo_estado_valido.values()
        if estado == "agotado"
    )

    disponibles = sum(
        1 for estado in ultimo_estado_valido.values()
        if estado == "disponible"
    )

    bloqueados = sum(
        1 for estado in estado_actual.values()
        if estado == "bloqueado"
    )

    mensaje = (
        "💓 BOT SIGUE ACTIVO\n\n"

        "✅ Railway ejecutando correctamente\n"
        "🔎 Monitoreo de Ticketmaster activo\n"
        "📡 Telegram conectado\n\n"

        f"⏱️ Tiempo activo: {tiempo_activo()}\n"
        f"🕐 Horas activas: {horas_activas_decimal():.2f} h\n\n"

        f"🔁 Ciclos realizados: {estadisticas['ciclos']}\n"
        f"🎫 Detecciones AGOTADO: "
        f"{estadisticas['agotado']}\n"
        f"🚨 Detecciones DISPONIBLE: "
        f"{estadisticas['disponible']}\n"
        f"🛡️ Bloqueos detectados: "
        f"{estadisticas['bloqueado']}\n"
        f"⚠️ Errores Selenium: "
        f"{estadisticas['error']}\n\n"

        f"📊 Estados válidos:\n"
        f"❌ Agotados: {agotados}\n"
        f"🚨 Disponibles: {disponibles}\n"
        f"🛡️ Bloqueados ahora: {bloqueados}"
    )

    if send_telegram(mensaje):

        log("💓 Heartbeat enviado correctamente")

    else:

        log("⚠️ No se pudo enviar el heartbeat")


def comprobar_heartbeat():

    global ultima_heartbeat

    ahora = time.time()

    if ahora - ultima_heartbeat >= HEARTBEAT_INTERVAL:

        enviar_heartbeat()

        ultima_heartbeat = ahora


# ============================================================
# 🚨 ALERTA DE DISPONIBILIDAD
# ============================================================

def alerta_disponibilidad(url):

    evento = EVENTOS.get(
        url,
        "EVENTO DESCONOCIDO"
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
        "🛡️ TICKETMASTER NO PERMITE VERIFICAR\n\n"

        f"🎫 Evento: {evento}\n\n"

        "Ticketmaster está devolviendo una "
        "página de protección en lugar de la "
        "página normal del evento.\n\n"

        "⚠️ El bot NO cambiará el último estado "
        "válido de las entradas.\n\n"

        "🔄 El monitoreo continuará automáticamente."
    )

    if send_telegram(mensaje):

        bloqueo_notificado[url] = True

        log(
            f"🛡️ Bloqueo notificado: {evento}"
        )


# ============================================================
# 🌐 CREAR CHROME
# ============================================================

def crear_driver():

    options = Options()

    options.binary_location = "/usr/bin/chromium"

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")

    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")

    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")

    options.add_argument("--window-size=1365,900")

    options.add_argument("--lang=es-CO")

    options.add_argument(
        "--disable-background-timer-throttling"
    )

    options.add_argument(
        "--disable-backgrounding-occluded-windows"
    )

    options.add_argument(
        "--disable-renderer-backgrounding"
    )

    # Mantener el mismo enfoque del bot antiguo
    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )

    # Carga más rápida
    options.page_load_strategy = "eager"

    service = Service(
        "/usr/bin/chromedriver"
    )

    driver_nuevo = webdriver.Chrome(
        service=service,
        options=options
    )

    driver_nuevo.set_page_load_timeout(
        TIMEOUT_CARGA
    )

    return driver_nuevo


# ============================================================
# 🚀 DRIVER GLOBAL
# ============================================================

driver = None


def iniciar_driver(notificar=True):

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

        # Abrir dominio principal primero
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
            f"❌ Error iniciando Chrome: {e}"
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

# Último estado válido confirmado
ultimo_estado_valido = {
    url: None
    for url in URLS
}


# Estado observado actualmente
estado_actual = {
    url: None
    for url in URLS
}


# Última alerta de disponibilidad
ultima_alerta = {
    url: 0
    for url in URLS
}


# Cantidad de bloqueos consecutivos
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
    "error": 0,
    "desconocido": 0
}


# ============================================================
# 🧹 NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    texto = texto.lower()

    texto = (
        texto
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# 🛡️ DETECTAR PÁGINA DE PROTECCIÓN
# ============================================================

def detectar_proteccion(texto_visible, page_source):

    visible = normalizar_texto(
        texto_visible
    )

    html = normalizar_texto(
        page_source
    )

    frases_proteccion = [

        "your browsing activity has been paused",

        "we've detected unusual behavior",

        "we have detected unusual behavior",

        "detected unusual behavior",

        "unusual behavior on either your network "
        "or your browser",

        "browsing activity has been paused",

        "change your wi-fi or cellular network",

        "change your wifi or cellular network",

        "switch devices or move to a different location",

        "your browsing activity",

        "unusual activity",

        "actividad inusual",

        "comportamiento inusual",

        "actividad sospechosa",

        "hemos detectado actividad inusual",

        "hemos detectado un comportamiento inusual"
    ]

    # La comprobación principal se hace sobre
    # el texto visible.
    for frase in frases_proteccion:

        if frase in visible:

            return True

    # También revisar HTML por si Ticketmaster
    # entrega parte del mensaje fuera del texto
    # visible.
    for frase in frases_proteccion:

        if frase in html:

            return True

    return False


# ============================================================
# 🎫 PALABRAS DE AGOTADO
# ============================================================

PALABRAS_AGOTADO = [

    "agotado",
    "agotados",
    "entrada agotada",
    "entradas agotadas",
    "boleta agotada",
    "boletas agotadas",
    "ticket agotado",
    "tickets agotados",

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
# 🚨 PALABRAS DE DISPONIBILIDAD
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
# 🔍 BUSCAR PALABRAS
# ============================================================

def contiene_alguna(texto, palabras):

    for palabra in palabras:

        if palabra in texto:

            return True

    return False


# ============================================================
# 🔎 DETECTAR BOTONES DE COMPRA
# ============================================================

def detectar_botones_compra():

    try:

        botones = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a"
        )

    except Exception:

        return False

    palabras_compra = [

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

    for elemento in botones:

        try:

            texto = normalizar_texto(
                elemento.text
            )

            if not texto:
                continue

            if contiene_alguna(
                texto,
                palabras_compra
            ):

                return True

        except Exception:

            continue

    return False


# ============================================================
# 🔗 DETECTAR ENLACES DE COMPRA
# ============================================================

def detectar_enlaces_compra():

    try:

        enlaces = driver.find_elements(
            By.CSS_SELECTOR,
            "a"
        )

    except Exception:

        return False

    palabras_url = [

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
                palabras_url
            ):

                return True

        except Exception:

            continue

    return False


# ============================================================
# 🎯 DETECCIÓN PRINCIPAL
# ============================================================

def detectar_disponibilidad(url):

    global driver

    try:

        if driver is None:

            log(
                "⚠️ Driver inexistente. "
                "Intentando iniciar..."
            )

            if not iniciar_driver():

                return "error"

        # ----------------------------------------------------
        # CARGAR URL
        # ----------------------------------------------------

        driver.get(url)

        time.sleep(
            random.uniform(
                1.5,
                ESPERA_RENDER
            )
        )

        # ----------------------------------------------------
        # OBTENER CONTENIDO
        # ----------------------------------------------------

        try:

            page_source = (
                driver.page_source
                or ""
            )

        except Exception:

            page_source = ""

        try:

            texto_visible = (
                driver.find_element(
                    By.TAG_NAME,
                    "body"
                ).text
                or ""
            )

        except Exception:

            texto_visible = ""

        # ----------------------------------------------------
        # NORMALIZAR
        # ----------------------------------------------------

        texto = normalizar_texto(
            texto_visible
        )

        html = normalizar_texto(
            page_source
        )

        # ----------------------------------------------------
        # DIAGNÓSTICO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 🛡️ PRIMERO: PROTECCIÓN
        # ----------------------------------------------------

        if detectar_proteccion(
            texto,
            html
        ):

            log(
                "🛡️ Ticketmaster devolvió "
                "una página de protección"
            )

            return "bloqueado"

        # ----------------------------------------------------
        # PÁGINA VACÍA
        # ----------------------------------------------------

        if len(texto) < 15:

            log(
                "⚠️ Página con muy poco "
                "contenido visible"
            )

            return "desconocido"

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
        # ❌ AGOTADO — HTML
        # ====================================================

        # Esto recupera la lógica que funcionaba
        # en tu bot antiguo.
        #
        # Importante:
        # solo llegamos aquí después de haber
        # descartado la página de protección.

        if contiene_alguna(
            html,
            PALABRAS_AGOTADO
        ):

            log(
                "❌ AGOTADO detectado "
                "en HTML"
            )

            return "agotado"

        # ====================================================
        # 🚨 DISPONIBLE — TEXTO VISIBLE
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
        # 🚨 DISPONIBLE — URL DE COMPRA
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
            "clara de estado"
        )

        return "desconocido"

    # ========================================================
    # 💥 ERROR SELENIUM
    # ========================================================

    except Exception as e:

        mensaje_error = str(e)

        log(
            f"⚠️ Error detectar: "
            f"{mensaje_error[:500]}"
        )

        estadisticas["error"] += 1

        error_lower = (
            mensaje_error.lower()
        )

        errores_chrome = [

            "tab crashed",
            "session deleted",
            "invalid session",
            "chrome not reachable",
            "disconnected",
            "no such window",
            "web view not found"
        ]

        debe_reiniciar = any(
            error in error_lower
            for error in errores_chrome
        )

        if debe_reiniciar:

            log(
                "🔄 Chrome parece haberse "
                "caído. Reiniciando..."
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

    global ultimo_estado_valido

    evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    log(
        f"📊 {evento} → {estado.upper()}"
    )

    estado_actual[url] = estado

    # ========================================================
    # 🛡️ BLOQUEADO
    # ========================================================

    if estado == "bloqueado":

        estadisticas["bloqueado"] += 1

        racha_bloqueos[url] += 1

        notificar_bloqueo(url)

        log(
            f"🛡️ Bloqueo consecutivo: "
            f"{racha_bloqueos[url]}"
        )

        # MUY IMPORTANTE:
        #
        # NO modificar ultimo_estado_valido.
        #
        # Si anteriormente estaba AGOTADO,
        # sigue considerándose AGOTADO como
        # último estado confirmado.

        return

    # ========================================================
    # 🔧 RECUPERACIÓN DE PÁGINA NORMAL
    # ========================================================

    if estado != "bloqueado":

        if racha_bloqueos[url] > 0:

            log(
                f"✅ Página normal recuperada "
                f"para {evento}"
            )

        racha_bloqueos[url] = 0

        bloqueo_notificado[url] = False

    # ========================================================
    # ❌ AGOTADO
    # ========================================================

    if estado == "agotado":

        estadisticas["agotado"] += 1

        anterior = (
            ultimo_estado_valido[url]
        )

        ultimo_estado_valido[url] = (
            "agotado"
        )

        if anterior == "disponible":

            send_telegram(
                "❌ ENTRADAS AGOTADAS\n\n"
                f"🎫 Evento: {evento}\n\n"
                f"{url}"
            )

        elif anterior is None:

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

        estadisticas["disponible"] += 1

        ahora = time.time()

        anterior = (
            ultimo_estado_valido[url]
        )

        ultimo_estado_valido[url] = (
            "disponible"
        )

        # Alertar inmediatamente.
        #
        # Después repetir cada 30 segundos
        # mientras continúe disponible.

        if (
            ahora - ultima_alerta[url]
            >= COOLDOWN_ALERTA
        ):

            log(
                f"🚨 DISPONIBILIDAD DETECTADA: "
                f"{evento}"
            )

            alerta_disponibilidad(url)

            ultima_alerta[url] = ahora

        if anterior == "agotado":

            log(
                f"🚨 CAMBIO: "
                f"{evento} "
                f"AGOTADO → DISPONIBLE"
            )

        return

    # ========================================================
    # ❓ DESCONOCIDO
    # ========================================================

    if estado == "desconocido":

        estadisticas["desconocido"] += 1

        log(
            f"❓ Estado no confirmado: "
            f"{evento}"
        )

        # No modificar el último estado válido.
        return

    # ========================================================
    # ⚠️ ERROR
    # ========================================================

    if estado == "error":

        log(
            f"⚠️ Error temporal en {evento}"
        )

        # No modificar el último estado válido.
        return


# ============================================================
# ⏳ ESPERA POR BLOQUEO
# ============================================================

def calcular_espera_bloqueo():

    max_racha = max(
        racha_bloqueos.values()
    )

    if max_racha <= 1:

        return ESPERA_BLOQUEO_1

    if max_racha == 2:

        return ESPERA_BLOQUEO_2

    return ESPERA_BLOQUEO_MAX


# ============================================================
# 🔁 CICLO DE MONITOREO
# ============================================================

def ciclo():

    estadisticas["ciclos"] += 1

    log(
        f"\n🔁 CICLO "
        f"{estadisticas['ciclos']}"
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
# 📊 RESUMEN DE ESTADOS
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

        actual = estado_actual[url]

        valido = ultimo_estado_valido[url]

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
# 🚀 INICIO DEL BOT
# ============================================================

log(
    "🚀 MODO MONITOREO ACTIVADO"
)

log(
    "🔎 Monitoreo de Ticketmaster iniciado"
)


# ============================================================
# 🔐 VALIDAR VARIABLES
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
# 📲 PRUEBA TELEGRAM
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
        "❌ No se pudo conectar con Telegram"
    )


# ============================================================
# 🌐 INICIAR CHROME
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

        resultados = ciclo()

        mostrar_resumen()

        comprobar_heartbeat()

        # ====================================================
        # DETERMINAR SI HAY BLOQUEO
        # ====================================================

        hay_bloqueo = any(
            estado == "bloqueado"
            for estado in resultados.values()
        )

        # ====================================================
        # ESPERA NORMAL
        # ====================================================

        if not hay_bloqueo:

            espera = random.randint(
                MIN_ESPERA,
                MAX_ESPERA
            )

            log(
                f"⏳ Esperando "
                f"{espera}s..."
            )

        # ====================================================
        # ESPERA POR BLOQUEO
        # ====================================================

        else:

            espera = calcular_espera_bloqueo()

            log(
                "🛡️ Ticketmaster continúa "
                "devolviendo protección."
            )

            log(
                f"⏳ Próxima comprobación "
                f"en {espera}s..."
            )

        time.sleep(
            espera
        )

    # ========================================================
    # 🛑 CTRL + C
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

        estadisticas["error"] += 1

        # Intentar recuperar solamente si
        # realmente parece un problema del proceso.

        try:

            if driver is None:

                iniciar_driver(
                    notificar=False
                )

        except Exception:

            pass

        time.sleep(30)
