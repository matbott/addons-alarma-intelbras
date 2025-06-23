# Archivo: addon_main.py
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

# --- Leer configuración desde variables de entorno (que pasará run.sh) ---
ALARM_IP = os.environ.get('ALARM_IP')
ALARM_PORT = int(os.environ.get('ALARM_PORT', 9009))
ALARM_PASS = os.environ.get('ALARM_PASS')
MQTT_BROKER = os.environ.get('MQTT_BROKER')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_USER = os.environ.get('MQTT_USER')
MQTT_PASS = os.environ.get('MQTT_PASS')
AVAILABILITY_TOPIC = "intelbras/alarm/availability"
COMMAND_TOPIC = "intelbras/alarm/command"

# --- Instancias Globales ---
alarm_client = AlarmClient(host=ALARM_IP, port=ALARM_PORT)
#mqtt_client = mqtt.Client()
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
is_alarm_authenticated = False

# --- Funciones de MQTT ---

def on_connect(client, userdata, flags, rc):
    """Callback que se ejecuta cuando nos conectamos al broker MQTT."""
    if rc == 0:
        logging.info(f"Conectado exitosamente al broker MQTT en {MQTT_BROKER}")
        client.subscribe(COMMAND_TOPIC)
        logging.info(f"Suscrito al topic de comandos: {COMMAND_TOPIC}")
        # Publicar que el addon está online
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    else:
        logging.error(f"Fallo al conectar al broker MQTT. Código de retorno: {rc}")

def on_message(client, userdata, msg):
    """Callback que se ejecuta cuando llega un mensaje MQTT."""
    command = msg.payload.decode()
    logging.info(f"Comando MQTT recibido en topic '{msg.topic}': '{command}'")

    global is_alarm_authenticated
    if not is_alarm_authenticated:
        logging.warning("Se recibió un comando pero la alarma no está autenticada. Intentando autenticar ahora.")
        if not connect_and_auth_alarm():
            logging.error("No se pudo ejecutar el comando porque la autenticación con la alarma falló.")
            return

    try:
        if command == "ARM_AWAY":
            logging.info("Enviando comando para ARMAR sistema...")
            alarm_client.arm_system(0)
        elif command == "DISARM":
            logging.info("Enviando comando para DESARMAR sistema...")
            alarm_client.disarm_system(0)
        else:
            logging.warning(f"Comando '{command}' no reconocido.")
    except (CommunicationError, AuthError) as e:
        logging.error(f"Error de comunicación con la alarma al ejecutar comando: {e}")
        is_alarm_authenticated = False # Marcar para re-autenticar

# --- Funciones de la Alarma ---

def connect_and_auth_alarm():
    """Gestiona la conexión y autenticación con la central de alarma."""
    global is_alarm_authenticated
    try:
        logging.info("Estableciendo conexión con la central de alarma...")
        alarm_client.connect()
        logging.info("Autenticando con la central de alarma...")
        alarm_client.auth(ALARM_PASS)
        logging.info("Autenticación con la alarma exitosa.")
        is_alarm_authenticated = True
        return True
    except (CommunicationError, AuthError) as e:
        logging.error(f"Fallo al conectar o autenticar con la alarma: {e}")
        is_alarm_authenticated = False
        return False

def process_receptorip_output(proc):
    """Lee la salida de 'receptorip' línea por línea y publica a MQTT."""
    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue
        
        logging.info(f"Evento de la Central (receptorip): {line}")

        if "Ativacao remota app" in line:
            mqtt_client.publish("intelbras/alarm/state", "Armada", retain=True)
        elif "Desativacao remota app" in line:
            mqtt_client.publish("intelbras/alarm/state", "Desarmada", retain=True)
        # Aquí puedes añadir más lógica de parseo como la tenías en run.sh
        # Ejemplo:
        # elif "Disparo de zona" in line:
        #     parts = line.split()
        #     zone_num = parts[-1]
        #     mqtt_client.publish(f"intelbras/alarm/zone_{zone_num}", "on", retain=True)
        #     mqtt_client.publish("intelbras/alarm/sounding", "Disparada", retain=True)

    logging.warning("El proceso 'receptorip' ha terminado.")

# --- Función Principal y Manejo de Cierre ---

def handle_shutdown(signum, frame):
    """Maneja el cierre gradual del addon."""
    logging.info("Cerrando el addon gradualmente...")
    # Publicar que el addon está offline
    mqtt_client.publish(AVAILABILITY_TOPIC, "offline", retain=True)
    time.sleep(1) # Dar tiempo a que se envíe el mensaje
    
    # Detener bucles y cerrar conexiones
    mqtt_client.loop_stop()
    alarm_client.close()
    
    # Terminar el proceso principal
    sys.exit(0)

if __name__ == "__main__":
    # Registrar las señales de cierre
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Validar que la configuración esencial exista
    if not all([ALARM_IP, ALARM_PASS, MQTT_BROKER]):
        logging.error("Faltan variables de entorno críticas (ALARM_IP, ALARM_PASS, MQTT_BROKER). Saliendo.")
        sys.exit(1)

    # Conectar y autenticar con la alarma al inicio
    connect_and_auth_alarm()

    # Configurar y conectar el cliente MQTT
    if MQTT_USER:
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.will_set(AVAILABILITY_TOPIC, "offline", retain=True) # Last Will and Testament
    
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        logging.error(f"No se pudo conectar al broker MQTT al inicio: {e}")
        sys.exit(1)

    # Iniciar el bucle de MQTT en un hilo separado
    mqtt_client.loop_start()

    # Iniciar el proceso 'receptorip' y el hilo que lo procesa
    try:
        logging.info("Iniciando el proceso 'receptorip'...")
        # La ruta debe ser relativa a la ubicación del script o absoluta
        receptorip_proc = subprocess.Popen(
            ["/alarme-intelbras/receptorip", "/alarme-intelbras/config.cfg"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        receptor_thread = threading.Thread(target=process_receptorip_output, args=(receptorip_proc,))
        receptor_thread.daemon = True
        receptor_thread.start()

    except FileNotFoundError:
        logging.error("No se pudo encontrar el ejecutable 'receptorip'. Asegúrate de que la ruta es correcta.")
        sys.exit(1)
        
    # Mantener el script principal vivo
    logging.info("El addon está en funcionamiento. Escuchando eventos y comandos.")
    while True:
        time.sleep(300) # Dormir en ciclos largos para no consumir CPU
        # Podríamos añadir aquí una verificación de estado si fuera necesario
