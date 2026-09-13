import os
import time
import random
import sys
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By


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


# ============================================================
# ⚙️ CONFIGURACIÓN
# ============================================================

# Tiempo aproximado entre ciclos
MIN_ESPERA = 15
MAX_ESPERA = 28

# Cada cuánto mandar mensaje de "sigo activo"
HEARTBEAT_INTERVAL = 24 * 60 * 60  # 24 horas


# ============================================================
# 🧠 LOG
# ============================================================

def log(msg):
    print(msg)
    sys.stdout.flush()


# ============================================================
# 📲 TELEGRAM
# ============================================================

def send_telegram(msg):

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
            return True

        log(f"⚠️ Telegram respondió: {response.status_code}")
        return False

    except Exception as e:

        log(f"❌ Error Telegram: {e}")
        return False


# ============================================================
# 💓 HEARTBEAT
# ============================================================

def enviar_heartbeat():

    mensaje = (
        "💓 BOT SIGUE ACTIVO\n\n"
        "✅ Railway ejecutando correctamente\n"
        "🔎 Monitoreo de Ticketmaster activo\n"
        "📡 Telegram conectado"
    )

    if send_telegram(mensaje):

        log("💓 Heartbeat enviado correctamente")

    else:

        log("⚠️ No se pudo enviar el heartbeat")


# ============================================================
# 🚨 ALERTA DE DISPONIBILIDAD
# ============================================================

def alerta_disponibilidad(url):

    mensaje = (
        "🚨🚨 TICKET DISPONIBLE 🚨🚨\n\n"
        "🎫 Posible disponibilidad detectada\n\n"
        f"{url}\n\n"
        "⚡ Revisa Ticketmaster inmediatamente."
    )

    send_telegram(mensaje)


# ============================================================
# 🌐 CREAR CHROME
# ============================================================

def crear_driver():

    options = Options()

    options.binary_location = "/usr/bin/chromium"

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Reducir consumo
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")

    # Evitar algunos procesos innecesarios
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )

    service = Service("/usr/bin/chromedriver")

    driver = webdriver.Chrome(
        service=service,
        options=options
    )

    return driver


# ============================================================
# 🚀 DRIVER GLOBAL
# ============================================================

driver = None


def iniciar_driver():

    global driver

    try:

        if driver:
            driver.quit()

    except Exception:
        pass

    try:

        driver = crear_driver()

        driver.set_page_load_timeout(20)

        driver.get("https://www.ticketmaster.co")

        time.sleep(2)

        log("✅ Chrome iniciado correctamente")

        send_telegram(
            "🚀 BOT ACTIVO\n"
            "✅ Chrome iniciado correctamente\n"
            "🔎 Monitoreo iniciado"
        )

        return True

    except Exception as e:

        log(f"❌ Error iniciando Chrome: {e}")

        send_telegram(
            "⚠️ ERROR DEL BOT\n\n"
            "Chrome/Selenium no pudo iniciarse.\n"
            "Revisa los logs de Railway."
        )

        return False


# ============================================================
# 🧠 ESTADOS
# ============================================================

estado_anterior = {
    url: None
    for url in URLS
}


# Última alerta enviada
ultima_alerta = {
    url: 0
    for url in URLS
}


# Evita repetir alertas constantemente
COOLDOWN_ALERTA = 60


# ============================================================
# 🔍 DETECCIÓN
# ============================================================

def detectar_disponibilidad(url):

    global driver

    try:

        driver.get(url)

        # Espera corta para que cargue contenido dinámico
        time.sleep(random.uniform(1.5, 2.5))

        page = driver.page_source.lower()

        # ----------------------------------------------------
        # PALABRAS QUE INDICAN AGOTADO
        # ----------------------------------------------------

        palabras_agotado = [
            "agotado",
            "sold out",
            "no hay entradas",
            "no tickets available",
            "tickets are currently unavailable",
            "currently unavailable"
        ]

        if any(palabra in page for palabra in palabras_agotado):

            return "agotado"


        # ----------------------------------------------------
        # BOTONES / ELEMENTOS DE COMPRA
        # ----------------------------------------------------

        botones = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a"
        )

        palabras_compra = [
            "comprar",
            "buy",
            "tickets",
            "entradas",
            "select",
            "seleccionar"
        ]

        for elemento in botones:

            try:

                texto = elemento.text.lower().strip()

                if any(
                    palabra in texto
                    for palabra in palabras_compra
                ):

                    return "disponible"

            except Exception:
                continue


        # ----------------------------------------------------
        # DETECCIÓN DE ENLACES DE COMPRA
        # ----------------------------------------------------

        enlaces = driver.find_elements(
            By.CSS_SELECTOR,
            "a"
        )

        for enlace in enlaces:

            try:

                href = enlace.get_attribute("href")

                if href:

                    href = href.lower()

                    if any(
                        palabra in href
                        for palabra in [
                            "checkout",
                            "purchase",
                            "buy",
                            "ticket"
                        ]
                    ):

                        return "disponible"

            except Exception:
                continue


        return "desconocido"


    except Exception as e:

        log(f"⚠️ Error detectar: {e}")

        # Si Chrome se cayó, reiniciarlo
        if (
            "tab crashed" in str(e).lower()
            or "session" in str(e).lower()
            or "chrome" in str(e).lower()
        ):

            log("🔄 Reiniciando Chrome...")

            iniciar_driver()

        return "error"


