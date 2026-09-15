# ============================================================
# BOT BTS - TICKETMASTER COLOMBIA
# MONITOR DE DISPONIBILIDAD + TELEGRAM
#
# FUNCIONES:
# - Monitoreo de viernes 2 de octubre de 2026
# - Monitoreo de sábado 3 de octubre de 2026
# - Detección de AGOTADO mediante texto + HTML
# - Detección de DISPONIBLE mediante indicadores explícitos
# - No cambia el estado si el resultado es DESCONOCIDO
# - Alerta inmediata cuando aparece disponibilidad
# - Repite alerta cada 30 segundos mientras haya disponibilidad
# - Alerta cuando una fecha vuelve a AGOTADO
# - Heartbeat cada 5 horas con estadísticas
# - Recuperación automática de Chrome/Selenium
# - Máximo 10 errores consecutivos de Telegram
#
# NO realiza compras.
# NO intenta evadir CAPTCHA ni protecciones.
# ============================================================


import os
import json
import time
import signal
import unicodedata
import re
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


# Orden de revisión:
# primero sábado, después viernes.
EVENTOS = [
    {
        "nombre": "Sábado 3 de octubre de 2026",
        "clave": "sabado",
        "url": LINK_SABADO,
    },
    {
        "nombre": "Viernes 2 de octubre de 2026",
        "clave": "viernes",
        "url": LINK_VIERNES,
    },
]


# ============================================================
# TIEMPOS
# ============================================================

INTERVALO_REVISION = 30

INTERVALO_HEARTBEAT = 5 * 60 * 60

PAGE_LOAD_TIMEOUT = 45

ESPERA_DESPUES_DE_CARGA = 3

MAX_INTENTOS_CHROME = 3

MAX_ERRORES_TELEGRAM = 10


# ============================================================
# ARCHIVO DE ESTADO
# ============================================================

ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"


# ============================================================
# DRIVER
# ============================================================

driver = None


# ============================================================
# ESTADO ACTUAL
# ============================================================

estado_actual = {
    "sabado": "desconocido",
    "viernes": "desconocido",
}


# Última vez que se envió alerta de disponibilidad.
ultimo_aviso_disponibilidad = {
    "sabado": 0,
    "viernes": 0,
}


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
    "recuperaciones_chrome": 0,

    "alertas_disponibilidad": 0,
    "alertas_agotado": 0,

    "ultimo_heartbeat": None,
}


# ============================================================
# ERRORES TELEGRAM
# ============================================================

errores_telegram_consecutivos = 0


# ============================================================
# EJECUCIÓN
# ============================================================

ejecutando = True


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

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

    texto = re.sub(
        r"\s+",
        " ",
        texto,
    )

    return texto.strip()


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
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje):

    global errores_telegram_consecutivos

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ TOKEN o CHAT_ID no están configurados."
        )

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TOKEN}/sendMessage"
    )

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

                print(
                    "✅ Telegram volvió a funcionar."
                )

            errores_telegram_consecutivos = 0

            return True

        errores_telegram_consecutivos += 1

        if (
            errores_telegram_consecutivos
            <= MAX_ERRORES_TELEGRAM
        ):

            print(
                "⚠️ Error Telegram "
                f"{errores_telegram_consecutivos}/"
                f"{MAX_ERRORES_TELEGRAM}: "
                f"HTTP {respuesta.status_code}"
            )

        return False

    except Exception as e:

        errores_telegram_consecutivos += 1

        if (
            errores_telegram_consecutivos
            <= MAX_ERRORES_TELEGRAM
        ):

            print(
                "⚠️ Error Telegram "
                f"{errores_telegram_consecutivos}/"
                f"{MAX_ERRORES_TELEGRAM}: "
                f"{type(e).__name__}"
            )

        return False


# ============================================================
# GUARDAR ESTADO
# ============================================================

def guardar_estado():

    try:

        datos = {

            "estado_actual": estado_actual,

            "ultimo_aviso_disponibilidad":
                ultimo_aviso_disponibilidad,

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
            "⚠️ No se pudo guardar el estado: "
            f"{type(e).__name__}"
        )


# ============================================================
# CARGAR ESTADO
# ============================================================

