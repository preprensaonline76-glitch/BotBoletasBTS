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
# 🎫 BOT DE MONITOREO TICKETMASTER
# ============================================================
#
# FUNCIONES:
#
# ✅ Monitoreo continuo de dos eventos
# ✅ Telegram
# ✅ Heartbeat cada 5 horas
# ✅ Alertas de disponibilidad repetidas
# ✅ Alertas de agotado
# ✅ Alertas de estado desconocido
# ✅ Alertas de cambio de estado
# ✅ Máximo 10 alertas de error
# ✅ Recuperación automática de Chrome
# ✅ Sin spam de mensajes normales
#
# ============================================================


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
# ⚙️ CONFIGURACIÓN GENERAL
# ============================================================

# Tiempo entre ciclos completos
MIN_ESPERA = 15
MAX_ESPERA = 28


# ============================================================
# 💓 HEARTBEAT
# ============================================================
#
# Un mensaje cada 5 horas.
#
# NO se envía cada vez que Chrome se reinicia.
#
# ============================================================

HEARTBEAT_INTERVAL = 5 * 60 * 60


# ============================================================
# 🚨 ALERTAS DE DISPONIBILIDAD
# ============================================================
#
# Cuando se detecta disponibilidad:
#
# El bot puede volver a avisar periódicamente.
#
# Esto es INTENCIONAL.
#
# ============================================================

COOLDOWN_DISPONIBILIDAD = 60


# ============================================================
# ❌ ALERTAS DE ERROR
# ============================================================
#
# Máximo 10 mensajes de error.
#
# Después de 10:
#
# Telegram queda silencioso.
#
# Los errores continúan apareciendo en Railway.
#
# ============================================================

MAX_ERRORES_TELEGRAM = 10


# ============================================================
# 🧠 VARIABLES INTERNAS
# ============================================================

driver = None


# Estado anterior de cada evento
estado_anterior = {
    url: None
    for url in URLS
}


# Última alerta de disponibilidad
ultima_alerta_disponibilidad = {
    url: 0
    for url in URLS
}


# Cantidad de errores enviados a Telegram
errores_telegram_enviados = 0


# Último heartbeat
ultima_heartbeat = time.time()


# ============================================================
# 📝 LOG
# ============================================================

def log(mensaje):

    print(mensaje)
    sys.stdout.flush()


# ============================================================
# 📲 TELEGRAM
# ============================================================

def send_telegram(mensaje):

    if not TOKEN:

        log("❌ TOKEN no configurado")

        return False


    if not CHAT_ID:

        log("❌ CHAT_ID no configurado")

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
            f"⚠️ Telegram respondió HTTP "
            f"{respuesta.status_code}"
        )

        return False


    except Exception as e:

        log(
            f"⚠️ Error enviando Telegram: {e}"
        )

        return False


# ============================================================
# ❌ ERROR CONTROLADO
# ============================================================

def enviar_error_controlado(mensaje):

    global errores_telegram_enviados


    # --------------------------------------------------------
    # Si ya llegamos al límite, NO enviar más mensajes.
    # --------------------------------------------------------

    if errores_telegram_enviados >= MAX_ERRORES_TELEGRAM:

        log(
            "🔇 Límite de errores de Telegram alcanzado. "
            "No se enviarán más errores."
        )

        return


    errores_telegram_enviados += 1


    mensaje_completo = (
        "⚠️ ERROR DEL BOT\n\n"
        f"{mensaje}\n\n"
        f"Error {errores_telegram_enviados}/"
        f"{MAX_ERRORES_TELEGRAM}"
    )


    if send_telegram(mensaje_completo):

        log(
            f"📲 Error enviado a Telegram "
            f"({errores_telegram_enviados}/"
            f"{MAX_ERRORES_TELEGRAM})"
        )

    else:

        log(
            "⚠️ No se pudo enviar el error a Telegram"
        )


# ============================================================
# 💓 HEARTBEAT
# ============================================================

