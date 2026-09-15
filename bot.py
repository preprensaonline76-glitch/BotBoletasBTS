# ============================================================
# BOT BOLETAS BTS - TICKETMASTER COLOMBIA
# ============================================================
#
# MONITOREA:
#   - Viernes 2 de octubre de 2026
#   - Sábado 3 de octubre de 2026
#
# FUNCIONES:
#   - Detectar AGOTADO
#   - Detectar DISPONIBILIDAD
#   - Alertar por Telegram
#   - Repetir disponibilidad cada 30 segundos
#   - Recuperar Chrome automáticamente
#   - Heartbeat cada 5 horas
#   - Mantener el último estado válido
#
# IMPORTANTE:
#   - NO realiza compras
#   - NO intenta evadir CAPTCHA
#   - NO intenta saltarse sistemas anti-bot
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
    TimeoutException
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
# URLS
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

INTERVALO_NORMAL = 30

INTERVALO_DISPONIBLE = 30

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
# ESTADO
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


# ============================================================
# ESTADÍSTICAS
# ============================================================

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
# ESTADO ACTUAL
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
# ENLACE SEGÚN EL EVENTO
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

    if "sabado" in nombre_normalizado:

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

            contador_errores_telegram = 0

            print(
                "📨 Telegram enviado correctamente."
            )

            return True


        contador_errores_telegram += 1


        print(
            "⚠️ Error Telegram:",
            respuesta.status_code
        )


        if (
            contador_errores_telegram
            <= MAX_ERRORES_TELEGRAM
        ):

            print(
                f"⚠️ Error Telegram "
                f"{contador_errores_telegram}/"
                f"{MAX_ERRORES_TELEGRAM}"
            )


    except Exception as e:

        contador_errores_telegram += 1


        if (
            contador_errores_telegram
            <= MAX_ERRORES_TELEGRAM
        ):

            print(
                f"⚠️ Error Telegram "
                f"{contador_errores_telegram}/"
                f"{MAX_ERRORES_TELEGRAM}:",
                str(e)
            )


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
            str(e)
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

            print(
                "ℹ️ No existe estado anterior."
            )

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

                estado_actual[
                    nombre
                ].update(
                    datos[nombre]
                )


        print(
            "💾 Estado anterior cargado."
        )


    except Exception as e:

        print(
            "⚠️ Error cargando estado:",
            str(e)
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
    # HEADLESS
    # --------------------------------------------------------

    opciones.add_argument(
        "--headless=new"
    )


    # --------------------------------------------------------
    # RAILWAY / LINUX
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
        "--no-first-run"
    )

    opciones.add_argument(
        "--no-default-browser-check"
    )

    opciones.add_argument(
        "--window-size=1920,1080"
    )


    # --------------------------------------------------------
    # CARGA
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
                f"🔧 Intento "
                f"{intento}/{MAX_INTENTOS_CHROME}"
            )


            driver = crear_driver()


            # ------------------------------------------------
            # Prueba sencilla
            # ------------------------------------------------

            driver.get(
                "https://www.ticketmaster.co/"
            )


            time.sleep(2)


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
        "❌ No fue posible recuperar Chrome."
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
            "🌐 Cargando:"
        )

        print(
            url
        )


        driver.get(
            url
        )


        # Espera corta para contenido dinámico.
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
        # TEXTO VISIBLE
        # ----------------------------------------------------

        texto_body = driver.find_element(
            "tag name",
            "body"
        ).text


        # ----------------------------------------------------
        # HTML
        # ----------------------------------------------------

        page_source = driver.page_source


        # ----------------------------------------------------
        # COMBINAR
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

def detectar_agotado_en_texto(
    contenido
):

    if not contenido:

        return False


    texto = normalizar_texto(
        contenido
    )


    indicadores_agotado = [

        "agotado",
        "agotada",
        "agotados",
        "agotadas",

        "sold out",
        "soldout",

        "entradas agotadas",
        "boletas agotadas",
        "tickets agotados",

        "no hay entradas",
        "no hay boletas",
        "no hay tickets",

        "sin entradas",
        "sin boletas",
        "sin tickets",

        "sin disponibilidad",

        "currently unavailable",
        "not available",
        "unavailable",

        "tickets are sold out",
        "tickets sold out",

        "event is sold out",

        "all tickets are sold out"

    ]


    for indicador in indicadores_agotado:

        if indicador in texto:

            print(
                f"🔴 AGOTADO detectado: "
                f"'{indicador}'"
            )

            return True


    return False


# ============================================================
# DETECTAR AGOTADO EN HTML
# ============================================================

