from mcp.server.fastmcp import FastMCP
from ..services.system_service import SystemService
from ..models.system import SystemSummaryModel

def register_system_tools(mcp: FastMCP, system_service: SystemService):
    """
    Registers the system_summary tool on FastMCP.
    """
    @mcp.tool(
        name="system_summary",
        description="Get a summary of the Windows system metadata including Windows Edition, version, build number, host, user, and uptime."
    )
    def system_summary() -> SystemSummaryModel:
        return system_service.get_system_summary()
