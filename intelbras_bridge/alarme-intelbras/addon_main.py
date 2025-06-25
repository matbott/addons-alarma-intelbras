# Archivo: addon_main.py (v3.4 - Sensores detallados y Pánico)
import os, sys, logging, subprocess, threading, signal, time
import paho.mqtt.client as mqtt
from client import Client as AlarmClient, CommunicationError, AuthError

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] - %(levelname)s - %(message)s', stream=sys.stdout)

# --- Configuración ---
ALARM_IP = os.environ.get('ALARM_IP'); ALARM_PORT = int(os.environ.get('ALARM_PORT', 9009)); ALARM_PASS = os.environ.get('ALARM_PASS')
MQTT_BROKER = os.environ.get('MQTT_BROKER'); MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883)); MQTT_USER = os.environ.get('MQTT_USER'); MQTT_PASS = os.environ.get('MQTT_PASS')
POLLING_INTERVAL_MINUTES = int(os.environ.get('POLLING_INTERVAL_MINUTES', 5))
ZONE_COUNT = int(os.environ.get('ZONE_COUNT', 0))
AVAILABILITY_TOPIC = "intelbras/alarm/availability"; COMMAND_TOPIC = "intelbras/alarm/command"; BASE_TOPIC = "intelbras/alarm"
alarm_client = AlarmClient(host=ALARM_IP, port=ALARM_PORT)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
shutdown_event = threading.Event(); alarm_lock = threading.Lock()

# --- Almacén Central de Estados ---
zone_states = {str(i): "Desconocido" for i in range(1, ZONE_COUNT + 1)}

# --- Funciones de MQTT ---
def publish_zone_states():
    for zone_id, state in zone_states.items():
        mqtt_client.publish(f"{BASE_TOPIC}/zone_{zone_id}", state, retain=True)
    logging.info(f"Estados de zona publicados a MQTT: {zone_states}")

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logging.info("Conectado a MQTT y suscrito.")
        client.subscribe(COMMAND_TOPIC)
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        # --- INICIO: Publicar estado inicial de nuevos sensores ---
        client.publish(f"{BASE_TOPIC}/ac_power", "on", retain=True)
        client.publish(f"{BASE_TOPIC}/system_battery", "on", retain=True)
        # --- FIN: Publicar estado inicial ---
    else:
        logging.error(f"Fallo al conectar a MQTT: {reason_code}")

def on_message(client, userdata, msg):
    command = msg.payload.decode()
    logging.info(f"Comando MQTT recibido: '{command}'")
    with alarm_lock:
        if not connect_and_auth_alarm(): logging.error("Fallo de auth, comando no ejecutado."); return
        try:
            if command == "ARM_AWAY":
                alarm_client.arm_system(0)
            elif command == "DISARM":
                alarm_client.disarm_system(0)
            elif command == "PANIC":
                logging.info("¡Activando pánico audible desde Home Assistant!")
                alarm_client.panic(1) # El tipo 1 suele ser pánico audible
        except (CommunicationError, AuthError) as e: logging.error(f"Error de comunicación en comando: {e}")

# --- Funciones de la Alarma ---
def connect_and_auth_alarm():
    try: alarm_client.connect(); alarm_client.auth(ALARM_PASS); return True
    except (CommunicationError, AuthError) as e: logging.error(f"Fallo de conexión/auth: {e}"); return False

def _map_battery_status_to_percentage(status: str) -> int:
    return {"full": 100, "middle": 75, "low": 25, "dead": 0}.get(status, 0)

def status_polling_thread():
    logging.info(f"Iniciando sondeo cada {POLLING_INTERVAL_MINUTES} minutos.")
    while not shutdown_event.is_set():
        with alarm_lock:
            if not connect_and_auth_alarm(): logging.warning("Sondeo omitido, no se pudo autenticar.")
            else:
                try:
                    logging.info("Sondeando estado de la central...")
                    status = alarm_client.status()
                    mqtt_client.publish(f"{BASE_TOPIC}/model", status.get("model", "Desconocido"), retain=True)
                    mqtt_client.publish(f"{BASE_TOPIC}/version", status.get("version", "Desconocido"), retain=True)
                    battery_level = _map_battery_status_to_percentage(status.get("batteryStatus"))
                    mqtt_client.publish(f"{BASE_TOPIC}/battery_percentage", battery_level, retain=True)
                    tamper_state = "on" if status.get("tamper", False) else "off"
                    mqtt_client.publish(f"{BASE_TOPIC}/tamper", tamper_state, retain=True)
                    logging.info(f"Publicados estados generales: Batería={battery_level}%, Tamper={tamper_state}")
                    if 'zones' in status and isinstance(status['zones'], dict):
                        for zone_id, new_state_str in status['zones'].items():
                            if int(zone_id) <= ZONE_COUNT:
                                if zone_states.get(zone_id) != "Disparada":
                                    zone_states[zone_id] = "Abierta" if new_state_str == "open" else "Cerrada"
                    publish_zone_states()
                except (CommunicationError, AuthError) as e: logging.warning(f"Error durante sondeo: {e}.")
        shutdown_event.wait(POLLING_INTERVAL_MINUTES * 60)
    logging.info("Hilo de sondeo terminado.")

def process_receptorip_output(proc):
    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        logging.info(f"Evento (receptorip): {line}")
        publish_required = False
        with alarm_lock:
            if "Ativacao remota app" in line: mqtt_client.publish(f"{BASE_TOPIC}/state", "Armada", retain=True)
            elif "Desativacao remota app" in line:
                mqtt_client.publish(f"{BASE_TOPIC}/state", "Desarmada", retain=True)
                for zone_id in zone_states: zone_states[zone_id] = "Cerrada"
                publish_required = True
            elif "Panico" in line:
                logging.info(f"¡Evento de pánico detectado: {line}!")
                mqtt_client.publish(f"{BASE_TOPIC}/panic", "on", retain=False)
                threading.Timer(30.0, lambda: mqtt_client.publish(f"{BASE_TOPIC}/panic", "off", retain=False)).start()
            # --- INICIO: Lógica para nuevos sensores de estado ---
            elif "Falta de energia AC" in line:
                mqtt_client.publish(f"{BASE_TOPIC}/ac_power", "off", retain=True)
            elif "Retorno de energia AC" in line:
                mqtt_client.publish(f"{BASE_TOPIC}/ac_power", "on", retain=True)
            elif "Bateria do sistema baixa" in line:
                mqtt_client.publish(f"{BASE_TOPIC}/system_battery", "off", retain=True)
            elif "Recuperacao bateria do sistema baixa" in line:
                mqtt_client.publish(f"{BASE_TOPIC}/system_battery", "on", retain=True)
            # --- FIN: Lógica para nuevos sensores ---
            elif "Disparo de zona" in line:
                try:
                    zone_id = line.split()[-1]
                    if int(zone_id) <= ZONE_COUNT:
                        zone_states[zone_id] = "Disparada"
                        mqtt_client.publish(f"{BASE_TOPIC}/state", "Disparada", retain=True)
                        logging.info(f"Panel de alarma puesto en estado 'Disparada' debido a zona {zone_id}")
                        publish_required = True
                except: logging.warning(f"No se pudo extraer ID de zona de: {line}")
            elif "Restauracao de zona" in line:
                try:
                    zone_id = line.split()[-1]
                    if int(zone_id) <= ZONE_COUNT:
                        zone_states[zone_id] = "Cerrada"
                        publish_required = True
                except: logging.warning(f"No se pudo extraer ID de zona de: {line}")
        if publish_required:
            with alarm_lock:
                publish_zone_states()
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
