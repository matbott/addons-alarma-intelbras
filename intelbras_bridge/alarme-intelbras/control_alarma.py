# Archivo: control_alarma.py
import sys
import logging
from client import Client, CommunicationError, AuthError

# --- Configuración del Logging ---
# Esto nos ayudará a ver qué está pasando cuando el script se ejecute.
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] - %(levelname)s - %(message)s',
    stream=sys.stdout
)

def main():
    """
    Función principal para conectar, autenticar y enviar un comando a la central Intelbras.
    """
    # --- Lectura de Argumentos desde la Línea de Comandos ---
    # El script esperará 5 argumentos:
    # 1. El nombre del script (automático)
    # 2. El comando a ejecutar (ej: "ARM_AWAY" o "DISARM")
    # 3. La IP de la alarma
    # 4. El puerto de la alarma
    # 5. La contraseña de la alarma
    if len(sys.argv) != 5:
        logging.error("Uso incorrecto. Se necesitan 4 argumentos: <comando> <ip_alarma> <puerto_alarma> <contraseña>")
        sys.exit(1)

    command = sys.argv[1]
    alarm_ip = sys.argv[2]
    alarm_port = int(sys.argv[3])
    alarm_password = sys.argv[4]

    logging.info(f"Iniciando ejecución de comando '{command}' para la alarma en {alarm_ip}:{alarm_port}")

    # --- Creación e Instancia del Cliente ---
    # Creamos un objeto 'Client' para comunicarnos con la alarma.
    client = Client(host=alarm_ip, port=alarm_port)
    
    try:
        # --- Conexión y Autenticación ---
        logging.info("Estableciendo conexión con la central...")
        client.connect()
        
        logging.info("Autenticando...")
        client.auth(alarm_password)
        logging.info("Autenticación exitosa.")

        # --- Ejecución del Comando ---
        if command == "ARM_AWAY":
            logging.info("Enviando comando para ARMAR sistema...")
            # El parámetro 0 significa "todas las particiones".
            result = client.arm_system(0)
            logging.info(f"Respuesta de la central al armar: {result}")

        elif command == "DISARM":
            logging.info("Enviando comando para DESARMAR sistema...")
            # El parámetro 0 significa "todas las particiones".
            result = client.disarm_system(0)
            logging.info(f"Respuesta de la central al desarmar: {result}")
            
        else:
            logging.warning(f"Comando '{command}' no reconocido.")

    except AuthError as e:
        logging.error(f"Error de autenticación: {e}")
        sys.exit(1) # Salir con error
    except CommunicationError as e:
        logging.error(f"Error de comunicación con la central: {e}")
        sys.exit(1) # Salir con error
    except Exception as e:
        logging.error(f"Ha ocurrido un error inesperado: {e}", exc_info=True)
        sys.exit(1) # Salir con error
    finally:
        # --- Cierre de Conexión ---
        # Es muy importante cerrar la conexión para no dejarla abierta en la central.
        logging.info("Cerrando la conexión.")
        client.close()

if __name__ == "__main__":
    main()