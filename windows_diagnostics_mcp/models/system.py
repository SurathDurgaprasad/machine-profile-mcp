from pydantic import BaseModel
from .metadata import CollectionMetadataModel


class SystemSummaryModel(BaseModel):
    edition: str
    version: str
    build_number: str
    architecture: str
    hostname: str
    username: str
    uptime_seconds: float
    uptime_formatted: str
    collection_metadata: CollectionMetadataModel
