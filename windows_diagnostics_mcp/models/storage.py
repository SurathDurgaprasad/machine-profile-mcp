from pydantic import BaseModel
from typing import List, Optional
from .metadata import CollectionMetadataModel


class DriveInfoModel(BaseModel):
    drive: str
    fstype: str
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    usage_percent: Optional[float] = None
    status: str  # "available", "permission_denied", "unavailable"


class StorageSummaryModel(BaseModel):
    drives: List[DriveInfoModel]
    collection_metadata: CollectionMetadataModel
