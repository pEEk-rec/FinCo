"""
Formatting and display utilities for the workflow run trace.
"""

from copilot.workflow.state import TraceEntry


def format_trace(trace: list[TraceEntry]) -> str:
    """
    Format a list of TraceEntry records into a clean, readable ASCII table.
    """
    if not trace:
        return "(empty trace)"

    lines = [
        "=" * 80,
        "WORKFLOW RUN TRACE".center(80),
        "=" * 80,
        f"{'NODE':<12} {'STATUS':<8} {'DURATION':<10} {'TOOLS CALLED':<24} {'COUNTS'}",
        "-" * 80,
    ]

    total_duration = 0.0
    for entry in trace:
        node = entry.get("node", "unknown")
        status = entry.get("status", "unknown")
        dur_ms = entry.get("duration_ms", 0.0)
        total_duration += dur_ms
        dur_str = f"{dur_ms:.1f}ms"

        tools = ", ".join(entry.get("tools_called", [])) or "-"
        if len(tools) > 23:
            tools = tools[:20] + "..."

        counts_dict = entry.get("counts") or {}
        counts_str = ", ".join(f"{k}: {v}" for k, v in counts_dict.items()) or "-"

        err = entry.get("error")
        if err:
            counts_str += f" [error: {err}]"

        lines.append(f"{node:<12} {status:<8} {dur_str:<10} {tools:<24} {counts_str}")

    lines.append("-" * 80)
    lines.append(f"Total duration: {total_duration:.1f}ms | Trace steps: {len(trace)}")
    lines.append("=" * 80)

    return "\n".join(lines)


def print_trace(trace: list[TraceEntry]) -> None:
    """Print the formatted trace to stdout."""
    print(format_trace(trace))
