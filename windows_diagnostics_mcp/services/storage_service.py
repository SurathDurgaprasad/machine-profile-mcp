import logging
import time
import psutil

from ..models.storage import DriveInfoModel, StorageSummaryModel
from ..models.metadata import CollectionMetadataModel, WarningItem

logger = logging.getLogger("windows-diagnostics.services.storage")


class StorageService:
    """
    Service for querying disk partitions and storage space utilization.
    """

    def get_storage_summary(self) -> StorageSummaryModel:
        """
        Retrieves disk information for all local mounted physical drives.
        """
        start_time = time.perf_counter()
        drives = []
        warnings = []
        status = "ok"

        try:
            partitions = psutil.disk_partitions(
                all=True
            )  # Retrieve all partitions (including removable/network/locked)
        except Exception as e:
            status = "error"
            logger.error(f"Error enumerating disk partitions: {e}")
            partitions = []

        for part in partitions:
            # Skip empty fstypes or standard network/loopback exclusions if appropriate
            # But keep removable/local drives for visibility
            if "cdrom" in part.opts or not part.fstype:
                # Still record optical drive as unavailable
                drives.append(
                    DriveInfoModel(
                        drive=part.mountpoint, fstype="Optical", status="unavailable"
                    )
                )
                continue

            try:
                usage = psutil.disk_usage(part.mountpoint)
                drives.append(
                    DriveInfoModel(
                        drive=part.mountpoint,
                        fstype=part.fstype,
                        total_bytes=usage.total,
                        used_bytes=usage.used,
                        free_bytes=usage.free,
                        usage_percent=round(usage.percent, 1),
                        status="available",
                    )
                )
            except PermissionError:
                # Restricted corporate machine drive or locked partition
                drives.append(
                    DriveInfoModel(
                        drive=part.mountpoint,
                        fstype=part.fstype,
                        status="permission_denied",
                    )
                )
                warnings.append(
                    WarningItem(
                        component="storage",
                        code="PARTITION_ACCESS_DENIED",
                        message=f"Access denied reading partition space on {part.mountpoint}",
                        severity="warning",
                    )
                )
                status = "partial"
            except FileNotFoundError:
                # Removable drive not plugged in or unmounted partition
                drives.append(
                    DriveInfoModel(
                        drive=part.mountpoint, fstype=part.fstype, status="unavailable"
                    )
                )
            except Exception as e:
                # General error reading the drive
                logger.warning(f"Error reading drive {part.mountpoint}: {e}")
                drives.append(
                    DriveInfoModel(
                        drive=part.mountpoint, fstype=part.fstype, status="unavailable"
                    )
                )
                warnings.append(
                    WarningItem(
                        component="storage",
                        code="PARTITION_QUERY_FAILED",
                        message=f"Failed to query partition {part.mountpoint}: {str(e)}",
                        severity="warning",
                    )
                )
                status = "partial"

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings,
        )

        return StorageSummaryModel(drives=drives, collection_metadata=metadata)
