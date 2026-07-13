import json
import logging
import sys

from ..services.system_service import SystemService
from ..services.process_service import ProcessService
from ..services.storage_service import StorageService
from ..services.developer_service import DeveloperService
from ..services.ai_service import AIService
from ..services.network_service import NetworkService
from ..services.health_service import HealthService

# Configure logging to console
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("verify-services")


def run_verification():
    logger.info("Initializing services...")

    system_service = SystemService()
    process_service = ProcessService()
    storage_service = StorageService()
    developer_service = DeveloperService()
    ai_service = AIService()
    network_service = NetworkService()
    health_service = HealthService(process_service, storage_service)

    logger.info("--- Testing SystemService ---")
    sys_summary = system_service.get_system_summary()
    print(json.dumps(sys_summary.model_dump(), indent=2))
    assert sys_summary.edition
    assert sys_summary.username

    logger.info("--- Testing ProcessService ---")
    # Limit to top 2 for testing output cleanliness
    process_data = process_service.get_processes(limit=2)
    print(f"Total processes tracked: {len(process_data.processes)}")
    print("Top CPU:")
    for p in process_data.top_cpu:
        print(f"  PID {p.pid} - {p.name}: {p.cpu_percent}%")
    print("Top Memory:")
    for p in process_data.top_memory:
        print(f"  PID {p.pid} - {p.name}: {round(p.memory_bytes / (1024**2), 1)} MB")
    assert len(process_data.top_cpu) > 0

    logger.info("--- Testing StorageService ---")
    storage_data = storage_service.get_storage_summary()
    print(json.dumps(storage_data.model_dump(), indent=2))
    assert len(storage_data.drives) > 0

    logger.info("--- Testing DeveloperService ---")
    dev_data = developer_service.get_developer_environment()
    print(json.dumps(dev_data.model_dump(), indent=2))
    assert dev_data.python.installed

    logger.info("--- Testing AIService ---")
    ai_data = ai_service.get_ai_environment()
    print(json.dumps(ai_data.model_dump(), indent=2))

    logger.info("--- Testing NetworkService ---")
    net_data = network_service.get_network_summary()
    print(json.dumps(net_data.model_dump(), indent=2))
    assert net_data.hostname

    logger.info("--- Testing HealthService ---")
    health_data = health_service.get_machine_health()
    print(json.dumps(health_data.model_dump(), indent=2))
    assert 0 <= health_data.health_score <= 100

    logger.info("SUCCESS: All core services initialized and validated successfully!")


if __name__ == "__main__":
    try:
        run_verification()
    except Exception as e:
        logger.error(f"VERIFICATION FAILED: {e}", exc_info=True)
        sys.exit(1)