def cargar_estado():

    global estado_actual
    global ultimo_aviso_disponibilidad

    try:

        if not os.path.exists(
            ARCHIVO_ESTADO
        ):

            return

        with open(
            ARCHIVO_ESTADO,
            "r",
            encoding="utf-8",
        ) as archivo:

            datos = json.load(archivo)

        estados = datos.get(
            "estado_actual",
            {},
        )

        if isinstance(estados, dict):

            for clave in (
                "sabado",
                "viernes",
            ):

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

            for clave in (
                "sabado",
                "viernes",
            ):

                valor = avisos.get(clave)

                if isinstance(
                    valor,
                    (int, float),
                ):

                    ultimo_aviso_disponibilidad[
                        clave
                    ] = valor

        print(
            "💾 Estado anterior cargado."
        )

        print(
            f"   Sábado: "
            f"{estado_actual['sabado']}"
        )

        print(
            f"   Viernes: "
            f"{estado_actual['viernes']}"
        )

    except Exception as e:

        print(
            "⚠️ No se pudo cargar el estado: "
            f"{type(e).__name__}"
        )


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    opciones = Options()

    # Railway / Linux
    opciones.add_argument(
        "--headless=new"
    )

    opciones.add_argument(
        "--no-sandbox"
    )

    opciones.add_argument(
        "--disable-dev-shm-usage"
    )

    # Estabilidad
    opciones.add_argument(
        "--disable-gpu"
    )

    opciones.add_argument(
        "--disable-extensions"
    )

    opciones.add_argument(
        "--disable-notifications"
    )

    opciones.add_argument(
        "--window-size=1365,900"
    )

    # Reducir procesos innecesarios
    opciones.add_argument(
        "--disable-background-networking"
    )

    opciones.add_argument(
        "--disable-background-timer-throttling"
    )

    opciones.add_argument(
        "--disable-renderer-backgrounding"
    )

    # Carga rápida inicial
    opciones.page_load_strategy = "eager"

    nuevo_driver = webdriver.Chrome(
        options=opciones
    )

    nuevo_driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    return nuevo_driver


# ============================================================
# INICIAR CHROME
# ============================================================

def iniciar_chrome():

    global driver

    for intento in range(
        1,
        MAX_INTENTOS_CHROME + 1,
    ):

        try:

            print(
                "🌐 Iniciando Chrome "
                f"(intento {intento}/"
                f"{MAX_INTENTOS_CHROME})..."
            )

            driver = crear_driver()

            print(
                "✅ Chrome iniciado correctamente."
            )

            return True

        except Exception as e:

            estadisticas[
                "errores_chrome"
            ] += 1

            print(
                "⚠️ Error iniciando Chrome: "
                f"{type(e).__name__}"
            )

            try:

                if driver:
                    driver.quit()

            except Exception:
                pass

            driver = None

            if intento < MAX_INTENTOS_CHROME:

                espera = intento * 5

                print(
                    f"🔄 Nuevo intento en "
                    f"{espera}s..."
                )

                time.sleep(espera)

    print(
        "❌ No se pudo iniciar Chrome."
    )

    return False


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global driver

    estadisticas[
        "recuperaciones_chrome"
    ] += 1

    print(
        "🔄 Intentando recuperar Chrome..."
    )

    try:

        if driver:

            driver.quit()

    except Exception:
        pass

    driver = None

    time.sleep(3)

    return iniciar_chrome()


# ============================================================
# OBTENER CONTENIDO
# ============================================================

def obtener_contenido():

    global driver

    if driver is None:
        return None

    try:

        # ----------------------------------------------------
        # TEXTO VISIBLE
        # ----------------------------------------------------

        elemento_body = driver.find_element(
            "tag name",
            "body",
        )

        texto = elemento_body.text

        # ----------------------------------------------------
        # HTML
        # ----------------------------------------------------

        html = driver.page_source

        # ----------------------------------------------------
        # NORMALIZACIÓN
        # ----------------------------------------------------

        return {
            "texto": normalizar_texto(
                texto
            ),

            "html": normalizar_texto(
                html
            ),
        }

    except Exception as e:

        print(
            "⚠️ No se pudo obtener "
            "el contenido: "
            f"{type(e).__name__}"
        )

        return None


