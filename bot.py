import os
import time
import random
import requests

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN:
    raise RuntimeError("❌ Falta la variable de entorno TOKEN")

if not CHAT_ID:
    raise RuntimeError("❌ Falta la variable de entorno CHAT_ID")


# ============================================================
# URLS DE TICKETMASTER
# ============================================================

URL_SABADO = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-sabado-3-octubre"
)

URL_VIERNES = (
    "https://www.ticketmaster.co/event/"
    "bts-world-tour-venta-general-viernes-2-octubre"
)


EVENTOS = {
    URL_SABADO: "SÁBADO 3 DE OCTUBRE",
    URL_VIERNES: "VIERNES 2 DE OCTUBRE",
}


# ============================================================
# TIEMPOS
# ============================================================

ESPERA_MINIMA = 20
ESPERA_MAXIMA = 30

REPETIR_ALERTA_DISPONIBLE = 30

HEARTBEAT_CADA = 5 * 60 * 60

TIMEOUT_CARGA = 40

ESPERA_RENDER = 4


# ============================================================
# DRIVER
# ============================================================

driver = None


# ============================================================
# ESTADOS
# ============================================================

estado_anterior = {
    URL_SABADO: None,
    URL_VIERNES: None,
}


ultima_alerta_disponible = {
    URL_SABADO: 0,
    URL_VIERNES: 0,
}


# ============================================================
# ESTADÍSTICAS
# ============================================================

estadisticas = {
    "consultas": 0,
    "disponibles": 0,
    "agotados": 0,
    "desconocidos": 0,
    "bloqueados": 0,
    "errores": 0,
    "recuperaciones": 0,
}


# ============================================================
# TIEMPO DE ACTIVIDAD
# ============================================================

inicio_bot = time.time()

ultimo_heartbeat = time.time()


# ============================================================
# TELEGRAM
# ============================================================

racha_errores_telegram = 0

MAX_ERRORES_TELEGRAM = 10


def enviar_telegram(mensaje, es_error=False):

    global racha_errores_telegram

    url = (
        f"https://api.telegram.org/"
        f"bot{TOKEN}/sendMessage"
    )

    datos = {
        "chat_id": CHAT_ID,
        "text": mensaje,
    }

    try:

        respuesta = requests.post(
            url,
            data=datos,
            timeout=15
        )

        if respuesta.status_code == 200:

            if es_error:
                racha_errores_telegram = 0

            return True

        if es_error:

            racha_errores_telegram += 1

            if (
                racha_errores_telegram
                <= MAX_ERRORES_TELEGRAM
            ):

                print(
                    f"⚠️ Error Telegram "
                    f"{racha_errores_telegram}/"
                    f"{MAX_ERRORES_TELEGRAM}: "
                    f"{respuesta.status_code}"
                )

            return False

        print(
            f"⚠️ Telegram respondió "
            f"{respuesta.status_code}"
        )

        return False

    except Exception as e:

        if es_error:

            racha_errores_telegram += 1

            if (
                racha_errores_telegram
                <= MAX_ERRORES_TELEGRAM
            ):

                print(
                    f"⚠️ Error Telegram "
                    f"{racha_errores_telegram}/"
                    f"{MAX_ERRORES_TELEGRAM}: "
                    f"{e}"
                )

            return False

        print(
            f"⚠️ Error enviando Telegram: {e}"
        )

        return False


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    return " ".join(
        str(texto)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .lower()
        .split()
    )


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

    "your browsing activity",

    "unusual activity",

    "actividad inusual",

    "comportamiento inusual",

    "actividad sospechosa",

    "hemos detectado actividad inusual",

    "hemos detectado un comportamiento inusual",
]


# ============================================================
# FRASES DE AGOTADO
# ============================================================

