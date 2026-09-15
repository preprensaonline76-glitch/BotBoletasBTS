# ============================================================
# BOT BOLETAS BTS - TICKETMASTER COLOMBIA
# ============================================================
#
# FUNCIONES:
# - Monitorear disponibilidad de entradas BTS
# - Viernes 2 de octubre de 2026
# - Sábado 3 de octubre de 2026
# - Enviar alertas por Telegram
# - Repetir alerta de disponibilidad cada 30 segundos
# - Detectar cambio a AGOTADO
# - Recuperar Chrome/Selenium automáticamente
# - Heartbeat cada 5 horas
#
# IMPORTANTE:
# - NO realiza compras
# - NO intenta saltarse CAPTCHA
# - NO intenta evadir sistemas anti-bot
#
# ============================================================

import os
import re
import json
import time
import signal
import requests

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
    SessionNotCreatedException
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


if not TOKEN:
    raise RuntimeError(
        "ERROR: No existe la variable TOKEN en Railway."
    )

if not CHAT_ID:
    raise RuntimeError(
        "ERROR: No existe la variable CHAT_ID en Railway."
    )


# ============================================================
# URLS DE TICKETMASTER
# ============================================================

LINK_VIERNES = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-viernes-2-octubre"
)

LINK_SABADO = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-sabado-3-octubre"
)


URLS = [

    {
        "nombre": "Viernes 2 de octubre de 2026",
        "url": LINK_VIERNES
    },

    {
        "nombre": "Sábado 3 de octubre de 2026",
        "url": LINK_SABADO
    }

]


# ============================================================
# INTERVALOS
# ============================================================

# Tiempo normal entre revisiones
INTERVALO_NORMAL = 30

# Tiempo entre revisiones cuando hay disponibilidad
INTERVALO_DISPONIBLE = 30

# Heartbeat cada 5 horas
INTERVALO_HEARTBEAT = 5 * 60 * 60


# ============================================================
# SELENIUM
# ============================================================

PAGE_LOAD_TIMEOUT = 45

SCRIPT_TIMEOUT = 30

MAX_INTENTOS_CHROME = 3


# ============================================================
# TELEGRAM
# ============================================================

MAX_ERRORES_TELEGRAM = 10


# ============================================================
# ARCHIVO DE ESTADO
# ============================================================

ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"


# ============================================================
# VARIABLES GLOBALES
# ============================================================

driver = None

ejecutando = True

contador_errores_telegram = 0

ultimo_heartbeat = time.time()

contador_revision = 0

estadisticas = {

    "agotado": {
        "Viernes 2 de octubre de 2026": 0,
        "Sábado 3 de octubre de 2026": 0
    },

    "disponible": {
        "Viernes 2 de octubre de 2026": 0,
        "Sábado 3 de octubre de 2026": 0
    },

    "errores": {
        "Viernes 2 de octubre de 2026": 0,
        "Sábado 3 de octubre de 2026": 0
    }

}


# ============================================================
# ESTADO DE LOS EVENTOS
# ============================================================

estado_actual = {

    "Viernes 2 de octubre de 2026": {
        "estado": None,
        "ultimo_aviso_disponible": 0,
        "ultimo_cambio": None
    },

    "Sábado 3 de octubre de 2026": {
        "estado": None,
        "ultimo_aviso_disponible": 0,
        "ultimo_cambio": None
    }

}


# ============================================================
# NORMALIZAR TEXTO
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

    for original, reemplazo in reemplazos.items():

        texto = texto.replace(
            original,
            reemplazo
        )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# ENLACE SEGÚN FECHA
# ============================================================