# ============================================================
# CARGAR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not iniciar_chrome():

            return None

    try:

        driver.get(url)

        time.sleep(
            ESPERA_DESPUES_DE_CARGA
        )

        return obtener_contenido()

    except TimeoutException:

        print(
            "⚠️ Timeout cargando página."
        )

        return None

    except WebDriverException as e:

        print(
            "⚠️ Error Selenium/Chrome: "
            f"{type(e).__name__}"
        )

        return None

    except Exception as e:

        print(
            "⚠️ Error cargando página: "
            f"{type(e).__name__}"
        )

        return None


# ============================================================
# FRASES DE AGOTADO
# ============================================================

FRASES_AGOTADO = [

    # Español
    "agotado",
    "agotada",
    "agotados",
    "agotadas",

    "entradas agotadas",
    "boletas agotadas",
    "tickets agotados",

    # Inglés
    "sold out",
    "sold-out",
    "soldout",

    "tickets are sold out",
    "event is sold out",

    "unavailable",
    "tickets unavailable",
    "tickets are unavailable",

    # Variaciones
    "no hay entradas",
    "no hay boletas",
    "no hay tickets",

]


# ============================================================
# FRASES DE DISPONIBILIDAD
# ============================================================

FRASES_DISPONIBILIDAD = [

    # Español
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

    # Inglés
    "select your tickets",
    "select your seats",

    "available tickets",
    "tickets available",
    "available seats",

]


# ============================================================
# DETECTAR AGOTADO
# ============================================================

def detectar_agotado(
    texto,
    html,
):

    for frase in FRASES_AGOTADO:

        if frase in texto:
            return True

        if frase in html:
            return True

    return False


# ============================================================
# DETECTAR DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(
    texto,
    html,
):

    for frase in FRASES_DISPONIBILIDAD:

        if frase in texto:
            return True

        if frase in html:
            return True

    return False


# ============================================================
# DETECTAR ESTADO
# ============================================================

def detectar_estado(contenido):

    if contenido is None:

        return "error"

    texto = contenido.get(
        "texto",
        "",
    )

    html = contenido.get(
        "html",
        "",
    )

    # ========================================================
    # PRIMERO AGOTADO
    # ========================================================
    #
    # Es intencional.
    #
    # Si existe una señal explícita de agotado,
    # tiene prioridad sobre cualquier otra palabra.
    #

    if detectar_agotado(
        texto,
        html,
    ):

        return "agotado"

    # ========================================================
    # DESPUÉS DISPONIBLE
    # ========================================================

    if detectar_disponibilidad(
        texto,
        html,
    ):

        return "disponible"

    # ========================================================
    # NO DETERMINADO
    # ========================================================

    return "desconocido"


# ============================================================
# ACTUALIZAR ESTADÍSTICAS
# ============================================================

