import sys
import logging

from server import mcp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("verify-resources")

def run_resource_verification():
    logger.info("Starting resource registration check...")

    # Fetch registered resources from FastMCP resource manager
    resources = mcp._resource_manager.list_resources()

    registered_uris = {str(res.uri) for res in resources}

    expected_uris = {
        "windows://system",
        "windows://developer",
        "windows://ai",
        "windows://network"
    }

    logger.info(f"Registered URIs found: {registered_uris}")

    # Assert all expected URIs exist
    missing_uris = expected_uris - registered_uris
    if missing_uris:
        logger.error(f"Missing registered resource URIs: {missing_uris}")
        sys.exit(1)

    extra_uris = registered_uris - expected_uris
    if extra_uris:
        logger.warning(f"Extra registered resource URIs found (not in expected list): {extra_uris}")

    # Check descriptions and MIME types
    for res in resources:
        uri_str = str(res.uri)
        if not res.description:
            logger.error(f"Resource '{uri_str}' is missing a description!")
            sys.exit(1)
        if res.mime_type != "application/json":
            logger.error(f"Resource '{uri_str}' has invalid MIME type: {res.mime_type} (expected application/json)")
            sys.exit(1)

        logger.info(f"Resource '{uri_str}' verified: OK. MIME: '{res.mime_type}' Description: '{res.description}'")

    logger.info("SUCCESS: All 4 MCP Resources are correctly registered and documented!")

if __name__ == "__main__":
    run_resource_verification()
