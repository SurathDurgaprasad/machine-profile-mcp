from mcp.server.fastmcp import FastMCP
from ..services.ai_service import AIService


def register_ai_resources(mcp: FastMCP, ai_service: AIService):
    """
    Registers the windows://ai resource on FastMCP.
    """

    @mcp.resource(
        uri="windows://ai",
        name="AI Environment Snapshot",
        description="A JSON snapshot of GPU details, local ML packages, and Ollama status/models.",
        mime_type="application/json",
    )
    def get_ai_resource() -> str:
        return ai_service.get_ai_environment().model_dump_json(indent=2)