FRASES_AGOTADO = [

    "entradas agotadas",

    "boletas agotadas",

    "tickets agotados",

    "entradas agotada",

    "boletas agotada",

    "tickets agotada",

    "sold out",

    "tickets are sold out",

    "tickets sold out",

    "entradas no disponibles",

    "boletas no disponibles",

    "tickets no disponibles",

    "tickets unavailable",

    "entradas agotadas para este evento",

    "no hay entradas disponibles",
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

    "ver entradas",

    "ver boletas",

    "ver tickets",

    "ver asientos",

    "comprar entradas",

    "comprar boletas",

    "comprar tickets",

    "comprar asientos",
]


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    print("🌐 Iniciando Chrome...")

    opciones = Options()

    # --------------------------------------------------------
    # Railway / Linux
    # --------------------------------------------------------

    opciones.add_argument("--headless=new")

    opciones.add_argument("--no-sandbox")

    opciones.add_argument("--disable-dev-shm-usage")

    # --------------------------------------------------------
    # Estabilidad
    # --------------------------------------------------------

    opciones.add_argument("--disable-gpu")

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

    # --------------------------------------------------------
    # Ventana
    # --------------------------------------------------------

    opciones.add_argument(
        "--window-size=1365,900"
    )

    # --------------------------------------------------------
    # Idioma
    # --------------------------------------------------------

    opciones.add_argument(
        "--lang=es-CO"
    )

    # --------------------------------------------------------
    # Menor consumo
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Estrategia de carga
    # --------------------------------------------------------

    opciones.page_load_strategy = "eager"

    # --------------------------------------------------------
    # Driver
    # --------------------------------------------------------

    servicio = Service(
        "/usr/bin/chromedriver"
    )

    nuevo_driver = webdriver.Chrome(
        service=servicio,
        options=opciones
    )

    nuevo_driver.set_page_load_timeout(
        TIMEOUT_CARGA
    )

    nuevo_driver.set_script_timeout(
        20
    )

    print(
        "✅ Chrome iniciado correctamente"
    )

    return nuevo_driver


# ============================================================
# INICIAR DRIVER
# ============================================================

def iniciar_driver():

    global driver

    try:

        driver = crear_driver()

        return True

    except Exception as e:

        print(
            f"❌ No se pudo iniciar Chrome: {e}"
        )

        driver = None

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


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global driver

    estadisticas["recuperaciones"] += 1

    print()
    print(
        "🔄 Intentando recuperar Chrome..."
    )

    cerrar_driver()

    time.sleep(3)

    for intento in range(1, 4):

        print(
            f"🔧 Intento de recuperación "
            f"{intento}/3..."
        )

        if iniciar_driver():

            print(
                "✅ Chrome recuperado"
            )

            return True

        time.sleep(5)

    print(
        "❌ No fue posible recuperar Chrome"
    )

    return False


# ============================================================
# OBTENER URL ACTUAL
# ============================================================

def obtener_url_actual():

    global driver

    if driver is None:
        return ""

    try:

        return driver.current_url or ""

    except Exception:

        return ""


# ============================================================
# OBTENER TÍTULO
# ============================================================

def obtener_titulo():

    global driver

    if driver is None:
        return ""

    try:

        return driver.title or ""

    except Exception:

        return ""


# ============================================================
# OBTENER TEXTO VISIBLE
# ============================================================

def obtener_texto_visible():

    global driver

    if driver is None:

        raise RuntimeError(
            "Driver no disponible"
        )

    try:

        texto = driver.execute_script(
            """
            if (!document.body) {
                return "";
            }

            return document.body.innerText || "";
            """
        )

        if texto and str(texto).strip():

            return str(texto)

        try:

            return driver.find_element(
                "tag name",
                "body"
            ).text

        except Exception:

            return ""

    except Exception as e:

        raise RuntimeError(
            f"No se pudo obtener texto visible: {e}"
        )


# ============================================================
# OBTENER HTML
# ============================================================

def obtener_html():

    global driver

    if driver is None:

        raise RuntimeError(
            "Driver no disponible"
        )

    try:

        return driver.page_source or ""

    except Exception as e:

        raise RuntimeError(
            f"No se pudo obtener HTML: {e}"
        )


# ============================================================
# DETECTAR PROTECCIÓN
# ============================================================

