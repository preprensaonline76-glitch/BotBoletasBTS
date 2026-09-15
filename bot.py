# ============================================================
# BOT BOLETAS BTS - TICKETMASTER COLOMBIA
# ============================================================
#
# MONITOREO:
#   - BTS WORLD TOUR ARIRANG - BOGOTÁ
#   - Viernes 2 de octubre de 2026
#   - Sábado 3 de octubre de 2026
#
# FUNCIONES:
#   ✓ Detecta AGOTADO directamente
#   ✓ Detecta disponibilidad real
#   ✓ No utiliza puntuaciones
#   ✓ No considera un crash de Chrome como disponibilidad
#   ✓ Recuperación automática de Chrome
#   ✓ Alerta inmediata al detectar disponibilidad
#   ✓ Repite alerta cada 30 segundos mientras esté disponible
#   ✓ Alerta cuando vuelve a agotado
#   ✓ Heartbeat cada 5 horas
#   ✓ Estadísticas
#   ✓ Máximo 10 mensajes de error por racha
#   ✓ Persistencia del estado
#
# Variables Railway necesarias:
#   TOKEN
#   CHAT_ID
#
# ============================================================

import os
import re
import json
import time
import traceback
import requests

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
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

URLS = [
    {
        "nombre": "Sábado 3 de octubre",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    },
    {
        "nombre": "Viernes 2 de octubre",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre",
    },
]

# Tiempo normal entre ciclos completos
INTERVALO_NORMAL = 30

# Tiempo entre revisiones cuando hay disponibilidad
INTERVALO_DISPONIBLE = 30

# Heartbeat
INTERVALO_HEARTBEAT = 5 * 60 * 60

# Timeout de carga
PAGE_LOAD_TIMEOUT = 45

# Timeout para encontrar elementos
ELEMENT_TIMEOUT = 10

# Archivo para conservar estados
ARCHIVO_ESTADO = "/tmp/ticketmaster_estado.json"

# Máximo de mensajes de error consecutivos
MAX_ERRORES_TELEGRAM = 10


# ============================================================
# VARIABLES GLOBALES
# ============================================================

driver = None

estado_anterior = {}

ultima_alerta_disponibilidad = {}

ultimo_heartbeat = time.time()

inicio_bot = time.time()

contador_revisiones = 0
contador_revisiones_correctas = 0
contador_errores = 0

contador_agotado = 0
contador_disponible = 0

contador_recuperaciones_chrome = 0

racha_errores_telegram = 0


# ============================================================
# LOG
# ============================================================

def log(mensaje):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ahora}] {mensaje}", flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje, forzar=False):
    global racha_errores_telegram

    if not TOKEN or not CHAT_ID:
        log("⚠️ TOKEN o CHAT_ID no configurados.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    datos = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "disable_web_page_preview": True,
    }

    try:
        respuesta = requests.post(
            url,
            data=datos,
            timeout=15,
        )

        if respuesta.ok:
            racha_errores_telegram = 0
            return True

        racha_errores_telegram += 1

        log(
            f"⚠️ Telegram respondió HTTP "
            f"{respuesta.status_code}: {respuesta.text[:300]}"
        )

        if forzar or racha_errores_telegram <= MAX_ERRORES_TELEGRAM:
            log(
                f"⚠️ Error Telegram "
                f"({racha_errores_telegram}/{MAX_ERRORES_TELEGRAM})"
            )

        return False

    except Exception as e:
        racha_errores_telegram += 1

        if forzar or racha_errores_telegram <= MAX_ERRORES_TELEGRAM:
            log(
                f"⚠️ Error enviando Telegram "
                f"({racha_errores_telegram}/{MAX_ERRORES_TELEGRAM}): {e}"
            )

        return False


# ============================================================
# ESTADO
# ============================================================

