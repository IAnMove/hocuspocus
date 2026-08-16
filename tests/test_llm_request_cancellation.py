"""Focused CANCEL-01 coverage for per-job streaming request aborts."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import llm_service  # noqa: E402
from services.task_manager import (  # noqa: E402
    CancellationToken,
    TaskRegistry,
    forget_task_registry,
    get_cancellation_token,
    task_context_scope,
)


class _BlockingResponse:
    status_code = 200
    text = ""

    def __init__(self, *, release: threading.Event | None = None) -> None:
        self.started = threading.Event()
        self.closed = threading.Event()
        self.release = release

    def raise_for_status(self):
        return None

    def close(self):
        self.closed.set()

    def iter_lines(self, **_kwargs):
        self.started.set()
        if self.release is None:
            self.closed.wait(2)
        else:
            while not self.release.wait(0.01):
                if self.closed.is_set():
                    return
        if self.closed.is_set():
            return
        yield 'data: {"choices":[{"delta":{"content":"kept"}}]}'
        yield "data: [DONE]"


class TestLlmRequestCancellation(unittest.TestCase):
    def setUp(self):
        self.original = {
            "provider": llm_service._provider,
            "remote_url": llm_service._remote_url,
            "model_id": llm_service._model_id,
            "device": llm_service._device,
            "vision": llm_service._vision_available,
        }
        llm_service._provider = "remote"
        llm_service._remote_url = "http://127.0.0.1:1234"
        llm_service._model_id = "fake-model"
        llm_service._device = "cpu"
        llm_service._vision_available = False

    def tearDown(self):
        llm_service._provider = self.original["provider"]
        llm_service._remote_url = self.original["remote_url"]
        llm_service._model_id = self.original["model_id"]
        llm_service._device = self.original["device"]
        llm_service._vision_available = self.original["vision"]

    def _run(self, response, token, errors, results):
        watcher = llm_service._watch_response_for_cancellation(response, token, "fake")
        try:
            chunks = []
            for line in response.iter_lines():
                llm_service._raise_if_token_cancelled(
                    token,
                    "fake",
                    abort_supported=bool(watcher and watcher[2].get("abort_supported")),
                )
                chunks.append(line)
            llm_service._raise_if_token_cancelled(
                token,
                "fake",
                abort_supported=bool(watcher and watcher[2].get("abort_supported")),
            )
            results.append("kept" if chunks else "")
        except BaseException as exc:  # preserve the assertion in the caller thread
            errors.append(exc)
        finally:
            llm_service._stop_response_cancellation_watcher(watcher)

    def test_cancel_closes_only_the_active_job_stream(self):
        first = _BlockingResponse()
        release_second = threading.Event()
        second = _BlockingResponse(release=release_second)
        cancel_token = CancellationToken()
        other_token = CancellationToken()
        errors = []
        results = []

        cancelled_thread = threading.Thread(
            target=self._run,
            args=(first, cancel_token, errors, results),
            daemon=True,
        )
        other_thread = threading.Thread(
            target=self._run,
            args=(second, other_token, errors, results),
            daemon=True,
        )
        cancelled_thread.start()
        other_thread.start()
        self.assertTrue(first.started.wait(1))
        self.assertTrue(second.started.wait(1))
        cancel_token.cancel("user requested cancellation")
        cancelled_thread.join(1)
        self.assertFalse(cancelled_thread.is_alive())
        self.assertTrue(other_thread.is_alive())
        self.assertTrue(first.closed.is_set())
        self.assertFalse(second.closed.is_set())
        release_second.set()
        other_thread.join(1)

        self.assertFalse(other_thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], llm_service.LLMRequestCancelled)
        self.assertTrue(errors[0].abort_supported)
        self.assertEqual(results, ["kept"])

    def test_non_abortable_response_reports_safe_boundary_limitation(self):
        release = threading.Event()
        response = _BlockingResponse(release=release)
        response.close = None
        token = CancellationToken()
        errors = []
        results = []
        worker = threading.Thread(
            target=self._run,
            args=(response, token, errors, results),
            daemon=True,
        )
        worker.start()
        self.assertTrue(response.started.wait(1))
        token.cancel("user requested cancellation")
        time.sleep(0.08)
        self.assertTrue(worker.is_alive())
        release.set()
        worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], llm_service.LLMRequestCancelled)
        self.assertFalse(errors[0].abort_supported)
        self.assertIn("could not be aborted", str(errors[0]))

    def test_public_streaming_client_propagates_token_to_http_response(self):
        response = _BlockingResponse()
        token = CancellationToken()
        errors = []
        results = []

        with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
            llm_service.requests, "post", return_value=response,
        ):
            worker = threading.Thread(
                target=self._run_public,
                args=(token, errors, results),
                daemon=True,
            )
            worker.start()
            self.assertTrue(response.started.wait(1))
            token.cancel("user requested cancellation")
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(response.closed.is_set())
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], llm_service.LLMRequestCancelled)

    def _run_public(self, token, errors, results):
        try:
            results.append(llm_service.generate_streaming(
                prompt="cancel public stream",
                max_new_tokens=8,
                cancellation_token=token,
            ))
        except BaseException as exc:
            errors.append(exc)

    def test_registry_cancellation_is_scoped_to_one_job(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = TaskRegistry(workspace, interrupt_stale=False)
            registry.create(id="job-a", status="running", phase="running")
            registry.create(id="job-b", status="running", phase="running")
            token_a = get_cancellation_token(workspace, "job-a")
            token_b = get_cancellation_token(workspace, "job-b")
            registry.update("job-a", status="running", phase="cancelling", force=True)
            self.assertTrue(token_a.is_cancelled())
            self.assertFalse(token_b.is_cancelled())

    def test_task_context_connects_registry_cancel_to_the_active_http_stream(self):
        response = _BlockingResponse()
        errors = []
        results = []
        with tempfile.TemporaryDirectory() as workspace:
            registry = TaskRegistry(workspace, interrupt_stale=False)
            registry.create(id="job-context", status="running", phase="running")

            def run_in_context():
                try:
                    with task_context_scope(
                        task_id="job-context",
                        workspace_dir=workspace,
                    ):
                        results.append(llm_service.generate_streaming(
                            prompt="cancel implicit stream",
                            max_new_tokens=8,
                        ))
                except BaseException as exc:
                    errors.append(exc)

            with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
                llm_service.requests, "post", return_value=response,
            ):
                worker = threading.Thread(target=run_in_context, daemon=True)
                worker.start()
                self.assertTrue(response.started.wait(1))
                registry.update(
                    "job-context",
                    status="running",
                    phase="cancelling",
                    force=True,
                )
                worker.join(1)

            self.assertFalse(worker.is_alive())
            self.assertTrue(response.closed.is_set())
            self.assertEqual(results, [])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], llm_service.LLMRequestCancelled)
            forget_task_registry(workspace)

    def test_ordinary_tasks_do_not_allocate_tokens_and_terminal_cleanup_releases_one(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = TaskRegistry(workspace, interrupt_stale=False)
            registry.create(id="job-token-life", status="running", phase="running")
            from services import task_manager

            key = task_manager._cancellation_token_key(workspace, "job-token-life")
            self.assertNotIn(key, task_manager._cancellation_tokens)
            token = get_cancellation_token(workspace, "job-token-life")
            self.assertIn(key, task_manager._cancellation_tokens)
            self.assertFalse(token.is_cancelled())
            registry.update("job-token-life", status="completed", phase="completed")
            self.assertNotIn(key, task_manager._cancellation_tokens)

    def test_public_cancel_message_distinguishes_abort_from_safe_boundary(self):
        source = Path(_APP_DIR, "launch.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_planning_cancel_message"
        )
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "launch.py", "exec"), namespace)

        aborted = namespace["_planning_cancel_message"]("Story generation", True)
        unsupported = namespace["_planning_cancel_message"]("Story generation", False)
        self.assertIn("closed immediately", aborted)
        self.assertIn("could not abort", unsupported)
        self.assertIn("safe boundary", unsupported)


if __name__ == "__main__":
    unittest.main()
