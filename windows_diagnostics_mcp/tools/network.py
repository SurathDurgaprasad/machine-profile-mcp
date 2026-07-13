from mcp.server.fastmcp import FastMCP
from ..services.network_service import NetworkService
from ..models.network import NetworkSummaryModel


def register_network_tools(mcp: FastMCP, network_service: NetworkService):
    """
    Registers the network_summary tool on FastMCP.
    """

    @mcp.tool(
        name="network_summary",
        description="Get local network specifications including host name, local IP address list, active DNS servers, gateway interface, and check outbound internet status.",
    )
    def network_summary() -> NetworkSummaryModel:
        return network_service.get_network_summary()