# ============================================================
# 📊 PROCESAR RESULTADO
# ============================================================

def procesar_resultado(url, estado):

    global estado_anterior

    log(
        f"📊 {url} → {estado}"
    )


    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if estado == "disponible":

        ahora = time.time()

        # Evitar spam
        if ahora - ultima_alerta[url] >= COOLDOWN_ALERTA:

            log(
                f"🚨 DISPONIBILIDAD DETECTADA: {url}"
            )

            alerta_disponibilidad(url)

            ultima_alerta[url] = ahora


        estado_anterior[url] = "disponible"

        return


    # --------------------------------------------------------
    # CAMBIO DE ESTADO
    # --------------------------------------------------------

    anterior = estado_anterior[url]

    if anterior is not None and estado != anterior:

        if estado == "agotado":

            send_telegram(
                "❌ ENTRADAS AGOTADAS\n\n"
                f"{url}"
            )

        elif estado == "desconocido":

            send_telegram(
                "⚠️ ESTADO NO CONFIRMADO\n\n"
                f"{url}\n\n"
                "El bot continuará monitoreando."
            )

        elif estado == "error":

            log(
                f"⚠️ Error temporal en {url}"
            )

    estado_anterior[url] = estado


# ============================================================
# 🔁 CICLO DE MONITOREO
# ============================================================

def ciclo():

    for url in URLS:

        estado = detectar_disponibilidad(url)

        procesar_resultado(
            url,
            estado
        )


# ============================================================
# ❤️ CONTROL DEL HEARTBEAT
# ============================================================

ultima_heartbeat = time.time()


def comprobar_heartbeat():

    global ultima_heartbeat

    ahora = time.time()

    if ahora - ultima_heartbeat >= HEARTBEAT_INTERVAL:

        enviar_heartbeat()

        ultima_heartbeat = ahora


# ============================================================
# 🚀 INICIO
# ============================================================

log(
    "🚀 MODO ÉLITE ACTIVADO"
)

log(
    "🔎 Monitoreo de Ticketmaster iniciado"
)


if not TOKEN:

    log("❌ ERROR: TOKEN no configurado")

    sys.exit(1)


if not CHAT_ID:

    log("❌ ERROR: CHAT_ID no configurado")

    sys.exit(1)


# ------------------------------------------------------------
# PRUEBA DE TELEGRAM
# ------------------------------------------------------------

if send_telegram(
    "🚀 BOT INICIANDO\n\n"
    "✅ Railway conectado\n"
    "📡 Telegram conectado\n"
    "🔎 Preparando monitoreo..."
):

    log("✅ Telegram conectado correctamente")

else:

    log("❌ No se pudo conectar con Telegram")


# ------------------------------------------------------------
# INICIAR CHROME
# ------------------------------------------------------------

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

        log(
            "\n🔁 Ciclo de monitoreo..."
        )

        ciclo()

        # Comprobar si toca heartbeat
        comprobar_heartbeat()

        # Espera variable
        espera = random.randint(
            MIN_ESPERA,
            MAX_ESPERA
        )

        log(
            f"⏳ Esperando {espera}s..."
        )

        time.sleep(espera)


    except KeyboardInterrupt:

        log(
            "🛑 Bot detenido manualmente."
        )

        try:
            driver.quit()
        except:
            pass

        break


    except Exception as e:

        log(
            f"❌ Error general: {e}"
        )

        # Intentar recuperar Chrome
        try:

            iniciar_driver()

        except Exception:

            pass

        # Esperar antes de volver a intentar
        time.sleep(10)