def enlace_acceso_por_fecha(nombre):

    nombre_normalizado = normalizar_texto(
        nombre
    )

    # --------------------------------------------------------
    # VIERNES
    # --------------------------------------------------------

    if "viernes" in nombre_normalizado:

        return (
            "\n\n"
            "🔗 ACCESO VIERNES 2 DE OCTUBRE:\n"
            f"{LINK_VIERNES}"
        )


    # --------------------------------------------------------
    # SÁBADO
    # --------------------------------------------------------

    if (
        "sabado" in nombre_normalizado
        or "sábado" in nombre.lower()
    ):

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

    global contador_errores_telegram

    url = (
        f"https://api.telegram.org/bot"
        f"{TOKEN}/sendMessage"
    )

    datos = {

        "chat_id": CHAT_ID,

        "text": mensaje,

        "disable_web_page_preview": False

    }


    try:

        respuesta = requests.post(
            url,
            json=datos,
            timeout=20
        )


        if respuesta.status_code == 200:

            # Reiniciar contador de errores
            contador_errores_telegram = 0

            return True


        contador_errores_telegram += 1

        print(
            "⚠️ Error Telegram:",
            respuesta.status_code
        )


    except Exception as e:

        contador_errores_telegram += 1

        print(
            "⚠️ Error enviando Telegram:",
            str(e)
        )


    # --------------------------------------------------------
    # Limitar mensajes de error
    # --------------------------------------------------------

    if (
        contador_errores_telegram
        <= MAX_ERRORES_TELEGRAM
    ):

        try:

            print(
                f"⚠️ Fallo Telegram "
                f"{contador_errores_telegram}/"
                f"{MAX_ERRORES_TELEGRAM}"
            )

        except Exception:
            pass


    return False


# ============================================================
# GUARDAR ESTADO
# ============================================================

def guardar_estado():

    try:

        with open(
            ARCHIVO_ESTADO,
            "w",
            encoding="utf-8"
        ) as archivo:

            json.dump(
                estado_actual,
                archivo,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "⚠️ No se pudo guardar estado:",
            e
        )


# ============================================================
# CARGAR ESTADO
# ============================================================

def cargar_estado():

    global estado_actual

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


        for nombre in estado_actual:

            if nombre in datos:

                estado_actual[nombre].update(
                    datos[nombre]
                )


        print(
            "💾 Estado anterior cargado."
        )


    except Exception as e:

        print(
            "⚠️ No se pudo cargar estado:",
            e
        )


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    print(
        "🚀 Iniciando Chrome..."
    )


    opciones = Options()

    # --------------------------------------------------------
    # MODO HEADLESS
    # --------------------------------------------------------

    opciones.add_argument(
        "--headless=new"
    )

    # --------------------------------------------------------
    # ESTABILIDAD EN RAILWAY
    # --------------------------------------------------------

    opciones.add_argument(
        "--no-sandbox"
    )

    opciones.add_argument(
        "--disable-dev-shm-usage"
    )

    opciones.add_argument(
        "--disable-gpu"
    )

    opciones.add_argument(
        "--disable-software-rasterizer"
    )

    opciones.add_argument(
        "--disable-background-networking"
    )

    opciones.add_argument(
        "--disable-background-timer-throttling"
    )

    opciones.add_argument(
        "--disable-backgrounding-occluded-windows"
    )

    opciones.add_argument(
        "--disable-renderer-backgrounding"
    )

    opciones.add_argument(
        "--disable-features=Translate"
    )

    opciones.add_argument(
        "--disable-extensions"
    )

    opciones.add_argument(
        "--disable-notifications"
    )

    opciones.add_argument(
        "--disable-popup-blocking"
    )

    opciones.add_argument(
        "--disable-infobars"
    )

    opciones.add_argument(
        "--window-size=1920,1080"
    )

    opciones.add_argument(
        "--start-maximized"
    )

    opciones.add_argument(
        "--remote-debugging-port=9222"
    )

    opciones.add_argument(
        "--no-first-run"
    )

    opciones.add_argument(
        "--no-default-browser-check"
    )

    opciones.add_argument(
        "--disable-blink-features=AutomationControlled"
    )


    # --------------------------------------------------------
    # PAGE LOAD STRATEGY
    # --------------------------------------------------------

    opciones.page_load_strategy = "eager"


    # --------------------------------------------------------
    # CREAR DRIVER
    # --------------------------------------------------------

    nuevo_driver = webdriver.Chrome(
        options=opciones
    )


    nuevo_driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    nuevo_driver.set_script_timeout(
        SCRIPT_TIMEOUT
    )


    print(
        "✅ Chrome iniciado correctamente."
    )


    return nuevo_driver


