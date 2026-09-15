# ============================================================
# BOT BTS - TICKETMASTER COLOMBIA
# MONITOREO DE DISPONIBILIDAD
# ============================================================

import os
import re
import time
import random
import unicodedata
from datetime import datetime

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

LINK_VIERNES = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-viernes-2-octubre"
)

LINK_SABADO = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-sabado-3-octubre"
)

# Tiempo entre revisiones
INTERVALO_MIN = 20
INTERVALO_MAX = 30

# Heartbeat
HEARTBEAT_HORAS = 5
HEARTBEAT_SEGUNDOS = HEARTBEAT_HORAS * 60 * 60

# Máximo de errores consecutivos enviados a Telegram
MAX_ERRORES_TELEGRAM = 10


# ============================================================
# ESTADOS
# ============================================================

ESTADO_VIERNES = None
ESTADO_SABADO = None

ULTIMO_AVISO_DISPONIBLE_VIERNES = 0
ULTIMO_AVISO_DISPONIBLE_SABADO = 0

ULTIMO_HEARTBEAT = time.time()

ERRORES_CONSECUTIVOS = 0

driver = None


# ============================================================
# ESTADÍSTICAS
# ============================================================

estadisticas = {
    "viernes": {
        "revisiones": 0,
        "agotado": 0,
        "disponible": 0,
        "bloqueado": 0,
        "desconocido": 0,
        "errores": 0,
    },
    "sabado": {
        "revisiones": 0,
        "agotado": 0,
        "disponible": 0,
        "bloqueado": 0,
        "desconocido": 0,
        "errores": 0,
    },
}


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje):
    global ERRORES_CONSECUTIVOS

    if not TOKEN or not CHAT_ID:
        print("⚠️ TOKEN o CHAT_ID no configurados.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    datos = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "disable_web_page_preview": False,
    }

    try:
        respuesta = requests.post(
            url,
            data=datos,
            timeout=20
        )

        if respuesta.ok:
            ERRORES_CONSECUTIVOS = 0
            return True

        ERRORES_CONSECUTIVOS += 1

        if ERRORES_CONSECUTIVOS <= MAX_ERRORES_TELEGRAM:
            print(
                f"⚠️ Error Telegram "
                f"{respuesta.status_code}: "
                f"{respuesta.text[:300]}"
            )

        return False

    except Exception as e:

        ERRORES_CONSECUTIVOS += 1

        if ERRORES_CONSECUTIVOS <= MAX_ERRORES_TELEGRAM:
            print(f"⚠️ Error enviando Telegram: {e}")

        return False


# ============================================================
# ENLACE SEGÚN FECHA
# ============================================================

def enlace_acceso_por_fecha(clave):

    if clave == "viernes":
        return (
            "\n\n"
            "🔗 ACCESO VIERNES 2 DE OCTUBRE:\n"
            f"{LINK_VIERNES}"
        )

    if clave == "sabado":
        return (
            "\n\n"
            "🔗 ACCESO SÁBADO 3 DE OCTUBRE:\n"
            f"{LINK_SABADO}"
        )

    return ""


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    texto = unicodedata.normalize(
        "NFKD",
        texto
    ).encode(
        "ascii",
        "ignore"
    ).decode(
        "ascii"
    )

    texto = texto.lower()

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# FRASES DE AGOTADO
# ============================================================

FRASES_AGOTADO = [

    "agotado",
    "agotada",
    "agotados",
    "agotadas",

    "entradas agotadas",
    "boletas agotadas",
    "tickets agotados",

    "sold out",
    "sold-out",
    "soldout",

    "tickets are sold out",
    "event is sold out",

    "unavailable",
    "tickets unavailable",
    "tickets are unavailable",

    "no hay entradas",
    "no hay boletas",
    "no hay tickets",
]


# ============================================================
# FRASES DE DISPONIBILIDAD
# ============================================================

FRASES_DISPONIBILIDAD = [

    "entradas disponibles",
    "boletas disponibles",
    "tickets disponibles",
    "asientos disponibles",

    "selecciona tus entradas",
    "selecciona tus boletas",
    "selecciona tus tickets",
    "selecciona tus asientos",

    "seleccionar entradas",
    "seleccionar boletas",
    "seleccionar tickets",
    "seleccionar asientos",

    "select your tickets",
    "select your seats",

    "available tickets",
    "tickets available",
    "available seats",
]


