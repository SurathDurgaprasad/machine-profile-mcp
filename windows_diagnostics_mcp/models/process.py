from pydantic import BaseModel
from typing import List
from .metadata import CollectionMetadataModel

class ProcessInfoModel(BaseModel):
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_bytes: int

class ProcessListModel(BaseModel):
    processes: List[ProcessInfoModel]
    top_cpu: List[ProcessInfoModel]
    top_memory: List[ProcessInfoModel]
    collection_metadata: CollectionMetadataModel