def enviar_heartbeat():

    mensaje = (
        "💓 BOT SIGUE ACTIVO\n\n"
        "✅ Railway ejecutando correctamente\n"
        "🔎 Ticketmaster monitoreado\n"
        "📡 Telegram conectado"
    )


    if send_telegram(mensaje):

        log("💓 Heartbeat enviado correctamente")

    else:

        log("⚠️ No se pudo enviar heartbeat")


# ============================================================
# 🚨 ALERTA DE DISPONIBILIDAD
# ============================================================

def alerta_disponibilidad(url):

    mensaje = (
        "🚨🚨🚨 TICKET DISPONIBLE 🚨🚨🚨\n\n"
        "🎫 POSIBLE DISPONIBILIDAD DETECTADA\n\n"
        f"{url}\n\n"
        "⚡ ENTRA A TICKETMASTER INMEDIATAMENTE."
    )


    if send_telegram(mensaje):

        log(
            f"🚨 ALERTA ENVIADA: {url}"
        )

    else:

        log(
            "⚠️ No se pudo enviar alerta "
            "de disponibilidad"
        )


# ============================================================
# 🌐 CREAR CHROME
# ============================================================

def crear_driver():

    log("🌐 Preparando Chromium...")


    options = Options()


    # --------------------------------------------------------
    # UBICACIÓN DE CHROMIUM
    # --------------------------------------------------------

    options.binary_location = "/usr/bin/chromium"


    # --------------------------------------------------------
    # HEADLESS
    # --------------------------------------------------------

    options.add_argument("--headless=new")


    # --------------------------------------------------------
    # RAILWAY / LINUX
    # --------------------------------------------------------

    options.add_argument("--no-sandbox")

    options.add_argument(
        "--disable-setuid-sandbox"
    )

    options.add_argument(
        "--disable-dev-shm-usage"
    )


    # --------------------------------------------------------
    # ESTABILIDAD
    # --------------------------------------------------------

    options.add_argument("--disable-gpu")

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
        "--disable-notifications"
    )

    options.add_argument(
        "--disable-popup-blocking"
    )

    options.add_argument(
        "--mute-audio"
    )

    options.add_argument(
        "--no-first-run"
    )

    options.add_argument(
        "--no-default-browser-check"
    )


    # --------------------------------------------------------
    # EVITAR PROCESOS DE FONDO
    # --------------------------------------------------------

    options.add_argument(
        "--disable-background-timer-throttling"
    )

    options.add_argument(
        "--disable-renderer-backgrounding"
    )

    options.add_argument(
        "--disable-backgrounding-occluded-windows"
    )


    # --------------------------------------------------------
    # TAMAÑO DE VENTANA
    # --------------------------------------------------------

    options.add_argument(
        "--window-size=1280,720"
    )


    # --------------------------------------------------------
    # PERFIL TEMPORAL
    # --------------------------------------------------------

    options.add_argument(
        "--user-data-dir=/tmp/chromium-ticketmaster"
    )


    # --------------------------------------------------------
    # USER AGENT
    # --------------------------------------------------------

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )


    # --------------------------------------------------------
    # DRIVER
    # --------------------------------------------------------

    service = Service(
        executable_path="/usr/bin/chromedriver"
    )


    log("🔎 Creando sesión Selenium...")


    navegador = webdriver.Chrome(
        service=service,
        options=options
    )


    log(
        "✅ Sesión Selenium creada correctamente"
    )


    return navegador


# ============================================================
# 🚀 INICIAR DRIVER
# ============================================================