def cargar_estado():

    global estado_anterior
    global ultima_alerta_disponibilidad

    if not os.path.exists(ARCHIVO_ESTADO):
        estado_anterior = {}
        ultima_alerta_disponibilidad = {}
        return

    try:

        with open(
            ARCHIVO_ESTADO,
            "r",
            encoding="utf-8",
        ) as archivo:

            datos = json.load(archivo)

        estado_anterior = datos.get(
            "estado_anterior",
            {},
        )

        ultima_alerta_disponibilidad = datos.get(
            "ultima_alerta_disponibilidad",
            {},
        )

        log("💾 Estado anterior cargado correctamente.")

    except Exception as e:

        log(
            f"⚠️ No se pudo cargar el estado anterior: {e}"
        )

        estado_anterior = {}
        ultima_alerta_disponibilidad = {}


def guardar_estado():

    datos = {
        "estado_anterior": estado_anterior,
        "ultima_alerta_disponibilidad": ultima_alerta_disponibilidad,
    }

    try:

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

        log(
            f"⚠️ Error guardando estado: {e}"
        )


# ============================================================
# CREAR CHROME
# ============================================================

def crear_driver():

    global driver

    log("🚀 Iniciando Chrome...")

    opciones = Options()

    # Headless para Railway
    opciones.add_argument("--headless=new")

    # Necesario en contenedores
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")

    # Reduce consumo
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--disable-software-rasterizer")

    # Reduce procesos innecesarios
    opciones.add_argument("--disable-extensions")
    opciones.add_argument("--disable-background-networking")
    opciones.add_argument("--disable-background-timer-throttling")
    opciones.add_argument("--disable-backgrounding-occluded-windows")
    opciones.add_argument("--disable-renderer-backgrounding")

    # Reduce consumo de memoria
    opciones.add_argument("--disable-features=Translate")
    opciones.add_argument("--disable-features=BackForwardCache")

    opciones.add_argument("--window-size=1280,900")

    # Evitar problemas de sandbox
    opciones.add_argument("--disable-setuid-sandbox")

    # Evitar ciertas optimizaciones problemáticas en contenedores
    opciones.add_argument("--disable-infobars")

    # Idioma
    opciones.add_argument("--lang=es-CO")

    # User agent normal
    opciones.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )

    # Estrategia de carga
    opciones.page_load_strategy = "eager"

    try:

        driver = webdriver.Chrome(
            options=opciones
        )

        driver.set_page_load_timeout(
            PAGE_LOAD_TIMEOUT
        )

        driver.set_script_timeout(
            15
        )

        log("✅ Selenium creado correctamente.")

        return True

    except Exception as e:

        log(
            f"❌ No se pudo iniciar Selenium: {e}"
        )

        driver = None

        return False


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
# PROBAR CHROME
# ============================================================

def probar_chrome():

    global driver

    if driver is None:
        return False

    try:

        driver.get(
            "https://www.ticketmaster.co/"
        )

        time.sleep(3)

        texto = driver.find_element(
            By.TAG_NAME,
            "body"
        ).text

        if texto:

            log(
                "📄 Ticketmaster: "
                + texto[:500].replace("\n", " ")
            )

        log(
            "✅ Chrome/Chromium operativo."
        )

        return True

    except Exception as e:

        log(
            f"❌ Chrome no respondió correctamente: {e}"
        )

        return False


# ============================================================
# RECUPERAR CHROME
# ============================================================

def recuperar_chrome():

    global contador_recuperaciones_chrome

    contador_recuperaciones_chrome += 1

    log("🔄 Recuperando Chrome...")

    cerrar_driver()

    time.sleep(2)

    for intento in range(1, 4):

        log(
            f"🔄 Intento de recuperación "
            f"{intento}/3..."
        )

        if not crear_driver():
            time.sleep(3)
            continue

        if probar_chrome():

            log(
                "✅ Chrome recuperado correctamente."
            )

            return True

        cerrar_driver()

        time.sleep(3)

    log(
        "❌ No fue posible recuperar Chrome."
    )

    return False


# ============================================================
# CARGAR PÁGINA
# ============================================================