def actualizar_estadisticas(
    clave,
    estado,
):

    estadisticas[
        "revisiones_totales"
    ] += 1

    if clave == "sabado":

        estadisticas[
            "revisiones_sabado"
        ] += 1

        if estado == "disponible":

            estadisticas[
                "disponibles_sabado"
            ] += 1

        elif estado == "agotado":

            estadisticas[
                "agotados_sabado"
            ] += 1

        elif estado == "desconocido":

            estadisticas[
                "desconocidos_sabado"
            ] += 1

        elif estado == "error":

            estadisticas[
                "errores_sabado"
            ] += 1

    elif clave == "viernes":

        estadisticas[
            "revisiones_viernes"
        ] += 1

        if estado == "disponible":

            estadisticas[
                "disponibles_viernes"
            ] += 1

        elif estado == "agotado":

            estadisticas[
                "agotados_viernes"
            ] += 1

        elif estado == "desconocido":

            estadisticas[
                "desconocidos_viernes"
            ] += 1

        elif estado == "error":

            estadisticas[
                "errores_viernes"
            ] += 1


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    evento,
    nuevo_estado,
):

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

    # ========================================================
    # ERROR
    # ========================================================

    if nuevo_estado == "error":

        print(
            f"❌ {url} → error"
        )

        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if nuevo_estado == "desconocido":

        print(
            f"❓ {url} → desconocido"
        )

        # NO modificamos el estado anterior.

        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if nuevo_estado == "agotado":

        print(
            f"📊 {url} → agotado"
        )

        estado_actual[clave] = (
            "agotado"
        )

        # Solo avisar si acaba de entrar
        # en estado agotado.

        if anterior != "agotado":

            mensaje = (
                "🔴 BTS TICKETMASTER\n\n"
                f"📅 {nombre}\n"
                "❌ ESTADO: AGOTADO"
                + enlace_acceso_por_fecha(
                    clave
                )
            )

            if enviar_telegram(
                mensaje
            ):

                estadisticas[
                    "alertas_agotado"
                ] += 1

        guardar_estado()

        return

    # ========================================================
    # DISPONIBLE
    # ========================================================

    if nuevo_estado == "disponible":

        print(
            f"🟢 {url} → disponible"
        )

        ahora = time.time()

        ultima_alerta = (
            ultimo_aviso_disponibilidad.get(
                clave,
                0,
            )
        )

        # Primera detección:
        # avisar inmediatamente.
        #
        # Si sigue disponible:
        # volver a avisar cada 30 segundos.

        debe_avisar = (

            anterior != "disponible"

            or

            (
                ahora - ultima_alerta
                >= INTERVALO_REVISION
            )

        )

        estado_actual[clave] = (
            "disponible"
        )

        if debe_avisar:

            mensaje = (
                "🚨🚨🚨 BTS TICKETMASTER 🚨🚨🚨\n\n"
                f"📅 {nombre}\n"
                "🟢 ¡HAY DISPONIBILIDAD!\n\n"
                "⚡ REVISA AHORA"
                + enlace_acceso_por_fecha(
                    clave
                )
            )

            if enviar_telegram(
                mensaje
            ):

                estadisticas[
                    "alertas_disponibilidad"
                ] += 1

                ultimo_aviso_disponibilidad[
                    clave
                ] = ahora

        guardar_estado()

        return


# ============================================================
# REVISAR EVENTO
# ============================================================

