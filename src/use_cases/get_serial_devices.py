def get_serial_devices_data(*, network_event_listener):
    devices = network_event_listener.get_available_devices()

    formatted_devices = []
    for device in devices:
        formatted_devices.append({
            "path": device.get("path"),
            "device_id": device.get("by_id"),
            "vendor_id": device.get("vendor_id"),
            "product_id": device.get("product_id"),
            "serial": device.get("serial"),
            "manufacturer": device.get("manufacturer"),
            "product": device.get("product"),
        })

    return {"devices": formatted_devices, "count": len(formatted_devices)}
