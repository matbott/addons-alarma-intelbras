#!/usr/bin/with-contenv bashio

# Imprimir un mensaje de inicio
bashio::log.info "Iniciando el addon Intelbras MQTT Bridge (v5.0 - Persistente)..."

# Leer la configuración del addon usando bashio
export ALARM_IP=$(bashio::config 'alarm_ip')
export ALARM_PORT=$(bashio::config 'alarm_port')
export ALARM_PASS=$(bashio::config 'alarm_password')
export MQTT_BROKER=$(bashio::config 'mqtt_broker')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASS=$(bashio::config 'mqtt_password')

# (Opcional) Generar el config.cfg si aún lo necesitas para receptorip
# Si receptorip puede funcionar sin él o si sus parámetros se pueden pasar por línea de comandos,
# esta sección podría no ser necesaria. Por ahora, la mantenemos como en tu script original.
PASSWORD_LENGTH=$(bashio::config 'password_length')
bashio::log.info "Generando config.cfg para receptorip..."
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

# Ejecutar el script principal de Python
# El script se encargará de todo lo demás
bashio::log.info "Lanzando el script principal de Python (addon_main.py)..."
exec python3 /alarme-intelbras/addon_main.py
