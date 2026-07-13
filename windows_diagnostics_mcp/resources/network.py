from mcp.server.fastmcp import FastMCP
from ..services.network_service import NetworkService

def register_network_resources(mcp: FastMCP, network_service: NetworkService):
    """
    Registers the windows://network resource on FastMCP.
    """
    @mcp.resource(
        uri="windows://network",
        name="Network Topology Snapshot",
        description="A JSON snapshot of local network settings, DNS servers, gateway, and internet status.",
        mime_type="application/json"
    )
    def get_network_resource() -> str:
        return network_service.get_network_summary().model_dump_json(indent=2)