def cargar_pagina(url):

    global driver

    if driver is None:

        if not crear_driver():

            return False

    for intento in range(1, 3):

        try:

            log(
                f"🌐 Cargando página "
                f"(intento {intento}/2)..."
            )

            driver.get(url)

            # Espera corta.
            # No queremos mantener Chrome ocupado demasiado tiempo.
            time.sleep(3)

            return True

        except TimeoutException:

            log(
                "⏱️ Timeout cargando página."
            )

            # Intentamos continuar porque eager
            # puede haber cargado suficiente contenido.

            try:

                driver.execute_script(
                    "window.stop();"
                )

            except Exception:
                pass

            time.sleep(2)

            try:

                body = driver.find_element(
                    By.TAG_NAME,
                    "body"
                )

                if body.text.strip():

                    return True

            except Exception:
                pass

        except WebDriverException as e:

            log(
                f"⚠️ Error Selenium cargando página: {e}"
            )

            # Si es un crash, no seguimos usando
            # ese navegador.

            if "tab crashed" in str(e).lower():

                return False

            time.sleep(2)

        except Exception as e:

            log(
                f"⚠️ Error cargando página: {e}"
            )

            time.sleep(2)

    return False


# ============================================================
# OBTENER CONTENIDO PRINCIPAL
# ============================================================

def obtener_contenido():

    global driver

    if driver is None:
        return ""

    textos = []

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    try:

        body = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        texto_body = body.text

        if texto_body:
            textos.append(texto_body)

    except Exception as e:

        log(
            f"⚠️ Error obteniendo BODY: {e}"
        )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    try:

        html = driver.page_source

        if html:
            textos.append(html)

    except Exception as e:

        log(
            f"⚠️ Error obteniendo HTML: {e}"
        )

    # --------------------------------------------------------
    # UNIR
    # --------------------------------------------------------

    contenido = "\n".join(textos)

    log(
        f"📄 Contenido obtenido: "
        f"{len(contenido)} caracteres"
    )

    return contenido


# ============================================================
# NORMALIZAR TEXTO
# ============================================================

def normalizar_texto(texto):

    if not texto:
        return ""

    texto = texto.lower()

    # Espacios
    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto.strip()


# ============================================================
# DETECTAR AGOTADO EN TEXTO
# ============================================================

def detectar_agotado_en_texto(contenido):

    texto = normalizar_texto(
        contenido
    )

    if not texto:
        return False

    patrones_agotado = [

        "agotado",
        "agotada",
        "agotados",
        "agotadas",

        "entradas agotadas",
        "boletas agotadas",
        "tickets agotados",

        "evento agotado",

        "no hay entradas",
        "no hay boletas",
        "no hay tickets",

        "entradas no disponibles",
        "boletas no disponibles",
        "tickets no disponibles",

        "sin entradas disponibles",
        "sin boletas disponibles",
        "sin tickets disponibles",

        "sold out",
        "sold-out",

        "no tickets available",
        "tickets unavailable",
        "tickets are currently unavailable",
        "tickets not available",

        "no seats available",
        "seats unavailable",
        "no seats currently available",
    ]

    for patron in patrones_agotado:

        if patron in texto:

            log(
                f"🔴 AGOTADO encontrado en texto: "
                f"'{patron}'"
            )

            return True

    return False


# ============================================================
# DETECTAR AGOTADO EN ELEMENTOS VISIBLES
# ============================================================

def detectar_agotado_elementos():

    global driver

    if driver is None:
        return False

    patrones = [
        "agotado",
        "agotada",
        "agotados",
        "agotadas",
        "sold out",
        "sold-out",
    ]

    try:

        elementos = driver.find_elements(
            By.CSS_SELECTOR,
            "body *"
        )

        # No recorremos indefinidamente.
        # Solo necesitamos encontrar una coincidencia.
        limite = min(
            len(elementos),
            5000
        )

        for elemento in elementos[:limite]:

            try:

                textos = []

                texto = elemento.text

                if texto:
                    textos.append(texto)

                for atributo in [
                    "aria-label",
                    "title",
                    "value",
                ]:

                    try:

                        valor = elemento.get_attribute(
                            atributo
                        )

                        if valor:
                            textos.append(valor)

                    except Exception:
                        pass

                combinado = normalizar_texto(
                    " ".join(textos)
                )

                if not combinado:
                    continue

                for patron in patrones:

                    if patron in combinado:

                        log(
                            "🔴 AGOTADO encontrado "
                            f"en elemento: "
                            f"'{combinado[:250]}'"
                        )

                        return True

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error inspeccionando "
            f"elementos: {e}"
        )

    return False