# ============================================================
# CERRAR CHROME
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


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global driver

    print(
        "🔄 RECUPERANDO CHROME..."
    )


    cerrar_driver()


    for intento in range(
        1,
        MAX_INTENTOS_CHROME + 1
    ):

        try:

            print(
                f"🔧 Intento de recuperación "
                f"{intento}/{MAX_INTENTOS_CHROME}"
            )


            driver = crear_driver()


            # Pequeña prueba
            driver.get(
                "https://www.ticketmaster.co/"
            )


            print(
                "✅ Chrome recuperado."
            )


            return True


        except Exception as e:

            print(
                "❌ Error recuperando Chrome:",
                str(e)
            )


            cerrar_driver()

            time.sleep(5)


    print(
        "❌ NO FUE POSIBLE RECUPERAR CHROME."
    )


    return False


# ============================================================
# CARGAR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not recuperar_chrome():

            return False


    try:

        print(
            f"🌐 Cargando:\n{url}"
        )


        driver.get(url)


        # Espera breve para que termine
        # de cargar contenido dinámico.
        time.sleep(3)


        return True


    except TimeoutException:

        print(
            "⚠️ Timeout cargando página."
        )

        return False


    except WebDriverException as e:

        print(
            "❌ WebDriverException:",
            str(e)
        )

        return False


    except Exception as e:

        print(
            "❌ Error cargando página:",
            str(e)
        )

        return False


# ============================================================
# OBTENER CONTENIDO
# ============================================================

def obtener_contenido():

    global driver

    if driver is None:

        return None


    try:

        # ----------------------------------------------------
        # Obtener texto visible
        # ----------------------------------------------------

        texto_body = driver.find_element(
            "tag name",
            "body"
        ).text


        # ----------------------------------------------------
        # Obtener source HTML
        # ----------------------------------------------------

        page_source = driver.page_source


        # ----------------------------------------------------
        # Combinar
        # ----------------------------------------------------

        contenido = (
            texto_body
            + "\n"
            + page_source
        )


        print(
            f"📄 Contenido obtenido: "
            f"{len(contenido)} caracteres"
        )


        return contenido


    except WebDriverException as e:

        print(
            "❌ Error obteniendo contenido:",
            str(e)
        )

        return None


    except Exception as e:

        print(
            "❌ Error leyendo contenido:",
            str(e)
        )

        return None


# ============================================================
# DETECTAR AGOTADO EN TEXTO
# ============================================================

def detectar_agotado_en_texto(contenido):

    if not contenido:

        return False


    texto = normalizar_texto(
        contenido
    )


    # --------------------------------------------------------
    # PALABRAS / FRASES DE AGOTADO
    # --------------------------------------------------------

    indicadores_agotado = [

        "agotado",

        "agotada",

        "sold out",

        "soldout",

        "no hay entradas",

        "no hay boletas",

        "entradas agotadas",

        "boletas agotadas",

        "tickets agotados",

        "tickets sold out",

        "currently unavailable",

        "not available",

        "unavailable",

        "sin disponibilidad",

        "sin entradas",

        "sin boletas"

    ]


    for indicador in indicadores_agotado:

        if indicador in texto:

            print(
                f"🔴 AGOTADO detectado por texto: "
                f"'{indicador}'"
            )

            return True


    return False


# ============================================================
# DETECTAR AGOTADO EN ELEMENTOS
# ============================================================

