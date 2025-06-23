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
BROKER=$(bashio::config 'mqtt_broker')
PORT=$(bashio::config 'mqtt_port')
USER=$(bashio::config 'mqtt_user')
PASS=$(bashio::config 'mqtt_password')

MQTT_OPTS=(-h "$BROKER" -p "$PORT")
[[ -n "$USER" ]] && MQTT_OPTS+=(-u "$USER" -P "$PASS")

AVAILABILITY_TOPIC="intelbras/alarm/availability"
STATE_TOPIC="intelbras/alarm/state"

log "MQTT broker: $BROKER:$PORT, user: $USER"
log "Alarm IP: $ALARM_IP, port: $ALARM_PORT"

# --- Configuración receptorip ---
log "Updating config.cfg..."
sed -i "s/^addr = .*/addr = 0.0.0.0/" ./config.cfg
sed -i "s/^port = .*/port = ${ALARM_PORT}/" ./config.cfg
sed -i "s/^caddr = .*/caddr = ${ALARM_IP}/" ./config.cfg
sed -i "s/^cport = .*/cport = ${ALARM_PORT}/" ./config.cfg
log "config.cfg ready."

# --- Ejecutar receptorip y procesar eventos ---
log "Publishing availability..."
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$AVAILABILITY_TOPIC" -m "online"

log "Starting receptorip..."

./receptorip config.cfg 2>&1 | while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    log "Event: $line"

    if echo "$line" | grep -q "Ativacao remota app"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$STATE_TOPIC" -m "armed"
        log "Alarm state set to: armed"
    elif echo "$line" | grep -q "Desativacao remota app"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$STATE_TOPIC" -m "disarmed"
        log "Alarm state set to: disarmed"
    fi
done

cleanup
