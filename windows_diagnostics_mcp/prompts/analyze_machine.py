from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent


def register_prompts(mcp: FastMCP):
    """
    Registers the analyze_machine prompt template on FastMCP.
    """

    @mcp.prompt(
        name="analyze_machine",
        description="Review this machine for overall health, developer readiness, AI readiness, performance concerns, and recommendations.",
    )
    def analyze_machine() -> list[PromptMessage]:
        prompt_text = (
            "I want to analyze the system health, developer environment, and AI readiness of my local Windows machine. "
            "Please call the appropriate diagnostic tools registered on this server to collect the required data. "
            "Follow these guidelines for intelligent tool orchestration:\n"
            "1. Inspect system and CPU information using the system_summary tool or windows://system resource.\n"
            "2. Inspect GPU capabilities, local AI runtimes (Ollama, LM Studio), offline model inventories, and Docker status/containers using the ai_environment tool or windows://ai resource.\n"
            "3. Inspect developer tooling and compiler paths using developer_environment or installed_tools.\n"
            "4. Inspect machine health (CPU/RAM usage, process list) using machine_health or running_processes only when relevant to performance troubleshooting.\n"
            "5. Avoid unnecessary tool calls when sufficient information is already collected (e.g., if ai_environment has been queried, do not call system_summary unless OS edition details are specifically requested).\n"
            "6. Distinguish clearly between: installed AI runtimes (e.g. Ollama CLI detected), active running runtimes (Ollama daemon responding), offline cached models (local files under LM Studio/Ollama), and containerized runtimes (running Docker AI containers).\n"
            "7. Never claim a model is currently runnable/loaded merely because a model file exists in the offline cache or directory inventory.\n\n"
            "Once you have gathered the diagnostic reports, write a comprehensive evaluation of the machine's state, highlight any warnings/concerns, and provide actionable recommendations. Do not fabricate any values."
        )

        return [
            PromptMessage(
                role="user", content=TextContent(type="text", text=prompt_text)
            )
        ]
