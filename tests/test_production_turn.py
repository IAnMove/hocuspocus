"""Productions on one instance take the GPU one at a time, in the order they were sent."""
import threading
import time

from services.production_control import request_cancel
from services.production_turn import queued, run_in_turn


class Piece:
    ws = "w"

    def __init__(self, production_id):
        self.id, self.state, self.lines = production_id, {}, []

    def log(self, line):
        self.lines.append(line)

    def save(self):
        pass


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_a_second_production_waits_queued_until_the_first_is_done():
    first, second, order = Piece("one"), Piece("two"), []
    release = threading.Event()

    def busy():
        order.append("one starts")
        release.wait(5)
        order.append("one ends")

    a = threading.Thread(target=run_in_turn, args=(first, busy), kwargs={"poll": 0.01})
    a.start()
    wait_for(lambda: order == ["one starts"])
    b = threading.Thread(target=run_in_turn, args=(second, lambda: order.append("two runs")), kwargs={"poll": 0.01})
    b.start()
    wait_for(lambda: second.state.get("status") == "queued")
    assert second.lines == ["queued behind one"] and queued() == ["w/one", "w/two"]
    release.set()
    a.join(5)
    b.join(5)
    assert order == ["one starts", "one ends", "two runs"]
    assert queued() == []


def test_a_cancel_while_queued_never_runs_and_frees_the_place():
    first, second, ran = Piece("long"), Piece("waiting"), []
    release = threading.Event()
    a = threading.Thread(target=run_in_turn, args=(first, lambda: release.wait(5)), kwargs={"poll": 0.01})
    a.start()
    wait_for(lambda: queued() == ["w/long"])
    b = threading.Thread(target=run_in_turn, args=(second, lambda: ran.append(True)), kwargs={"poll": 0.01})
    b.start()
    wait_for(lambda: second.state.get("status") == "queued")
    lock = threading.Lock()
    assert request_cancel("w", "waiting", {"w/waiting": b}, lock)
    b.join(5)
    assert second.state["status"] == "cancelled" and ran == []
    assert queued() == ["w/long"]
    release.set()
    a.join(5)


def test_a_failing_production_still_hands_on_the_turn():
    def boom():
        raise RuntimeError("stage failed")

    try:
        run_in_turn(Piece("bad"), boom)
    except RuntimeError:
        pass
    assert queued() == []
    done = []
    run_in_turn(Piece("next"), lambda: done.append(True))
    assert done == [True]
