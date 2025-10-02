from . import CLIENT, CLIENTS, HOST_NAME, addClient
from tools.logger import *

def run_new_container(image_name: str, container_name: str):
    """
    Run a new container with specified image, attach it to a custom network along with
    the main container, set restart policy, expose port 5000, and save its IP.
    """

    log_debug(
        f'Attempting to run a new container "{container_name}" with image: {image_name}'
    )

    if container_name in CLIENTS:
        log_error(f"Container name {container_name} is already in use.")
        return

    try:
        network_name = f"{container_name}_network"
        try:
            network = CLIENT.networks.get(network_name)
            log_debug(f"Network {network_name} already exists")
        except:
            network = CLIENT.networks.create(network_name, driver="bridge")
            log_info(f"Network {network_name} created")

        container = CLIENT.containers.run(
            image=image_name,
            name=container_name,
            detach=True,
            restart_policy={"Name": "always"}
        )
        log_info(f"Container {container_name} created successfully")

        network.connect(container)
        log_debug(f"Connected {container_name} to network {network_name}")

        try:
            main_container = CLIENT.containers.get(HOST_NAME)
            network.connect(main_container)
            log_debug(f"Connected {HOST_NAME} to network {network_name}")
        except Exception as e:
            log_error(f"Could not connect main container {HOST_NAME}: {e}")

        container.reload()
        network_settings = container.attrs["NetworkSettings"]["Networks"]
        ip_addr = network_settings[network_name]["IPAddress"]

        addClient(container_name, ip_addr)
        log_info(f"Container {container_name} has IP {ip_addr}")

    except Exception as e:
        log_error(f"Failed to create container {container_name}. Error: {e}")