# ============================================================
# DETECTAR CONTROLES DE COMPRA
# ============================================================

def detectar_controles_compra():

    global driver

    if driver is None:
        return False

    # IMPORTANTE:
    # NO usamos simplemente "comprar".
    #
    # Ticketmaster puede mostrar recomendaciones
    # de otros eventos con botones "Comprar".
    #
    # Buscamos acciones mucho más relacionadas
    # directamente con la selección de entradas.

    patrones = [

        "comprar boletas",
        "comprar entradas",
        "comprar tickets",

        "seleccionar localidad",
        "seleccionar asiento",
        "seleccionar asientos",

        "seleccionar entradas",
        "seleccionar boletas",
        "seleccionar tickets",

        "continuar con la compra",

        "buy tickets",
        "buy now",
        "purchase tickets",

        "select seats",
        "select tickets",
        "choose seats",
        "choose tickets",

        "get tickets",
        "checkout",
    ]

    try:

        elementos = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button'], "
            "input, [data-testid]"
        )

        for elemento in elementos:

            try:

                textos = []

                texto = elemento.text

                if texto:
                    textos.append(texto)

                for atributo in [
                    "aria-label",
                    "title",
                    "value",
                    "data-testid",
                ]:

                    try:

                        valor = elemento.get_attribute(
                            atributo
                        )

                        if valor:
                            textos.append(valor)

                    except Exception:
                        pass

                combinado = normalizar_texto(
                    " ".join(textos)
                )

                if not combinado:
                    continue

                for patron in patrones:

                    if patron in combinado:

                        # Comprobamos que esté visible.
                        try:

                            if not elemento.is_displayed():
                                continue

                        except Exception:
                            pass

                        log(
                            "🟢 Control de compra "
                            f"detectado: "
                            f"'{combinado[:200]}'"
                        )

                        return True

            except Exception:
                continue

    except Exception as e:

        log(
            f"⚠️ Error controles compra: {e}"
        )

    log(
        "⚪ No se detectaron controles "
        "de compra activos."
    )

    return False


# ============================================================
# DETECTAR INDICADORES DE DISPONIBILIDAD
# ============================================================

def detectar_indicadores_disponibilidad():

    global driver

    if driver is None:
        return False

    patrones = [

        "selecciona tus entradas",
        "selecciona tus boletas",
        "selecciona tus tickets",

        "seleccione sus entradas",
        "seleccione sus boletas",
        "seleccione sus tickets",

        "entradas disponibles",
        "boletas disponibles",
        "tickets disponibles",
        "localidades disponibles",

        "seleccionar localidad",
        "seleccionar asiento",
        "seleccionar asientos",

        "seleccionar entradas",
        "seleccionar boletas",
        "seleccionar tickets",

        "elige tus entradas",
        "elige tus boletas",

        "select your tickets",
        "select your seats",

        "choose your seats",
        "choose your tickets",

        "available tickets",
        "tickets available",

        "available seats",
        "seats available",
    ]

    try:

        # Primero revisamos el BODY, que es mucho más barato
        # que recorrer todo el DOM.

        body = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        texto = normalizar_texto(
            body.text
        )

        for patron in patrones:

            if patron in texto:

                log(
                    "🟢 Indicador explícito "
                    f"de disponibilidad: "
                    f"'{patron}'"
                )

                return True

    except Exception as e:

        log(
            f"⚠️ Error buscando indicadores "
            f"de disponibilidad: {e}"
        )

    return False


# ============================================================
# DETECCIÓN PRINCIPAL
# ============================================================

