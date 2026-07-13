import logging
import os
import time
import winreg
import psutil

from ..models.health import MachineHealthModel, RecommendationItem
from ..models.metadata import CollectionMetadataModel, WarningItem
from .process_service import ProcessService
from .storage_service import StorageService

logger = logging.getLogger("windows-diagnostics.services.health")


class HealthService:
    """
    Service for calculating overall system health score and compiling warnings/recommendations.
    """

    def __init__(
        self, process_service: ProcessService, storage_service: StorageService
    ):
        self.process_service = process_service
        self.storage_service = storage_service

    def _get_startup_programs_count(self) -> int:
        """
        Queries Windows registry Run keys to count configured startup applications.
        """
        count = 0
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                with winreg.OpenKey(
                    root, r"Software\Microsoft\Windows\CurrentVersion\Run"
                ) as key:
                    info = winreg.QueryInfoKey(key)
                    count += info[1]  # count of registry values (startup apps)
            except Exception:
                pass
        return count

    def get_machine_health(self) -> MachineHealthModel:
        """
        Performs diagnostic calculations to evaluate CPU, RAM, and Storage,
        and constructs warnings and recommendations.
        """
        start_time = time.perf_counter()
        warnings = []
        recommendations = []
        health_score = 100
        status = "ok"

        # Determine dynamic Windows System Drive letter (defaults to C:)
        sys_drive = os.environ.get("SystemDrive", "C:")
        sys_drive_path = sys_drive + "\\" if not sys_drive.endswith("\\") else sys_drive

        # 1. CPU Check
        try:
            cpu_util = psutil.cpu_percent(interval=0.1)
            if cpu_util > 80.0:
                health_score -= 15
                warnings.append(
                    WarningItem(
                        component="cpu",
                        code="HIGH_CPU_UTILIZATION",
                        message=f"High CPU utilization: {cpu_util}%",
                        severity="critical" if cpu_util > 95.0 else "warning",
                    )
                )
                recommendations.append(
                    RecommendationItem(
                        message="Identify and close high-CPU processes, or terminate hung tasks."
                    )
                )
        except Exception as e:
            cpu_util = 0.0
            status = "partial"
            logger.warning(f"Failed to query CPU utilization: {e}")

        # 2. Memory Check
        try:
            mem = psutil.virtual_memory()
            mem_util = mem.percent
            if mem_util > 85.0:
                health_score -= 15
                warnings.append(
                    WarningItem(
                        component="memory",
                        code="HIGH_MEMORY_UTILIZATION",
                        message=f"High Memory utilization: {mem_util}%",
                        severity="critical" if mem_util > 95.0 else "warning",
                    )
                )
                recommendations.append(
                    RecommendationItem(
                        message="Close unused applications or web browser tabs to free up RAM."
                    )
                )
        except Exception as e:
            mem_util = 0.0
            status = "partial"
            logger.warning(f"Failed to query memory utilization: {e}")

        # 3. Storage Check
        sys_drive_util = 0.0
        try:
            c_usage = psutil.disk_usage(sys_drive_path)
            c_free = c_usage.free
            sys_drive_util = c_usage.percent
            c_free_gb = c_free / (1024**3)

            if c_free_gb < 10.0:
                health_score -= 20
                warnings.append(
                    WarningItem(
                        component="storage",
                        code="LOW_SYSTEM_DISK_SPACE",
                        message=f"Low disk space on {sys_drive} - only {round(c_free_gb, 1)} GB free",
                        severity="critical" if c_free_gb < 5.0 else "warning",
                    )
                )
                recommendations.append(
                    RecommendationItem(
                        message=f"Run Disk Cleanup or move large developer projects off of your {sys_drive} drive."
                    )
                )
            elif sys_drive_util > 90.0:
                health_score -= 10
                warnings.append(
                    WarningItem(
                        component="storage",
                        code="SYSTEM_DISK_NEAR_CAPACITY",
                        message=f"{sys_drive} drive is filling up ({sys_drive_util}% used)",
                        severity="warning",
                    )
                )
                recommendations.append(
                    RecommendationItem(
                        message=f"Consider archiving old files or clearing package manager caches on {sys_drive}."
                    )
                )
        except Exception as e:
            status = "partial"
            logger.warning(
                f"Failed to query system installation drive {sys_drive_path}: {e}"
            )

        # 4. Startup Applications Check
        try:
            startup_count = self._get_startup_programs_count()
            if startup_count > 15:
                health_score -= 5
                warnings.append(
                    WarningItem(
                        component="system",
                        code="HIGH_STARTUP_APPLICATIONS",
                        message=f"High number of startup applications detected ({startup_count} apps)",
                        severity="warning",
                    )
                )
                recommendations.append(
                    RecommendationItem(
                        message="Disable unnecessary startup apps via Task Manager to speed up boot times."
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to query startup applications count: {e}")

        # Cap health score to range [0, 100]
        health_score = max(0, min(100, health_score))

        # Get top consuming processes (from process service)
        try:
            process_data = self.process_service.get_processes(limit=5)
            top_cpu = process_data.top_cpu
            top_mem = process_data.top_memory
        except Exception as e:
            top_cpu = []
            top_mem = []
            status = "partial"
            warnings.append(
                WarningItem(
                    component="process",
                    code="PROCESS_DETAILS_UNAVAILABLE",
                    message=f"Failed to fetch running processes: {e}",
                )
            )
            logger.warning(f"Failed to fetch running processes for health check: {e}")

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings,
        )

        return MachineHealthModel(
            health_score=health_score,
            cpu_utilization=cpu_util,
            memory_utilization=mem_util,
            disk_utilization=sys_drive_util,
            warnings=warnings,
            recommendations=recommendations,
            top_cpu_processes=top_cpu,
            top_memory_processes=top_mem,
            collection_metadata=metadata,
        )