def iniciar_driver(notificar=False):

    global driver
    global errores_telegram_enviados


    # --------------------------------------------------------
    # Cerrar driver anterior
    # --------------------------------------------------------

    if driver is not None:

        try:

            driver.quit()

        except Exception:

            pass


        driver = None


    # --------------------------------------------------------
    # Intentar crear nuevo navegador
    # --------------------------------------------------------

    try:

        log(
            "🚀 Iniciando Chrome/Chromium..."
        )


        driver = crear_driver()


        driver.set_page_load_timeout(30)


        # ----------------------------------------------------
        # Prueba de conexión
        # ----------------------------------------------------

        log(
            "🌐 Probando conexión con Ticketmaster..."
        )


        driver.get(
            "https://www.ticketmaster.co"
        )


        time.sleep(3)


        log(
            "✅ CHROME/SELENIUM FUNCIONANDO"
        )


        # ----------------------------------------------------
        # Solo mandar mensaje cuando se solicite.
        #
        # Los reinicios automáticos NO mandan mensajes.
        # ----------------------------------------------------

        if notificar:

            send_telegram(
                "🚀 BOT ACTIVO\n\n"
                "✅ Railway conectado\n"
                "✅ Chrome/Chromium funcionando\n"
                "✅ Selenium funcionando\n"
                "🔎 Monitoreo iniciado"
            )


        return True


    except Exception as e:

        error = str(e)


        log(
            "❌ ERROR AL INICIAR CHROME"
        )

        log(error)


        driver = None


        # ----------------------------------------------------
        # Solo Telegram si no hemos superado el límite.
        # ----------------------------------------------------

        enviar_error_controlado(
            "Chrome/Selenium no pudo iniciarse.\n\n"
            f"{error[:1500]}"
        )


        return False


# ============================================================
# 🔍 DETECCIÓN DE DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(url):

    global driver


    if driver is None:

        log(
            "⚠️ Driver inexistente"
        )

        return "error"


    try:

        log(
            f"🔎 Consultando:\n{url}"
        )


        # ----------------------------------------------------
        # Abrir evento
        # ----------------------------------------------------

        driver.get(url)


        # ----------------------------------------------------
        # Espera dinámica corta
        # ----------------------------------------------------

        time.sleep(
            random.uniform(2.0, 3.5)
        )


        # ----------------------------------------------------
        # Obtener página
        # ----------------------------------------------------

        page = driver.page_source.lower()


        # ====================================================
        # ❌ AGOTADO
        # ====================================================

        palabras_agotado = [

            "agotado",

            "sold out",

            "no hay entradas",

            "no tickets available",

            "tickets are currently unavailable",

            "currently unavailable",

            "entradas no disponibles",

            "evento agotado"

        ]


        for palabra in palabras_agotado:

            if palabra in page:

                return "agotado"


        # ====================================================
        # 🎫 BOTONES DE COMPRA
        # ====================================================

        palabras_compra = [

            "comprar",

            "buy",

            "tickets",

            "entradas",

            "seleccionar",

            "select",

            "purchase"

        ]


        botones = driver.find_elements(

            By.CSS_SELECTOR,

            "button, a"

        )


        for elemento in botones:

            try:

                texto = (
                    elemento.text
                    .lower()
                    .strip()
                )


                if not texto:

                    continue


                # ------------------------------------------------
                # Comprobar que el elemento esté visible.
                # ------------------------------------------------

                try:

                    visible = elemento.is_displayed()

                except Exception:

                    visible = True


                if not visible:

                    continue


                # ------------------------------------------------
                # Comprobar que esté habilitado.
                # ------------------------------------------------

                try:

                    habilitado = elemento.is_enabled()

                except Exception:

                    habilitado = True


                if not habilitado:

                    continue


                # ------------------------------------------------
                # Coincidencia
                # ------------------------------------------------

                for palabra in palabras_compra:

                    if palabra in texto:

                        return "disponible"


            except Exception:

                continue


        # ====================================================
        # 🔗 ENLACES DE COMPRA
        # ====================================================

        enlaces = driver.find_elements(

            By.CSS_SELECTOR,

            "a"

        )


        palabras_href = [

            "checkout",

            "purchase",

            "buy",

            "ticket"

        ]


        for enlace in enlaces:

            try:

                href = enlace.get_attribute(
                    "href"
                )


                if not href:

                    continue


                href = href.lower()


                for palabra in palabras_href:

                    if palabra in href:

                        try:

                            if enlace.is_displayed():

                                return "disponible"

                        except Exception:

                            return "disponible"


            except Exception:

                continue


        # ====================================================
        # ⚠️ NO SE PUDO CONFIRMAR
        # ====================================================

        return "desconocido"


    except Exception as e:

        error = str(e)


        log(
            f"⚠️ Error consultando Ticketmaster:\n"
            f"{error}"
        )


        # ----------------------------------------------------
        # Marcar driver como potencialmente dañado.
        # ----------------------------------------------------

        texto_error = error.lower()


        if (

            "tab crashed" in texto_error

            or "session" in texto_error

            or "chrome" in texto_error

            or "disconnected" in texto_error

            or "invalid session" in texto_error

        ):

            log(
                "🔄 Chrome parece haberse caído."
            )


            try:

                iniciar_driver(
                    notificar=False
                )

            except Exception as reinicio_error:

                log(
                    f"⚠️ Falló reinicio: "
                    f"{reinicio_error}"
                )


        return "error"


