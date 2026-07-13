from pydantic import BaseModel
from typing import List, Optional
from .metadata import CollectionMetadataModel


class NetworkSummaryModel(BaseModel):
    hostname: str
    local_ips: List[str]
    default_gateway: Optional[str] = None
    dns_servers: List[str]
    network_interface_available: bool
    local_network_available: bool
    internet_reachability_check: str  # "success", "failed", "timeout", "unknown"
    internet_connected: bool
    collection_metadata: CollectionMetadataModel
