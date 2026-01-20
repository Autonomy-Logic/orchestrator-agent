from tools.contract_validation import BASE_MESSAGE
from tools.network_event_listener import network_event_listener
from tools.logger import log_info, log_debug
from . import topic, validate_message

NAME = "get_serial_devices"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client):
    """
    Handle the 'get_serial_devices' topic to list available serial devices on the host.

    Returns a list of serial devices that can be configured for passthrough to
    runtime containers. Each device includes:
    - path: Current device path (e.g., /dev/ttyUSB0)
    - by_id: Stable device identifier (e.g., /dev/serial/by-id/usb-FTDI_...)
    - vendor_id: USB vendor ID
    - product_id: USB product ID
    - serial: USB serial number
    - manufacturer: Device manufacturer
    - product: Product name

    The 'by_id' field should be used as the 'device_id' when configuring
    serial ports in create_new_runtime, as it remains stable across reboots
    and USB port changes.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        correlation_id = message.get("correlation_id")

        log_info("Retrieving list of available serial devices")

        # Get devices from the network event listener's cache
        devices = network_event_listener.get_available_devices()

        # Format devices for response
        formatted_devices = []
        for device in devices:
            formatted_device = {
                "path": device.get("path"),
                "device_id": device.get("by_id"),  # Use by_id as the stable identifier
                "vendor_id": device.get("vendor_id"),
                "product_id": device.get("product_id"),
                "serial": device.get("serial"),
                "manufacturer": device.get("manufacturer"),
                "product": device.get("product"),
            }
            formatted_devices.append(formatted_device)

        log_debug(f"Found {len(formatted_devices)} serial device(s)")

        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "success",
            "devices": formatted_devices,
            "count": len(formatted_devices),
        }