# ============================================================
# 📊 PROCESAR RESULTADO
# ============================================================

def procesar_resultado(url, estado):

    global estado_anterior
    global ultima_alerta_disponibilidad


    log(
        f"📊 {url} → {estado}"
    )


    anterior = estado_anterior[url]


    # ========================================================
    # 🚨 DISPONIBLE
    # ========================================================

    if estado == "disponible":

        ahora = time.time()


        # ----------------------------------------------------
        # Primera detección de disponibilidad
        # ----------------------------------------------------

        if anterior != "disponible":

            log(
                "🚨🚨🚨 DISPONIBILIDAD DETECTADA 🚨🚨🚨"
            )


            alerta_disponibilidad(url)


            ultima_alerta_disponibilidad[url] = ahora


        # ----------------------------------------------------
        # Si sigue disponible:
        #
        # Se permite repetir la alerta cada minuto.
        #
        # Esto es el ÚNICO caso donde queremos spam.
        # ----------------------------------------------------

        elif (
            ahora
            - ultima_alerta_disponibilidad[url]
            >= COOLDOWN_DISPONIBILIDAD
        ):

            log(
                "🚨 La disponibilidad continúa. "
                "Enviando nueva alerta."
            )


            alerta_disponibilidad(url)


            ultima_alerta_disponibilidad[url] = ahora


        estado_anterior[url] = "disponible"


        return


    # ========================================================
    # ❌ AGOTADO
    # ========================================================

    if estado == "agotado":

        # ----------------------------------------------------
        # Solo avisar cuando cambia hacia agotado.
        # ----------------------------------------------------

        if anterior != "agotado":

            send_telegram(

                "❌ ENTRADAS AGOTADAS\n\n"
                f"{url}"

            )


            log(
                "❌ Estado: AGOTADO"
            )


        estado_anterior[url] = "agotado"


        return


    # ========================================================
    # ⚠️ DESCONOCIDO
    # ========================================================

    if estado == "desconocido":

        # ----------------------------------------------------
        # Solo avisar cuando cambia hacia desconocido.
        # ----------------------------------------------------

        if anterior != "desconocido":

            send_telegram(

                "⚠️ ESTADO NO CONFIRMADO\n\n"
                f"{url}\n\n"
                "El bot continuará monitoreando."

            )


            log(
                "⚠️ Estado: DESCONOCIDO"
            )


        estado_anterior[url] = "desconocido"


        return


    # ========================================================
    # ❌ ERROR
    # ========================================================

    if estado == "error":

        # ----------------------------------------------------
        # NO mandamos aquí otro mensaje.
        #
        # detectar_disponibilidad() ya controla el error.
        # ----------------------------------------------------

        log(
            f"⚠️ Error temporal en:\n{url}"
        )


        return


    # ========================================================
    # 🔄 CAMBIO DE ESTADO GENERAL
    # ========================================================

    if (
        anterior is not None
        and estado != anterior
    ):

        send_telegram(

            "🔄 CAMBIO DE ESTADO\n\n"
            f"{url}\n\n"
            f"Anterior: {anterior}\n"
            f"Nuevo: {estado}"

        )


    estado_anterior[url] = estado


