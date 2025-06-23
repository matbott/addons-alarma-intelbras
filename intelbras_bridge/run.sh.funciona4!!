#!/usr/bin/with-contenv bashio

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
cleanup() { log "Shutting down..."; mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${AVAILABILITY_TOPIC}" -m "offline" || true; exit 0; }
trap cleanup SIGTERM SIGINT

log "=== Starting Intelbras MQTT Bridge Add-on (Discovery Mode) ==="

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
DEVICE_ID="intelbras_alarm"
DISCOVERY_PREFIX="homeassistant"

log "MQTT broker: $BROKER:$PORT, user: $USER"
log "Alarm IP: $ALARM_IP, port: $ALARM_PORT, Zone count: $ZONE_COUNT"

publish_discovery() {
    local name=$1; local uid=$2; local device_class=$3; local payload_on=$4; local payload_off=$5
    local state_topic="intelbras/alarm/${uid}"
    local payload='{'
    payload+='"name":"'$name'",'
    payload+='"state_topic":"'$state_topic'",'
    payload+='"unique_id":"'$uid'",'
    [[ -n "$device_class" ]] && payload+='"device_class":"'$device_class'",'
    payload+='"payload_on":"'$payload_on'",'
    payload+='"payload_off":"'$payload_off'",'
    payload+='"availability_topic":"'$AVAILABILITY_TOPIC'",'
    payload+='"device":{"identifiers":["'$DEVICE_ID'"],"name":"Intelbras Alarm","model":"AMT-8000","manufacturer":"Intelbras"}'
    payload+='}'
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/binary_sensor/${DEVICE_ID}/${uid}/config" -m "${payload}"
}

log "Setting up Home Assistant discovery..."
publish_discovery "Alarm State" "state" "lock" "armed" "disarmed"
publish_discovery "Alarm Sounding" "sounding" "safety" "on" "off"
publish_discovery "Panic" "panic" "safety" "on" "off"
for i in $(seq 1 "$ZONE_COUNT"); do
    publish_discovery "Zone $i" "zone_${i}" "opening" "on" "off"
done

log "Updating config.cfg..."
sed -i "s/^addr = .*/addr = 0.0.0.0/" ./config.cfg
sed -i "s/^port = .*/port = ${ALARM_PORT}/" ./config.cfg
sed -i "s/^caddr = .*/caddr = ${ALARM_IP}/" ./config.cfg
sed -i "s/^cport = .*/cport = ${ALARM_PORT}/" ./config.cfg
log "config.cfg ready."

log "Publishing availability and initial states..."
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$AVAILABILITY_TOPIC" -m "online"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "disarmed"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "off"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off"
for i in $(seq 1 "$ZONE_COUNT"); do
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${i}" -m "off"
done

log "Starting receptorip..."
declare -A ACTIVE_ZONES=()
./receptorip config.cfg 2>&1 | while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    log "Event: $line"

    if echo "$line" | grep -q "Ativacao remota app"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "armed"
    elif echo "$line" | grep -q "Desativacao remota app"; then
        # --- AQUÍ ESTABA EL ERROR, AHORA CORREGIDO ---
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "disarmed"
    elif [[ "$line" =~ Disparo\ de\ zona\ ([0-9]+) ]]; then
        zone="${BASH_REMATCH[1]}"
        ACTIVE_ZONES["$zone"]=1
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "on"
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "on"
    elif [[ "$line" =~ Restauracao\ de\ zona\ ([0-9]+) ]]; then
        zone="${BASH_REMATCH[1]}"
        unset ACTIVE_ZONES["$zone"]
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "off"
        if [[ ${#ACTIVE_ZONES[@]} -eq 0 ]]; then
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "off"
        fi
    elif echo "$line" | grep -q "Panico silencioso"; then
        mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "on"
        (sleep 30 && mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off") &
    fi
done
cleanup