# ============================================================
# FRASES DE BLOQUEO
# ============================================================

FRASES_BLOQUEO = [

    "your browsing activity has been paused",

    "we've detected unusual behavior",

    "we have detected unusual behavior",

    "detected unusual behavior",

    "unusual behavior on either your network or your browser",

    "browsing activity has been paused",

    "change your wi-fi or cellular network",

    "change your wifi or cellular network",

    "switch devices or move to a different location",

    "if possible",

    "your browsing activity",
]


# ============================================================
# DETECTAR BLOQUEO
# ============================================================

def detectar_bloqueo(texto, html):

    contenido = f"{texto} {html}"

    for frase in FRASES_BLOQUEO:

        if frase in contenido:
            return True

    return False


# ============================================================
# DETECTAR AGOTADO
# ============================================================

def detectar_agotado(texto, html):

    contenido = f"{texto} {html}"

    for frase in FRASES_AGOTADO:

        if frase in contenido:
            return True

    return False


# ============================================================
# DETECTAR DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(texto, html):

    contenido = f"{texto} {html}"

    for frase in FRASES_DISPONIBILIDAD:

        if frase in contenido:
            return True

    return False


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    print("🌐 Iniciando Chrome...")

    options = Options()

    # Railway / entorno sin interfaz
    options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")

    options.add_argument("--disable-dev-shm-usage")

    options.add_argument("--disable-gpu")

    options.add_argument("--window-size=1365,900")

    options.add_argument("--disable-notifications")

    options.add_argument("--disable-popup-blocking")

    options.add_argument("--disable-extensions")

    options.add_argument("--disable-background-networking")

    options.add_argument("--disable-background-timer-throttling")

    options.add_argument("--disable-renderer-backgrounding")

    options.add_argument("--disable-features=Translate")

    options.add_argument("--remote-allow-origins=*")

    options.add_argument(
        "--user-agent="
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )

    options.add_experimental_option(
        "useAutomationExtension",
        False
    )

    try:

        service = Service(
            executable_path="/usr/bin/chromedriver"
        )

        nuevo_driver = webdriver.Chrome(
            service=service,
            options=options
        )

        nuevo_driver.set_page_load_timeout(45)

        print("✅ Chrome iniciado correctamente.")

        return nuevo_driver

    except Exception as e:

        print(f"❌ No se pudo iniciar Chrome: {e}")

        return None


# ============================================================
# CERRAR DRIVER
# ============================================================

def cerrar_driver():

    global driver

    if driver is not None:

        try:
            driver.quit()

        except Exception:
            pass

    driver = None


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_driver():

    global driver

    print()
    print("🔄 INICIANDO RECUPERACIÓN DE CHROME")
    print("=" * 65)

    cerrar_driver()

    time.sleep(5)

    for intento in range(1, 4):

        print(
            f"🔧 Intento de recuperación "
            f"{intento}/3..."
        )

        driver = crear_driver()

        if driver is not None:

            print("✅ Recuperación completada.")

            return True

        time.sleep(10)

    print("❌ No fue posible recuperar Chrome.")

    return False


# ============================================================
# CARGAR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        driver = crear_driver()

        if driver is None:
            return False

    try:

        driver.get(url)

        # Espera corta para que cargue contenido dinámico,
        # sin hacer escaneo pesado del DOM.
        time.sleep(4)

        return True

    except Exception as e:

        print(f"❌ Error cargando página: {e}")

        return False


# ============================================================
# OBTENER CONTENIDO
# ============================================================

def obtener_contenido():

    global driver

    if driver is None:
        return None

    try:

        # Solamente obtenemos el body completo.
        # NO hacemos body *.
        # NO recorremos todos los elementos.
        # NO buscamos iframes.
        # NO buscamos Shadow DOM.

        elemento_body = driver.find_element(
            "tag name",
            "body"
        )

        texto = elemento_body.text

        html = driver.page_source

        return {
            "texto": normalizar_texto(texto),
            "html": normalizar_texto(html),
        }

    except Exception as e:

        print(
            f"⚠️ No se pudo obtener contenido: {e}"
        )

        return None


# ============================================================
# DETECTAR ESTADO
# ============================================================

