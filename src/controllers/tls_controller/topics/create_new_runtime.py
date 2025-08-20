from use_cases.docker_manager.create_new_container import run_new_container
from tools.logger import *

NAME = "create_new_runtime"

callback = lambda container_image, container_name: (
    log_info(f"Using image: {container_image}"),
    run_new_container(container_image, container_name),
)
