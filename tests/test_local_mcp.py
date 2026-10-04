"""Server jobs call tool handlers in process, on the server loop when it is known."""
import asyncio
import threading

from fastapi import HTTPException

from services.local_mcp import LocalMcp


def test_handlers_answer_like_mcp_tools_and_errors_keep_their_code():
    async def asynchronous(arguments):
        return {"result": arguments["input"]["value"] * 2}

    async def refusing(_arguments):
        raise HTTPException(409, {"code": "intent_conflict", "message": "used"})

    tools = LocalMcp(lambda: {"double": asynchronous, "plain": lambda arguments: {"ok": True}, "refuse": refusing})
    assert tools.call("double", {"input": {"value": 4}}) == {"result": 8}
    assert tools.call("plain", {}) == {"ok": True}
    assert tools.call("refuse", {}) == {"_is_error": True, "error": {"code": "intent_conflict", "message": "used", "status": 409}}
    assert tools.call("missing", {})["error"]["code"] == "unknown_tool"


def test_coroutines_run_on_the_bound_server_loop_from_a_worker_thread():
    seen = {}

    async def where(_arguments):
        seen["loop"] = asyncio.get_running_loop()
        return {"ok": True}

    tools = LocalMcp(lambda: {"where": where})
    loop = asyncio.new_event_loop()
    runner = threading.Thread(target=loop.run_forever, daemon=True)
    runner.start()
    try:
        tools.bind_loop(loop)
        result = {}
        worker = threading.Thread(target=lambda: result.update(tools.call("where", {})))
        worker.start()
        worker.join(5)
        assert result == {"ok": True} and seen["loop"] is loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        runner.join(5)
        loop.close()
