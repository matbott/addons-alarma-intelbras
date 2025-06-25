"""Module for amt-8000 communication."""

import socket
import logging
from typing import Dict, Any, List

LOGGER = logging.getLogger(__name__)

timeout = 2  # Set the timeout to 2 seconds

dst_id = [0x00, 0x00]
our_id = [0x8F, 0xFF]
commands = {
    "auth": [0xF0, 0xF0],
    "status": [0x0B, 0x4A],
    "arm_disarm": [0x40, 0x1e],
    "panic": [0x40, 0x1a],
    "paired_sensors": [0x0B, 0x01]
}

# Constantes para el procesamiento de zonas (offset de la versión que funciona)
ZONE_STATUS_PAYLOAD_OFFSET = 22 # The first zone byte within the payload (from the working fork)
MAX_ZONES = 64 # Maximum number of zones that can be read (8 bytes * 8 bits)

def split_into_octets(n):
    """Splits an integer into high and low bytes."""
    if 0 <= n <= 0xFFFF:
        high_byte = (n >> 8) & 0xFF
        low_byte = n & 0xFF
        return [high_byte, low_byte]
    else:
        raise ValueError("Número fora do intervalo (0 a 65535)")

def calculate_checksum(buffer):
    """Calculate a checksum for a given array of bytes."""
    checksum = 0
    for value in buffer:
        checksum ^= value
    checksum ^= 0xFF
    checksum &= 0xFF
    return checksum

def merge_octets(buf):
    """Merge octets."""
    return buf[0] * 256 + buf[1]

def battery_status_for(resp):
    """Retrieve the battery status."""
    if len(resp) <= 134:
        LOGGER.debug("Payload too short for battery status. Length: %d", len(resp))
        return "unknown"
    batt = resp[134]
    if batt == 0x01:
        return "dead"
    if batt == 0x02:
        return "low"
    if batt == 0x03:
        return "middle"
    if batt == 0x04:
        return "full"
    LOGGER.debug("Unknown battery status code: 0x%02x", batt)
    return "unknown"

def get_status(payload):
    """Retrieve the current status from a given array of bytes."""
    if len(payload) <= 20:
        LOGGER.debug("Payload too short for general status. Length: %d", len(payload))
        return "unknown"
    status = (payload[20] >> 5) & 0x03
    if status == 0x00:
        return "disarmed"
    if status == 0x01:
        return "partial_armed"
    if status == 0x03:
        return "armed_away"
    LOGGER.debug("Unknown arming status code: 0x%02x", status)
    return "unknown"

def get_zones_status_from_payload(payload: bytearray, num_zones: int = MAX_ZONES) -> Dict[str, str]:
    """
    Decodes the zone status from the payload.
    The zone status bytes start at ZONE_STATUS_PAYLOAD_OFFSET (22) in the status payload.
    Each bit represents a zone (0 = closed, 1 = open/faulted).
    Returns a dictionary of zone_id (str) to "open" or "closed".
    """
    zones_status_dict = {}
    
    required_bytes_for_zones = (num_zones + 7) // 8
    
    if len(payload) < ZONE_STATUS_PAYLOAD_OFFSET + required_bytes_for_zones:
        LOGGER.warning(f"Payload too short to decode all {num_zones} zones from offset {ZONE_STATUS_PAYLOAD_OFFSET}. Required at least {ZONE_STATUS_PAYLOAD_OFFSET + required_bytes_for_zones} bytes, got {len(payload)}.")
        bytes_to_process = payload[ZONE_STATUS_PAYLOAD_OFFSET:]
    else:
        bytes_to_process = payload[ZONE_STATUS_PAYLOAD_OFFSET : ZONE_STATUS_PAYLOAD_OFFSET + required_bytes_for_zones]

    zone_current_idx = 0
    for byte_val in bytes_to_process:
        for bit_index in range(8):
            if zone_current_idx < num_zones:
                zone_number = zone_current_idx + 1
                is_open = bool(byte_val & (1 << bit_index))
                zones_status_dict[str(zone_number)] = "open" if is_open else "closed"
                zone_current_idx += 1
            else:
                break
        if zone_current_idx >= num_zones:
            break

    LOGGER.debug(f"Decoded zones status: {zones_status_dict}")
    return zones_status_dict