def detectar_disponibilidad(url):

    global contador_revisiones
    global contador_revisiones_correctas
    global contador_errores
    global contador_agotado
    global contador_disponible

    contador_revisiones += 1

    log("=" * 65)

    log(
        f"🔎 Revisando:\n{url}"
    )

    # --------------------------------------------------------
    # CARGAR
    # --------------------------------------------------------

    if not cargar_pagina(url):

        contador_errores += 1

        log(
            "❌ No fue posible cargar "
            "la página correctamente."
        )

        return "error"

    # --------------------------------------------------------
    # CONTENIDO
    # --------------------------------------------------------

    contenido = obtener_contenido()

    if not contenido:

        contador_errores += 1

        log(
            "❌ No se obtuvo contenido."
        )

        return "error"

    texto_normalizado = normalizar_texto(
        contenido
    )

    log(
        "🔬 Contiene palabra 'agotado': "
        f"{'agotado' in texto_normalizado}"
    )

    # --------------------------------------------------------
    # AGOTADO - PRIORIDAD ABSOLUTA
    # --------------------------------------------------------

    if detectar_agotado_en_texto(
        contenido
    ):

        contador_revisiones_correctas += 1
        contador_agotado += 1

        log(
            "🔴🔴🔴 AGOTADO CONFIRMADO 🔴🔴🔴"
        )

        log(
            "📊 RESULTADO FINAL: AGOTADO"
        )

        return "agotado"

    # --------------------------------------------------------
    # SEGUNDA COMPROBACIÓN DE AGOTADO
    # --------------------------------------------------------

    if detectar_agotado_elementos():

        contador_revisiones_correctas += 1
        contador_agotado += 1

        log(
            "🔴🔴🔴 AGOTADO CONFIRMADO "
            "EN ELEMENTOS 🔴🔴🔴"
        )

        log(
            "📊 RESULTADO FINAL: AGOTADO"
        )

        return "agotado"

    # --------------------------------------------------------
    # DISPONIBILIDAD
    # --------------------------------------------------------

    tiene_indicador = (
        detectar_indicadores_disponibilidad()
    )

    tiene_control = (
        detectar_controles_compra()
    )

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if tiene_indicador or tiene_control:

        contador_revisiones_correctas += 1
        contador_disponible += 1

        log(
            "🟢🟢🟢 DISPONIBILIDAD CONFIRMADA 🟢🟢🟢"
        )

        log(
            "📊 RESULTADO FINAL: DISPONIBLE"
        )

        return "disponible"

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    contador_revisiones_correctas += 1

    log(
        "⚪ No se encontró una señal clara "
        "de agotado ni disponibilidad."
    )

    log(
        "📊 RESULTADO FINAL: DESCONOCIDO"
    )

    return "desconocido"


# ============================================================
# PROCESAR RESULTADO
# ============================================================

