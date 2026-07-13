from mcp.server.fastmcp import FastMCP
from ..services.health_service import HealthService
from ..models.health import MachineHealthModel

def register_health_tools(mcp: FastMCP, health_service: HealthService):
    """
    Registers the machine_health tool on FastMCP.
    """
    @mcp.tool(
        name="machine_health",
        description="Check the machine's overall diagnostics, calculating a health score, and returning CPU, RAM, Disk usage stats, active startup apps count, warnings, recommendations, and high-resource processes."
    )
    def machine_health() -> MachineHealthModel:
        return health_service.get_machine_health()
