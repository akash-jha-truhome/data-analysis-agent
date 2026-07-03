from graph.state import AgentState


def route_after_execute(state: AgentState) -> str:
    """ok -> answer | (code error & attempt < max) -> write_code | else -> handle_error."""
    if state.get("error"):
        # Sandbox infrastructure failure — fatal.
        return "handle_error"
    exec_result = state.get("exec_result") or {}
    if exec_result.get("ok"):
        return "answer"
    attempt = int(state.get("attempt", 0))
    max_steps = int(state.get("max_steps", 3))
    if attempt < max_steps:
        return "write_code"
    return "handle_error"
