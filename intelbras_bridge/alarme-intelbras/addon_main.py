# Archivo: addon_main.py (v2.6 - con Lock para evitar race conditions)
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
POLLING_INTERVAL_MINUTES = int(os.environ.get('polling_interval_minutes', 5))
AVAILABILITY_TOPIC = "intelbras/alarm/availability"
COMMAND_TOPIC = "intelbras/alarm/command"
BASE_TOPIC = "intelbras/alarm"

# --- Instancias Globales ---
alarm_client = AlarmClient(host=ALARM_IP, port=ALARM_PORT)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
shutdown_event = threading.Event()
# --- CAMBIO AQUÍ (1/3): Creamos el candado global ---
alarm_lock = threading.Lock()

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
    """Callback que se ejecuta cuando llega un mensaje MQTT."""
    command = msg.payload.decode()
    logging.info(f"Comando MQTT recibido: '{command}'")

    # --- CAMBIO AQUÍ (2/3): Usamos el candado para proteger esta sección ---
    with alarm_lock:
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
            logging.error(f"Error de comunicación durante comando: {e}")

# --- Funciones de la Alarma ---
def connect_and_auth_alarm():
    """Gestiona la conexión y autenticación. ESTA FUNCIÓN DEBE SER LLAMADA DENTRO DE UN LOCK."""
    try:
        alarm_client.connect()
        alarm_client.auth(ALARM_PASS)
        return True
    except (CommunicationError, AuthError) as e:
        logging.error(f"Fallo de conexión/auth: {e}")
        return False
        
def _map_battery_status_to_percentage(status: str):
    return {"full": 100, "middle": 75, "low": 25, "dead": 0}.get(status)

def status_polling_thread():
    """Un hilo que pide el estado de la alarma periódicamente."""
    logging.info(f"Iniciando hilo de sondeo cada {POLLING_INTERVAL_MINUTES} minutos.")
    while not shutdown_event.is_set():
        # --- CAMBIO AQUÍ (3/3): Usamos el candado también para proteger el sondeo ---
        with alarm_lock:
            logging.info("Refrescando sesión para el sondeo periódico...")
            if not connect_and_auth_alarm():
                logging.warning("Sondeo de estado omitido, no se pudo autenticar.")
            else:
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
                    mqtt_client.publish(f"{BASE_TOPIC}/zones_firing", "Disparada" if status.get("zonesFiring") else "Normal", retain=True)
                    logging.info("Estado de la central publicado a MQTT.")
                except (CommunicationError, AuthError) as e:
                    logging.warning(f"Error durante el sondeo de estado: {e}.")
        
        # Esperar para el siguiente sondeo fuera del lock
        shutdown_event.wait(POLLING_INTERVAL_MINUTES * 60)
    logging.info("Hilo de sondeo de estado terminado.")

# El resto del archivo (process_receptorip_output, handle_shutdown, if __name__ == "__main__") se mantiene igual
def process_receptorip_output(proc):
    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        #logging.info(f"Evento de la Central (receptorip): {line}")
        # --- INICIO DE LA MEJORA ---
        # Intentamos separar la fecha/hora del resto del mensaje
        parts = line.split()
        message_content = line
        if len(parts) > 2 and "T" not in parts[0] and ":" in parts[1]:
            # Asumimos que es un log con formato "YYYY-MM-DD HH:MM:SS Mensaje..."
            message_content = " ".join(parts[2:])

        logging.info(f"Evento de la Central (receptorip): {message_content}")
        # --- FIN DE LA MEJORA ---
        if "Ativacao remota app" in line: mqtt_client.publish(f"{BASE_TOPIC}/state", "Armada", retain=True)
        elif "Desativacao remota app" in line: mqtt_client.publish(f"{BASE_TOPIC}/state", "Desarmada", retain=True)
        elif line.startswith("Panico"):
            logging.info(f"¡Evento de pánico detectado: {line}!")
            mqtt_client.publish(f"{BASE_TOPIC}/panic", "on", retain=False)
            threading.Timer(30.0, lambda: mqtt_client.publish(f"{BASE_TOPIC}/panic", "off", retain=False)).start()
    logging.warning("Proceso 'receptorip' terminado.")

def handle_shutdown(signum, frame):
    logging.info("Cerrando addon..."); shutdown_event.set()
    mqtt_client.publish(AVAILABILITY_TOPIC, "offline", retain=True); time.sleep(1)
    mqtt_client.loop_stop(); alarm_client.close(); sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown); signal.signal(signal.SIGINT, handle_shutdown)
    if not all([ALARM_IP, ALARM_PASS, MQTT_BROKER]): logging.error("Faltan variables críticas."); sys.exit(1)
    mqtt_client.on_connect = on_connect; mqtt_client.on_message = on_message
    mqtt_client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    if MQTT_USER: mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    try: mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e: logging.error(f"Fallo al conectar a MQTT: {e}"); sys.exit(1)
    mqtt_client.loop_start()
    threading.Thread(target=status_polling_thread, daemon=True).start()
    try:
        logging.info("Iniciando 'receptorip'...")
        proc = subprocess.Popen(["/alarme-intelbras/receptorip", "/alarme-intelbras/config.cfg"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=process_receptorip_output, args=(proc,), daemon=True).start()
    except FileNotFoundError: logging.error("No se encontró 'receptorip'."); sys.exit(1)
    logging.info("Addon en funcionamiento. Esperando eventos..."); shutdown_event.wait()
