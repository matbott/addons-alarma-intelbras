# Puente MQTT para Centrales de Alarma Intelbras (Add-on de Home Assistant)

![image](https://github.com/user-attachments/assets/9bd1785d-8e71-4b77-a15f-4b118a667281)

Este proyecto es un Add-on para Home Assistant que actúa como un puente (bridge) entre las centrales de alarma Intelbras (como la serie AMT) y un bróker MQTT. Permite monitorear el estado completo de la alarma y controlarla (armar/desarmar, panico) directamente desde la interfaz de Home Assistant.

## Características Principales

* **Monitoreo en tiempo real** del estado de la alarma (Armada, Desarmada).
* **Sensores individuales por zona** para saber cuáles están abiertas, cerradas o disparada. (el estado abirta/cerrada de zonas esta en desarrollo puede generar falsos estados; el Disparado funciona ok!)
* **Sensor de pánico** para notificar activaciones de emergencia.
* **Control Remoto:** Entidad de Panel de Alarma en Home Assistant para armar y desarmar la central. (y Disparada)
* **Auto-descubrimiento (MQTT Discovery):** Todas las entidades se crean y configuran automáticamente en Home Assistant al iniciar el add-on.

## Requisitos Previos

Para que este Add-on funcione correctamente, necesitas tener lo siguiente:

### En Home Assistant
* Un **Bróker MQTT** instalado y funcionando. El add-on oficial **Mosquitto broker** es la opción recomendada.
* El bróker debe estar configurado para requerir un **nombre de usuario y contraseña**.

### En la Central de Alarma Intelbras
* La central debe tener una **Dirección IP Fija** asignada en tu red local (puedes configurarla en las opciones de red de la central o mediante una reserva de DHCP en tu router).
* Debes tener configurada una **contraseña de acceso remoto**.
* Se debe configurar la ip del Home Assistant como IP de Monitoreo 1 en la Central de Alarmas (ip Home Assistant, Puerto 9009)
  * Configuracion > Comunicacion > Monitoreo de IP > Servidor 1
    * IP: Home Assistant
    * Puerto: 9009
    * Habilitar la transmision...: check
  * Prioridad en la Comunicacion: solo ethernet
  * Modo de Informes: Regular IP  

## Configuración del Add-on

Una vez instalado, ve a la pestaña "Configuración" del add-on e introduce los siguientes datos:

* **Datos de la Alarma:**
    * `alarm_ip`: La dirección IP fija de tu central de alarma.
    * `alarm_port`: El puerto de comunicación de la central (ej: 9009).
    * `alarm_password`: La contraseña de **acceso remoto** que configuraste en la central.
    * `password_length`: La cantidad de dígitos que tiene tu contraseña (ej: 6).
    * `zone_count`: El número total de zonas de tu alarma.
* **Datos del Bróker MQTT:**
    * `mqtt_broker`: La dirección de tu bróker (normalmente `core-mosquitto`).
    * `mqtt_port`: El puerto de tu bróker (normalmente `1883`).
    * `mqtt_user` y `mqtt_password`: El usuario y contraseña para conectarse al bróker.

## Consejos Importantes

Para asegurar la máxima compatibilidad con el sistema de comunicación de la central, por favor sigue estas reglas para la contraseña:

* :warning: La **contraseña de acceso remoto** de la central DEBE ser de **6 dígitos**.
* :warning: La contraseña **NO DEBE contener el dígito cero (0)**.

El incumplimiento de estas reglas puede causar que la comunicación con la central falle.

![image](https://github.com/user-attachments/assets/0ccaab28-4c5f-4aa5-acff-a3995af82a7a)

## Agradecimientos

Este proyecto no sería posible sin el increíble trabajo de ingeniería inversa realizado por **elvis-epx** en su proyecto original. Gran parte de la comunicación directa con la central se basa en sus hallazgos.

* **Proyecto Original:** [receptorip-intelbras en GitHub](https://github.com/elvis-epx/alarme-intelbras)

Tambien el agradecimiento a https://github.com/merencia
* https://github.com/merencia/amt8000-hass-integration
