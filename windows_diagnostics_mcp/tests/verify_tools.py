import sys
import logging

from server import mcp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("verify-tools")

def run_tool_verification():
    logger.info("Starting tool registration check...")

    # Fetch registered tools from FastMCP tool manager
    tools = mcp._tool_manager.list_tools()

    registered_names = {tool.name for tool in tools}

    expected_tools = {
        "system_summary",
        "machine_health",
        "developer_environment",
        "installed_tools",
        "ai_environment",
        "storage_summary",
        "running_processes",
        "network_summary"
    }

    logger.info(f"Registered tools found: {registered_names}")

    # Assert all expected tools exist
    missing_tools = expected_tools - registered_names
    if missing_tools:
        logger.error(f"Missing registered tools: {missing_tools}")
        sys.exit(1)

    extra_tools = registered_names - expected_tools
    if extra_tools:
        logger.warning(f"Extra registered tools found (not in expected list): {extra_tools}")

    # Check descriptions
    for tool in tools:
        if not tool.description:
            logger.error(f"Tool '{tool.name}' is missing a description!")
            sys.exit(1)
        logger.info(f"Tool '{tool.name}' verified: OK. Description: '{tool.description[:60]}...'")

    logger.info("SUCCESS: All 8 MCP Tools are correctly registered and documented!")

if __name__ == "__main__":
    run_tool_verification()