def build_status(data: bytearray) -> Dict[str, Any]:
    """Build the amt-8000 status from a given array of bytes, including zone status."""
    if len(data) < 8:
        LOGGER.error("Received status data is too short (less than 8 bytes). Data: %s", data.hex())
        return {
            "model": "Unknown",
            "version": "Unknown",
            "status": "unknown",
            "zonesFiring": False,
            "zonesClosed": False,
            "siren": False,
            "batteryStatus": "unknown",
            "tamper": False,
            "zones": {}
        }

    length_bytes = data[4:6]
    if len(length_bytes) < 2:
        LOGGER.error("Length bytes are missing or insufficient in status data. Data: %s", data.hex())
        return {
            "model": "Unknown",
            "version": "Unknown",
            "status": "unknown",
            "zonesFiring": False,
            "zonesClosed": False,
            "siren": False,
            "batteryStatus": "unknown",
            "tamper": False,
            "zones": {}
        }

    expected_payload_length = merge_octets(data[4:6])

    if len(data) < 8 + expected_payload_length:
        LOGGER.debug("Received data is shorter than indicated length. Expected: %d, Received: %d. Data: %s",
                        8 + expected_payload_length, len(data), data.hex())
        payload = data[8:]
    else:
        payload = data[8 : 8 + expected_payload_length]

    LOGGER.debug("Raw payload for status: %s", payload.hex())

    status_data = {}

    status_data["model"] = "Unknown"
    if len(payload) > 0:
        status_data["model"] = "AMT-8000" if payload[0] == 1 else "Unknown"

    status_data["version"] = "Unknown"
    if len(payload) > 3:
        status_data["version"] = f"{payload[1]}.{payload[2]}.{payload[3]}"
    
    status_data["status"] = "unknown"
    status_data["zonesFiring"] = False
    status_data["zonesClosed"] = False
    status_data["siren"] = False
    if len(payload) > 20:
        status_data["status"] = get_status(payload)
        status_data["zonesFiring"] = (payload[20] & 0x8) > 0
        status_data["zonesClosed"] = (payload[20] & 0x4) > 0
        status_data["siren"] = (payload[20] & 0x2) > 0
    else:
        LOGGER.debug("Payload too short for full status bits. Length: %d", len(payload))

    status_data["batteryStatus"] = battery_status_for(payload)

    status_data["tamper"] = False
    if len(payload) > 71:
        status_data["tamper"] = (payload[71] & (1 << 0x01)) > 0
    else:
        LOGGER.debug("Payload too short for tamper status. Length: %d", len(payload))

    status_data["zones"] = get_zones_status_from_payload(payload)

    LOGGER.debug("Decoded status: %s", status_data)
    return status_data


class CommunicationError(Exception):
    """Exception raised for communication error."""

    def __init__(self, message="Communication error"):
        """Initialize the error."""
        self.message = message
        super().__init__(self.message)


class AuthError(Exception):
    """Exception raised for authentication error."""

    def __init__(self, message="Authentication Error"):
        """Initialize the error."""
        self.message = message
        super().__init__(self.message)