def detectar_estado(contenido):

    if contenido is None:
        return "error"

    texto = contenido.get(
        "texto",
        ""
    )

    html = contenido.get(
        "html",
        ""
    )

    # --------------------------------------------------------
    # 1. BLOQUEO
    # --------------------------------------------------------

    if detectar_bloqueo(
        texto,
        html
    ):

        return "bloqueado"

    # --------------------------------------------------------
    # 2. AGOTADO
    # --------------------------------------------------------

    if detectar_agotado(
        texto,
        html
    ):

        return "agotado"

    # --------------------------------------------------------
    # 3. DISPONIBLE
    # --------------------------------------------------------

    if detectar_disponibilidad(
        texto,
        html
    ):

        return "disponible"

    # --------------------------------------------------------
    # 4. NO HAY INFORMACIÓN SUFICIENTE
    # --------------------------------------------------------

    return "desconocido"


# ============================================================
# NOMBRE BONITO
# ============================================================

def nombre_fecha(clave):

    if clave == "viernes":
        return "Viernes 2 de octubre de 2026"

    if clave == "sabado":
        return "Sábado 3 de octubre de 2026"

    return clave


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    clave,
    estado
):

    global ESTADO_VIERNES
    global ESTADO_SABADO

    global ULTIMO_AVISO_DISPONIBLE_VIERNES
    global ULTIMO_AVISO_DISPONIBLE_SABADO

    ahora = time.time()

    anterior = (
        ESTADO_VIERNES
        if clave == "viernes"
        else ESTADO_SABADO
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if estado == "error":

        estadisticas[clave]["errores"] += 1

        print(
            f"❌ {nombre_fecha(clave)} "
            f"→ error de Selenium"
        )

        return "error"

    # --------------------------------------------------------
    # BLOQUEADO
    # --------------------------------------------------------

    if estado == "bloqueado":

        estadisticas[clave]["bloqueado"] += 1

        print(
            f"🛑 {nombre_fecha(clave)} "
            f"→ Ticketmaster bloqueó temporalmente la sesión"
        )

        # MUY IMPORTANTE:
        # No modificamos el estado anterior.
        #
        # Si antes era:
        # agotado
        #
        # continúa siendo:
        # agotado
        #
        # No lo convertimos a desconocido.

        return "bloqueado"

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    if estado == "desconocido":

        estadisticas[clave]["desconocido"] += 1

        print(
            f"❓ {nombre_fecha(clave)} "
            f"→ desconocido"
        )

        # Tampoco reemplazamos el último estado válido.

        return "desconocido"

    # --------------------------------------------------------
    # AGOTADO
    # --------------------------------------------------------

    if estado == "agotado":

        estadisticas[clave]["agotado"] += 1

        if clave == "viernes":
            ESTADO_VIERNES = "agotado"
        else:
            ESTADO_SABADO = "agotado"

        print(
            f"📊 {nombre_fecha(clave)} "
            f"→ agotado"
        )

        # Solo avisar cuando cambia hacia agotado.
        if anterior != "agotado":

            mensaje = (
                "🔴 BTS WORLD TOUR\n\n"
                f"📅 {nombre_fecha(clave)}\n"
                "🎟️ ESTADO: AGOTADO\n\n"
                "Ticketmaster no muestra entradas "
                "disponibles en este momento."
                + enlace_acceso_por_fecha(clave)
            )

            enviar_telegram(mensaje)

        return "agotado"

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if estado == "disponible":

        estadisticas[clave]["disponible"] += 1

        if clave == "viernes":

            ESTADO_VIERNES = "disponible"

            ultimo_aviso = (
                ULTIMO_AVISO_DISPONIBLE_VIERNES
            )

        else:

            ESTADO_SABADO = "disponible"

            ultimo_aviso = (
                ULTIMO_AVISO_DISPONIBLE_SABADO
            )

        print(
            f"🟢 {nombre_fecha(clave)} "
            f"→ DISPONIBLE"
        )

        # ----------------------------------------------------
        # Avisar inmediatamente al detectar disponibilidad.
        # Después, repetir cada 30 segundos.
        # ----------------------------------------------------

        if (
            anterior != "disponible"
            or ahora - ultimo_aviso >= 30
        ):

            mensaje = (
                "🚨🚨🚨 BTS WORLD TOUR 🚨🚨🚨\n\n"
                f"📅 {nombre_fecha(clave)}\n"
                "🟢 ¡BOLETAS DISPONIBLES!\n\n"
                "⚡ Ticketmaster está mostrando "
                "indicadores de disponibilidad."
                + enlace_acceso_por_fecha(clave)
            )

            if enviar_telegram(mensaje):

                if clave == "viernes":

                    ULTIMO_AVISO_DISPONIBLE_VIERNES = (
                        ahora
                    )

                else:

                    ULTIMO_AVISO_DISPONIBLE_SABADO = (
                        ahora
                    )

        return "disponible"

    return estado


# ============================================================
# REVISAR UNA FECHA
# ============================================================

def revisar_fecha(
    clave,
    url
):

    print(
        f"🔎 Revisando: "
        f"{nombre_fecha(clave)}"
    )

    # --------------------------------------------------------
    # CARGAR
    # --------------------------------------------------------

    if not cargar_pagina(url):

        procesar_resultado(
            clave,
            "error"
        )

        return "error"

    # --------------------------------------------------------
    # OBTENER CONTENIDO
    # --------------------------------------------------------

    contenido = obtener_contenido()

    if contenido is None:

        procesar_resultado(
            clave,
            "error"
        )

        return "error"

    # --------------------------------------------------------
    # DETECTAR
    # --------------------------------------------------------

    estado = detectar_estado(
        contenido
    )

    # --------------------------------------------------------
    # SI ES BLOQUEO
    # --------------------------------------------------------

    if estado == "bloqueado":

        procesar_resultado(
            clave,
            "bloqueado"
        )

        return "bloqueado"

    # --------------------------------------------------------
    # RESULTADO NORMAL
    # --------------------------------------------------------

    return procesar_resultado(
        clave,
        estado
    )


# ============================================================
# HEARTBEAT
# ============================================================

def enviar_heartbeat():

    global ULTIMO_HEARTBEAT

    ahora = time.time()

    if (
        ahora - ULTIMO_HEARTBEAT
        < HEARTBEAT_SEGUNDOS
    ):

        return

    ULTIMO_HEARTBEAT = ahora

    mensaje = (
        "💓 HEARTBEAT BOT BTS\n\n"

        "🤖 El bot continúa funcionando.\n\n"

        "📅 VIERNES 2 DE OCTUBRE\n"
        f"Estado: {ESTADO_VIERNES or 'sin estado válido'}\n"
        f"Revisiones: "
        f"{estadisticas['viernes']['revisiones']}\n"
        f"🟢 Disponibles: "
        f"{estadisticas['viernes']['disponible']}\n"
        f"🔴 Agotado: "
        f"{estadisticas['viernes']['agotado']}\n"
        f"🛑 Bloqueado: "
        f"{estadisticas['viernes']['bloqueado']}\n"
        f"❓ Desconocido: "
        f"{estadisticas['viernes']['desconocido']}\n"
        f"❌ Errores: "
        f"{estadisticas['viernes']['errores']}\n\n"

        "📅 SÁBADO 3 DE OCTUBRE\n"
        f"Estado: {ESTADO_SABADO or 'sin estado válido'}\n"
        f"Revisiones: "
        f"{estadisticas['sabado']['revisiones']}\n"
        f"🟢 Disponibles: "
        f"{estadisticas['sabado']['disponible']}\n"
        f"🔴 Agotado: "
        f"{estadisticas['sabado']['agotado']}\n"
        f"🛑 Bloqueado: "
        f"{estadisticas['sabado']['bloqueado']}\n"
        f"❓ Desconocido: "
        f"{estadisticas['sabado']['desconocido']}\n"
        f"❌ Errores: "
        f"{estadisticas['sabado']['errores']}\n\n"

        "⏱️ Revisión automática activa."
    )

    enviar_telegram(mensaje)

    print()
    print("💓 HEARTBEAT ENVIADO")
    print()


# ============================================================
# ESPERAR
# ============================================================

def esperar_intervalo():

    segundos = random.randint(
        INTERVALO_MIN,
        INTERVALO_MAX
    )

    print(
        f"⏳ Esperando {segundos}s"
    )

    for restante in range(
        segundos,
        0,
        -1
    ):

        time.sleep(1)

        # No imprimimos cada segundo.
        # Así Railway queda mucho más limpio.

    return


# ============================================================
# RECUPERACIÓN AUTOMÁTICA
# ============================================================

def manejar_recuperacion(
    resultados
):

    # Si hubo error real de Selenium,
    # recuperamos Chrome.

    if "error" in resultados:

        print()
        print(
            "⚠️ Se detectó un error real de Selenium."
        )

        recuperar_driver()

        return

    # Si Ticketmaster está bloqueando la sesión,
    # no hacemos escaneos adicionales.
    #
    # Esperamos y reiniciamos Chrome.
    #
    # Esto NO intenta saltarse la protección.

    if "bloqueado" in resultados:

        print()
        print(
            "🛑 Ticketmaster está mostrando "
            "una página de protección."
        )

        print(
            "⏳ Esperando antes de reiniciar Chrome..."
        )

        time.sleep(30)

        recuperar_driver()


# ============================================================
# INICIO
# ============================================================

def mensaje_inicio():

    return (
        "🤖 BOT BTS INICIADO\n\n"

        "📅 Monitoreando:\n"
        "• Viernes 2 de octubre de 2026\n"
        "• Sábado 3 de octubre de 2026\n\n"

        "⏱️ Revisión aproximada cada "
        "20–30 segundos.\n"

        "💓 Heartbeat cada 5 horas.\n\n"

        "🔴 Se avisa cuando una fecha pasa "
        "a agotado.\n"

        "🟢 Se avisa inmediatamente si aparecen "
        "indicadores de disponibilidad.\n\n"

        "🛑 Las páginas de protección de Ticketmaster "
        "se tratan como bloqueo temporal y NO como "
        "desconocido.\n\n"

        "🔗 Viernes:\n"
        f"{LINK_VIERNES}\n\n"

        "🔗 Sábado:\n"
        f"{LINK_SABADO}"
    )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    global driver

    print()
    print("=" * 65)
    print("🤖 BOT BTS - TICKETMASTER COLOMBIA")
    print("=" * 65)

    print()
    print("⏱️ Revisión cada 20–30s")
    print("💓 Heartbeat cada 5 horas")

    print()
    print("📅 VIERNES 2 DE OCTUBRE:")
    print(LINK_VIERNES)

    print()
    print("📅 SÁBADO 3 DE OCTUBRE:")
    print(LINK_SABADO)

    print("=" * 65)

    # --------------------------------------------------------
    # INICIAR CHROME
    # --------------------------------------------------------

    driver = crear_driver()

    if driver is None:

        print(
            "❌ No fue posible iniciar Chrome."
        )

        enviar_telegram(
            "❌ BOT BTS\n\n"
            "No fue posible iniciar Chrome. "
            "El bot intentará recuperarse automáticamente."
        )

    else:

        enviar_telegram(
            mensaje_inicio()
        )

    # --------------------------------------------------------
    # LOOP INFINITO
    # --------------------------------------------------------

    while True:

        try:

            print()
            print("=" * 65)

            hora = datetime.now().strftime(
                "%H:%M:%S"
            )

            print(
                f"🔄 NUEVO CICLO - {hora}"
            )

            print("=" * 65)

            resultados = []

            # =================================================
            # SÁBADO
            # =================================================

            estadisticas["sabado"]["revisiones"] += 1

            resultado_sabado = revisar_fecha(
                "sabado",
                LINK_SABADO
            )

            resultados.append(
                resultado_sabado
            )

            # =================================================
            # VIERNES
            # =================================================

            estadisticas["viernes"]["revisiones"] += 1

            resultado_viernes = revisar_fecha(
                "viernes",
                LINK_VIERNES
            )

            resultados.append(
                resultado_viernes
            )

            # =================================================
            # RECUPERACIÓN
            # =================================================

            manejar_recuperacion(
                resultados
            )

            # =================================================
            # HEARTBEAT
            # =================================================

            enviar_heartbeat()

            # =================================================
            # ESPERA
            # =================================================

            esperar_intervalo()

        except KeyboardInterrupt:

            print()
            print(
                "🛑 Bot detenido manualmente."
            )

            cerrar_driver()

            break

        except Exception as e:

            print()
            print(
                "💥 ERROR GENERAL DEL BOT:"
            )

            print(e)

            try:

                enviar_telegram(
                    "⚠️ BOT BTS\n\n"
                    "Se presentó un error general. "
                    "El bot intentará recuperarse automáticamente."
                )

            except Exception:
                pass

            recuperar_driver()

            time.sleep(15)


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
