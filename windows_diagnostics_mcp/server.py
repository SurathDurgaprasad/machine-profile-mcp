"""
Windows Diagnostics MCP Server - Packaged Bootstrap

This file contains the server bootstrap implementation inside the package namespace.
It initializes all domain-specific services, registers the MCP tools, resources, and prompts, and runs the server.
"""

import sys
import logging
from mcp.server.fastmcp import FastMCP

# Import Services
from windows_diagnostics_mcp.services.system_service import SystemService
from windows_diagnostics_mcp.services.process_service import ProcessService
from windows_diagnostics_mcp.services.storage_service import StorageService
from windows_diagnostics_mcp.services.developer_service import DeveloperService
from windows_diagnostics_mcp.services.ai_service import AIService
from windows_diagnostics_mcp.services.network_service import NetworkService
from windows_diagnostics_mcp.services.health_service import HealthService

# Import Tool Registrars
from windows_diagnostics_mcp.tools.system import register_system_tools
from windows_diagnostics_mcp.tools.health import register_health_tools
from windows_diagnostics_mcp.tools.developer import register_developer_tools
from windows_diagnostics_mcp.tools.ai import register_ai_tools
from windows_diagnostics_mcp.tools.storage import register_storage_tools
from windows_diagnostics_mcp.tools.process import register_process_tools
from windows_diagnostics_mcp.tools.network import register_network_tools

# Import Resource Registrars
from windows_diagnostics_mcp.resources.system import register_system_resources
from windows_diagnostics_mcp.resources.developer import register_developer_resources
from windows_diagnostics_mcp.resources.ai import register_ai_resources
from windows_diagnostics_mcp.resources.network import register_network_resources

# Import Prompt Registrars
from windows_diagnostics_mcp.prompts.analyze_machine import register_prompts

# Configure logging to stderr to prevent interference with stdout stdio transport protocol
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("machine-profile")

# Create FastMCP server instance
mcp = FastMCP(
    "machine-profile",
    instructions="A Windows machine profile and current environment diagnostic tool built with the Python MCP SDK",
)

# Instantiate Core Services
system_service = SystemService()
process_service = ProcessService()
storage_service = StorageService()
developer_service = DeveloperService()
ai_service = AIService()
network_service = NetworkService()
health_service = HealthService(process_service, storage_service)

# Register MCP Tools
register_system_tools(mcp, system_service)
register_health_tools(mcp, health_service)
register_developer_tools(mcp, developer_service, ai_service)
register_ai_tools(mcp, ai_service)
register_storage_tools(mcp, storage_service)
register_process_tools(mcp, process_service)
register_network_tools(mcp, network_service)

# Register MCP Resources
register_system_resources(mcp, system_service)
register_developer_resources(mcp, developer_service)
register_ai_resources(mcp, ai_service)
register_network_resources(mcp, network_service)

# Register MCP Prompts
register_prompts(mcp)


def main():
    """
    Standard entry point for console script launches.
    """
    try:
        logger.info("Starting MachineProfile MCP Server...")
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server stopped cleanly via user interrupt.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error running server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
