#!/usr/bin/with-contenv bashio

# --- FUNCIONES Y TRAPS (TRAMPAS) ---
log() { echo "=> $1"; }
cleanup() {
    log "Encerrando..."; pkill -P $$
    local BROKER_IP=$(bashio::config 'mqtt_broker'); local BROKER_PORT=$(bashio::config 'mqtt_port'); local MQTT_USER=$(bashio::config 'mqtt_user'); local MQTT_PASS=$(bashio::config 'mqtt_password')
    local MQTT_CLEANUP_OPTS=(-h "$BROKER_IP" -p "$BROKER_PORT"); [[ -n "$MQTT_USER" ]] && MQTT_CLEANUP_OPTS+=(-u "$MQTT_USER" -P "$MQTT_PASS")
    mosquitto_pub "${MQTT_CLEANUP_OPTS[@]}" -r -t "intelbras/alarm/availability" -m "offline" || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# --- LECTURA DE CONFIGURACIÓN ---
log "Iniciando Intelbras MQTT Bridge Add-on (v7.0 - Sensores de Zona Avanzados)"
export ALARM_IP=$(bashio::config 'alarm_ip'); export ALARM_PORT=$(bashio::config 'alarm_port'); export ALARM_PASS=$(bashio::config 'alarm_password')
export MQTT_BROKER=$(bashio::config 'mqtt_broker'); export MQTT_PORT=$(bashio::config 'mqtt_port'); export MQTT_USER=$(bashio::config 'mqtt_user'); export MQTT_PASS=$(bashio::config 'mqtt_password')
export POLLING_INTERVAL_MINUTES=$(bashio::config 'polling_interval_minutes' 5)
export ZONE_COUNT=$(bashio::config 'zone_count' 0)
PASSWORD_LENGTH=$(bashio::config 'password_length')
MQTT_OPTS=(-h "$MQTT_BROKER" -p "$MQTT_PORT"); [[ -n "$MQTT_USER" ]] && MQTT_OPTS+=(-u "$MQTT_USER" -P "$MQTT_PASS")
AVAILABILITY_TOPIC="intelbras/alarm/availability"; DEVICE_ID="intelbras_alarm"; DISCOVERY_PREFIX="homeassistant"
log "Configuración cargada. Zonas a gestionar: $ZONE_COUNT."

# --- FUNCIONES DE DISCOVERY (compactadas) ---
publish_device_info() { echo "\"device\":{\"identifiers\":[\"${DEVICE_ID}\"],\"name\":\"Alarme Intelbras\",\"model\":\"AMT-8000\",\"manufacturer\":\"Intelbras\"}"; }
publish_binary_sensor_discovery(){ local n=$1;local u=$2;local d=$3;local s="intelbras/alarm/${u}";local p='{';p+="\"name\":\"${n}\",\"stat_t\":\"${s}\",\"uniq_id\":\"${u}\",\"dev_cla\":\"${d}\",";p+="\"pl_on\":\"on\",\"pl_off\":\"off\",\"av_t\":\"${AVAILABILITY_TOPIC}\",";p+="$(publish_device_info)";p+='}';mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/binary_sensor/${DEVICE_ID}/${u}/config" -m "${p}"; }
publish_text_sensor_discovery(){ local n=$1;local u=$2;local i=$3;local s="intelbras/alarm/${u}";local p='{';p+="\"name\":\"${n}\",\"stat_t\":\"${s}\",\"uniq_id\":\"${u}\",\"icon\":\"${i}\",";p+="\"av_t\":\"${AVAILABILITY_TOPIC}\",";p+="$(publish_device_info)";p+='}';mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/sensor/${DEVICE_ID}/${u}/config" -m "${p}"; }
publish_numeric_sensor_discovery(){ local n=$1;local u=$2;local d=$3;local un=$4;local i=$5;local s="intelbras/alarm/${u}";local p='{';p+="\"name\":\"${n}\",\"stat_t\":\"${s}\",\"uniq_id\":\"${u}\",\"dev_cla\":\"${d}\",";p+="\"unit_of_meas\":\"${un}\",\"icon\":\"${i}\",\"av_t\":\"${AVAILABILITY_TOPIC}\",";p+="$(publish_device_info)";p+='}';mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/sensor/${DEVICE_ID}/${u}/config" -m "${p}"; }
publish_alarm_panel_discovery(){ log "Publicando Painel de Alarme...";local u="${DEVICE_ID}_panel";local c="intelbras/alarm/command";local s="intelbras/alarm/state";local p='{';p+="\"name\":\"Painel de Alarma Intelbras\",\"uniq_id\":\"${u}\",\"stat_t\":\"${s}\",";p+="\"cmd_t\":\"${c}\",\"av_t\":\"${AVAILABILITY_TOPIC}\",";p+="\"val_tpl\":\"{% if value == 'Armada' %}armed_away{% elif value == 'Desarmada' %}disarmed{% else %}disarmed{% endif %}\",";p+="\"pl_disarm\":\"DISARM\",\"pl_arm_away\":\"ARM_AWAY\",\"sup_feat\":[\"arm_away\"],";p+="\"code_arm_req\":false,\"code_disarm_req\":false,";p+="$(publish_device_info)";p+='}';mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/alarm_control_panel/${DEVICE_ID}/config" -m "${p}"; }

# --- PASO 0: LIMPIEZA DE SENSORES BINARIOS HUÉRFANOS (TEMPORAL) ---
log "Limpiando sensores de zona binarios antiguos..."
for i in $(seq 1 "$ZONE_COUNT"); do
    zone_uid="zone_$i"
    # Envía un mensaje vacío y retenido para borrar la configuración del sensor antiguo
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/binary_sensor/${DEVICE_ID}/${zone_uid}/config" -m ""
done
log "Limpieza completada."
# NOTA: Después del primer reinicio exitoso, puedes eliminar este bloque de limpieza.

# --- PUBLICACIÓN DE ENTIDADES ---
log "Configurando Home Assistant Discovery..."
publish_alarm_panel_discovery
publish_text_sensor_discovery "Estado Alarma" "state" "mdi:shield-lock"
publish_text_sensor_discovery "Modelo Alarma" "model" "mdi:chip"
publish_text_sensor_discovery "Versión Firmware" "version" "mdi:git"
publish_numeric_sensor_discovery "Batería Alarma" "battery_percentage" "battery" "%" "mdi:battery"
publish_binary_sensor_discovery "Tamper Alarma" "tamper" "tamper"
publish_binary_sensor_discovery "Sirena" "siren" "sound"
publish_binary_sensor_discovery "Pánico Silencioso" "panic" "safety"
publish_text_sensor_discovery "Estado Zonas Disparadas" "zones_firing" "mdi:alarm-light"

# --- PASO 1: CREACIÓN DE NUEVOS SENSORES DE ZONA DE TEXTO ---
log "Publicando sensores de zona de texto individuales..."
for i in $(seq 1 "$ZONE_COUNT"); do
    zone_name="Zona $i"
    zone_uid="zone_$i"
    # Usamos 'mdi:radiobox-blank', 'mdi:radiobox-marked', o 'mdi:alert-circle' como íconos base
    publish_text_sensor_discovery "$zone_name" "$zone_uid" "mdi:door"
done

# --- GENERACIÓN DE CONFIG.CFG ---
log "Generando config.cfg para receptorip...";cat >/alarme-intelbras/config.cfg <<EOF
[receptorip]
addr=0.0.0.0;port=${ALARM_PORT};centrais=.*;maxconn=1;caddr=${ALARM_IP};cport=${ALARM_PORT};senha=${ALARM_PASS};tamanho=${PASSWORD_LENGTH};folder_dlfoto=.;logfile=receptorip.log
EOF

# --- LANZAMIENTO DEL SCRIPT PRINCIPAL ---
log "Lanzando el script principal de Python (addon_main.py)..."
exec python3 /alarme-intelbras/addon_main.py
