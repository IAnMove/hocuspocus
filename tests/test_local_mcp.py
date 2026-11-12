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


def test_legacy_tools_are_adapted_like_an_mcp_client_through_the_router(tmp_path):
    """The production runner polls ``status`` and submits ``generate`` in process. ``get_status(job_id)`` takes the
    id, not the arguments object; without the router's adaptation the call raised TypeError (unhashable dict)."""
    from routers.wangp_mcp import create_wangp_mcp_router

    jobs = {"j1": {"status": "running"}}
    submitted = []

    def get_status(job_id: str):
        return {"job_id": job_id, **jobs[job_id]}

    async def generate(request):
        submitted.append(await request.json())
        return {"job_id": "j2", "status": "queued"}

    async def operation(arguments):
        return {"echo": arguments}

    handlers = {"status": get_status, "generate": generate, "jobs.peek": operation}
    tools = LocalMcp(lambda: handlers)
    create_wangp_mcp_router(handlers=handlers, journal_path=tmp_path / "requests.db", token_getter=lambda: "t", local_mcp=tools,
                            command_operations=[{"name": "jobs.peek", "version": 1, "mutation": False,
                                                 "inputSchema": {"type": "object"}}])
    assert tools.call("status", {"job_id": "j1"}) == {"job_id": "j1", "status": "running"}
    request = {"request_id": "piece-clip-1", "params": {"generation_mode": "video", "prompt": "a dance"}}
    first = tools.call("generate", request)
    assert first["job_id"] == "j2" and tools.call("generate", request) == first and len(submitted) == 1, "the journal replays"
    assert tools.call("jobs.peek", {"anything": 1}) == {"echo": {"anything": 1}}, "operations keep their arguments as sent"
    assert tools.call("status", {})["error"]["code"] == "invalid_command"
    bare = LocalMcp(lambda: handlers)
    try:
        bare.call("status", {"job_id": "j1"})
        raise AssertionError("a plain handler call cannot adapt status")
    except TypeError:
        pass