def detectar_agotado_en_html():

    global driver


    if driver is None:

        return False


    try:

        html = driver.execute_script(
            "return document.documentElement.outerHTML;"
        )


        if not html:

            return False


        html_normalizado = normalizar_texto(
            html
        )


        indicadores = [

            "agotado",
            "agotada",
            "agotados",
            "agotadas",

            "sold out",
            "soldout",

            "entradas agotadas",
            "boletas agotadas",
            "tickets agotados",

            "unavailable",

            "currently unavailable",

            "not available",

            "sin disponibilidad"

        ]


        for indicador in indicadores:

            if indicador in html_normalizado:

                print(
                    "🔴 AGOTADO encontrado "
                    f"en HTML: '{indicador}'"
                )

                return True


    except WebDriverException as e:

        print(
            "⚠️ Error leyendo HTML:",
            str(e)
        )


    except Exception as e:

        print(
            "⚠️ Error revisando HTML:",
            str(e)
        )


    return False


# ============================================================
# DETECTAR AGOTADO EN ELEMENTOS IMPORTANTES
# ============================================================

def detectar_agotado_elementos():

    global driver


    if driver is None:

        return False


    try:

        # ----------------------------------------------------
        # NO SE USA body *
        #
        # Esto evita recorrer miles de elementos y reduce
        # enormemente la posibilidad de "tab crashed".
        # ----------------------------------------------------

        selectores = [

            "[role='alert']",

            "[role='status']",

            "[aria-label]",

            "[data-testid]",

            "[class*='sold']",

            "[class*='Sold']",

            "[class*='agot']",

            "[class*='Agot']",

            "[class*='unavailable']",

            "[class*='Unavailable']"

        ]


        indicadores = [

            "agotado",
            "agotada",
            "agotados",
            "agotadas",

            "sold out",
            "soldout",

            "unavailable",

            "not available",

            "sin disponibilidad"

        ]


        for selector in selectores:

            try:

                elementos = driver.find_elements(
                    "css selector",
                    selector
                )


            except Exception:

                continue


            # ------------------------------------------------
            # Limitar elementos por selector
            # ------------------------------------------------

            for elemento in elementos[:100]:

                try:

                    valores = []


                    # Texto
                    texto = elemento.text

                    if texto:

                        valores.append(
                            texto
                        )


                    # aria-label
                    aria = elemento.get_attribute(
                        "aria-label"
                    )

                    if aria:

                        valores.append(
                            aria
                        )


                    # title
                    title = elemento.get_attribute(
                        "title"
                    )

                    if title:

                        valores.append(
                            title
                        )


                    # class
                    clase = elemento.get_attribute(
                        "class"
                    )

                    if clase:

                        valores.append(
                            clase
                        )


                    # data-testid
                    testid = elemento.get_attribute(
                        "data-testid"
                    )

                    if testid:

                        valores.append(
                            testid
                        )


                    contenido = normalizar_texto(
                        " ".join(valores)
                    )


                    for indicador in indicadores:

                        if indicador in contenido:

                            print(
                                "🔴 AGOTADO encontrado "
                                "en elemento."
                            )

                            print(
                                f"   Indicador: "
                                f"{indicador}"
                            )


                            return True


                except Exception:

                    continue


    except Exception as e:

        print(
            "⚠️ Error analizando elementos:",
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

            "seleccionar asientos",

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


        for elemento in elementos[:500]:

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
                "🟢 Indicador de disponibilidad:",
                indicador
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
    # NORMALIZAR
    # --------------------------------------------------------

    texto_normalizado = normalizar_texto(
        contenido
    )


    print(
        f"📄 Tamaño contenido: "
        f"{len(contenido)} caracteres"
    )


    print(
        "🔬 Contiene palabra 'agotado':",
        "agotado" in texto_normalizado
    )


    # ========================================================
    # PRIORIDAD 1
    # AGOTADO EN TEXTO
    # ========================================================

    if detectar_agotado_en_texto(
        contenido
    ):

        print(
            "🔴🔴🔴 AGOTADO CONFIRMADO "
            "POR TEXTO"
        )

        return "agotado"


    # ========================================================
    # PRIORIDAD 2
    # AGOTADO EN HTML
    # ========================================================

    if detectar_agotado_en_html():

        print(
            "🔴🔴🔴 AGOTADO CONFIRMADO "
            "POR HTML"
        )

        return "agotado"


    # ========================================================
    # PRIORIDAD 3
    # ELEMENTOS IMPORTANTES
    # ========================================================

    if detectar_agotado_elementos():

        print(
            "🔴🔴🔴 AGOTADO CONFIRMADO "
            "POR ELEMENTO"
        )

        return "agotado"


    # ========================================================
    # PRIORIDAD 4
    # DISPONIBILIDAD POR CONTROL
    # ========================================================

    if detectar_controles_compra():

        print(
            "🟢🟢🟢 DISPONIBILIDAD "
            "CONFIRMADA POR CONTROL"
        )

        return "disponible"


    # ========================================================
    # PRIORIDAD 5
    # DISPONIBILIDAD POR TEXTO
    # ========================================================

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


        # NO cambiar estado.

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
        # Solo avisar cuando cambia a agotado
        # ----------------------------------------------------

        if estado_anterior != "agotado":

            mensaje = (

                "🔴🔴🔴 BOLETAS AGOTADAS\n\n"

                "🎤 BTS WORLD TOUR ARIRANG\n"

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
                "🔴 Continúa AGOTADO."
            )

            print(
                "   No se repite alerta."
            )


        estado_actual[
            nombre
        ]["estado"] = "agotado"


        estado_actual[
            nombre
        ]["ultimo_cambio"] = (
            datetime.now().isoformat()
        )


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


        ultimo_aviso = estado_actual[
            nombre
        ].get(
            "ultimo_aviso_disponible",
            0
        )


        debe_avisar = False


        # ----------------------------------------------------
        # CAMBIO A DISPONIBLE
        # ----------------------------------------------------

        if estado_anterior != "disponible":

            debe_avisar = True


        # ----------------------------------------------------
        # RECORDATORIO CADA 30 SEGUNDOS
        # ----------------------------------------------------

        elif (
            ahora - ultimo_aviso
            >= INTERVALO_DISPONIBLE
        ):

            debe_avisar = True


        # ----------------------------------------------------
        # ALERTA
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
        ]["ultimo_cambio"] = (
            datetime.now().isoformat()
        )


        guardar_estado()


        return


