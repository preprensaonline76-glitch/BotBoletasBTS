# ============================================================
# BOT BTS - TICKETMASTER COLOMBIA
# MONITOR DE DISPONIBILIDAD + TELEGRAM
#
# Objetivos:
# - Monitorear las dos fechas de BTS.
# - Detectar AGOTADO / DISPONIBLE.
# - No cambiar el estado ante un resultado DESCONOCIDO.
# - Avisar inmediatamente cuando aparece disponibilidad.
# - Repetir aviso cada 30 s mientras siga disponible.
# - Avisar cuando una fecha vuelve a agotarse.
# - Heartbeat cada 5 horas con estadísticas.
# - Recuperar Chrome/Selenium automáticamente ante errores.
# - Mantener el proceso sencillo para evitar crashes.
#
# NO realiza compras.
# NO intenta saltarse CAPTCHA ni protecciones.
# ============================================================

import os
import re
import json
import time
import signal
import unicodedata
from datetime import datetime

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
)


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

EVENTOS = [
    {
        "nombre": "Sábado 3 de octubre de 2026",
        "url": LINK_SABADO,
        "clave": "sabado",
    },
    {
        "nombre": "Viernes 2 de octubre de 2026",
        "url": LINK_VIERNES,
        "clave": "viernes",
    },
]


# ============================================================
# TIEMPOS
# ============================================================

INTERVALO_REVISION = 30
INTERVALO_HEARTBEAT = 5 * 60 * 60

PAGE_LOAD_TIMEOUT = 45

MAX_INTENTOS_RECUPERACION = 3

MAX_ERRORES_TELEGRAM = 10


# ============================================================
# ARCHIVO DE ESTADO
# ============================================================

ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"


# ============================================================
# ESTADÍSTICAS
# ============================================================

estadisticas = {
    "inicio": datetime.now().isoformat(),

    "revisiones_totales": 0,

    "revisiones_sabado": 0,
    "revisiones_viernes": 0,

    "disponibles_sabado": 0,
    "disponibles_viernes": 0,

    "agotados_sabado": 0,
    "agotados_viernes": 0,

    "desconocidos_sabado": 0,
    "desconocidos_viernes": 0,

    "errores_sabado": 0,
    "errores_viernes": 0,

    "errores_chrome": 0,

    "alertas_disponibilidad": 0,
    "alertas_agotado": 0,

    "recuperaciones_chrome": 0,

    "ultimo_heartbeat": None,
}


# ============================================================
# ESTADO ACTUAL
# ============================================================

estado_actual = {
    "sabado": "desconocido",
    "viernes": "desconocido",
}

ultimo_aviso_disponibilidad = {
    "sabado": 0,
    "viernes": 0,
}


# ============================================================
# TELEGRAM
# ============================================================

errores_telegram_consecutivos = 0


def enviar_telegram(mensaje):
    """
    Envía un mensaje a Telegram.

    Si Telegram falla:
    - registra el error;
    - intenta continuar;
    - después de 10 errores consecutivos deja de imprimir
      el mismo tipo de error constantemente.

    Cuando Telegram vuelve a funcionar, el contador se reinicia.
    """

    global errores_telegram_consecutivos

    if not TOKEN or not CHAT_ID:
        print("⚠️ TOKEN o CHAT_ID no están configurados.")
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
            json=datos,
            timeout=20,
        )

        if respuesta.ok:
            if errores_telegram_consecutivos > 0:
                print("✅ Telegram volvió a funcionar.")

            errores_telegram_consecutivos = 0
            return True

        errores_telegram_consecutivos += 1

        if errores_telegram_consecutivos <= MAX_ERRORES_TELEGRAM:
            print(
                f"⚠️ Error Telegram "
                f"{errores_telegram_consecutivos}/"
                f"{MAX_ERRORES_TELEGRAM}: "
                f"HTTP {respuesta.status_code}"
            )

        return False

    except Exception as e:

        errores_telegram_consecutivos += 1

        if errores_telegram_consecutivos <= MAX_ERRORES_TELEGRAM:
            print(
                f"⚠️ Error Telegram "
                f"{errores_telegram_consecutivos}/"
                f"{MAX_ERRORES_TELEGRAM}: "
                f"{type(e).__name__}"
            )

        return False


# ============================================================
# NORMALIZACIÓN DE TEXTO
# ============================================================

def normalizar_texto(texto):
    """
    Convierte el texto a una forma sencilla para comparar
    palabras independientemente de mayúsculas/minúsculas
    y algunos acentos.
    """

    if not texto:
        return ""

    texto = texto.lower()

    texto = unicodedata.normalize(
        "NFD",
        texto,
    )

    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ============================================================