class Client:
    """Client to communicate with amt-8000."""

    def __init__(self, host, port, device_type=1, software_version=0x10):
        """Initialize the client."""
        self.host = host
        self.port = port
        self.device_type = device_type
        self.software_version = software_version
        self._socket = None # Usar un atributo privado para el socket
        self._is_connected = False # Nuevo flag para el estado de la conexión persistente

    def connect(self):
        """Establish a persistent socket connection."""
        if self._is_connected and self._socket:
            LOGGER.debug("Already connected to %s:%d.", self.host, self.port)
            return True
        
        # Si hay un socket pero no está conectado (e.g., previo error), cerrar para limpiar
        if self._socket:
            try:
                self._socket.close() 
            except OSError as e:
                LOGGER.debug("Error closing stale socket: %s", e)
            finally:
                self._socket = None

        LOGGER.debug("Attempting to establish persistent connection to %s:%d", self.host, self.port)
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(timeout)
            self._socket.connect((self.host, self.port))
            self._is_connected = True
            LOGGER.info("Persistent connection established to %s:%d.", self.host, self.port)
            return True
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            self._is_connected = False
            self._socket = None # Limpiar el socket en caso de fallo
            raise CommunicationError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def close(self):
        """Close the persistent socket connection."""
        if self._socket:
            LOGGER.debug("Closing persistent connection.")
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            except OSError as e:
                LOGGER.debug("Error during socket shutdown/close: %s", e)
            finally:
                self._socket = None
                self._is_connected = False

    def _send_command_and_receive_response(self, data_to_send: bytes) -> bytearray:
        """Helper to send a command and receive its response using the persistent connection."""
        if not self._is_connected or not self._socket:
            LOGGER.warning("Attempting to send command without an active connection. Reconnecting.")
            self.connect() # Intenta reconectar si no está conectado

        try:
            self._socket.send(data_to_send)
            return_data = bytearray(self._socket.recv(1024))
            LOGGER.debug("Received response for command: %s", return_data.hex())
            return return_data
        except (socket.timeout, ConnectionResetError, BrokenPipeError) as e:
            # En caso de error de comunicación, marcar como desconectado para forzar reconexión
            self._is_connected = False 
            self._socket = None
            raise CommunicationError(f"Communication error during command: {e}. Connection lost.")
        except OSError as e:
            self._is_connected = False
            self._socket = None
            raise CommunicationError(f"OS error during command communication: {e}")

    def auth(self, password):
        """Create an authentication for the current connection."""
        if not isinstance(password, str):
            LOGGER.error(f"Password provided to auth() is not a string. Type: {type(password)}, Value: {password}")
            raise CommunicationError("Password must be a string of 6 digits.")

        pass_array = []
        if len(password) != 6 or not password.isdigit():
            raise CommunicationError(
                "Cannot parse password, only 6 digits long are accepted"
            )
            
        for char in password:
            pass_array.append(int(char))

        length = [0x00, 0x0a]
        data = (
            dst_id
            + our_id
            + length
            + commands["auth"]
            + [self.device_type]
            + pass_array
            + [self.software_version]
        )

        cs = calculate_checksum(data)
        payload = bytes(data + [cs])

        LOGGER.debug("Sending authentication: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)

        if len(return_data) < 9:
            raise CommunicationError(f"Authentication response too short. Length: {len(return_data)}. Raw: {return_data.hex()}")

        result = return_data[8:9][0]

        if result == 0:
            LOGGER.info("Authentication successful.")
            return True
        if result == 1:
            raise AuthError("Invalid password")
        if result == 2:
            raise AuthError("Incorrect software version")
        if result == 3:
            raise AuthError("Alarm panel will call back")
        if result == 4:
            raise AuthError("Waiting for user permission")
        raise CommunicationError(f"Unknown payload response for authentication: 0x{result:02x}")

    def status(self):
        """Return the current status."""
        length = [0x00, 0x02]
        status_data = dst_id + our_id + length + commands["status"]
        cs = calculate_checksum(status_data)
        payload = bytes(status_data + [cs])

        LOGGER.debug("Sending status command: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)
        
        status = build_status(return_data)
        return status

    def arm_system(self, partition):
        """Arm the system for a given partition."""
        if partition == 0:
            partition = 0xFF

        length = [0x00, 0x04]
        arm_data = dst_id + our_id + length + commands["arm_disarm"] + [ partition, 0x01 ] # 0x01 for arm
        cs = calculate_checksum(arm_data)
        payload = bytes(arm_data + [cs])

        LOGGER.debug("Sending arm command: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)
        
        if len(return_data) > 9 and return_data[9] in [0x91, 0x99]:
        # Determinamos qué tipo de armado fue para un log más claro
            arm_type = "con bypass de zonas" if return_data[9] == 0x99 else "normal"
            LOGGER.info(f"Sistema armado exitosamente ({arm_type}).")
            return 'armed'
            
        LOGGER.warning("Arm command failed. Response: %s", return_data.hex())
        return 'not_armed'

    def disarm_system(self, partition):
        """Disarm the system for a given partition."""
        if partition == 0:
            partition = 0xFF

        length = [0x00, 0x04]
        disarm_data = dst_id + our_id + length + commands["arm_disarm"] + [ partition, 0x00 ] # 0x00 for disarm
        cs = calculate_checksum(disarm_data)
        payload = bytes(disarm_data + [cs])

        LOGGER.debug("Sending disarm command: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)
        
        if len(return_data) > 9 and return_data[9] == 0x90:
            LOGGER.info("System disarmed successfully.")
            return 'disarmed'
            
        LOGGER.warning("Disarm command failed. Response: %s", return_data.hex())
        return 'not_disarmed'

    def panic(self, panic_type):
        """Trigger a panic alarm."""
        length = [0x00, 0x03]
        panic_data = dst_id + our_id + length + commands["panic"] +[ panic_type ]
        cs = calculate_checksum(panic_data)
        payload = bytes(panic_data + [cs])

        LOGGER.debug("Sending panic command: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)
        
        if len(return_data) > 7 and return_data[7] == 0xfe:
            LOGGER.info("Panic alarm triggered.")
            return 'triggered'
            
        LOGGER.warning("Panic command failed. Response: %s", return_data.hex())
        return 'not_triggered'
    
    def get_paired_sensors(self) -> Dict[str, bool]:
        """Get the list of paired sensors from the alarm panel."""
        length = [0x00, 0x02] # Command is 2 bytes
        sensors_data = dst_id + our_id + length + commands["paired_sensors"]
        cs = calculate_checksum(sensors_data)
        payload = bytes(sensors_data + [cs])

        LOGGER.debug("Sending paired sensors command: %s", payload.hex())
        return_data = self._send_command_and_receive_response(payload)

        # Check for error response first (0xfd at index 8, if panel sends it)
        if len(return_data) > 8 and return_data[8] == 0xfd:
            LOGGER.warning("Panel returned error for get_paired_sensors command (0xfd).")
            return {} # Return empty if command failed

        # The response starts in the byte 8 (after header)
        # Each byte represents 8 zones (1 bit per zone)
        paired_zones = {}
        try:
            # Skip header (8 bytes) and read the 8 bytes of zone data
            for byte_index in range(8):  # 8 bytes = 64 zones
                # Ensure we have enough data in return_data for the current byte
                if len(return_data) > 8 + byte_index:
                    byte_value = return_data[8 + byte_index]
                    for bit in range(8):
                        zone_number = (byte_index * 8) + bit + 1
                        # If the bit is 1, the zone is paired
                        if (byte_value & (1 << bit)) > 0:
                            paired_zones[str(zone_number)] = True
                else:
                    LOGGER.warning(f"Datos de paired zones incompletos en el byte {byte_index} del payload esperado.")
                    break # Exit if no more data

        except Exception as e:
            LOGGER.error(f"Error procesando datos de sensores emparejados: {e}", exc_info=True)
            return {} # Return an empty dictionary in case of error

        return paired_zones
