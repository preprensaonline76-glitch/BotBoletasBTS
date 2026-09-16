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
# CONFIGURACIÓN DE TIEMPOS
# ============================================================

ESPERA_MINIMA = 20
ESPERA_MAXIMA = 30

# Si continúa disponible, repetir alerta cada 30 segundos.
REPETIR_ALERTA_DISPONIBLE = 30

# Heartbeat cada 5 horas.
HEARTBEAT_CADA = 5 * 60 * 60

# Tiempo máximo de carga de página.
TIMEOUT_CARGA = 35


# ============================================================
# ESTADO GLOBAL
# ============================================================

driver = None

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
# CONTROL DE ERRORES DE TELEGRAM
# ============================================================

racha_errores_telegram = 0
MAX_ERRORES_TELEGRAM = 10


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    return " ".join(
        str(texto)
        .replace("\xa0", " ")
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
]


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

    "tickets are sold out",

    "tickets sold out",

    "unavailable",

    "not available",

    "entradas no disponibles",

    "boletas no disponibles",

    "tickets no disponibles",
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

    # Se mantiene para compatibilidad.
    # NO se busca "comprar" en todo el HTML.
    "comprar",
]


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje, es_error=False):

    global racha_errores_telegram

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

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

            if racha_errores_telegram <= MAX_ERRORES_TELEGRAM:

                print(
                    f"⚠️ Error Telegram "
                    f"{racha_errores_telegram}/{MAX_ERRORES_TELEGRAM}: "
                    f"{respuesta.status_code}"
                )

            return False

        print(
            f"⚠️ Telegram respondió con "
            f"código {respuesta.status_code}"
        )

        return False

    except Exception as e:

        if es_error:

            racha_errores_telegram += 1

            if racha_errores_telegram <= MAX_ERRORES_TELEGRAM:

                print(
                    f"⚠️ Error Telegram "
                    f"{racha_errores_telegram}/{MAX_ERRORES_TELEGRAM}: "
                    f"{e}"
                )

            return False

        print(
            f"⚠️ Error enviando Telegram: {e}"
        )

        return False


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    print("🌐 Iniciando Chrome...")

    opciones = Options()

    # Railway / Linux
    opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")

    # Estabilidad
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--disable-software-rasterizer")
    opciones.add_argument("--disable-extensions")

    # Reducir consumo
    opciones.add_argument("--disable-background-networking")
    opciones.add_argument("--disable-background-timer-throttling")
    opciones.add_argument("--disable-backgrounding-occluded-windows")
    opciones.add_argument("--disable-renderer-backgrounding")

    # Ventana
    opciones.add_argument("--window-size=1365,900")

    # Idioma
    opciones.add_argument("--lang=es-CO")

    # Características innecesarias
    opciones.add_argument("--disable-notifications")
    opciones.add_argument("--disable-popup-blocking")

    # No esperar recursos secundarios innecesarios.
    opciones.page_load_strategy = "eager"

    servicio = Service("/usr/bin/chromedriver")

    nuevo_driver = webdriver.Chrome(
        service=servicio,
        options=opciones
    )

    nuevo_driver.set_page_load_timeout(
        TIMEOUT_CARGA
    )

    nuevo_driver.set_script_timeout(20)

    print("✅ Chrome iniciado correctamente")

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

    if driver is not None:

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
# DETECTAR BOTÓN / ENLACE DE DISPONIBILIDAD
# ============================================================

