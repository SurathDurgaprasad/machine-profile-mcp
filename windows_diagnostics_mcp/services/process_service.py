import logging
import time
from typing import List
import psutil

from ..models.process import ProcessInfoModel, ProcessListModel
from ..models.metadata import CollectionMetadataModel

logger = logging.getLogger("windows-diagnostics.services.process")

class ProcessService:
    """
    Service for querying active processes and sorting them by CPU/Memory consumption.
    """

    def get_processes(self, limit: int = 10) -> ProcessListModel:
        """
        Gathers CPU, Memory and metadata for all processes.
        Performs a double-pass over active processes to capture non-blocking CPU usage.
        Reuses cached attributes to minimize Windows handle-opening overhead.

        Args:
            limit (int): The number of top processes to return for CPU and memory rankings.
        """
        start_time = time.perf_counter()
        warnings = []
        status = "ok"
        active_processes = []

        # First pass: trigger CPU check and cache process info in batch
        try:
            for proc in psutil.process_iter(attrs=['name', 'memory_percent', 'memory_info']):
                try:
                    # Triggers measurement calculation since last call
                    proc.cpu_percent(interval=None)
                    active_processes.append((proc, proc.info))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue
        except Exception as e:
            status = "error"
            logger.error(f"Error enumerating processes in first pass: {e}")

        # Wait briefly for CPU sample interval accumulation
        time.sleep(0.1)

        # Second pass: calculate CPU utilization and compile results
        all_process_models: List[ProcessInfoModel] = []

        for proc, info in active_processes:
            try:
                cpu = proc.cpu_percent(interval=None)

                # Retrieve batch-cached properties from info dict
                name = info.get('name') or "unknown"
                mem_percent = info.get('memory_percent') or 0.0

                mem_info = info.get('memory_info')
                mem_bytes = mem_info.rss if mem_info else 0

                all_process_models.append(
                    ProcessInfoModel(
                        pid=proc.pid,
                        name=name,
                        cpu_percent=round(cpu, 1),
                        memory_percent=round(mem_percent, 1),
                        memory_bytes=mem_bytes
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Sort top processes
        top_cpu = sorted(all_process_models, key=lambda x: x.cpu_percent, reverse=True)[:limit]
        top_mem = sorted(all_process_models, key=lambda x: x.memory_bytes, reverse=True)[:limit]

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings
        )

        return ProcessListModel(
            processes=all_process_models,
            top_cpu=top_cpu,
            top_memory=top_mem,
            collection_metadata=metadata
        )
