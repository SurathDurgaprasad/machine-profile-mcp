from pydantic import BaseModel
from typing import List


class WarningItem(BaseModel):
    component: str  # e.g., "gpu", "ollama", "process"
    code: str  # e.g., "GPU_DETAILS_UNAVAILABLE"
    message: str  # descriptive message
    severity: str = "warning"  # "warning" | "critical"


class CollectionMetadataModel(BaseModel):
    timestamp: float
    duration_ms: float
    status: str  # "ok" | "partial" | "unavailable" | "error"
    warnings: List[WarningItem] = []
