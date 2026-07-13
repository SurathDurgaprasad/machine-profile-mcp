from pydantic import BaseModel
from typing import List
from .process import ProcessInfoModel
from .metadata import CollectionMetadataModel, WarningItem


class RecommendationItem(BaseModel):
    message: str


class MachineHealthModel(BaseModel):
    health_score: int
    cpu_utilization: float
    memory_utilization: float
    disk_utilization: float  # Main system drive utilization percent
    warnings: List[WarningItem]
    recommendations: List[RecommendationItem]
    top_cpu_processes: List[ProcessInfoModel]
    top_memory_processes: List[ProcessInfoModel]
    collection_metadata: CollectionMetadataModel
