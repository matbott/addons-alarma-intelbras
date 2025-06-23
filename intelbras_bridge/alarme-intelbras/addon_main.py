# Archivo: addon_main.py (v2.5 - con logging de zonas)
import os
import sys
import logging
import subprocess
import threading
import signal
import time
import paho.mqtt.client as mqtt
from client import Client as AlarmClient, CommunicationError, AuthError

# --- Configuración del Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# --- Leer configuración desde variables de entorno ---
ALARM_IP = os.environ.get('ALARM_IP')
ALARM_PORT = int(os.environ.get('ALARM_PORT', 9009))
ALARM_PASS = os.environ.get('ALARM_PASS')
MQTT_BROKER = os.environ.get('MQTT_BROKER')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_USER = os.environ.get('MQTT_USER')
MQTT_PASS = os.environ.get('MQTT_PASS')
# Leemos la nueva variable de entorno
POLLING_INTERVAL_MINUTES = int(os.environ.get('POLLING_INTERVAL_MINUTES', 5))
AVAILABILITY_TOPIC = "intelbras/alarm/availability"
COMMAND_TOPIC = "intelbras/alarm/command"
BASE_TOPIC = "intelbras/alarm"

# --- Instancias Globales ---
alarm_client = AlarmClient(host=ALARM_IP, port=ALARM_PORT)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
is_alarm_authenticated = False
# Nuevo evento para manejar el cierre gradual
shutdown_event = threading.Event()

# --- Funciones de MQTT (sin cambios) ---
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logging.info(f"Conectado exitosamente al broker MQTT en {MQTT_BROKER}")
        client.subscribe(COMMAND_TOPIC)
        logging.info(f"Suscrito al topic de comandos: {COMMAND_TOPIC}")
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    else:
        logging.error(f"Fallo al conectar al broker MQTT: {reason_code}")

def on_message(client, userdata, msg):
    command = msg.payload.decode()
    logging.info(f"Comando MQTT recibido: '{command}'")
    logging.info("Refrescando sesión con la central antes de enviar el comando...")
    if not connect_and_auth_alarm():
        logging.error("No se pudo ejecutar el comando porque la re-autenticación con la alarma falló.")
        return
    try:
        if command == "ARM_AWAY":
            logging.info("Enviando comando para ARMAR sistema...")
            alarm_client.arm_system(0)
        elif command == "DISARM":
            logging.info("Enviando comando para DESARMAR sistema...")
            alarm_client.disarm_system(0)
    except (CommunicationError, AuthError) as e:
        global is_alarm_authenticated
        logging.error(f"Error de comunicación durante comando: {e}")
        is_alarm_authenticated = False

# --- Funciones de la Alarma (sin cambios) ---
def connect_and_auth_alarm():
    global is_alarm_authenticated
    try:
        alarm_client.connect(); alarm_client.auth(ALARM_PASS)
        is_alarm_authenticated = True; return True
    except (CommunicationError, AuthError) as e:
        is_alarm_authenticated = False; logging.error(f"Fallo de conexión/auth: {e}"); return False

# --- NUEVA FUNCIÓN DE SONDEO Y LOGGING ---
def status_polling_thread():
    """Un hilo que pide el estado de la alarma periódicamente y lo muestra en el log."""
    logging.info(f"Iniciando hilo de sondeo de estado cada {POLLING_INTERVAL_MINUTES} minutos.")
    
    while not shutdown_event.is_set():
        # --- INICIO DE LA CORRECCIÓN ---
        # En lugar de comprobar una variable, llamamos a connect_and_auth_alarm()
        # al inicio de CADA ciclo para asegurar una sesión fresca.
        logging.info("Refrescando sesión para el sondeo periódico...")
        if not connect_and_auth_alarm():
            logging.warning("Sondeo de estado omitido, no se pudo autenticar. Reintentando en 60s.")
            shutdown_event.wait(60) # Esperar 60 segundos antes de reintentar si falla
            continue
        # --- FIN DE LA CORRECCIÓN ---
        
        try:
            logging.info("Sondeando estado de la central para el log...")
            status = alarm_client.status()
            
            # ¡AQUÍ ESTÁ LA LÓGICA CLAVE!
            # En lugar de publicar a MQTT, simplemente mostramos el diccionario de zonas en el log.
            if 'zones' in status:
                logging.info(f"Estado de Zonas detectado: {status['zones']}")
            else:
                logging.warning("No se encontró información de zonas en la respuesta de estado.")

        except (CommunicationError, AuthError) as e:
            logging.warning(f"Error durante el sondeo de estado: {e}. Se marcará como no autenticado.")
            is_alarm_authenticated = False
        
        # Esperar para el siguiente ciclo, convirtiendo minutos a segundos
        shutdown_event.wait(POLLING_INTERVAL_MINUTES * 60)
    
    logging.info("Hilo de sondeo de estado terminado.")

# --- process_receptorip_output (sin cambios) ---
def process_receptorip_output(proc):
    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        logging.info(f"Evento de la Central (receptorip): {line}")
        if "Ativacao remota app" in line: mqtt_client.publish(f"{BASE_TOPIC}/state", "Armada", retain=True)
        elif "Desativacao remota app" in line: mqtt_client.publish(f"{BASE_TOPIC}/state", "Desarmada", retain=True)
        elif line.startswith("Panico"):
            logging.info(f"¡Evento de pánico detectado: {line}!")
            mqtt_client.publish(f"{BASE_TOPIC}/panic", "on", retain=False)
            threading.Timer(30.0, lambda: mqtt_client.publish(f"{BASE_TOPIC}/panic", "off", retain=False)).start()
    logging.warning("Proceso 'receptorip' terminado.")

# --- Función de Cierre (actualizada para manejar el nuevo evento) ---
def handle_shutdown(signum, frame):
    logging.info("Cerrando addon gradualmente...")
    shutdown_event.set() # Avisar a los hilos que deben terminar
    mqtt_client.publish(AVAILABILITY_TOPIC, "offline", retain=True); time.sleep(1)
    mqtt_client.loop_stop(); alarm_client.close(); sys.exit(0)

# --- Bucle Principal (actualizado para iniciar el nuevo hilo) ---
if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown); signal.signal(signal.SIGINT, handle_shutdown)
    if not all([ALARM_IP, ALARM_PASS, MQTT_BROKER]): logging.error("Faltan variables críticas."); sys.exit(1)
    
    mqtt_client.on_connect = on_connect; mqtt_client.on_message = on_message
    mqtt_client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    if MQTT_USER: mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    try: mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e: logging.error(f"Fallo al conectar a MQTT: {e}"); sys.exit(1)
    
    mqtt_client.loop_start()

    # --- INICIAR EL NUEVO HILO DE SONDEO ---
    polling_thread = threading.Thread(target=status_polling_thread, daemon=True)
    polling_thread.start()

    # Iniciar el proceso 'receptorip' (sin cambios)
    try:
        logging.info("Iniciando 'receptorip'...")
        proc = subprocess.Popen(["/alarme-intelbras/receptorip", "/alarme-intelbras/config.cfg"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=process_receptorip_output, args=(proc,), daemon=True).start()
    except FileNotFoundError: logging.error("No se encontró 'receptorip'."); sys.exit(1)
        
    logging.info("Addon en funcionamiento. Esperando eventos, comandos y sondeando estado para el log.")
    # El hilo principal espera al evento de cierre
    shutdown_event.wait()
