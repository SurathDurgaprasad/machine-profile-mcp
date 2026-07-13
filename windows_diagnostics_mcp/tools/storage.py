from mcp.server.fastmcp import FastMCP
from ..services.storage_service import StorageService
from ..models.storage import StorageSummaryModel

def register_storage_tools(mcp: FastMCP, storage_service: StorageService):
    """
    Registers the storage_summary tool on FastMCP.
    """
    @mcp.tool(
        name="storage_summary",
        description="Get storage specifications of all local drives, reporting total storage capacities, current utilized spaces, free spaces, and usage percent mappings."
    )
    def storage_summary() -> StorageSummaryModel:
        return storage_service.get_storage_summary()
