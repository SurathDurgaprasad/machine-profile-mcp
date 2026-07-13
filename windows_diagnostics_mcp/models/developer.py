from pydantic import BaseModel
from typing import Optional
from .metadata import CollectionMetadataModel


class ToolInfoModel(BaseModel):
    installed: bool
    status: str  # "installed", "not_detected", "unavailable", "error"
    version: Optional[str] = None
    path: Optional[str] = None
    error_message: Optional[str] = None


class DevEnvStatusModel(BaseModel):
    python: ToolInfoModel
    git: ToolInfoModel
    node: ToolInfoModel
    docker: ToolInfoModel
    java: ToolInfoModel
    vscode: ToolInfoModel
    collection_metadata: CollectionMetadataModel
