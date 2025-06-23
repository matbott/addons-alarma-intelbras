ARG BUILD_FROM=ghcr.io/hassio-addons/base:17.2.5
FROM ${BUILD_FROM}
ENV LANG C.UTF-8

# Instalar paquetes necesarios Y LAS DEPENDENCIAS QUE FALTAN
RUN apk add --no-cache \
    bash \
    git \
    python3 \
    py3-pip \
    mosquitto-clients \
    jq \
    curl \
    ca-certificates \
    libstdc++ \
    openssl
    
RUN pip3 install paho-mqtt

# Instalar bashio
RUN mkdir -p /usr/lib/bashio && \
    curl -sSL https://raw.githubusercontent.com/hassio-addons/bashio/main/lib/bashio.sh -o /usr/lib/bashio/bashio.sh && \
    chmod +x /usr/lib/bashio/bashio.sh

# Clonar el proyecto
# La ruta /alarme-intelbras es correcta
#RUN git clone https://github.com/matbott/alarme-intelbras /alarme-intelbras

# Establecer el directorio de trabajo. ¡Esto es muy importante!
COPY alarme-intelbras /alarme-intelbras

WORKDIR /alarme-intelbras

# Dar permisos de ejecución a todos los archivos
RUN find . -type f -exec chmod +x {} \;

# Dar permisos de ejecución a los scripts y binarios
# Ahora usamos rutas relativas gracias a WORKDIR
RUN chmod a+x ./comandar && \
    chmod a+x ./receptorip

# Copiar y dar permisos al script principal
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
