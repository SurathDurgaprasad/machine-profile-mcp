from mcp.server.fastmcp import FastMCP
from ..services.process_service import ProcessService
from ..models.process import ProcessListModel

def register_process_tools(mcp: FastMCP, process_service: ProcessService):
    """
    Registers the running_processes tool on FastMCP.
    """
    @mcp.tool(
        name="running_processes",
        description="Query active running processes, returning overall process details and top CPU and memory consumers."
    )
    def running_processes(limit: int = 10) -> ProcessListModel:
        """
        Retrieves active running processes, returned as lists sorted by highest CPU and Memory utilization.

        Args:
            limit (int): Maximum number of top processes to return in top lists (default 10).
        """
        return process_service.get_processes(limit=limit)
