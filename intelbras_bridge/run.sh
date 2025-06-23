#!/usr/bin/with-contenv bashio

# --- FUNCIONES Y TRAPS (TRAMPAS) ---
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
cleanup() {
    log "Encerrando... Deteniendo procesos en segundo plano."
    pkill -P $$
    # Asegúrate de que las opciones MQTT estén disponibles para el cleanup
    local BROKER_IP=$(bashio::config 'mqtt_broker')
    local BROKER_PORT=$(bashio::config 'mqtt_port')
    local MQTT_USER=$(bashio::config 'mqtt_user')
    local MQTT_PASS=$(bashio::config 'mqtt_password')
    local MQTT_CLEANUP_OPTS=(-h "$BROKER_IP" -p "$BROKER_PORT")
    [[ -n "$MQTT_USER" ]] && MQTT_CLEANUP_OPTS+=(-u "$MQTT_USER" -P "$MQTT_PASS")
    
    mosquitto_pub "${MQTT_CLEANUP_OPTS[@]}" -r -t "intelbras/alarm/availability" -m "offline" || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# --- LECTURA DE CONFIGURACIÓN ---
log "=== Iniciando Intelbras MQTT Bridge Add-on (v6.0 - Sensores Extendidos) ==="

# Leer la configuración y exportarla para que addon_main.py la pueda usar
export ALARM_IP=$(bashio::config 'alarm_ip')
export ALARM_PORT=$(bashio::config 'alarm_port')
export ALARM_PASS=$(bashio::config 'alarm_password')
export MQTT_BROKER=$(bashio::config 'mqtt_broker')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASS=$(bashio::config 'mqtt_password')
export POLLING_INTERVAL_MINUTES=$(bashio::config 'polling_interval_minutes' 5) # Usamos tu variable, con 5 min por defecto

# Configuración que solo usa este script
PASSWORD_LENGTH=$(bashio::config 'password_length')

# --- CONFIGURACIÓN DE MQTT (Para el Discovery) ---
MQTT_OPTS=(-h "$MQTT_BROKER" -p "$MQTT_PORT")
[[ -n "$MQTT_USER" ]] && MQTT_OPTS+=(-u "$MQTT_USER" -P "$MQTT_PASS")
AVAILABILITY_TOPIC="intelbras/alarm/availability"
DEVICE_ID="intelbras_alarm"
DISCOVERY_PREFIX="homeassistant"

log "Broker MQTT: $MQTT_BROKER:$MQTT_PORT, usuario: $MQTT_USER"
log "Alarma IP: $ALARM_IP, puerto: $ALARM_PORT"
log "Intervalo de actualización de estado: $POLLING_INTERVAL_MINUTES minutos"

# --- INICIO: FUNCIONES DE DISCOVERY AÑADIDAS ---
publish_device_info() {
    echo "\"device\":{\"identifiers\":[\"${DEVICE_ID}\"],\"name\":\"Alarme Intelbras\",\"model\":\"AMT-8000\",\"manufacturer\":\"Intelbras\"}"
}

publish_binary_sensor_discovery() {
    local name=$1; local uid=$2; local device_class=$3
    local state_topic="intelbras/alarm/${uid}"
    
    local payload='{'
    payload+="\"name\":\"${name}\","
    payload+="\"state_topic\":\"${state_topic}\","
    payload+="\"unique_id\":\"${uid}\","
    payload+="\"device_class\":\"${device_class}\","
    payload+="\"payload_on\":\"on\",\"payload_off\":\"off\","
    payload+="\"availability_topic\":\"${AVAILABILITY_TOPIC}\","
    payload+="$(publish_device_info)"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/binary_sensor/${DEVICE_ID}/${uid}/config" -m "${payload}"
}

publish_text_sensor_discovery() {
    local name=$1; local uid=$2; local icon=$3
    local state_topic="intelbras/alarm/${uid}"

    local payload='{'
    payload+="\"name\":\"${name}\","
    payload+="\"state_topic\":\"${state_topic}\","
    payload+="\"unique_id\":\"${uid}\","
    payload+="\"icon\":\"${icon}\","
    payload+="\"availability_topic\":\"${AVAILABILITY_TOPIC}\","
    payload+="$(publish_device_info)"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/sensor/${DEVICE_ID}/${uid}/config" -m "${payload}"
}

publish_numeric_sensor_discovery() {
    local name=$1; local uid=$2; local device_class=$3; local unit=$4; local icon=$5
    local state_topic="intelbras/alarm/${uid}"

    local payload='{'
    payload+="\"name\":\"${name}\","
    payload+="\"state_topic\":\"${state_topic}\","
    payload+="\"unique_id\":\"${uid}\","
    payload+="\"device_class\":\"${device_class}\","
    payload+="\"unit_of_measurement\":\"${unit}\","
    payload+="\"icon\":\"${icon}\","
    payload+="\"availability_topic\":\"${AVAILABILITY_TOPIC}\","
    payload+="$(publish_device_info)"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/sensor/${DEVICE_ID}/${uid}/config" -m "${payload}"
}

publish_alarm_panel_discovery() {
    log "Publicando configuração do Painel de Alarme..."
    local uid="${DEVICE_ID}_panel"
    local command_topic="intelbras/alarm/command"
    local state_topic="intelbras/alarm/state"

    local payload='{'
    payload+="\"name\":\"Painel de Alarma Intelbras\","
    payload+="\"unique_id\":\"${uid}\","
    payload+="\"state_topic\":\"${state_topic}\","
    payload+="\"command_topic\":\"${command_topic}\","
    payload+="\"availability_topic\":\"${AVAILABILITY_TOPIC}\","
    payload+="\"value_template\":\"{% if value == 'Armada' %}armed_away{% elif value == 'Desarmada' %}disarmed{% else %}disarmed{% endif %}\","
    payload+="\"payload_disarm\":\"DISARM\","
    payload+="\"payload_arm_away\":\"ARM_AWAY\","
    payload+="\"supported_features\":[\"arm_away\"],"
    payload+="\"code_arm_required\":false,"
    payload+="\"code_disarm_required\":false,"
    payload+="$(publish_device_info)"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/alarm_control_panel/${DEVICE_ID}/config" -m "${payload}"
}
# --- FIN: FUNCIONES DE DISCOVERY AÑADIDAS ---

# --- PUBLICACIÓN DE CONFIGURACIÓN DE ENTIDADES ---
log "Configurando o Home Assistant Discovery..."
publish_alarm_panel_discovery
publish_text_sensor_discovery "Estado Alarma" "state" "mdi:shield-lock"

# --- PUBLICACIÓN DE NUEVOS SENSORES ---
log "Publicando sensores extendidos..."
publish_text_sensor_discovery "Modelo Alarma" "model" "mdi:chip"
publish_text_sensor_discovery "Versión Firmware" "version" "mdi:git"
publish_numeric_sensor_discovery "Batería Alarma" "battery_percentage" "battery" "%" "mdi:battery"
publish_binary_sensor_discovery "Tamper Alarma" "tamper" "tamper"
publish_binary_sensor_discovery "Sirena" "siren" "sound"
publish_binary_sensor_discovery "Zonas Disparadas" "zones_firing" "problem"

# --- GENERACIÓN DE CONFIG.CFG ---
log "Generando config.cfg para receptorip..."
cat > /alarme-intelbras/config.cfg << EOF
[receptorip]
addr = 0.0.0.0
port = ${ALARM_PORT}
centrais = .*
maxconn = 1
caddr = ${ALARM_IP}
cport = ${ALARM_PORT}
senha = ${ALARM_PASS}
tamanho = ${PASSWORD_LENGTH}
folder_dlfoto = .
logfile = receptorip.log
EOF

# --- LANZAMIENTO DEL SCRIPT PRINCIPAL ---
log "Lanzando el script principal de Python (addon_main.py)..."
exec python3 /alarme-intelbras/addon_main.py