def revisar_evento(evento):

    nombre = evento["nombre"]
    url = evento["url"]

    print()
    print(
        f"🔎 Revisando: {nombre}"
    )

    contenido = cargar_pagina(
        url
    )

    if contenido is None:

        procesar_resultado(
            evento,
            "error",
        )

        return False

    estado = detectar_estado(
        contenido
    )

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

    mensaje = (

        "💓 HEARTBEAT BTS BOT\n\n"

        f"🕐 Hora: {ahora}\n"
        f"🚀 Inicio: "
        f"{estadisticas['inicio']}\n\n"

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

        f"• Detectado disponible: "
        f"{estadisticas['disponibles_sabado']}\n"

        f"• Detectado agotado: "
        f"{estadisticas['agotados_sabado']}\n"

        f"• Desconocido: "
        f"{estadisticas['desconocidos_sabado']}\n"

        f"• Errores: "
        f"{estadisticas['errores_sabado']}\n\n"


        "📅 VIERNES 2 DE OCTUBRE\n"

        f"• Estado actual: "
        f"{estado_actual['viernes'].upper()}\n"

        f"• Revisiones: "
        f"{estadisticas['revisiones_viernes']}\n"

        f"• Detectado disponible: "
        f"{estadisticas['disponibles_viernes']}\n"

        f"• Detectado agotado: "
        f"{estadisticas['agotados_viernes']}\n"

        f"• Desconocido: "
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

    mensaje = generar_heartbeat()

    estadisticas[
        "ultimo_heartbeat"
    ] = datetime.now().isoformat()

    print()
    print(
        "💓 HEARTBEAT: enviando estadísticas..."
    )

    enviar_telegram(
        mensaje
    )


# ============================================================
# RECUPERACIÓN ANTE SEÑALES
# ============================================================

def detener_bot(
    signum,
    frame,
):

    global ejecutando

    print()
    print(
        "🛑 Señal de apagado recibida."
    )

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
# ESPERA
# ============================================================

def esperar_intervalo(
    segundos,
):

    fin = (
        time.time()
        + segundos
    )

    while ejecutando:

        restante = int(
            fin - time.time()
        )

        if restante <= 0:
            break

        print(
            f"⏳ Esperando {restante}s",
            end="\r",
            flush=True,
        )

        time.sleep(
            min(5, restante)
        )

    print()


# ============================================================
# MAIN
# ============================================================

def main():

    global driver

    print("=" * 65)
    print(
        "🚀 BOT BTS - TICKETMASTER COLOMBIA"
    )
    print("=" * 65)

    print()
    print(
        "📅 SÁBADO 3 DE OCTUBRE:"
    )
    print(
        LINK_SABADO
    )

    print()
    print(
        "📅 VIERNES 2 DE OCTUBRE:"
    )
    print(
        LINK_VIERNES
    )

    print()
    print(
        f"⏱️ Revisión cada "
        f"{INTERVALO_REVISION}s"
    )

    print(
        "💓 Heartbeat cada 5 horas"
    )

    print()

    # --------------------------------------------------------
    # ESTADO
    # --------------------------------------------------------

    cargar_estado()

    # --------------------------------------------------------
    # CHROME
    # --------------------------------------------------------

    chrome_ok = iniciar_chrome()

    if chrome_ok:

        enviar_telegram(
            "🟢 BTS BOT INICIADO\n\n"
            "El monitor está activo.\n"
            "Se revisarán las dos fechas."
        )

    else:

        enviar_telegram(
            "⚠️ BTS BOT\n\n"
            "Chrome no pudo iniciarse "
            "inicialmente.\n"
            "El bot continuará intentando "
            "recuperarlo."
        )

    # --------------------------------------------------------
    # HEARTBEAT
    # --------------------------------------------------------

    ultimo_heartbeat = time.time()

    # --------------------------------------------------------
    # LOOP
    # --------------------------------------------------------

    while ejecutando:

        inicio_ciclo = time.time()

        print()
        print("=" * 65)

        print(
            "🔄 NUEVO CICLO - "
            + datetime.now().strftime(
                "%H:%M:%S"
            )
        )

        print("=" * 65)

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

                # Si hubo error con Selenium,
                # recuperamos Chrome.

                if not correcto:

                    print(
                        "🔄 Error detectado. "
                        "Iniciando recuperación..."
                    )

                    recuperado = (
                        recuperar_chrome()
                    )

                    if recuperado:

                        print(
                            "✅ Chrome recuperado."
                        )

                    else:

                        print(
                            "⚠️ Chrome continúa "
                            "sin recuperarse."
                        )

            except Exception as e:

                print(
                    "⚠️ Error inesperado: "
                    f"{type(e).__name__}"
                )

                try:

                    recuperado = (
                        recuperar_chrome()
                    )

                    if recuperado:

                        print(
                            "✅ Recuperación completada."
                        )

                except Exception as error_recuperacion:

                    print(
                        "❌ Falló recuperación: "
                        f"{type(error_recuperacion).__name__}"
                    )

        # ----------------------------------------------------
        # HEARTBEAT
        # ----------------------------------------------------

        ahora = time.time()

        if (
            ahora - ultimo_heartbeat
            >= INTERVALO_HEARTBEAT
        ):

            enviar_heartbeat()

            ultimo_heartbeat = ahora

        # ----------------------------------------------------
        # CALCULAR ESPERA
        # ----------------------------------------------------

        tiempo_ciclo = (
            time.time()
            - inicio_ciclo
        )

        espera = max(
            1,
            INTERVALO_REVISION
            - tiempo_ciclo,
        )

        print()

        print(
            f"⏳ Esperando "
            f"{int(espera)}s"
        )

        esperar_intervalo(
            espera
        )

    # --------------------------------------------------------
    # APAGADO
    # --------------------------------------------------------

    print()
    print(
        "🛑 Cerrando bot..."
    )

    cerrar_chrome()

    print(
        "✅ Bot detenido correctamente."
    )


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "🛑 Bot detenido manualmente."
        )

    except Exception as e:

        print()
        print(
            "❌ ERROR CRÍTICO: "
            f"{type(e).__name__}"
        )

        try:

            enviar_telegram(
                "⚠️ BTS BOT\n\n"
                "Se produjo un error crítico."
            )

        except Exception:
            pass

    finally:

        cerrar_chrome()