def detectar_agotado_elementos():

    global driver

    if driver is None:

        return False


    try:

        elementos = driver.find_elements(
            "css selector",
            "body *"
        )


        # Limitar el análisis para evitar
        # sobrecargar Chrome.
        limite = min(
            len(elementos),
            5000
        )


        for elemento in elementos[:limite]:

            try:

                texto = elemento.text


                if not texto:
                    continue


                texto_normalizado = normalizar_texto(
                    texto
                )


                if (
                    texto_normalizado == "agotado"
                    or
                    "sold out" in texto_normalizado
                ):

                    print(
                        "🔴 AGOTADO encontrado "
                        "en elemento."
                    )

                    return True


            except Exception:

                continue


    except WebDriverException as e:

        print(
            "⚠️ Error analizando elementos:",
            str(e)
        )


    except Exception as e:

        print(
            "⚠️ Error en análisis de elementos:",
            str(e)
        )


    return False


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra():

    global driver

    if driver is None:

        return False


    try:

        elementos = driver.find_elements(
            "css selector",
            "button, a, input, [role='button']"
        )


        indicadores = [

            "comprar entradas",
            "comprar boletas",
            "comprar tickets",

            "seleccionar entradas",
            "seleccionar boletas",
            "seleccionar tickets",

            "select tickets",
            "select seats",
            "choose seats",
            "choose tickets",

            "ver entradas",
            "ver boletas",
            "ver tickets",

            "buscar entradas",
            "buscar boletas",
            "buscar tickets",

            "find tickets",
            "find seats",

            "get tickets"

        ]


        for elemento in elementos:

            try:

                texto = elemento.text


                if not texto:
                    continue


                texto = normalizar_texto(
                    texto
                )


                for indicador in indicadores:

                    if indicador in texto:

                        print(
                            "🟢 Control de compra "
                            f"detectado: {indicador}"
                        )

                        return True


            except Exception:

                continue


    except WebDriverException as e:

        print(
            "⚠️ Error buscando controles:",
            str(e)
        )


    except Exception as e:

        print(
            "⚠️ Error detectando controles:",
            str(e)
        )


    return False


# ============================================================
# DETECTAR INDICADORES DE DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad(
    contenido
):

    if not contenido:

        return False


    texto = normalizar_texto(
        contenido
    )


    indicadores = [

        "selecciona tus entradas",

        "selecciona tus boletas",

        "selecciona tus tickets",

        "selecciona tus asientos",

        "seleccion de entradas",

        "seleccion de boletas",

        "seleccion de asientos",

        "select your tickets",

        "select your seats",

        "choose your seats",

        "available tickets",

        "tickets available",

        "entradas disponibles",

        "boletas disponibles",

        "tickets disponibles",

        "asientos disponibles"

    ]


    for indicador in indicadores:

        if indicador in texto:

            print(
                f"🟢 Indicador de disponibilidad: "
                f"'{indicador}'"
            )

            return True


    return False