def detectar_proteccion(
    texto_visible,
    html,
    titulo,
    url_actual
):

    texto = normalizar_texto(
        texto_visible
    )

    titulo_normalizado = normalizar_texto(
        titulo
    )

    url_normalizada = normalizar_texto(
        url_actual
    )

    # --------------------------------------------------------
    # Primero revisar señales explícitas.
    # --------------------------------------------------------

    for frase in FRASES_BLOQUEO:

        if frase in texto:

            print(
                f"🛡️ Protección detectada: {frase}"
            )

            return True

        if frase in titulo_normalizado:

            print(
                f"🛡️ Protección detectada "
                f"en título: {frase}"
            )

            return True

    # --------------------------------------------------------
    # Señales típicas del challenge.
    # --------------------------------------------------------

    indicadores_challenge = [

        "access denied",

        "verify you are human",

        "checking your browser",

        "please wait",

        "security check",

        "bot detection",

        "captcha",

    ]

    for indicador in indicadores_challenge:

        if indicador in texto:

            print(
                f"🛡️ Challenge detectado: "
                f"{indicador}"
            )

            return True

    # --------------------------------------------------------
    # Si la URL actual cambió a una página de protección.
    # --------------------------------------------------------

    urls_proteccion = [

        "access-denied",

        "blocked",

        "challenge",

        "captcha",

        "security",

    ]

    for indicador in urls_proteccion:

        if indicador in url_normalizada:

            print(
                f"🛡️ URL de protección detectada: "
                f"{indicador}"
            )

            return True

    # --------------------------------------------------------
    # Detectar páginas anormalmente dominadas por JavaScript.
    #
    # NO se utiliza esto para declarar agotado.
    # Solamente evita interpretar un challenge como página
    # normal.
    # --------------------------------------------------------

    texto_largo = len(texto)

    cantidad_funciones = texto.count(
        "function "
    )

    cantidad_document = texto.count(
        "document."
    )

    cantidad_cookie = texto.count(
        "cookie"
    )

    if (
        texto_largo > 10000
        and cantidad_funciones >= 3
        and cantidad_document >= 2
        and cantidad_cookie >= 1
    ):

        print(
            "🛡️ El contenido recibido parece "
            "una página técnica/challenge."
        )

        return True

    return False


# ============================================================
# DETECTAR BOTONES DE DISPONIBILIDAD
# ============================================================

def detectar_boton_disponibilidad():

    global driver

    if driver is None:
        return False

    try:

        elementos = driver.find_elements(
            "css selector",
            "button, a"
        )

    except Exception as e:

        print(
            f"⚠️ Error revisando botones: {e}"
        )

        return False

    for elemento in elementos:

        try:

            if not elemento.is_displayed():

                continue

            texto = normalizar_texto(
                elemento.text
            )

            aria = normalizar_texto(
                elemento.get_attribute(
                    "aria-label"
                )
            )

            title = normalizar_texto(
                elemento.get_attribute(
                    "title"
                )
            )

            identificador = normalizar_texto(
                elemento.get_attribute(
                    "id"
                )
            )

            contenido = " ".join(
                [
                    texto,
                    aria,
                    title,
                    identificador,
                ]
            )

            if not contenido:

                continue

            # ------------------------------------------------
            # Nunca aceptar un botón que indique agotado.
            # ------------------------------------------------

            if any(
                frase in contenido
                for frase in FRASES_AGOTADO
            ):

                continue

            # ------------------------------------------------
            # Botones explícitos.
            # ------------------------------------------------

            botones_validos = [

                "ver entradas",

                "ver boletas",

                "ver tickets",

                "ver asientos",

                "comprar entradas",

                "comprar boletas",

                "comprar tickets",

                "comprar asientos",

                "select your tickets",

                "select your seats",

            ]

            if any(
                frase in contenido
                for frase in botones_validos
            ):

                print(
                    "🟢 Botón/enlace de compra "
                    "detectado."
                )

                print(
                    f"   Texto: {texto}"
                )

                return True

        except Exception:

            continue

    return False