# ============================================================
# 🔁 CICLO DE MONITOREO
# ============================================================

def ciclo():

    for url in URLS:

        try:

            estado = detectar_disponibilidad(
                url
            )


            procesar_resultado(
                url,
                estado
            )


        except Exception as e:

            log(
                f"❌ Error procesando URL:\n{e}"
            )


# ============================================================
# 💓 COMPROBAR HEARTBEAT
# ============================================================

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
# 🔄 RECUPERACIÓN DEL DRIVER
# ============================================================

def asegurar_driver():

    global driver


    if driver is not None:

        return True


    log(
        "🔄 Intentando recuperar Chrome..."
    )


    return iniciar_driver(
        notificar=False
    )


# ============================================================
# 🚀 INICIO DEL BOT
# ============================================================

log("")
log("============================================================")
log("🚀 BOT BTS TICKETMASTER")
log("============================================================")
log("")


# ============================================================
# COMPROBAR VARIABLES
# ============================================================

if not TOKEN:

    log(
        "❌ ERROR: TOKEN no configurado en Railway."
    )

    sys.exit(1)


if not CHAT_ID:

    log(
        "❌ ERROR: CHAT_ID no configurado en Railway."
    )

    sys.exit(1)


log(
    "✅ TOKEN encontrado"
)

log(
    "✅ CHAT_ID encontrado"
)


# ============================================================
# PRUEBA TELEGRAM
# ============================================================

log(
    "📡 Probando conexión con Telegram..."
)


if send_telegram(

    "🚀 BOT INICIANDO\n\n"
    "✅ Railway conectado\n"
    "📡 Telegram conectado\n"
    "🔎 Preparando monitoreo de Ticketmaster..."

):

    log(
        "✅ Telegram conectado correctamente"
    )

else:

    log(
        "❌ Telegram no respondió correctamente"
    )


# ============================================================
# INICIAR CHROME
# ============================================================

if iniciar_driver(
    notificar=False
):

    # --------------------------------------------------------
    # IMPORTANTE:
    #
    # Ya enviamos el mensaje inicial antes.
    #
    # No mandamos otro BOT ACTIVO.
    # --------------------------------------------------------

    log(
        "✅ Bot completamente iniciado"
    )


else:

    log(
        "⚠️ Chrome no pudo iniciar inicialmente."
    )

    log(
        "🔄 El bot continuará intentando recuperarse."
    )


# ============================================================
# LOOP PRINCIPAL
# ============================================================

while True:

    try:

        # ----------------------------------------------------
        # Asegurar que Chrome exista
        # ----------------------------------------------------

        if driver is None:

            asegurar_driver()


        # ----------------------------------------------------
        # Ejecutar monitoreo
        # ----------------------------------------------------

        log("")
        log(
            "🔁 Ciclo de monitoreo..."
        )


        ciclo()


        # ----------------------------------------------------
        # Heartbeat cada 5 horas
        # ----------------------------------------------------

        comprobar_heartbeat()


        # ----------------------------------------------------
        # Espera variable
        # ----------------------------------------------------

        espera = random.randint(
            MIN_ESPERA,
            MAX_ESPERA
        )


        log(
            f"⏳ Próximo ciclo en "
            f"{espera} segundos..."
        )


        time.sleep(espera)


    # ========================================================
    # CTRL + C
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
    # ERROR GENERAL
    # ========================================================

    except Exception as e:

        log(
            f"❌ ERROR GENERAL:\n{e}"
        )


        # ----------------------------------------------------
        # Intentar recuperar Chrome.
        #
        # NO se manda mensaje de Telegram cada vez.
        # ----------------------------------------------------

        try:

            if driver:

                driver.quit()

        except Exception:

            pass


        driver = None


        asegurar_driver()


        time.sleep(10)
