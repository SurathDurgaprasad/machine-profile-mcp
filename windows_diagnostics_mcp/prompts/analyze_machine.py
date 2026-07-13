from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent

def register_prompts(mcp: FastMCP):
    """
    Registers the analyze_machine prompt template on FastMCP.
    """
    @mcp.prompt(
        name="analyze_machine",
        description="Review this machine for overall health, developer readiness, AI readiness, performance concerns, and recommendations."
    )
    def analyze_machine() -> list[PromptMessage]:
        prompt_text = (
            "I want to analyze the system health, developer environment, and AI readiness of my local Windows machine. "
            "Please call the appropriate diagnostic tools registered on this server to collect the required data, such as:\n"
            "- system_summary (for OS edition, version, build number, hostname, and uptime)\n"
            "- machine_health (for CPU/RAM utilization, startup apps, system drive alerts, warnings, and high-resource processes)\n"
            "- developer_environment or installed_tools (for compiler/runtime versions and installation paths)\n"
            "- ai_environment (for GPU status, local ML packages like PyTorch/ONNX, Ollama servers, and workspace virtualenvs)\n"
            "- storage_summary (for local disk capacities and partition usage mapping)\n"
            "- network_summary (for default gateway routing, DNS configurations, local IPs, and internet checks)\n\n"
            "Once you have gathered the diagnostic reports, write a comprehensive evaluation. "
            "Do not fabricate any values. Assess the machine's state, highlight any warnings/concerns, and provide actionable recommendations based on the findings."
        )

        return [
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=prompt_text)
            )
        ]