# ENLACE SEGÚN FECHA
# ============================================================

def enlace_acceso_por_fecha(clave):
    """
    MUY IMPORTANTE:
    Cada alerta contiene solamente el enlace correspondiente
    a su fecha.
    """

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
# ESTADO EN DISCO
# ============================================================

def cargar_estado():

    global estado_actual
    global ultimo_aviso_disponibilidad

    try:

        if not os.path.exists(ARCHIVO_ESTADO):
            return

        with open(
            ARCHIVO_ESTADO,
            "r",
            encoding="utf-8",
        ) as archivo:

            datos = json.load(archivo)

        estados = datos.get("estado_actual", {})

        if isinstance(estados, dict):

            for clave in ("sabado", "viernes"):

                valor = estados.get(clave)

                if valor in (
                    "agotado",
                    "disponible",
                    "desconocido",
                ):
                    estado_actual[clave] = valor

        avisos = datos.get(
            "ultimo_aviso_disponibilidad",
            {},
        )

        if isinstance(avisos, dict):

            for clave in ("sabado", "viernes"):

                valor = avisos.get(clave)

                if isinstance(valor, (int, float)):
                    ultimo_aviso_disponibilidad[clave] = valor

        print("💾 Estado anterior cargado.")

    except Exception as e:

        print(
            f"⚠️ No se pudo cargar el estado: "
            f"{type(e).__name__}"
        )


def guardar_estado():

    try:

        datos = {
            "estado_actual": estado_actual,
            "ultimo_aviso_disponibilidad": (
                ultimo_aviso_disponibilidad
            ),
        }

        with open(
            ARCHIVO_ESTADO,
            "w",
            encoding="utf-8",
        ) as archivo:

            json.dump(
                datos,
                archivo,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as e:

        print(
            f"⚠️ No se pudo guardar el estado: "
            f"{type(e).__name__}"
        )


# ============================================================
# CHROME
# ============================================================

driver = None


def crear_driver():

    opciones = Options()

    # Ejecución en Railway/Linux
    opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")

    # Estabilidad
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--disable-extensions")
    opciones.add_argument("--disable-notifications")
    opciones.add_argument("--window-size=1365,900")

    # Menos carga de recursos
    opciones.add_argument("--disable-background-networking")
    opciones.add_argument("--disable-background-timer-throttling")
    opciones.add_argument("--disable-renderer-backgrounding")

    # No usamos técnicas de evasión.
    # No se intenta modificar la identidad de Selenium.

    opciones.page_load_strategy = "eager"

    nuevo_driver = webdriver.Chrome(
        options=opciones
    )

    nuevo_driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    return nuevo_driver


def iniciar_chrome():

    global driver

    for intento in range(1, MAX_INTENTOS_RECUPERACION + 1):

        try:

            print(
                f"🌐 Iniciando Chrome "
                f"(intento {intento}/"
                f"{MAX_INTENTOS_RECUPERACION})..."
            )

            driver = crear_driver()

            print("✅ Chrome iniciado correctamente.")

            return True

        except Exception as e:

            estadisticas["errores_chrome"] += 1

            print(
                f"⚠️ No se pudo iniciar Chrome: "
                f"{type(e).__name__}"
            )

            try:

                if driver:
                    driver.quit()

            except Exception:
                pass

            driver = None

            if intento < MAX_INTENTOS_RECUPERACION:

                espera = intento * 5

                print(
                    f"🔄 Reintentando Chrome en "
                    f"{espera}s..."
                )

                time.sleep(espera)

    print("❌ No fue posible iniciar Chrome.")

    return False


def recuperar_chrome():

    global driver

    estadisticas["recuperaciones_chrome"] += 1

    print("🔄 Recuperando Chrome...")

    try:

        if driver:
            driver.quit()

    except Exception:
        pass

    driver = None

    time.sleep(3)

    return iniciar_chrome()


# ============================================================
# CARGA DE PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not iniciar_chrome():
            return None

    try:

        driver.get(url)

        # Espera corta.
        # No hacemos análisis pesado del DOM.
        time.sleep(3)

        return obtener_contenido()

    except TimeoutException:

        print("⚠️ Timeout cargando la página.")

        return None

    except WebDriverException as e:

        print(
            f"⚠️ Error Selenium/Chrome: "
            f"{type(e).__name__}"
        )

        return None

    except Exception as e:

        print(
            f"⚠️ Error cargando página: "
            f"{type(e).__name__}"
        )

        return None


# ============================================================
# OBTENER CONTENIDO
# ============================================================

def obtener_contenido():

    global driver

    if driver is None:
        return None

    try:

        # Solamente obtenemos el texto visible.
        #
        # Esto es deliberadamente ligero.
        # No recorremos body *.
        # No buscamos iframes.
        # No recorremos Shadow DOM.

        texto = driver.find_element(
            "tag name",
            "body",
        ).text

        if texto:
            return normalizar_texto(texto)

        return ""

    except Exception as e:

        print(
            f"⚠️ No se pudo leer la página: "
            f"{type(e).__name__}"
        )

        return None


# ============================================================
# DETECCIÓN DE AGOTADO
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
    "tickets are sold out",
    "event is sold out",

    "unavailable",
    "tickets unavailable",
    "tickets are unavailable",

    "no hay entradas",
    "no hay boletas",
    "no hay tickets",

]


