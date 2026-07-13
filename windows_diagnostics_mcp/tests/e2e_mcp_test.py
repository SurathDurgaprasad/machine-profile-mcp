import asyncio
import os
import sys
import logging
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("e2e-mcp-test")


async def run_e2e_test():
    logger.info("Initializing E2E MCP Protocol Test...")

    # Configure server execution parameters
    env = os.environ.copy()

    import shutil

    machine_profile_bin = shutil.which("machine-profile")

    if machine_profile_bin:
        logger.info(f"Using installed console script: {machine_profile_bin}")
        server_params = StdioServerParameters(
            command=machine_profile_bin, args=[], env=env
        )
    else:
        logger.info(
            "Console script not found in PATH. Falling back to python -m windows_diagnostics_mcp.server"
        )
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "windows_diagnostics_mcp.server"],
            env=env,
        )

    logger.info("Spawning server process and establishing stdio client transport...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        logger.info("Transport established. Starting ClientSession...")
        async with ClientSession(read_stream, write_stream) as session:

            # 1. Initialize Protocol & Negotiate Capabilities
            logger.info("Sending initialize request...")
            await session.initialize()
            logger.info("Capability Handshake: SUCCESS")

            # 2. List registered Tools E2E
            logger.info("Requesting tools/list...")
            tools_res = await session.list_tools()
            tool_names = {t.name for t in tools_res.tools}
            logger.info(f"tools/list Success. Registered tools: {tool_names}")

            expected_tools = {
                "system_summary",
                "machine_health",
                "developer_environment",
                "installed_tools",
                "ai_environment",
                "storage_summary",
                "running_processes",
                "network_summary",
            }
            assert expected_tools.issubset(
                tool_names
            ), f"Missing expected tools: {expected_tools - tool_names}"

            # 3. List registered Resources E2E
            logger.info("Requesting resources/list...")
            resources_res = await session.list_resources()
            resource_uris = {str(r.uri) for r in resources_res.resources}
            logger.info(
                f"resources/list Success. Registered resources: {resource_uris}"
            )

            expected_resources = {
                "windows://system",
                "windows://developer",
                "windows://ai",
                "windows://network",
            }
            assert expected_resources.issubset(
                resource_uris
            ), f"Missing expected resources: {expected_resources - resource_uris}"

            # 4. List registered Prompts E2E
            logger.info("Requesting prompts/list...")
            prompts_res = await session.list_prompts()
            prompt_names = {p.name for p in prompts_res.prompts}
            logger.info(f"prompts/list Success. Registered prompts: {prompt_names}")
            assert (
                "analyze_machine" in prompt_names
            ), "Missing expected prompt 'analyze_machine'"

            # 5. Invoke and Validate all 8 Tools individually
            logger.info("--- Invoking and validating all 8 tools individually ---")
            for tool_name in expected_tools:
                logger.info(f"Calling tool: {tool_name}...")
                args = {"limit": 5} if tool_name == "running_processes" else {}
                tool_call = await session.call_tool(tool_name, arguments=args)

                # Check for successful call and content
                assert (
                    len(tool_call.content) > 0
                ), f"Tool {tool_name} returned empty content array"
                assert (
                    tool_call.content[0].type == "text"
                ), f"Tool {tool_name} returned non-text format"
                text_out = tool_call.content[0].text

                # Verify that it is valid JSON
                data = json.loads(text_out)
                assert isinstance(
                    data, (dict, list)
                ), f"Tool {tool_name} output is not a JSON object/array"

                # Verify that there are no Python tracebacks
                assert (
                    "traceback" not in text_out.lower()
                ), f"Tool {tool_name} output contains a traceback"
                assert (
                    "tracebacktype" not in text_out.lower()
                ), f"Tool {tool_name} output contains a traceback"
                assert (
                    "syntaxerror" not in text_out.lower()
                ), f"Tool {tool_name} output contains a syntax error"
                assert (
                    "nameerror" not in text_out.lower()
                ), f"Tool {tool_name} output contains a NameError"

                # Verify metadata exists on dict outputs
                if isinstance(data, dict):
                    if "collection_metadata" in data:
                        metadata = data["collection_metadata"]
                        assert (
                            "status" in metadata
                        ), f"Tool {tool_name} is missing metadata status"
                        assert (
                            "warnings" in metadata
                        ), f"Tool {tool_name} is missing metadata warnings"
                        logger.info(
                            f"Tool {tool_name} SUCCESS. Status: {metadata['status']}, Latency: {metadata.get('duration_ms')} ms"
                        )
                    else:
                        logger.info(
                            f"Tool {tool_name} SUCCESS (no direct metadata block, standard raw layout)."
                        )
                else:
                    logger.info(f"Tool {tool_name} SUCCESS.")

            # 6. Read and Validate all 4 Resources individually
            logger.info("--- Reading and validating all 4 resources individually ---")
            for resource_uri in expected_resources:
                logger.info(f"Reading resource: {resource_uri}...")
                resource_read = await session.read_resource(resource_uri)

                assert (
                    len(resource_read.contents) > 0
                ), f"Resource {resource_uri} returned empty contents"
                content_item = resource_read.contents[0]
                assert (
                    content_item.mimeType == "application/json"
                ), f"Resource {resource_uri} is not application/json"
                text_out = content_item.text

                # Verify that it is valid JSON
                data = json.loads(text_out)
                assert isinstance(
                    data, dict
                ), f"Resource {resource_uri} output is not a JSON object"

                # Check tracebacks
                assert (
                    "traceback" not in text_out.lower()
                ), f"Resource {resource_uri} contains a traceback"
                logger.info(f"Resource {resource_uri} SUCCESS.")

            # 7. Get and Validate Prompt Template
            logger.info("--- Retrieving and validating prompt template ---")
            prompt_get = await session.get_prompt("analyze_machine", arguments={})
            assert (
                len(prompt_get.messages) > 0
            ), "Prompt analyze_machine returned empty message list"
            assert (
                prompt_get.messages[0].role == "user"
            ), "Prompt message role is not 'user'"
            prompt_text = prompt_get.messages[0].content.text
            assert (
                "Please call the appropriate diagnostic tools" in prompt_text
            ), "Prompt instruction text mismatch"
            logger.info("Prompt analyze_machine SUCCESS.")

    logger.info("Shutting down E2E client. Subprocess terminated gracefully.")
    logger.info(
        "SUCCESS: All E2E protocol tools, resources, and prompt handshakes validated successfully!"
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_e2e_test())
    except Exception as e:
        logger.error(f"E2E PROTOCOL VALIDATION FAILED: {e}", exc_info=True)
        sys.exit(1)