def procesar_resultado(nombre, url, resultado):

    global estado_anterior
    global ultima_alerta_disponibilidad

    anterior = estado_anterior.get(
        url
    )

    ahora = time.time()

    log(
        f"📊 {url} → {resultado}"
    )

    # ========================================================
    # ERROR
    # ========================================================

    if resultado == "error":

        log(
            "⚠️ Error de Chrome/Selenium."
        )

        # MUY IMPORTANTE:
        # No cambiamos el estado anterior.
        #
        # Si estaba AGOTADO y Chrome falla,
        # sigue considerándose AGOTADO hasta
        # tener una revisión válida.

        recuperar_chrome()

        return

    # ========================================================
    # DESCONOCIDO
    # ========================================================

    if resultado == "desconocido":

        # Tampoco sobrescribimos un estado válido
        # por una revisión que no tiene señal clara.

        log(
            "⚪ Resultado desconocido."
        )

        log(
            "ℹ️ Se conserva el estado anterior."
        )

        return

    # ========================================================
    # AGOTADO
    # ========================================================

    if resultado == "agotado":

        if anterior != "agotado":

            mensaje = (
                "🔴 AGOTADO\n\n"
                f"🎫 BTS WORLD TOUR ARIRANG - BOGOTÁ\n"
                f"📅 {nombre}\n\n"
                "Ticketmaster indica que las entradas "
                "están agotadas."
            )

            enviar_telegram(
                mensaje
            )

            log(
                "📨 Alerta de AGOTADO enviada."
            )

        else:

            log(
                "🔴 Sigue AGOTADO. "
                "No se envía alerta repetida."
            )

        estado_anterior[url] = "agotado"

        # Reiniciar contador de disponibilidad
        ultima_alerta_disponibilidad[url] = 0

        guardar_estado()

        return

    # ========================================================
    # DISPONIBLE
    # ========================================================

    if resultado == "disponible":

        # ----------------------------------------------------
        # PRIMERA DETECCIÓN
        # ----------------------------------------------------

        if anterior != "disponible":

            mensaje = (
                "🚨🚨🚨 DISPONIBILIDAD DETECTADA 🚨🚨🚨\n\n"
                f"🎫 BTS WORLD TOUR ARIRANG - BOGOTÁ\n"
                f"📅 {nombre}\n\n"
                "🟢 Ticketmaster muestra señales "
                "de disponibilidad.\n\n"
                f"🔗 {url}"
            )

            enviar_telegram(
                mensaje
            )

            ultima_alerta_disponibilidad[url] = ahora

            log(
                "🚨 ALERTA DE DISPONIBILIDAD ENVIADA."
            )

        # ----------------------------------------------------
        # YA ESTABA DISPONIBLE
        # ----------------------------------------------------

        else:

            ultima = ultima_alerta_disponibilidad.get(
                url,
                0
            )

            if (
                ahora - ultima
                >= INTERVALO_DISPONIBLE
            ):

                mensaje = (
                    "🚨 DISPONIBILIDAD SIGUE ACTIVA 🚨\n\n"
                    f"🎫 BTS WORLD TOUR ARIRANG - BOGOTÁ\n"
                    f"📅 {nombre}\n\n"
                    "🟢 Ticketmaster continúa "
                    "mostrando disponibilidad.\n\n"
                    f"🔗 {url}"
                )

                enviar_telegram(
                    mensaje
                )

                ultima_alerta_disponibilidad[url] = ahora

                log(
                    "📨 Recordatorio de disponibilidad enviado."
                )

            else:

                log(
                    "🟢 Sigue DISPONIBLE. "
                    "Aún no corresponde otro aviso."
                )

        estado_anterior[url] = "disponible"

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

    uptime = int(
        ahora - inicio_bot
    )

    horas = uptime // 3600
    minutos = (
        uptime % 3600
    ) // 60

    mensaje = (
        "💓 BOT BTS ACTIVO\n\n"

        f"⏱️ Tiempo activo: "
        f"{horas} h {minutos} min\n\n"

        f"🔎 Revisiones totales: "
        f"{contador_revisiones}\n"

        f"✅ Revisiones correctas: "
        f"{contador_revisiones_correctas}\n"

        f"⚠️ Errores: "
        f"{contador_errores}\n\n"

        f"🔴 Detecciones AGOTADO: "
        f"{contador_agotado}\n"

        f"🟢 Detecciones DISPONIBLE: "
        f"{contador_disponible}\n\n"

        f"🔄 Recuperaciones de Chrome: "
        f"{contador_recuperaciones_chrome}\n\n"

        "🤖 Monitoreo funcionando."
    )

    enviar_telegram(
        mensaje
    )

    ultimo_heartbeat = ahora

    log(
        "💓 Heartbeat enviado."
    )


# ============================================================
# VIGILAR CHROME
# ============================================================

def chrome_sigue_vivo():

    global driver

    if driver is None:
        return False

    try:

        driver.current_url

        return True

    except Exception as e:

        log(
            f"⚠️ Chrome dejó de responder: {e}"
        )

        return False


# ============================================================
# INICIALIZACIÓN
# ============================================================