def detectar_agotado(texto):

    if not texto:
        return False

    for frase in FRASES_AGOTADO:

        if frase in texto:
            return True

    return False


# ============================================================
# DETECCIÓN DE DISPONIBILIDAD
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


def detectar_disponibilidad(texto):

    if not texto:
        return False

    for frase in FRASES_DISPONIBILIDAD:

        if frase in texto:
            return True

    return False


# ============================================================
# DETECTAR ESTADO
# ============================================================

def detectar_estado(texto):

    if texto is None:
        return "error"

    if not texto:
        return "desconocido"

    # IMPORTANTE:
    # Primero comprobamos AGOTADO.
    #
    # Esto evita interpretar como disponible una página
    # que contiene otras palabras relacionadas con tickets
    # pero que realmente está agotada.

    if detectar_agotado(texto):
        return "agotado"

    if detectar_disponibilidad(texto):
        return "disponible"

    return "desconocido"


# ============================================================
# ESTADÍSTICAS POR FECHA
# ============================================================

def actualizar_estadisticas(clave, estado):

    estadisticas["revisiones_totales"] += 1

    if clave == "sabado":
        estadisticas["revisiones_sabado"] += 1

        if estado == "disponible":
            estadisticas["disponibles_sabado"] += 1

        elif estado == "agotado":
            estadisticas["agotados_sabado"] += 1

        elif estado == "desconocido":
            estadisticas["desconocidos_sabado"] += 1

        elif estado == "error":
            estadisticas["errores_sabado"] += 1

    elif clave == "viernes":
        estadisticas["revisiones_viernes"] += 1

        if estado == "disponible":
            estadisticas["disponibles_viernes"] += 1

        elif estado == "agotado":
            estadisticas["agotados_viernes"] += 1

        elif estado == "desconocido":
            estadisticas["desconocidos_viernes"] += 1

        elif estado == "error":
            estadisticas["errores_viernes"] += 1


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(evento, nuevo_estado):

    clave = evento["clave"]
    nombre = evento["nombre"]
    url = evento["url"]

    anterior = estado_actual.get(
        clave,
        "desconocido",
    )

    actualizar_estadisticas(
        clave,
        nuevo_estado,
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if nuevo_estado == "error":

        print(
            f"❌ {url} → error"
        )

        return

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    if nuevo_estado == "desconocido":

        print(
            f"❓ {url} → desconocido"
        )

        # MUY IMPORTANTE:
        # NO cambiamos el estado anterior.
        #
        # Si estaba agotado y una carga falla parcialmente,
        # continúa siendo "agotado" hasta obtener evidencia
        # real de otro estado.

        return

    # --------------------------------------------------------
    # AGOTADO
    # --------------------------------------------------------

    if nuevo_estado == "agotado":

        print(
            f"📊 {url} → agotado"
        )

        estado_actual[clave] = "agotado"

        # Avisamos solamente cuando cambia a agotado.

        if anterior != "agotado":

            mensaje = (
                "🔴 BTS TICKETMASTER\n\n"
                f"📅 {nombre}\n"
                "❌ ESTADO: AGOTADO"
                + enlace_acceso_por_fecha(clave)
            )

            if enviar_telegram(mensaje):

                estadisticas["alertas_agotado"] += 1

        guardar_estado()

        return

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if nuevo_estado == "disponible":

        print(
            f"🟢 {url} → disponible"
        )

        ahora = time.time()

        ultima_alerta = ultimo_aviso_disponibilidad.get(
            clave,
            0,
        )

        # Avisar:
        #
        # 1. Si acaba de cambiar a disponible.
        # 2. O si ya estaba disponible pero pasaron
        #    al menos 30 segundos desde el último aviso.

        debe_avisar = (
            anterior != "disponible"
            or ahora - ultima_alerta >= INTERVALO_REVISION
        )

        estado_actual[clave] = "disponible"

        if debe_avisar:

            mensaje = (
                "🚨🚨🚨 BTS TICKETMASTER 🚨🚨🚨\n\n"
                f"📅 {nombre}\n"
                "🟢 ¡HAY DISPONIBILIDAD!\n\n"
                "⚡ REVISA AHORA"
                + enlace_acceso_por_fecha(clave)
            )

            if enviar_telegram(mensaje):

                estadisticas["alertas_disponibilidad"] += 1

                ultimo_aviso_disponibilidad[clave] = ahora

        guardar_estado()

        return


# ============================================================
# REVISAR UNA FECHA
# ============================================================

def revisar_evento(evento):

    global driver

    nombre = evento["nombre"]
    url = evento["url"]

    print()
    print(f"🔎 Revisando: {nombre}")

    texto = cargar_pagina(url)

    # Si cargar_pagina devuelve None, tenemos un problema
    # con Selenium/Chrome y no con el estado de Ticketmaster.

    if texto is None:

        procesar_resultado(
            evento,
            "error",
        )

        return False

    estado = detectar_estado(texto)

    procesar_resultado(
        evento,
        estado,
    )

    return True


# ============================================================
# HEARTBEAT
# ============================================================

def generar_heartbeat():

    ahora = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    inicio = estadisticas["inicio"]

    mensaje = (
        "💓 HEARTBEAT BTS BOT\n\n"

        f"🕐 Fecha: {ahora}\n"
        f"🚀 Inicio: {inicio}\n\n"

        "📊 ESTADÍSTICAS GENERALES\n"
        f"• Revisiones totales: "
        f"{estadisticas['revisiones_totales']}\n"
        f"• Recuperaciones Chrome: "
        f"{estadisticas['recuperaciones_chrome']}\n"
        f"• Errores Chrome: "
        f"{estadisticas['errores_chrome']}\n\n"

        "📅 SÁBADO 3 DE OCTUBRE\n"
        f"• Estado actual: "
        f"{estado_actual['sabado'].upper()}\n"
        f"• Revisiones: "
        f"{estadisticas['revisiones_sabado']}\n"
        f"• Detecciones disponibles: "
        f"{estadisticas['disponibles_sabado']}\n"
        f"• Detecciones agotado: "
        f"{estadisticas['agotados_sabado']}\n"
        f"• Desconocidos: "
        f"{estadisticas['desconocidos_sabado']}\n"
        f"• Errores: "
        f"{estadisticas['errores_sabado']}\n\n"

        "📅 VIERNES 2 DE OCTUBRE\n"
        f"• Estado actual: "
        f"{estado_actual['viernes'].upper()}\n"
        f"• Revisiones: "
        f"{estadisticas['revisiones_viernes']}\n"
        f"• Detecciones disponibles: "
        f"{estadisticas['disponibles_viernes']}\n"
        f"• Detecciones agotado: "
        f"{estadisticas['agotados_viernes']}\n"
        f"• Desconocidos: "
        f"{estadisticas['desconocidos_viernes']}\n"
        f"• Errores: "
        f"{estadisticas['errores_viernes']}\n\n"

        "🚨 ALERTAS\n"
        f"• Disponibilidad: "
        f"{estadisticas['alertas_disponibilidad']}\n"
        f"• Agotado: "
        f"{estadisticas['alertas_agotado']}\n\n"

        "🟢 BOT ACTIVO"
    )

    return mensaje


def enviar_heartbeat():

    estadisticas["ultimo_heartbeat"] = (
        datetime.now().isoformat()
    )

    mensaje = generar_heartbeat()

    print()
    print("💓 Enviando heartbeat...")

    enviar_telegram(mensaje)


# ============================================================
# RECUPERACIÓN ANTE SEÑALES
# ============================================================

ejecutando = True


def detener_bot(signum, frame):

    global ejecutando

    print()
    print("🛑 Señal de apagado recibida.")

    ejecutando = False


signal.signal(
    signal.SIGTERM,
    detener_bot,
)

signal.signal(
    signal.SIGINT,
    detener_bot,
)


# ============================================================
# CERRAR CHROME
# ============================================================

def cerrar_chrome():

    global driver

    try:

        if driver:
            driver.quit()

    except Exception:
        pass

    driver = None


# ============================================================
# BUCLE PRINCIPAL
# ============================================================

def main():

    global driver

    print("=" * 60)
    print("🚀 BOT BTS - TICKETMASTER COLOMBIA")
    print("=" * 60)

    print()
    print("📅 Sábado:")
    print(LINK_SABADO)

    print()
    print("📅 Viernes:")
    print(LINK_VIERNES)

    print()
    print("⏱️ Intervalo:", INTERVALO_REVISION, "segundos")
    print(
        "💓 Heartbeat:",
        INTERVALO_HEARTBEAT // 3600,
        "horas",
    )

    # --------------------------------------------------------
    # CARGAR ESTADO
    # --------------------------------------------------------

    cargar_estado()

    # --------------------------------------------------------
    # INICIAR CHROME
    # --------------------------------------------------------

    if not iniciar_chrome():

        enviar_telegram(
            "❌ BTS BOT\n\n"
            "No fue posible iniciar Chrome después "
            "de varios intentos.\n"
            "El proceso continuará intentando recuperarse."
        )

    else:

        enviar_telegram(
            "🟢 BTS BOT INICIADO\n\n"
            "El monitor está activo.\n"
            "Se están revisando las dos fechas de BTS."
        )

    ultimo_heartbeat = time.time()

    # --------------------------------------------------------
    # LOOP INFINITO
    # --------------------------------------------------------

    while ejecutando:

        inicio_ciclo = time.time()

        print()
        print("=" * 60)
        print(
            "🔄 NUEVO CICLO",
            datetime.now().strftime("%H:%M:%S"),
        )
        print("=" * 60)

        # ----------------------------------------------------
        # REVISAR LAS DOS FECHAS
        # ----------------------------------------------------

        for evento in EVENTOS:

            if not ejecutando:
                break

            try:

                correcto = revisar_evento(
                    evento
                )

                # Si Selenium falló, intentamos recuperar
                # Chrome inmediatamente.

                if not correcto:

                    print(
                        "🔄 Se detectó un error. "
                        "Intentando recuperación..."
                    )

                    if recuperar_chrome():

                        print(
                            "✅ Chrome recuperado."
                        )

                    else:

                        print(
                            "⚠️ Chrome no pudo recuperarse "
                            "en este intento."
                        )

            except Exception as e:

                print(
                    f"⚠️ Error inesperado revisando "
                    f"{evento['nombre']}: "
                    f"{type(e).__name__}"
                )

                # Intento de recuperación.

                try:

                    if recuperar_chrome():

                        print(
                            "✅ Recuperación completada."
                        )

                except Exception as recovery_error:

                    print(
                        "❌ Falló la recuperación: "
                        f"{type(recovery_error).__name__}"
                    )

        # ----------------------------------------------------
        # HEARTBEAT CADA 5 HORAS
        # ----------------------------------------------------

        ahora = time.time()

        if ahora - ultimo_heartbeat >= INTERVALO_HEARTBEAT:

            enviar_heartbeat()

            ultimo_heartbeat = ahora

        # ----------------------------------------------------
        # ESPERA
        # ----------------------------------------------------

        tiempo_transcurrido = (
            time.time() - inicio_ciclo
        )

        espera = max(
            1,
            INTERVALO_REVISION - tiempo_transcurrido,
        )

        print()
        print(
            f"⏳ Esperando {int(espera)}s"
        )

        # Espera dividida en bloques pequeños.
        #
        # Esto permite que Railway pueda detener el proceso
        # correctamente sin dejar un sleep enorme.

        fin_espera = time.time() + espera

        while (
            ejecutando
            and time.time() < fin_espera
        ):

            restante = int(
                fin_espera - time.time()
            )

            if restante > 0:

                print(
                    f"⏳ Esperando {restante}s",
                    end="\r",
                    flush=True,
                )

                time.sleep(
                    min(5, restante)
                )

        print()

    # --------------------------------------------------------
    # APAGADO
    # --------------------------------------------------------

    print()
    print("🛑 Cerrando bot...")

    cerrar_chrome()

    print("✅ Bot detenido correctamente.")


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print("🛑 Bot detenido manualmente.")

    except Exception as e:

        print()
        print(
            f"❌ Error crítico: "
            f"{type(e).__name__}"
        )

        try:

            enviar_telegram(
                "⚠️ BTS BOT\n\n"
                "Se produjo un error crítico. "
                "El proceso intentará ser reiniciado "
                "por el entorno de ejecución."
            )

        except Exception:
            pass

    finally:

        cerrar_chrome()
