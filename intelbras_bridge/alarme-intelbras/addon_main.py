# Archivo: addon_main.py (v2 - con sondeo de estado)
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
POLLING_INTERVAL_MINUTES = int(os.environ.get('POLLING_INTERVAL_MINUTES', 5))

# --- Constantes MQTT ---
AVAILABILITY_TOPIC = "intelbras/alarm/availability"
COMMAND_TOPIC = "intelbras/alarm/command"
BASE_TOPIC = "intelbras/alarm" # Topic base para todos los sensores

# --- Instancias Globales ---
alarm_client = AlarmClient(host=ALARM_IP, port=ALARM_PORT)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
is_alarm_authenticated = False
shutdown_event = threading.Event()

# --- Funciones de MQTT ---
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
    logging.info(f"Comando MQTT recibido en topic '{msg.topic}': '{command}'")

    if not connect_and_auth_alarm(): # Asegura sesión fresca antes del comando
        logging.error("No se pudo ejecutar el comando porque la autenticación con la alarma falló.")
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
        logging.error(f"Error de comunicación con la alarma al ejecutar comando: {e}")
        is_alarm_authenticated = False # Marcar para re-autenticar

# --- Funciones de la Alarma ---
def connect_and_auth_alarm():
    """Gestiona la conexión y autenticación con la central. Devuelve True si es exitoso."""
    global is_alarm_authenticated
    try:
        alarm_client.connect()
        alarm_client.auth(ALARM_PASS)
        is_alarm_authenticated = True
        return True
    except (CommunicationError, AuthError) as e:
        is_alarm_authenticated = False
        logging.error(f"Fallo al conectar o autenticar con la alarma: {e}")
        return False

def _map_battery_status_to_percentage(status: str) -> int | None:
    """Mapea el estado de la batería en texto a un porcentaje."""
    if status == "full": return 100
    if status == "middle": return 75
    if status == "low": return 25
    if status == "dead": return 0
    return None

def status_polling_thread():
    """Un hilo que pide el estado de la alarma periódicamente y lo publica en MQTT."""
    logging.info(f"Iniciando hilo de sondeo de estado cada {POLLING_INTERVAL_MINUTES} minutos.")
    while not shutdown_event.is_set():
        if not is_alarm_authenticated:
             if not connect_and_auth_alarm():
                logging.warning("Sondeo de estado omitido, no se pudo autenticar.")
                shutdown_event.wait(60) # Reintentar en 60 segundos si falla
                continue
        
        try:
            logging.info("Sondeando estado de la central...")
            status = alarm_client.status()
            
            # Publicar cada valor a su topic correspondiente
            mqtt_client.publish(f"{BASE_TOPIC}/model", status.get("model"), retain=True)
            mqtt_client.publish(f"{BASE_TOPIC}/version", status.get("version"), retain=True)
            
            battery_percent = _map_battery_status_to_percentage(status.get("batteryStatus"))
            if battery_percent is not None:
                mqtt_client.publish(f"{BASE_TOPIC}/battery_percentage", battery_percent, retain=True)
            
            mqtt_client.publish(f"{BASE_TOPIC}/tamper", "on" if status.get("tamper") else "off", retain=True)
            mqtt_client.publish(f"{BASE_TOPIC}/siren", "on" if status.get("siren") else "off", retain=True)
            mqtt_client.publish(f"{BASE_TOPIC}/zones_firing", "on" if status.get("zonesFiring") else "off", retain=True)
            
            logging.info("Estado de la central publicado a MQTT.")

        except (CommunicationError, AuthError) as e:
            global is_alarm_authenticated
            logging.warning(f"Error durante el sondeo de estado: {e}. Se marcará como no autenticado.")
            is_alarm_authenticated = False
        
        # Esperar para el siguiente sondeo, convirtiendo minutos a segundos
        shutdown_event.wait(POLLING_INTERVAL_MINUTES * 60)
    logging.info("Hilo de sondeo de estado terminado.")

def process_receptorip_output(proc):
    """Lee la salida de 'receptorip' y publica a MQTT."""
    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        
        logging.info(f"Evento de la Central (receptorip): {line}")

        if "Ativacao remota app" in line:
            mqtt_client.publish(f"{BASE_TOPIC}/state", "Armada", retain=True)
        elif "Desativacao remota app" in line:
            mqtt_client.publish(f"{BASE_TOPIC}/state", "Desarmada", retain=True)
    logging.warning("El proceso 'receptorip' ha terminado.")

# --- Función Principal y Manejo de Cierre ---
def handle_shutdown(signum, frame):
    logging.info("Cerrando el addon gradualmente...")
    shutdown_event.set() # Señalizar a los hilos que deben terminar
    mqtt_client.publish(AVAILABILITY_TOPIC, "offline", retain=True)
    time.sleep(1)
    mqtt_client.loop_stop()
    alarm_client.close()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    if not all([ALARM_IP, ALARM_PASS, MQTT_BROKER]):
        logging.error("Faltan variables de entorno críticas. Saliendo.")
        sys.exit(1)

    # Configurar y conectar el cliente MQTT
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    if MQTT_USER: mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        logging.error(f"No se pudo conectar al broker MQTT al inicio: {e}")
        sys.exit(1)

    mqtt_client.loop_start()

    # Iniciar el hilo de sondeo de estado
    polling_thread = threading.Thread(target=status_polling_thread)
    polling_thread.daemon = True
    polling_thread.start()

    # Iniciar el proceso 'receptorip'
    try:
        logging.info("Iniciando el proceso 'receptorip'...")
        receptorip_proc = subprocess.Popen(
            ["/alarme-intelbras/receptorip", "/alarme-intelbras/config.cfg"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        receptor_thread = threading.Thread(target=process_receptorip_output, args=(receptorip_proc,))
        receptor_thread.daemon = True
        receptor_thread.start()
    except FileNotFoundError:
        logging.error("No se pudo encontrar 'receptorip'. Asegúrate de que la ruta es correcta.")
        sys.exit(1)
        
    logging.info("El addon está en funcionamiento. Escuchando eventos, comandos y sondeando estado.")
    shutdown_event.wait()
