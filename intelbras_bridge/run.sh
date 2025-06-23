#!/usr/bin/with-contenv bashio

# --- FUNCIONES Y TRAPS (TRAMPAS) ---
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
cleanup() {
    log "Encerrando... Deteniendo procesos en segundo plano."
    pkill -P $$
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${AVAILABILITY_TOPIC}" -m "offline" || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# --- LECTURA DE CONFIGURACIÓN ---
log "=== Iniciando Intelbras MQTT Bridge Add-on (v4.0 - Estável) ==="

ALARM_PORT=$(bashio::config 'alarm_port')
ALARM_IP=$(bashio::config 'alarm_ip')
ALARM_PASS=$(bashio::config 'alarm_password')
PASSWORD_LENGTH=$(bashio::config 'password_length')
ZONE_COUNT=$(bashio::config 'zone_count')
BROKER=$(bashio::config 'mqtt_broker')
PORT=$(bashio::config 'mqtt_port')
USER=$(bashio::config 'mqtt_user')
PASS=$(bashio::config 'mqtt_password')

# --- CONFIGURACIÓN DE MQTT ---
MQTT_OPTS=(-h "$BROKER" -p "$PORT")
[[ -n "$USER" ]] && MQTT_OPTS+=(-u "$USER" -P "$PASS")
AVAILABILITY_TOPIC="intelbras/alarm/availability"
DEVICE_ID="intelbras_alarm"
DISCOVERY_PREFIX="homeassistant"

log "Broker MQTT: $BROKER:$PORT, usuario: $USER"
log "Alarma IP: $ALARM_IP, puerto: $ALARM_PORT, zonas: $ZONE_COUNT, tam. senha: $PASSWORD_LENGTH"

# --- FUNCIONES DE DISCOVERY (CON MÉTODO DE STRING SEGURO) ---

publish_binary_sensor_discovery() {
    local name=$1; local uid=$2; local device_class=$3; local payload_on=$4; local payload_off=$5
    local state_topic="intelbras/alarm/${uid}"
    
    # Construcción de JSON línea por línea (método seguro y compatible)
    local payload='{'
    payload+="\"name\":\"${name}\","
    payload+="\"state_topic\":\"${state_topic}\","
    payload+="\"unique_id\":\"${uid}\","
    payload+="\"device_class\":\"${device_class}\","
    payload+="\"payload_on\":\"${payload_on}\","
    payload+="\"payload_off\":\"${payload_off}\","
    payload+="\"availability_topic\":\"${AVAILABILITY_TOPIC}\","
    payload+="\"device\":{\"identifiers\":[\"${DEVICE_ID}\"],\"name\":\"Alarme Intelbras\",\"model\":\"AMT-8000\",\"manufacturer\":\"Intelbras\"}"
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
    payload+="\"device\":{\"identifiers\":[\"${DEVICE_ID}\"],\"name\":\"Alarme Intelbras\",\"model\":\"AMT-8000\",\"manufacturer\":\"Intelbras\"}"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/sensor/${DEVICE_ID}/${uid}/config" -m "${payload}"
}

publish_alarm_panel_discovery() {
    log "Publicando configuração do Painel de Alarme para o Home Assistant..."
    local uid="${DEVICE_ID}_panel"
    local command_topic="intelbras/alarm/command"
    local state_topic="intelbras/alarm/state"

    local payload='{'
    payload+="\"name\":\"Panel de Alarma Intelbras\","
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
    payload+="\"device\":{\"identifiers\":[\"${DEVICE_ID}\"],\"name\":\"Alarme Intelbras\",\"model\":\"AMT-8000\",\"manufacturer\":\"Intelbras\"}"
    payload+='}'

    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "${DISCOVERY_PREFIX}/alarm_control_panel/${DEVICE_ID}/config" -m "${payload}"
}

# --- PUBLICACIÓN DE CONFIGURACIÓN DE ENTIDADES ---
log "Configurando o Home Assistant Discovery..."
publish_text_sensor_discovery "Estado Alarma" "state" "mdi:shield-lock"
publish_text_sensor_discovery "Sirene" "sounding" "mdi:alarm-bell"
publish_binary_sensor_discovery "Pânico" "panic" "safety" "on" "off"
for i in $(seq 1 "$ZONE_COUNT"); do
    publish_binary_sensor_discovery "Zona $i" "zone_${i}" "opening" "on" "off"
done
publish_alarm_panel_discovery

# --- GENERACIÓN DE CONFIG.CFG ---
log "Gerando config.cfg..."
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

# --- PUBLICACIÓN DE ESTADOS INICIALES ---
log "Publicando disponibilidade e estados iniciais..."
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "$AVAILABILITY_TOPIC" -m "online"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "Desarmada"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "Normal"
mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off"
for i in $(seq 1 "$ZONE_COUNT"); do
    mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${i}" -m "off"
done

# --- ESTRUCTURA DE PROCESOS PARALELOS ---
listen_for_events() {
    log "Iniciando receptorip para escutar eventos da central..."
    declare -A ACTIVE_ZONES=()
    ./receptorip config.cfg 2>&1 | while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        log "Evento da Central: $line"
        if echo "$line" | grep -q "Ativacao remota app"; then
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "Armada"
        elif echo "$line" | grep -q "Desativacao remota app"; then
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/state" -m "Desarmada"
        elif [[ "$line" =~ Disparo\ de\ zona\ ([0-9]+) ]]; then
            local zone="${BASH_REMATCH[1]}"
            ACTIVE_ZONES["$zone"]=1
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "on"
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "Disparada"
        elif [[ "$line" =~ Restauracao\ de\ zona\ ([0-9]+) ]]; then
            local zone="${BASH_REMATCH[1]}"
            unset ACTIVE_ZONES["$zone"]
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/zone_${zone}" -m "off"
            if [[ ${#ACTIVE_ZONES[@]} -eq 0 ]]; then
                mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/sounding" -m "Normal"
            fi
        elif echo "$line" | grep -q "Panico silencioso"; then
            mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "on"
            (sleep 30 && mosquitto_pub "${MQTT_OPTS[@]}" -r -t "intelbras/alarm/panic" -m "off") &
        fi
    done
}

listen_for_commands() {
    log "Iniciando listener de comandos MQTT de Home Assistant..."
    mosquitto_sub "${MQTT_OPTS[@]}" -t "intelbras/alarm/command" | while IFS= read -r command; do
        log "Comando MQTT recibido de Home Assistant: '$command'"
        
        # Usamos 'case' para asegurarnos de que solo se ejecuten comandos conocidos.
        case "$command" in
            "ARM_AWAY"|"DISARM")
                log "Verificando contraseña. Longitud: ${#ALARM_PASS}, Primer carácter: ${ALARM_PASS:0:1}"
                log "Ejecutando script de Python para el comando '$command'..."
                # Llamamos a nuestro nuevo script de Python pasándole los argumentos necesarios.
                # Asegúrate de que python3 esté disponible en tu addon.
                python3 /alarme-intelbras/control_alarma.py "$command" "$ALARM_IP" "$ALARM_PORT" "$ALARM_PASS"
                log "La ejecución del script de Python ha finalizado."
                ;;
            *)
                log "Comando desconocido o no soportado: '$command'"
                ;;
        esac
    done
}

# --- LANZAMIENTO Y GESTIÓN DE PROCESOS ---
listen_for_events &
listen_for_commands &
wait
