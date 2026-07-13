from mcp.server.fastmcp import FastMCP
from ..services.developer_service import DeveloperService
from ..services.ai_service import AIService
from ..models.developer import DevEnvStatusModel, ToolInfoModel


def register_developer_tools(
    mcp: FastMCP, developer_service: DeveloperService, ai_service: AIService
):
    """
    Registers the developer_environment and installed_tools tools on FastMCP.
    """

    @mcp.tool(
        name="developer_environment",
        description="Verify status of the developer environment, returning installed versions and paths for Python, Git, Node.js, Docker, Java, and VS Code.",
    )
    def developer_environment() -> DevEnvStatusModel:
        return developer_service.get_developer_environment()

    @mcp.tool(
        name="installed_tools",
        description="Return a simplified check matrix of common developer and AI tools (Python, Git, Docker, Node, Java, VS Code, and Ollama) with versions.",
    )
    def installed_tools() -> dict:
        dev_env = developer_service.get_developer_environment()
        ai_env = ai_service.get_ai_environment()

        ollama_version = None
        if ai_env.ollama_installed:
            ollama_version = "Running" if ai_env.ollama_running else "Installed"

        ollama_info = ToolInfoModel(
            installed=ai_env.ollama_installed,
            status="installed" if ai_env.ollama_installed else "not_detected",
            version=ollama_version,
            path=None,
        )

        return {
            "python": dev_env.python,
            "git": dev_env.git,
            "node": dev_env.node,
            "docker": dev_env.docker,
            "java": dev_env.java,
            "vscode": dev_env.vscode,
            "ollama": ollama_info,
        }
