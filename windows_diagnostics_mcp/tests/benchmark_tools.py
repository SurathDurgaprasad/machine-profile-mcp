import time
import logging
from tabulate import tabulate  # if installed, else fallback to standard string format

# Import services from server bootstrap
from server import (
    system_service,
    health_service,
    developer_service,
    ai_service,
    process_service,
    storage_service,
    network_service,
)

logging.basicConfig(level=logging.WARNING)


def run_benchmarks():
    print("====================================================")
    print("   WINDOWS DIAGNOSTICS MCP PERFORMANCE BENCHMARK   ")
    print("====================================================\n")
    print("Executing diagnostic queries to measure performance budgets...\n")

    targets = [
        ("system_summary", system_service.get_system_summary),
        ("machine_health", health_service.get_machine_health),
        ("developer_environment", developer_service.get_developer_environment),
        (
            "installed_tools",
            lambda: {
                "developer": developer_service.get_developer_environment(),
                "ai": ai_service.get_ai_environment(),
            },
        ),
        ("ai_environment", ai_service.get_ai_environment),
        ("running_processes", lambda: process_service.get_processes(limit=10)),
        ("storage_summary", storage_service.get_storage_summary),
        ("network_summary", network_service.get_network_summary),
    ]

    results = []

    for name, query_func in targets:
        start_time = time.perf_counter()
        try:
            res = query_func()
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Retrieve status from model collection metadata
            status = "unknown"
            if hasattr(res, "collection_metadata"):
                status = res.collection_metadata.status
            elif isinstance(res, dict) and "developer" in res:
                status = (
                    "ok"
                    if res["developer"].collection_metadata.status == "ok"
                    and res["ai"].collection_metadata.status == "ok"
                    else "partial"
                )

            results.append(
                (name, f"{round(duration_ms, 1)} ms", status.upper(), "PASSED")
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            results.append(
                (name, f"{round(duration_ms, 1)} ms", "ERROR", f"FAILED: {str(e)[:40]}")
            )

    print(
        tabulate(
            results,
            headers=["Tool Name", "Execution Latency", "Status Code", "Result State"],
        )
        if "tabulate" in globals()
        else "\n".join([f"{n:<25} {l:<15} {s:<12} {r}" for n, l, s, r in results])
    )

    print("\n====================================================")


if __name__ == "__main__":
    run_benchmarks()