# ============================================================
# DETECTAR DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad():

    # --------------------------------------------------------
    # OBTENER CONTENIDO
    # --------------------------------------------------------

    contenido = obtener_contenido()


    if contenido is None:

        print(
            "❌ No fue posible obtener contenido."
        )

        return "error"


    if len(contenido.strip()) < 20:

        print(
            "⚠️ Contenido insuficiente."
        )

        return "error"


    # --------------------------------------------------------
    # INFORMACIÓN DE DEPURACIÓN
    # --------------------------------------------------------

    texto_normalizado = normalizar_texto(
        contenido
    )


    print(
        "🔬 Contiene palabra 'agotado':",
        "agotado" in texto_normalizado
    )


    # ========================================================
    # PRIORIDAD ABSOLUTA:
    # AGOTADO
    # ========================================================

    if detectar_agotado_en_texto(
        contenido
    ):

        print(
            "🔴🔴🔴 AGOTADO CONFIRMADO"
        )

        return "agotado"


    # --------------------------------------------------------
    # Buscar agotado en elementos solo si
    # no apareció en el contenido general.
    # --------------------------------------------------------

    if detectar_agotado_elementos():

        print(
            "🔴🔴🔴 AGOTADO CONFIRMADO "
            "POR ELEMENTO"
        )

        return "agotado"


    # ========================================================
    # DISPONIBILIDAD
    # ========================================================

    if detectar_controles_compra():

        print(
            "🟢🟢🟢 DISPONIBILIDAD "
            "CONFIRMADA POR CONTROL"
        )

        return "disponible"


    if detectar_indicadores_disponibilidad(
        contenido
    ):

        print(
            "🟢🟢🟢 DISPONIBILIDAD "
            "CONFIRMADA POR TEXTO"
        )

        return "disponible"


    # ========================================================
    # DESCONOCIDO
    # ========================================================

    print(
        "🟡 RESULTADO: DESCONOCIDO"
    )

    return "desconocido"


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    nombre,
    resultado
):

    global estado_actual
    global estadisticas


    estado_anterior = estado_actual[
        nombre
    ]["estado"]


    print(
        f"📊 {nombre}"
    )

    print(
        f"   Estado anterior: "
        f"{estado_anterior}"
    )

    print(
        f"   Estado actual: "
        f"{resultado}"
    )


    # ========================================================
    # ERROR
    # ========================================================

    if resultado == "error":

        estadisticas[
            "errores"
        ][nombre] += 1


        print(
            "⚠️ ERROR DE SELENIUM/CHROME"
        )


        # NO modificar estado anterior.
        # Esto es importante:
        # un crash NO significa agotado
        # ni desconocido.


        return


    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if resultado == "desconocido":

        print(
            "🟡 DESCONOCIDO."
        )

        print(
            "   Se conserva el último "
            "estado válido."
        )


        return


    # ========================================================
    # AGOTADO
    # ========================================================

    if resultado == "agotado":

        estadisticas[
            "agotado"
        ][nombre] += 1


        # ----------------------------------------------------
        # Primera detección o cambio a agotado
        # ----------------------------------------------------

        if estado_anterior != "agotado":

            mensaje = (

                "🔴🔴🔴 BOLETAS AGOTADAS\n\n"

                f"🎤 BTS WORLD TOUR ARIRANG\n"
                f"📅 {nombre}\n\n"

                "❌ Ticketmaster indica que "
                "las entradas están AGOTADAS."

            )


            mensaje += enlace_acceso_por_fecha(
                nombre
            )


            enviar_telegram(
                mensaje
            )


            print(
                "📨 Alerta de AGOTADO enviada."
            )


        else:

            print(
                "🔴 Continúa AGOTADO. "
                "No se repite alerta."
            )


        estado_actual[
            nombre
        ]["estado"] = "agotado"


        estado_actual[
            nombre
        ]["ultimo_cambio"] = datetime.now().isoformat()


        guardar_estado()


        return


    # ========================================================
    # DISPONIBLE
    # ========================================================

    if resultado == "disponible":

        estadisticas[
            "disponible"
        ][nombre] += 1


        ahora = time.time()


        # ----------------------------------------------------
        # Determinar si debemos avisar
        # ----------------------------------------------------

        ultimo_aviso = estado_actual[
            nombre
        ].get(
            "ultimo_aviso_disponible",
            0
        )


        debe_avisar = False


        # ----------------------------------------------------
        # Primera detección
        # ----------------------------------------------------

        if estado_anterior != "disponible":

            debe_avisar = True


        # ----------------------------------------------------
        # Recordatorio cada 30 segundos
        # ----------------------------------------------------

        elif (
            ahora - ultimo_aviso
            >= INTERVALO_DISPONIBLE
        ):

            debe_avisar = True


        # ----------------------------------------------------
        # Enviar alerta
        # ----------------------------------------------------

        if debe_avisar:

            mensaje = (

                "🚨🚨🚨 BOLETAS DISPONIBLES 🚨🚨🚨\n\n"

                "🎤 BTS WORLD TOUR ARIRANG\n"

                f"📅 {nombre}\n\n"

                "🟢 Ticketmaster muestra "
                "indicadores de disponibilidad.\n\n"

                "⚠️ REVISA INMEDIATAMENTE."

            )


            mensaje += enlace_acceso_por_fecha(
                nombre
            )


            enviar_telegram(
                mensaje
            )


            estado_actual[
                nombre
            ]["ultimo_aviso_disponible"] = ahora


            print(
                "📨 ALERTA DE DISPONIBILIDAD "
                "ENVIADA."
            )


        else:

            print(
                "🟢 Continúa DISPONIBLE."
            )


        estado_actual[
            nombre
        ]["estado"] = "disponible"


        estado_actual[
            nombre
        ]["ultimo_cambio"] = datetime.now().isoformat()


        guardar_estado()


        return