def inicializar():

    log("=" * 65)
    log("🤖 BOT BTS - TICKETMASTER")
    log("=" * 65)

    log(
        "📅 Eventos monitoreados:"
    )

    for evento in URLS:

        log(
            f"   • {evento['nombre']}"
        )

    log(
        f"⏱️ Intervalo normal: "
        f"{INTERVALO_NORMAL} segundos"
    )

    log(
        f"🚨 Intervalo disponibilidad: "
        f"{INTERVALO_DISPONIBLE} segundos"
    )

    log(
        f"💓 Heartbeat: "
        f"{INTERVALO_HEARTBEAT // 3600} horas"
    )

    log("=" * 65)

    cargar_estado()

    # --------------------------------------------------------
    # CREAR CHROME
    # --------------------------------------------------------

    if not crear_driver():

        log(
            "❌ No se pudo iniciar Chrome."
        )

        return False

    # --------------------------------------------------------
    # PRUEBA
    # --------------------------------------------------------

    if not probar_chrome():

        log(
            "⚠️ Chrome no pasó la prueba inicial."
        )

        if not recuperar_chrome():

            return False

    log(
        "✅ Chrome listo."
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    enviar_telegram(
        "🤖 Bot BTS iniciado correctamente.\n\n"
        "🎫 Monitoreo de Ticketmaster activo.\n"
        "🔴 Detección de agotado activa.\n"
        "🟢 Detección de disponibilidad activa.\n"
        "🔄 Recuperación automática de Chrome activa."
    )

    return True


# ============================================================
# BUCLE PRINCIPAL
# ============================================================

def ejecutar_bot():

    if not inicializar():

        log(
            "❌ No se pudo inicializar el bot."
        )

        return

    ciclo = 0

    while True:

        try:

            ciclo += 1

            log("=" * 65)
            log(
                f"🔁 CICLO #{ciclo}"
            )
            log("=" * 65)

            # ------------------------------------------------
            # COMPROBAR CHROME
            # ------------------------------------------------

            if not chrome_sigue_vivo():

                if not recuperar_chrome():

                    log(
                        "❌ No se pudo recuperar Chrome."
                    )

                    time.sleep(15)

                    continue

            # ------------------------------------------------
            # REVISAR EVENTOS
            # ------------------------------------------------

            hubo_disponibilidad = False

            for evento in URLS:

                nombre = evento["nombre"]
                url = evento["url"]

                try:

                    resultado = detectar_disponibilidad(
                        url
                    )

                    procesar_resultado(
                        nombre,
                        url,
                        resultado
                    )

                    if resultado == "disponible":

                        hubo_disponibilidad = True

                except Exception as e:

                    log(
                        "🔥 Error inesperado "
                        f"revisando {url}:\n"
                        f"{traceback.format_exc()}"
                    )

                    # El estado anterior se conserva.

                    continue

                # ------------------------------------------------
                # PAUSA PEQUEÑA ENTRE EVENTOS
                # ------------------------------------------------

                time.sleep(2)

            # ------------------------------------------------
            # HEARTBEAT
            # ------------------------------------------------

            enviar_heartbeat()

            # ------------------------------------------------
            # INTERVALO
            # ------------------------------------------------

            if hubo_disponibilidad:

                intervalo = INTERVALO_DISPONIBLE

            else:

                intervalo = INTERVALO_NORMAL

            log(
                f"😴 Próxima revisión en "
                f"{intervalo} segundos."
            )

            # Dormir en pequeños bloques permite
            # detectar problemas de forma más limpia.

            tiempo_dormido = 0

            while tiempo_dormido < intervalo:

                time.sleep(1)

                tiempo_dormido += 1

        except KeyboardInterrupt:

            log(
                "🛑 Bot detenido manualmente."
            )

            break

        except Exception:

            log(
                "🔥 ERROR EN BUCLE PRINCIPAL:\n"
                + traceback.format_exc()
            )

            # Intentar recuperar Chrome
            try:

                recuperar_chrome()

            except Exception:

                pass

            time.sleep(10)


# ============================================================
# CERRAR
# ============================================================

def cerrar():

    global driver

    log(
        "🛑 Cerrando bot..."
    )

    cerrar_driver()

    log(
        "✅ Bot cerrado."
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        ejecutar_bot()

    except KeyboardInterrupt:

        log(
            "🛑 Interrupción manual."
        )

    except Exception:

        log(
            "🔥 ERROR FATAL:\n"
            + traceback.format_exc()
        )

    finally:

        cerrar()
