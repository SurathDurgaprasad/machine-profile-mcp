from mcp.server.fastmcp import FastMCP
from ..services.system_service import SystemService


def register_system_resources(mcp: FastMCP, system_service: SystemService):
    """
    Registers the windows://system resource on FastMCP.
    """

    @mcp.resource(
        uri="windows://system",
        name="System Summary Snapshot",
        description="A JSON snapshot of Windows system metadata and uptime.",
        mime_type="application/json",
    )
    def get_system_resource() -> str:
        return system_service.get_system_summary().model_dump_json(indent=2)