# ============================================================
# HEARTBEAT
# ============================================================

def enviar_heartbeat():

    global ultimo_heartbeat


    ahora = time.time()


    if (
        ahora - ultimo_heartbeat
        < INTERVALO_HEARTBEAT
    ):

        return


    agotado_viernes = estadisticas[
        "agotado"
    ]["Viernes 2 de octubre de 2026"]


    agotado_sabado = estadisticas[
        "agotado"
    ]["Sábado 3 de octubre de 2026"]


    disponible_viernes = estadisticas[
        "disponible"
    ]["Viernes 2 de octubre de 2026"]


    disponible_sabado = estadisticas[
        "disponible"
    ]["Sábado 3 de octubre de 2026"]


    errores_viernes = estadisticas[
        "errores"
    ]["Viernes 2 de octubre de 2026"]


    errores_sabado = estadisticas[
        "errores"
    ]["Sábado 3 de octubre de 2026"]


    mensaje = (

        "💓 BOT BTS ACTIVO\n\n"

        "🤖 El monitor continúa funcionando "
        "correctamente.\n\n"

        "📊 ESTADÍSTICAS\n\n"

        "🔴 AGOTADO\n"
        f"• Viernes: {agotado_viernes}\n"
        f"• Sábado: {agotado_sabado}\n\n"

        "🟢 DISPONIBLE\n"
        f"• Viernes: {disponible_viernes}\n"
        f"• Sábado: {disponible_sabado}\n\n"

        "⚠️ ERRORES\n"
        f"• Viernes: {errores_viernes}\n"
        f"• Sábado: {errores_sabado}\n\n"

        f"🔄 Revisiones realizadas: "
        f"{contador_revision}"

    )


    enviar_telegram(
        mensaje
    )


    ultimo_heartbeat = ahora


# ============================================================
# WATCHDOG DE CHROME
# ============================================================

def watchdog_chrome():

    global driver


    if driver is None:

        print(
            "⚠️ Watchdog: Chrome no existe."
        )

        return recuperar_chrome()


    try:

        # Prueba sencilla.
        _ = driver.current_url

        return True


    except Exception as e:

        print(
            "⚠️ Watchdog detectó problema:",
            str(e)
        )


        return recuperar_chrome()


# ============================================================
# MANEJO DE SEÑALES
# ============================================================

def manejar_salida(
    signum,
    frame
):

    global ejecutando

    print(
        "\n🛑 Señal de apagado recibida."
    )

    ejecutando = False


# ============================================================
# INICIALIZACIÓN
# ============================================================

def inicializar():

    global driver


    print(
        "\n"
        "====================================================\n"
        "🤖 BOT BOLETAS BTS\n"
        "🎤 TICKETMASTER COLOMBIA\n"
        "====================================================\n"
    )


    print(
        "📅 Eventos monitoreados:"
    )


    for evento in URLS:

        print(
            f"   • {evento['nombre']}"
        )

        print(
            f"     {evento['url']}"
        )


    print()


    cargar_estado()


    if not recuperar_chrome():

        raise RuntimeError(
            "No se pudo iniciar Chrome."
        )


    # --------------------------------------------------------
    # Telegram de inicio
    # --------------------------------------------------------

    mensaje_inicio = (

        "🤖 BOT BTS INICIADO\n\n"

        "🎤 BTS WORLD TOUR ARIRANG\n\n"

        "📅 Monitoreando:\n"
        "• Viernes 2 de octubre\n"
        "• Sábado 3 de octubre\n\n"

        "🔄 Revisión cada 30 segundos.\n"

        "🚨 Alertas de disponibilidad "
        "inmediatas.\n"

        "🔴 Alertas de agotado por cambio "
        "de estado.\n\n"

        "💓 Heartbeat cada 5 horas."

    )


    enviar_telegram(
        mensaje_inicio
    )


# ============================================================
# PROCESAR UNA URL
# ============================================================

