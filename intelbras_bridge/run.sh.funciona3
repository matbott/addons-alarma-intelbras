#!/usr/bin/with-contenv bashio

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

cleanup() {
    log "Shutting down addon..."
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${AVAILABILITY_TOPIC}" -m "offline" || true
    exit 0
}
trap cleanup SIGTERM SIGINT

log "=== Starting Intelbras MQTT Bridge Add-on ==="

# --- Configuración ---
ALARM_PORT=$(bashio::config 'alarm_port')
ALARM_IP=$(bashio::config 'alarm_ip')
ZONE_COUNT=$(bashio::config 'zone_count')
BROKER=$(bashio::config 'mqtt_broker')
PORT=$(bashio::config 'mqtt_port')
USER=$(bashio::config 'mqtt_user')
PASS=$(bashio::config 'mqtt_password')

MQTT_OPTS=(-h "$BROKER" -p "$PORT")
[[ -n "$USER" ]] && MQTT_OPTS+=(-u "$USER" -P "$PASS")

AVAILABILITY_TOPIC="intelbras/alarm/availability"
STATE_TOPIC="intelbras/alarm/state"
DEVICE_ID="intelbras_alarm"
DISCOVERY_PREFIX="homeassistant"

log "MQTT broker: $BROKER:$PORT, user: $USER"
log "Alarm IP: $ALARM_IP, port: $ALARM_PORT"
log "Zone count: $ZONE_COUNT"

# --- Función de Discovery (simplificada) ---
publish_discovery() {
    local name=$1
    local uid=$2
    local device_class=$3
    
    local payload='{'
    payload+='"name":"'$name'",'
    payload+='"state_topic":"intelbras/alarm/'$uid'",'
    payload+='"unique_id":"'$uid'",'
    
    if [[ -n "$device_class" ]]; then
        payload+='"device_class":"'$device_class'",'
    fi
    
    payload+='"availability_topic":"'$AVAILABILITY_TOPIC'",'
    payload+='"device":{'
    payload+='"identifiers":["'$DEVICE_ID'"],'
    payload+='"name":"Intelbras Alarm",'
    payload+='"model":"AMT-8000",'
    payload+='"manufacturer":"Intelbras"'
    payload+='}}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r \
        -t "${DISCOVERY_PREFIX}/binary_sensor/${DEVICE_ID}/${uid}/config" \
        -m "${payload}"
}

# --- Crear dispositivos Discovery ---
log "Setting up Home Assistant discovery..."
publish_discovery "Alarm State" "state" ""
publish_discovery "Alarm Sounding" "sounding" "safety"
publish_discovery "Panic" "panic" "safety"

# Crear zonas
for i in $(seq 1 "$ZONE_COUNT"); do
    publish_discovery "Zone $i" "zone_${i}" "opening"
done

# --- Configuración receptorip ---
log "Updating config.cfg..."
sed -i "s/^addr = .*/addr = 0.0.0.0/" ./config.cfg
sed -i "s/^port = .*/port = ${ALARM_PORT}/" ./config.cfg
sed -i "s/^caddr = .*/caddr = ${ALARM_IP}/" ./config.cfg
sed -i "s/^cport = .*/cport = ${ALARM_PORT}/" ./config.cfg
log "config.cfg ready."

# --- Estados iniciales ---
log "Publishing availability and initial states..."
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$AVAILABILITY_TOPIC" -m "online"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "disarmed"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "off"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off"

for i in $(seq 1 "$ZONE_COUNT"); do
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${i}" -m "off"
done

# --- Variables para tracking ---
declare -A ACTIVE_ZONES=()

# --- Ejecutar receptorip y procesar eventos ---
log "Starting receptorip..."
./receptorip config.cfg 2>&1 | while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    log "Event: $line"
    
    # Eventos de armado/desarmado
    if echo "$line" | grep -q "Ativacao remota app"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "armed"
        log "Alarm state set to: armed"
        
    elif echo "$line" | grep -q "Desativacao remota app"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "disarmed"
        log "Alarm state set to: disarmed"
        
    # Eventos de zonas
    elif echo "$line" | grep -q "Disparo de zona"; then
        if [[ "$line" =~ Disparo\ de\ zona\ ([0-9]+) ]]; then
            local zone="${BASH_REMATCH[1]}"
            log "Zone $zone triggered"
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "on"
            ACTIVE_ZONES["$zone"]=1
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "on"
        fi
        
    elif echo "$line" | grep -q "Restauracao de zona"; then
        if [[ "$line" =~ Restauracao\ de\ zona\ ([0-9]+) ]]; then
            local zone="${BASH_REMATCH[1]}"
            log "Zone $zone restored"
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "off"
            unset ACTIVE_ZONES["$zone"]
            
            # Si no hay zonas activas, apagar alarma
            if [[ ${#ACTIVE_ZONES[@]} -eq 0 ]]; then
                mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "off"
            fi
        fi
        
    # Evento de pánico
    elif echo "$line" | grep -q "Panico silencioso"; then
        log "Panic triggered"
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "on"
        # Auto-reset pánico después de 30 segundos
        (sleep 30 && mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off") &
    fi
done

cleanup