# ============================================================
# GUARDAR HTML DE DEPURACIÓN
# ============================================================
#
# Se utiliza únicamente cuando el detector devuelve
# DESCONOCIDO.
#
# Esto NO analiza miles de elementos y NO se ejecuta
# normalmente.
#
# ============================================================

def guardar_debug_ticketmaster(
    nombre
):

    global driver


    if driver is None:

        return


    try:

        nombre_archivo = normalizar_texto(
            nombre
        ).replace(
            " ",
            "_"
        )


        archivo = (
            f"/tmp/debug_"
            f"{nombre_archivo}.html"
        )


        html = driver.execute_script(
            "return document.documentElement.outerHTML;"
        )


        if not html:

            return


        with open(
            archivo,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                html
            )


        print(
            "🧪 HTML de depuración guardado:"
        )

        print(
            archivo
        )


    except Exception as e:

        print(
            "⚠️ No se pudo guardar debug:",
            str(e)
        )


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
# WATCHDOG
# ============================================================

def watchdog_chrome():

    global driver


    if driver is None:

        print(
            "⚠️ Watchdog: Chrome no existe."
        )

        return recuperar_chrome()


    try:

        _ = driver.current_url

        return True


    except Exception as e:

        print(
            "⚠️ Watchdog detectó problema:",
            str(e)
        )


        return recuperar_chrome()


# ============================================================
# SEÑALES
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
        "===================================================="
    )

    print(
        "🤖 BOT BOLETAS BTS"
    )

    print(
        "🎤 TICKETMASTER COLOMBIA"
    )

    print(
        "===================================================="
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
    # CARGAR
    # --------------------------------------------------------

    cargada = cargar_pagina(
        url
    )


    if not cargada:

        print(
            "❌ No se pudo cargar la página."
        )


        print(
            "🔄 Intentando recuperar Chrome..."
        )


        recuperado = recuperar_chrome()


        if not recuperado:

            procesar_resultado(
                nombre,
                "error"
            )

            return


        # ----------------------------------------------------
        # SEGUNDO INTENTO
        # ----------------------------------------------------

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
    # DETECTAR
    # --------------------------------------------------------

    resultado = detectar_disponibilidad()


    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if resultado == "error":

        procesar_resultado(
            nombre,
            "error"
        )


        print(
            "🔄 Recuperando Chrome..."
        )


        recuperar_chrome()


        return


    # --------------------------------------------------------
    # DEBUG SOLO SI DESCONOCIDO
    # --------------------------------------------------------

    if resultado == "desconocido":

        guardar_debug_ticketmaster(
            nombre
        )


    # --------------------------------------------------------
    # PROCESAR
    # --------------------------------------------------------

    procesar_resultado(
        nombre,
        resultado
    )


# ============================================================
# MAIN
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
        # WATCHDOG
        # ----------------------------------------------------

        if not watchdog_chrome():

            print(
                "⚠️ Chrome no está disponible."
            )


            time.sleep(10)

            continue


        # ----------------------------------------------------
        # EVENTOS
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


                recuperar_chrome()


            # ------------------------------------------------
            # Pequeña pausa
            # ------------------------------------------------

            time.sleep(2)


        # ----------------------------------------------------
        # HEARTBEAT
        # ----------------------------------------------------

        enviar_heartbeat()


        # ----------------------------------------------------
        # ESPERA
        # ----------------------------------------------------

        print(
            f"\n⏳ Próxima revisión en "
            f"{INTERVALO_NORMAL} segundos."
        )


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

                "❌ Error fatal:\n"

                f"{str(e)[:1000]}"

            )

        except Exception:

            pass


    finally:

        limpieza()
