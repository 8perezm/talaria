# agent_core.py — thin turn orchestrator over llm.callLLMWithTools (Phase 1).
# MicroPython-safe: utf-8 only, no new imports at module level, tiny wrapper.
# No loop-logic fork: the iteration budget is enforced inside llm.py.


def clampIters(v, default=3):
    try:
        n = int(v)
    except Exception:
        return default
    if n < 1:
        return 1
    if n > 5:
        return 5
    return n


def runTurn(userMsg, history=None, out=None, max_iters=None):
    """Run one agentic turn. Returns the reply string (or 'ERROR: ...').

    max_iters caps tool-call rounds (default from config.agent_max_iters,
    clamped 1..5). max_iters=1 stops after the first tool round and returns
    the results-summary path from llm.py.
    """
    try:
        import delegate as _dlg
        _dlg.begin_turn()
    except Exception:
        pass
    import config
    import llm
    if max_iters is None:
        try:
            max_iters = int(config.agent_max_iters)
        except Exception:
            max_iters = 3
    max_iters = clampIters(max_iters, 3)
    return llm.callLLMWithTools(userMsg, history, out, max_iters)