def detectar_boton_disponibilidad():

    global driver

    if driver is None:
        return False

    try:

        # SOLO revisamos botones y enlaces.
        # No se hace body *, iframes ni Shadow DOM.
        elementos = driver.find_elements(
            "css selector",
            "button, a"
        )

        for elemento in elementos:

            try:

                if not elemento.is_displayed():
                    continue

                texto_elemento = normalizar_texto(
                    elemento.text
                )

                if not texto_elemento:
                    continue

                # ------------------------------------------------
                # IMPORTANTE:
                # Si un botón visible dice AGOTADO,
                # NO lo consideramos disponibilidad.
                # ------------------------------------------------

                if any(
                    frase in texto_elemento
                    for frase in FRASES_AGOTADO
                ):

                    continue

                # ------------------------------------------------
                # VER ENTRADAS
                # ------------------------------------------------

                if texto_elemento in [

                    "ver entradas",

                    "ver boletas",

                    "ver tickets",

                ]:

                    print(
                        "🎟️ DISPONIBILIDAD DETECTADA: "
                        f"{texto_elemento.upper()}"
                    )

                    return True

                # ------------------------------------------------
                # COMPRAR
                # ------------------------------------------------

                if texto_elemento == "comprar":

                    print(
                        "🛒 DISPONIBILIDAD DETECTADA: COMPRAR"
                    )

                    return True

                if texto_elemento in [

                    "comprar entradas",

                    "comprar boletas",

                    "comprar tickets",

                ]:

                    print(
                        "🛒 DISPONIBILIDAD DETECTADA: "
                        f"{texto_elemento.upper()}"
                    )

                    return True

                # ------------------------------------------------
                # ATRIBUTOS DE BOTONES DE TICKETMASTER
                # ------------------------------------------------

                identificador = normalizar_texto(
                    elemento.get_attribute("id")
                )

                aria_label = normalizar_texto(
                    elemento.get_attribute("aria-label")
                )

                title = normalizar_texto(
                    elemento.get_attribute("title")
                )

                atributos = (
                    identificador
                    + " "
                    + aria_label
                    + " "
                    + title
                )

                # Ejemplo: buyButton.
                # Solo se considera si el elemento es visible
                # y no contiene una señal de agotado.
                if (
                    "buybutton" in atributos
                    or "buy button" in atributos
                ):

                    print(
                        "🛒 DISPONIBILIDAD DETECTADA "
                        "EN BOTÓN DE COMPRA"
                    )

                    return True

            except Exception:

                # Si un elemento falla,
                # continuamos con el siguiente.
                continue

    except Exception as e:

        print(
            "⚠️ No se pudieron revisar "
            f"botones/enlaces: {e}"
        )

    return False


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

        # Ticketmaster renderiza contenido dinámicamente.
        # innerText obtiene el texto renderizado sin recorrer
        # todos los elementos del DOM.
        texto = driver.execute_script(
            """
            if (document.body) {
                return document.body.innerText ||
                       document.body.textContent ||
                       "";
            }

            return "";
            """
        )

        if texto and str(texto).strip():

            return str(texto)

        # Respaldo ligero.
        return driver.find_element(
            "tag name",
            "body"
        ).text

    except Exception as e:

        raise RuntimeError(
            f"No se pudo obtener el texto visible: {e}"
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

        return driver.page_source

    except Exception as e:

        raise RuntimeError(
            f"No se pudo obtener el HTML: {e}"
        )


# ============================================================
# DETECTAR ESTADO DE LA PÁGINA
# ============================================================

def detectar_estado_pagina(
    texto_visible,
    html
):

    contenido = normalizar_texto(
        (texto_visible or "")
        + " "
        + (html or "")
    )

    # ========================================================
    # 1. BLOQUEO
    # ========================================================

    for frase in FRASES_BLOQUEO:

        if frase in contenido:

            return "bloqueado"

    # ========================================================
    # 2. AGOTADO
    # ========================================================

    for frase in FRASES_AGOTADO:

        if frase in contenido:

            print(
                f"🔴 Señal de AGOTADO encontrada: {frase}"
            )

            return "agotado"

    # ========================================================
    # 3. DISPONIBILIDAD POR TEXTO
    # ========================================================

    for frase in FRASES_DISPONIBILIDAD:

        # "comprar" no se busca en HTML general.
        if frase == "comprar":
            continue

        if frase in contenido:

            print(
                f"🟢 Señal de DISPONIBILIDAD encontrada: "
                f"{frase}"
            )

            return "disponible"

    # ========================================================
    # 4. DISPONIBILIDAD EN BOTONES / ENLACES
    # ========================================================

    if detectar_boton_disponibilidad():

        return "disponible"

    # ========================================================
    # 5. DESCONOCIDO
    # ========================================================

    return "desconocido"


# ============================================================
# ABRIR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not iniciar_driver():

            return None

    try:

        driver.get(url)

        # Ticketmaster puede tardar unos segundos en
        # renderizar el contenido principal.
        time.sleep(3)

        texto_visible = obtener_texto_visible()

        # Si llegó vacío, esperamos un poco más.
        for _ in range(4):

            if len(
                normalizar_texto(texto_visible)
            ) >= 20:

                break

            time.sleep(1)

            texto_visible = obtener_texto_visible()

        html = obtener_html()

        return texto_visible, html

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

        return

    # ========================================================
    # BLOQUEADO
    # ========================================================

    if resultado == "bloqueado":

        estadisticas["bloqueados"] += 1

        print(
            f"🛡️ {nombre_evento} → BLOQUEADO"
        )

        # No cambiamos el estado anterior.
        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if resultado == "desconocido":

        estadisticas["desconocidos"] += 1

        print(
            f"❓ {nombre_evento} → desconocido"
        )

        # No sobrescribimos un estado válido.
        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if resultado == "agotado":

        estadisticas["agotados"] += 1

        print(
            f"📊 {url} → agotado"
        )

        estado_previo = estado_anterior.get(url)

        estado_anterior[url] = "agotado"

        # Solo avisar cuando cambia a agotado.
        if estado_previo != "agotado":

            mensaje = (

                "🔴 BTS WORLD TOUR\n\n"

                f"📅 {nombre_evento}\n"

                "🎫 Estado: AGOTADO\n\n"

                "Ticketmaster no muestra "
                "entradas disponibles en esta consulta."
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

        print(
            f"📊 {url} → disponible"
        )

        estado_previo = estado_anterior.get(url)

        estado_anterior[url] = "disponible"

        # Primera detección disponible.
        if estado_previo != "disponible":

            mensaje = (

                "🚨🚨🚨 BTS WORLD TOUR 🚨🚨🚨\n\n"

                f"📅 {nombre_evento}\n"

                "🎫 ¡ENTRADAS DISPONIBLES!\n\n"

                "⚡ Ticketmaster muestra "
                "una opción de compra.\n\n"

                "🔗 Entra inmediatamente a Ticketmaster."
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponible[url] = ahora

            return

        # Mientras continúe disponible:
        # repetir alerta cada 30 segundos.
        if (
            ahora
            - ultima_alerta_disponible.get(url, 0)
            >= REPETIR_ALERTA_DISPONIBLE
        ):

            mensaje = (

                "🚨 BTS WORLD TOUR\n\n"

                f"📅 {nombre_evento}\n"

                "🎫 ¡SIGUEN DISPONIBLES!\n\n"

                "⚡ Revisa Ticketmaster ahora."
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponible[url] = ahora

        return


# ============================================================
# CONSULTAR UNA FECHA
# ============================================================

def consultar_fecha(url):

    estadisticas["consultas"] += 1

    nombre_evento = EVENTOS.get(
        url,
        "EVENTO"
    )

    resultado_carga = cargar_pagina(url)

    if resultado_carga is None:

        print(
            f"❌ {nombre_evento} → error"
        )

        procesar_resultado(
            url,
            "error"
        )

        return "error"

    texto_visible, html = resultado_carga

    try:

        texto_normalizado = normalizar_texto(
            texto_visible
        )

        html_normalizado = normalizar_texto(
            html
        )

        print(
            f"📏 Texto visible: "
            f"{len(texto_visible)} caracteres"
        )

        print(
            f"📏 HTML: "
            f"{len(html)} caracteres"
        )

        # ----------------------------------------------------
        # Diagnóstico: muestra solamente los primeros 1000
        # caracteres para no llenar los logs de Railway.
        # ----------------------------------------------------

        muestra = (
            texto_visible[:1000]
            .replace("\n", " ")
        )

        print(
            f"📝 Texto recibido: {muestra}"
        )

        # ----------------------------------------------------
        # PRUEBA DIRECTA DE AGOTADO
        # ----------------------------------------------------

        if "agotado" in texto_normalizado:

            print(
                "🔴 PRUEBA DIRECTA: "
                "'agotado' ENCONTRADO "
                "EN TEXTO VISIBLE"
            )

        elif "agotado" in html_normalizado:

            print(
                "🔴 PRUEBA DIRECTA: "
                "'agotado' ENCONTRADO "
                "EN HTML"
            )

        else:

            print(
                "❌ PRUEBA DIRECTA: "
                "'agotado' NO ENCONTRADO"
            )

        # ----------------------------------------------------
        # PRUEBA DIRECTA DE BLOQUEO
        # ----------------------------------------------------

        if any(
            frase in texto_normalizado
            for frase in FRASES_BLOQUEO
        ):

            print(
                "🛡️ PRUEBA DIRECTA: "
                "PÁGINA DE PROTECCIÓN DETECTADA"
            )

        # ----------------------------------------------------
        # DETECTAR ESTADO
        # ----------------------------------------------------

        estado = detectar_estado_pagina(
            texto_visible,
            html
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
# FORMATEAR TIEMPO
# ============================================================

def formatear_duracion(segundos):

    segundos = int(segundos)

    dias = segundos // 86400

    segundos %= 86400

    horas = segundos // 3600

    segundos %= 3600

    minutos = segundos // 60

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

    return " ".join(partes)


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

    tiempo_activo = formatear_duracion(
        ahora - inicio_bot
    )

    horas_activas = (
        ahora - inicio_bot
    ) / 3600

    estado_sabado = (
        estado_anterior.get(URL_SABADO)
        or "sin datos"
    )

    estado_viernes = (
        estado_anterior.get(URL_VIERNES)
        or "sin datos"
    )

    mensaje = (

        "💓 HEARTBEAT BTS BOT\n\n"

        "🟢 Bot activo y monitoreando.\n\n"

        "📅 Estados actuales:\n"

        f"• Sábado 3: {estado_sabado}\n"

        f"• Viernes 2: {estado_viernes}\n\n"

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

        f"🕐 "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    enviar_telegram(
        mensaje
    )


# ============================================================
# RECUPERACIÓN DESPUÉS DE ERROR / BLOQUEO
# ============================================================

def manejar_recuperacion(resultado):

    if resultado not in [
        "error",
        "bloqueado"
    ]:

        return

    if resultado == "bloqueado":

        print(
            "🛡️ Ticketmaster detectó "
            "actividad sospechosa."
        )

        print(
            "🔄 Se reiniciará Chrome "
            "sin intentar evadir la protección."
        )

    else:

        print(
            "⚠️ Se detectó un error."
        )

        print(
            "🔄 Intentando recuperar Chrome..."
        )

    recuperar_chrome()


# ============================================================
# ESPERA ALEATORIA
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

    print(
        "=" * 60
    )

    print(
        "🤖 BOT BTS TICKETMASTER"
    )

    print(
        "=" * 60
    )

    print(
        "📅 Monitoreando:"
    )

    print(
        "   • Sábado 3 de octubre de 2026"
    )

    print(
        "   • Viernes 2 de octubre de 2026"
    )

    print(
        "⏱️ Heartbeat: cada 5 horas"
    )

    print(
        "📈 El heartbeat mostrará el tiempo total activo"
    )

    print(
        "🚫 Sin compra automática"
    )

    print(
        "🛡️ Sin evasión de protección"
    )

    print(
        "=" * 60
    )

    # ========================================================
    # INICIAR CHROME
    # ========================================================

    if not iniciar_driver():

        mensaje = (

            "🔴 BTS BOT\n\n"

            "❌ No fue posible iniciar Chrome.\n"

            "El bot continuará intentando "
            "recuperarse."
        )

        enviar_telegram(
            mensaje,
            es_error=True
        )

        time.sleep(10)

    # ========================================================
    # LOOP PRINCIPAL
    # ========================================================

    while True:

        try:

            print()
            print("=" * 60)

            print(
                "🔄 NUEVO CICLO - "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )

            print(
                "=" * 60
            )

            # =================================================
            # SÁBADO
            # =================================================

            print(
                "🔎 Revisando: "
                "Sábado 3 de octubre de 2026"
            )

            resultado_sabado = consultar_fecha(
                URL_SABADO
            )

            manejar_recuperacion(
                resultado_sabado
            )

            # =================================================
            # VIERNES
            # =================================================

            print(
                "🔎 Revisando: "
                "Viernes 2 de octubre de 2026"
            )

            resultado_viernes = consultar_fecha(
                URL_VIERNES
            )

            manejar_recuperacion(
                resultado_viernes
            )

            # =================================================
            # HEARTBEAT
            # =================================================

            enviar_heartbeat()

            # =================================================
            # ESPERA
            # =================================================

            esperar_siguiente_ciclo()

        except KeyboardInterrupt:

            print(
                "\n🛑 Bot detenido manualmente."
            )

            break

        except Exception as e:

            estadisticas["errores"] += 1

            print(
                f"💥 Error inesperado "
                f"en el ciclo principal: {e}"
            )

            enviar_telegram(

                "⚠️ BTS BOT\n\n"

                "Se produjo un error inesperado.\n"

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
