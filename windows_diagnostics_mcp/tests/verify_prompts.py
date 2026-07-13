import sys
import logging

from server import mcp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("verify-prompts")

def run_prompt_verification():
    logger.info("Starting prompt registration check...")

    # Fetch registered prompts from FastMCP prompt manager
    prompts = mcp._prompt_manager.list_prompts()

    registered_names = {p.name for p in prompts}

    expected_prompt = "analyze_machine"

    logger.info(f"Registered prompts found: {registered_names}")

    if expected_prompt not in registered_names:
        logger.error(f"Missing expected prompt: {expected_prompt}")
        sys.exit(1)

    for p in prompts:
        if p.name == expected_prompt:
            if not p.description:
                logger.error(f"Prompt '{p.name}' is missing a description!")
                sys.exit(1)
            logger.info(f"Prompt '{p.name}' verified: OK. Description: '{p.description}'")

    logger.info("SUCCESS: The MCP Prompt is correctly registered and documented!")

if __name__ == "__main__":
    run_prompt_verification()
