from mcp.server.fastmcp import FastMCP
from ..services.developer_service import DeveloperService

def register_developer_resources(mcp: FastMCP, developer_service: DeveloperService):
    """
    Registers the windows://developer resource on FastMCP.
    """
    @mcp.resource(
        uri="windows://developer",
        name="Developer Environment Snapshot",
        description="A JSON snapshot of installed compilers, runtimes, and IDEs.",
        mime_type="application/json"
    )
    def get_developer_resource() -> str:
        return developer_service.get_developer_environment().model_dump_json(indent=2)