# ============================================================
# DETECTAR ESTADO
# ============================================================

def detectar_estado_pagina(
    texto_visible,
    html,
    titulo,
    url_actual
):

    texto = normalizar_texto(
        texto_visible
    )

    # --------------------------------------------------------
    # 1. PROTECCIÓN
    # --------------------------------------------------------

    if detectar_proteccion(
        texto_visible,
        html,
        titulo,
        url_actual
    ):

        return "bloqueado"

    # --------------------------------------------------------
    # Si no hay contenido visible suficiente,
    # no inventamos un estado.
    # --------------------------------------------------------

    if len(texto) < 15:

        print(
            "⚠️ Texto visible insuficiente."
        )

        return "desconocido"

    # --------------------------------------------------------
    # 2. AGOTADO
    #
    # IMPORTANTE:
    # solamente se analiza TEXTO VISIBLE.
    #
    # No buscamos "agotado" en page_source porque puede
    # aparecer dentro de JavaScript, datos internos,
    # traducciones, scripts, etc.
    # --------------------------------------------------------

    for frase in FRASES_AGOTADO:

        if frase in texto:

            print(
                f"🔴 AGOTADO detectado: {frase}"
            )

            return "agotado"

    # --------------------------------------------------------
    # 3. DISPONIBILIDAD POR TEXTO
    # --------------------------------------------------------

    for frase in FRASES_DISPONIBILIDAD:

        if frase in texto:

            print(
                f"🟢 DISPONIBILIDAD detectada: "
                f"{frase}"
            )

            return "disponible"

    # --------------------------------------------------------
    # 4. DISPONIBILIDAD POR BOTÓN
    # --------------------------------------------------------

    if detectar_boton_disponibilidad():

        return "disponible"

    # --------------------------------------------------------
    # 5. DESCONOCIDO
    # --------------------------------------------------------

    return "desconocido"


