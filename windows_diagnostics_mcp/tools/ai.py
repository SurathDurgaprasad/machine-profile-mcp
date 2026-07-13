from mcp.server.fastmcp import FastMCP
from ..services.ai_service import AIService
from ..models.ai import AIEnvStatusModel


def register_ai_tools(mcp: FastMCP, ai_service: AIService):
    """
    Registers the ai_environment tool on FastMCP.
    """

    @mcp.tool(
        name="ai_environment",
        description="Verify status of local AI / ML configurations including GPU hardware specs, local package installations (PyTorch, ONNX Runtime), Ollama server readiness, active models list, and workspace virtual environments.",
    )
    def ai_environment() -> AIEnvStatusModel:
        return ai_service.get_ai_environment()