def procesar_url(
    nombre,
    url
):

    print(
        "\n"
        "===================================================="
    )

    print(
        f"🎫 {nombre}"
    )

    print(
        "===================================================="
    )


    # --------------------------------------------------------
    # Cargar página
    # --------------------------------------------------------

    cargada = cargar_pagina(
        url
    )


    if not cargada:

        print(
            "❌ No se pudo cargar la página."
        )


        # Intentar recuperación
        recuperado = recuperar_chrome()


        if not recuperado:

            print(
                "❌ No fue posible recuperar Chrome."
            )


            procesar_resultado(
                nombre,
                "error"
            )

            return


        # Reintentar una vez
        cargada = cargar_pagina(
            url
        )


        if not cargada:

            print(
                "❌ Segundo intento fallido."
            )


            procesar_resultado(
                nombre,
                "error"
            )

            return


    # --------------------------------------------------------
    # Detectar estado
    # --------------------------------------------------------

    resultado = detectar_disponibilidad()


    # --------------------------------------------------------
    # Si hubo error, recuperar Chrome
    # --------------------------------------------------------

    if resultado == "error":

        print(
            "🔄 Se intentará recuperar Chrome "
            "por resultado de error."
        )


        procesar_resultado(
            nombre,
            "error"
        )


        recuperar_chrome()


        return


    # --------------------------------------------------------
    # Procesar
    # --------------------------------------------------------

    procesar_resultado(
        nombre,
        resultado
    )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    global contador_revision
    global ejecutando


    signal.signal(
        signal.SIGTERM,
        manejar_salida
    )

    signal.signal(
        signal.SIGINT,
        manejar_salida
    )


    inicializar()


    print(
        "\n🚀 MONITOREO INICIADO.\n"
    )


    while ejecutando:

        contador_revision += 1


        print(
            "\n"
            "####################################################"
        )

        print(
            f"🔄 REVISIÓN #{contador_revision}"
        )

        print(
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print(
            "####################################################"
        )


        # ----------------------------------------------------
        # Watchdog
        # ----------------------------------------------------

        if not watchdog_chrome():

            print(
                "⚠️ Chrome no está disponible."
            )

            time.sleep(10)

            continue


        # ----------------------------------------------------
        # Revisar cada evento
        # ----------------------------------------------------

        for evento in URLS:

            if not ejecutando:

                break


            nombre = evento[
                "nombre"
            ]

            url = evento[
                "url"
            ]


            try:

                procesar_url(
                    nombre,
                    url
                )


            except Exception as e:

                print(
                    f"❌ ERROR procesando "
                    f"{nombre}: {e}"
                )


                procesar_resultado(
                    nombre,
                    "error"
                )


                # Intentar recuperación
                recuperar_chrome()


            # ------------------------------------------------
            # Pausa pequeña entre eventos
            # ------------------------------------------------

            time.sleep(2)


        # ----------------------------------------------------
        # Heartbeat
        # ----------------------------------------------------

        enviar_heartbeat()


        # ----------------------------------------------------
        # Esperar próxima revisión
        # ----------------------------------------------------

        print(
            f"\n⏳ Próxima revisión en "
            f"{INTERVALO_NORMAL} segundos."
        )


        # ----------------------------------------------------
        # Espera fragmentada
        # ----------------------------------------------------
        # Esto permite detectar una señal de apagado
        # sin tener que esperar 30 segundos completos.
        # ----------------------------------------------------

        for _ in range(
            INTERVALO_NORMAL
        ):

            if not ejecutando:

                break

            time.sleep(1)


    print(
        "\n🛑 BOT DETENIDO."
    )


# ============================================================
# LIMPIEZA
# ============================================================

def limpieza():

    print(
        "🧹 Cerrando Chrome..."
    )


    cerrar_driver()


    print(
        "✅ Limpieza finalizada."
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    try:

        main()


    except KeyboardInterrupt:

        print(
            "\n🛑 Bot detenido manualmente."
        )


    except Exception as e:

        print(
            "\n❌ ERROR FATAL:"
        )

        print(
            str(e)
        )


        try:

            enviar_telegram(
                "🚨 BOT BTS DETENIDO\n\n"
                f"❌ Error fatal:\n{str(e)[:1000]}"
            )

        except Exception:
            pass


    finally:

        limpieza()