# ============================================================
# CARGAR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not iniciar_driver():

            return None

    try:

        print(
            f"🌐 Cargando URL..."
        )

        driver.get(url)

        # ----------------------------------------------------
        # Esperar renderizado.
        # ----------------------------------------------------

        time.sleep(
            ESPERA_RENDER
        )

        texto_visible = ""

        # ----------------------------------------------------
        # Dar oportunidad a contenido dinámico.
        # ----------------------------------------------------

        for intento in range(5):

            try:

                texto_visible = (
                    obtener_texto_visible()
                )

            except Exception:

                texto_visible = ""

            if len(
                normalizar_texto(
                    texto_visible
                )
            ) >= 20:

                break

            print(
                f"⏳ Esperando contenido "
                f"({intento + 1}/5)..."
            )

            time.sleep(1)

        html = obtener_html()

        titulo = obtener_titulo()

        url_actual = obtener_url_actual()

        return {
            "texto": texto_visible,
            "html": html,
            "titulo": titulo,
            "url_actual": url_actual,
        }

    except Exception as e:

        print(
            f"❌ Error cargando página: {e}"
        )

        return None


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(
    url,
    resultado
):

    global estado_anterior
    global ultima_alerta_disponible

    nombre_evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    ahora = time.time()

    # ========================================================
    # ERROR
    # ========================================================

    if resultado == "error":

        estadisticas["errores"] += 1

        print(
            f"❌ {nombre_evento} → ERROR"
        )

        return

    # ========================================================
    # BLOQUEADO
    # ========================================================

    if resultado == "bloqueado":

        estadisticas["bloqueados"] += 1

        print(
            f"🛡️ {nombre_evento} → BLOQUEADO"
        )

        # ----------------------------------------------------
        # No cambiamos estado anterior.
        # ----------------------------------------------------

        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if resultado == "desconocido":

        estadisticas["desconocidos"] += 1

        print(
            f"❓ {nombre_evento} → DESCONOCIDO"
        )

        # ----------------------------------------------------
        # No sobrescribimos un estado válido.
        # ----------------------------------------------------

        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if resultado == "agotado":

        estadisticas["agotados"] += 1

        estado_previo = (
            estado_anterior.get(url)
        )

        estado_anterior[url] = "agotado"

        print(
            f"🔴 {nombre_evento} → AGOTADO"
        )

        # ----------------------------------------------------
        # Solo avisar cuando cambia a agotado.
        # ----------------------------------------------------

        if estado_previo != "agotado":

            mensaje = (

                "🔴 BTS WORLD TOUR\n\n"

                f"📅 {nombre_evento}\n\n"

                "🎫 Estado: AGOTADO\n\n"

                "Ticketmaster no muestra "
                "entradas disponibles "
                "en esta consulta."
            )

            enviar_telegram(
                mensaje
            )

        return

    # ========================================================
    # DISPONIBLE
    # ========================================================

    if resultado == "disponible":

        estadisticas["disponibles"] += 1

        estado_previo = (
            estado_anterior.get(url)
        )

        estado_anterior[url] = "disponible"

        print(
            f"🚨 {nombre_evento} → "
            "DISPONIBLE"
        )

        # ----------------------------------------------------
        # Primera detección.
        # ----------------------------------------------------

        if estado_previo != "disponible":

            mensaje = (

                "🚨🚨🚨 BTS WORLD TOUR 🚨🚨🚨\n\n"

                f"📅 {nombre_evento}\n\n"

                "🎫 ¡ENTRADAS DISPONIBLES!\n\n"

                "⚡ Ticketmaster muestra "
                "una señal de compra "
                "o disponibilidad.\n\n"

                "🔗 Revisa Ticketmaster "
                "inmediatamente."
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponible[url] = (
                ahora
            )

            return

        # ----------------------------------------------------
        # Continuar alertando cada 30 segundos.
        # ----------------------------------------------------

        if (
            ahora
            - ultima_alerta_disponible.get(
                url,
                0
            )
            >= REPETIR_ALERTA_DISPONIBLE
        ):

            mensaje = (

                "🚨 BTS WORLD TOUR\n\n"

                f"📅 {nombre_evento}\n\n"

                "🎫 ¡SIGUEN DISPONIBLES!\n\n"

                "⚡ Revisa Ticketmaster ahora."
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponible[url] = (
                ahora
            )

        return


# ============================================================
# CONSULTAR FECHA
# ============================================================

def consultar_fecha(url):

    estadisticas["consultas"] += 1

    nombre_evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    print()
    print(
        f"🔎 Revisando: {nombre_evento}"
    )

    resultado_carga = cargar_pagina(
        url
    )

    if resultado_carga is None:

        procesar_resultado(
            url,
            "error"
        )

        return "error"

    texto_visible = (
        resultado_carga["texto"]
    )

    html = (
        resultado_carga["html"]
    )

    titulo = (
        resultado_carga["titulo"]
    )

    url_actual = (
        resultado_carga["url_actual"]
    )

    try:

        texto_normalizado = (
            normalizar_texto(
                texto_visible
            )
        )

        html_normalizado = (
            normalizar_texto(
                html
            )
        )

        print(
            f"📏 Texto visible: "
            f"{len(texto_visible)} caracteres"
        )

        print(
            f"📏 HTML: "
            f"{len(html)} caracteres"
        )

        print(
            f"🌐 URL actual: "
            f"{url_actual}"
        )

        print(
            f"📄 Título: "
            f"{titulo[:150]}"
        )

        # ----------------------------------------------------
        # Diagnóstico del texto visible.
        # ----------------------------------------------------

        muestra = (
            texto_visible[:800]
            .replace("\n", " ")
            .strip()
        )

        if muestra:

            print(
                f"📝 Texto visible: {muestra}"
            )

        else:

            print(
                "📝 Texto visible: VACÍO"
            )

        # ----------------------------------------------------
        # PRUEBA DIRECTA DE AGOTADO
        #
        # SOLO texto visible.
        # ----------------------------------------------------

        if "agotado" in texto_normalizado:

            print(
                "🔴 PRUEBA DIRECTA: "
                "'agotado' ENCONTRADO "
                "EN TEXTO VISIBLE"
            )

        else:

            print(
                "ℹ️ 'agotado' no aparece "
                "en el texto visible."
            )

        # ----------------------------------------------------
        # Diagnóstico de protección.
        # ----------------------------------------------------

        proteccion = detectar_proteccion(
            texto_visible,
            html,
            titulo,
            url_actual
        )

        if proteccion:

            estado = "bloqueado"

        else:

            estado = detectar_estado_pagina(
                texto_visible,
                html,
                titulo,
                url_actual
            )

    except Exception as e:

        print(
            f"❌ Error detectando estado "
            f"de {nombre_evento}: {e}"
        )

        procesar_resultado(
            url,
            "error"
        )

        return "error"

    procesar_resultado(
        url,
        estado
    )

    return estado


# ============================================================
# FORMATEAR DURACIÓN
# ============================================================

def formatear_duracion(
    segundos
):

    segundos = int(
        max(0, segundos)
    )

    dias = (
        segundos // 86400
    )

    segundos %= 86400

    horas = (
        segundos // 3600
    )

    segundos %= 3600

    minutos = (
        segundos // 60
    )

    segundos %= 60

    partes = []

    if dias:

        partes.append(
            f"{dias}d"
        )

    if horas:

        partes.append(
            f"{horas}h"
        )

    if minutos:

        partes.append(
            f"{minutos}m"
        )

    partes.append(
        f"{segundos}s"
    )

    return " ".join(
        partes
    )


# ============================================================
# HEARTBEAT
# ============================================================

def enviar_heartbeat():

    global ultimo_heartbeat

    ahora = time.time()

    if (
        ahora - ultimo_heartbeat
        < HEARTBEAT_CADA
    ):

        return

    ultimo_heartbeat = ahora

    tiempo_activo = (
        formatear_duracion(
            ahora - inicio_bot
        )
    )

    horas_activas = (
        ahora - inicio_bot
    ) / 3600

    estado_sabado = (
        estado_anterior.get(
            URL_SABADO
        )
        or "sin datos"
    )

    estado_viernes = (
        estado_anterior.get(
            URL_VIERNES
        )
        or "sin datos"
    )

    mensaje = (

        "💓 HEARTBEAT BTS BOT\n\n"

        "🟢 Bot activo y monitoreando.\n\n"

        "🌐 Ticketmaster:\n"
        "• Monitoreo activo\n"
        "• Sin compra automática\n"
        "• Sin evasión de protección\n\n"

        "📅 Estados actuales:\n"

        f"• Sábado 3: "
        f"{estado_sabado}\n"

        f"• Viernes 2: "
        f"{estado_viernes}\n\n"

        "📊 Estadísticas:\n"

        f"• Consultas: "
        f"{estadisticas['consultas']}\n"

        f"• Disponibles: "
        f"{estadisticas['disponibles']}\n"

        f"• Agotados: "
        f"{estadisticas['agotados']}\n"

        f"• Desconocidos: "
        f"{estadisticas['desconocidos']}\n"

        f"• Bloqueados: "
        f"{estadisticas['bloqueados']}\n"

        f"• Errores: "
        f"{estadisticas['errores']}\n"

        f"• Recuperaciones Chrome: "
        f"{estadisticas['recuperaciones']}\n\n"

        f"⏱️ Tiempo activo: "
        f"{tiempo_activo}\n"

        f"🕐 Horas activo: "
        f"{horas_activas:.2f} h\n\n"

        f"🕐 Último heartbeat: "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    enviar_telegram(
        mensaje
    )


# ============================================================
# ESPERA
# ============================================================

def esperar_siguiente_ciclo():

    espera = random.randint(
        ESPERA_MINIMA,
        ESPERA_MAXIMA
    )

    print(
        f"⏳ Esperando {espera}s"
    )

    time.sleep(
        espera
    )


# ============================================================
# INICIO
# ============================================================

def main():

    print()
    print(
        "=" * 65
    )

    print(
        "🤖 BOT BTS TICKETMASTER"
    )

    print(
        "=" * 65
    )

    print(
        "📅 Monitoreando:"
    )

    print(
        "   • Viernes 2 de octubre de 2026"
    )

    print(
        "   • Sábado 3 de octubre de 2026"
    )

    print(
        "⏱️ Consulta aproximada: "
        f"{ESPERA_MINIMA}-{ESPERA_MAXIMA}s"
    )

    print(
        "💓 Heartbeat: cada 5 horas"
    )

    print(
        "🚨 Alertas disponibles: inmediatas"
    )

    print(
        "🔁 Repetición disponibilidad: "
        f"cada {REPETIR_ALERTA_DISPONIBLE}s"
    )

    print(
        "🚫 Sin compra automática"
    )

    print(
        "🛡️ Sin evasión de protección"
    )

    print(
        "=" * 65
    )

    # ========================================================
    # INICIAR CHROME
    # ========================================================

    if not iniciar_driver():

        enviar_telegram(

            "🔴 BTS BOT\n\n"

            "❌ No fue posible iniciar Chrome.\n\n"

            "El bot continuará intentando "
            "recuperarse.",

            es_error=True
        )

        time.sleep(10)

    # ========================================================
    # LOOP
    # ========================================================

    while True:

        try:

            print()
            print(
                "=" * 65
            )

            print(
                "🔄 NUEVO CICLO - "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )

            print(
                "=" * 65
            )

            # ------------------------------------------------
            # Resultados del ciclo.
            # ------------------------------------------------

            resultados = {}

            # =================================================
            # SÁBADO
            # =================================================

            resultados[
                URL_SABADO
            ] = consultar_fecha(
                URL_SABADO
            )

            # =================================================
            # VIERNES
            # =================================================

            resultados[
                URL_VIERNES
            ] = consultar_fecha(
                URL_VIERNES
            )

            # =================================================
            # RECUPERACIÓN ÚNICA POR CICLO
            # =================================================
            #
            # IMPORTANTE:
            # antes se recuperaba Chrome inmediatamente después
            # de cada URL bloqueada.
            #
            # Eso podía producir:
            #
            # sábado bloqueado
            #     ↓
            # recuperar Chrome
            #     ↓
            # viernes bloqueado
            #     ↓
            # recuperar Chrome otra vez
            #
            # Ahora solamente se recupera UNA vez si hace falta.
            # =================================================

            necesita_recuperacion = any(
                resultado in [
                    "error",
                    "bloqueado"
                ]
                for resultado in resultados.values()
            )

            if necesita_recuperacion:

                hubo_bloqueo = any(
                    resultado == "bloqueado"
                    for resultado in resultados.values()
                )

                hubo_error = any(
                    resultado == "error"
                    for resultado in resultados.values()
                )

                if hubo_bloqueo:

                    print()
                    print(
                        "🛡️ Una o más páginas "
                        "están bloqueadas."
                    )

                    print(
                        "🔄 Se realizará una "
                        "recuperación controlada."
                    )

                elif hubo_error:

                    print()
                    print(
                        "⚠️ Se detectó un error."
                    )

                    print(
                        "🔄 Se realizará una "
                        "recuperación controlada."
                    )

                recuperar_chrome()

            # =================================================
            # HEARTBEAT
            # =================================================

            enviar_heartbeat()

            # =================================================
            # ESPERA
            # =================================================

            esperar_siguiente_ciclo()

        except KeyboardInterrupt:

            print()
            print(
                "🛑 Bot detenido manualmente."
            )

            break

        except Exception as e:

            estadisticas["errores"] += 1

            print()
            print(
                f"💥 Error inesperado "
                f"en el ciclo principal: {e}"
            )

            enviar_telegram(

                "⚠️ BTS BOT\n\n"

                "Se produjo un error inesperado.\n\n"

                "El bot intentará recuperarse "
                "automáticamente.",

                es_error=True
            )

            recuperar_chrome()

            time.sleep(10)

    # ========================================================
    # CIERRE
    # ========================================================

    cerrar_driver()

    print(
        "👋 Bot finalizado."
    )


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":

    main()
