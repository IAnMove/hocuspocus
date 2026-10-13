"""Move-aware code-health ratchet: the guard stays strict about real growth.

The scenarios repeat the refactor design's ratchet experiments: A, a verbatim
move of a complexity-131 route out of launch; B, a moved function over 1,200
lines; C, a small move; D, a dated waiver; E, a move into a folder the
ratchet does not measure. Each one builds a small git repository, measures
it with the real ``collect()`` before and after the change, and runs the real
``compare()``. See docs/development/CODE_HEALTH.md, "Moves, splits and
unmeasured code".
"""
import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("code_health", ROOT / "scripts" / "code_health.py")
code_health = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = code_health
SPEC.loader.exec_module(code_health)

LAUNCH = "app/launch.py"


def branchy(name, decisions, *, decorator="", docstring="", start=0, body_extra="", lines_per_branch=1):
    """A function with exactly ``decisions`` if-statements (complexity decisions + 1)."""
    out = [decorator] if decorator else []
    out.append(f"def {name}(body, value=0):")
    if docstring:
        out.append(f'    """{docstring}"""')
    for index in range(start, start + decisions):
        out.append(f"    if body.get('k{index}'):")
        out.append(f"        value += {index}")
        out.extend("        value -= 0" for _ in range(lines_per_branch - 1))
    if body_extra:
        out.append(body_extra)
    out.append("    return value")
    return "\n".join(out) + "\n"


def small_helpers():
    return textwrap.dedent('''
        def list_favorites(store):
            return sorted(store)


        def toggle_favorite(store, key):
            if key in store:
                store.remove(key)
            else:
                store.add(key)
            return store
    ''')


class _Repo:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._git("init", "-q")
        self._git("config", "user.email", "ratchet@example.invalid")
        self._git("config", "user.name", "ratchet")

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.folder), *args], check=True, capture_output=True)

    def write(self, files: dict) -> None:
        for relative, source in files.items():
            path = self.folder / relative
            if source is None:
                self._git("rm", "-q", relative)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        # Like the design's probes: new files are tracked with intent-to-add.
        self._git("add", "-N", ".")

    def commit(self) -> None:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")

    def report(self) -> dict:
        with mock.patch.object(code_health, "ROOT", self.folder), \
                mock.patch.object(code_health, "_ui_complexity", return_value=[]):
            return code_health.collect(require_ui=False)


def measure(base_files: dict, changes: dict) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory(prefix="ratchet-moves-") as temporary:
        repo = _Repo(Path(temporary))
        repo.write(base_files)
        repo.commit()
        base = repo.report()
        repo.write(changes)
        return repo.report(), base


def run(base_files: dict, changes: dict) -> tuple[list[str], list[str], dict, dict]:
    current, base = measure(base_files, changes)
    warnings, failures = code_health.compare(current, base)
    return warnings, failures, current, base


# 128 if-statements plus a filtered comprehension (2 decisions): complexity 131,
# like director_comic_plan in experiment A.
COMIC_PLAN = branchy(
    "director_comic_plan", 128,
    decorator='@app.post("/api/v1/director/comic/plan")',
    docstring="Create a strict, editable comic plan without generating images.",
    body_extra="    pages = [item for item in body.get('pages', []) if item]\n    value += len(pages)",
)
# A verbatim move into a router: the decorator becomes the router's, a comment
# appears and the docstring is reworded. None of that is logic.
COMIC_PLAN_MOVED = "# Moved from launch.\n" + COMIC_PLAN.replace(
    '@app.post("/api/v1/director/comic/plan")', '@router.post("/api/v1/director/comic/plan")',
).replace("Create a strict, editable comic plan", "Create an editable comic plan")


def launch_with(*functions):
    return "\n\n".join(("import json\n", small_helpers(), *functions))


def split_case(*, own_before, own_after, pieces):
    """``_run_generation`` before and after carving out ``pieces`` blocks of 15 decisions."""
    def own(count):
        return "".join(f"    if body.get('own{j}'):\n        value += 1\n" for j in range(count))

    blocks = {
        k: "".join(f"    if body.get('s{k}_{j}'):\n        value += {j}\n" for j in range(15))
        for k in range(pieces)
    }
    before = (
        "def _run_generation(body, value=0):\n" + own(own_before)
        + "".join(blocks.values()) + "    return value\n"
    )
    after = (
        "def _run_generation(body, value=0):\n" + own(own_after)
        + "".join(f"    value = _run_generation_stage{k}(body, value)\n" for k in blocks)
        + "    return value\n"
    )
    carved = [
        f"def _run_generation_stage{k}(body, value):\n" + block + "    return value\n"
        for k, block in blocks.items()
    ]
    return {LAUNCH: launch_with(before)}, {LAUNCH: launch_with(after, *carved)}


class MoveAwareRatchetTests(unittest.TestCase):
    def assertNoFailures(self, failures):
        self.assertEqual(failures, [], "\n".join(failures))

    def test_a_verbatim_move_of_a_cx131_function_passes_and_is_reported(self):
        base = {LAUNCH: launch_with(COMIC_PLAN)}
        warnings, failures, current, old = run(base, {
            LAUNCH: launch_with(),
            "app/routers/comic_plan.py": "from fastapi import APIRouter\nrouter = APIRouter()\n\n\n" + COMIC_PLAN_MOVED,
        })
        self.assertEqual(current["complexity_hotspots"]["app/routers/comic_plan.py"], 131)
        self.assertNoFailures(failures)
        self.assertIn(
            "moved: director_comic_plan (complexity 131) from app/launch.py "
            "to app/routers/comic_plan.py",
            warnings,
        )
        # The same move against a base report without fingerprints (written by
        # the analyzer before this change) gets no credit: strict as before.
        del old["fingerprints"]
        _, strict = code_health.compare(current, old)
        self.assertTrue(any(item.startswith(
            "new complexity hotspot app/routers/comic_plan.py is 131; limit is 25"
        ) for item in strict), strict)

    def test_a_move_where_complexity_went_up_fails(self):
        raised = COMIC_PLAN_MOVED.replace(
            "    return value\n", "    if body.get('extra'):\n        value += 1\n    return value\n",
        )
        _, failures, current, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            LAUNCH: launch_with(), "app/routers/comic_plan.py": raised,
        })
        self.assertEqual(current["complexity_hotspots"]["app/routers/comic_plan.py"], 132)
        self.assertEqual(len(failures), 1, failures)
        self.assertTrue(failures[0].startswith(
            "new complexity hotspot app/routers/comic_plan.py is 132; limit is 25"
        ), failures)
        self.assertIn("director_comic_plan (132) has the name of base app/launch.py (131)", failures[0])
        self.assertIn("different code", failures[0])

    def test_same_name_with_new_logic_is_new_code_and_fails(self):
        # Same name, same complexity (131), different logic: not a move.
        rewritten = COMIC_PLAN_MOVED.replace("value += 7\n", "value *= 7\n")
        warnings, failures, current, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            LAUNCH: launch_with(), "app/routers/comic_plan.py": rewritten,
        })
        self.assertEqual(current["complexity_hotspots"]["app/routers/comic_plan.py"], 131)
        self.assertFalse([item for item in warnings if item.startswith("moved: ")], warnings)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("new complexity hotspot app/routers/comic_plan.py is 131", failures[0])
        self.assertIn("different code, so it counts as new", failures[0])

    def test_a_copy_is_not_a_move(self):
        _, failures, _, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            "app/routers/comic_plan.py": COMIC_PLAN_MOVED,
        })
        self.assertTrue(any(
            "new complexity hotspot app/routers/comic_plan.py" in item and "is a copy" in item
            for item in failures
        ), failures)

    def test_a_move_into_an_existing_router_file_passes(self):
        router = "def existing(body):\n" + "".join(
            f"    if body.get({index}):\n        return {index}\n" for index in range(19)
        ) + "    return None\n"
        warnings, failures, _, old = run(
            {LAUNCH: launch_with(COMIC_PLAN), "app/routers/comics.py": router},
            {LAUNCH: launch_with(), "app/routers/comics.py": router + "\n\n" + COMIC_PLAN_MOVED},
        )
        self.assertEqual(old["complexity_hotspots"]["app/routers/comics.py"], 20)
        self.assertNoFailures(failures)
        self.assertTrue(any(item.startswith("moved: director_comic_plan") for item in warnings), warnings)

    def test_b_moved_function_over_1200_lines_still_fails_the_line_rule(self):
        runner = branchy("_run_generation", 355, lines_per_branch=4)
        self.assertGreater(len(runner.splitlines()), 1_200)
        warnings, failures, _, _ = run({LAUNCH: launch_with(runner)}, {
            LAUNCH: launch_with(), "app/services/generation_runner.py": runner,
        })
        self.assertIn(
            "moved: _run_generation (complexity 356) from app/launch.py "
            "to app/services/generation_runner.py",
            warnings,
        )
        self.assertEqual(len(failures), 1, failures)
        self.assertRegex(failures[0], r"^new hotspot app/services/generation_runner.py has 1,\d{3} lines; limit is 1,200$")
        waivers = [
            {"path": "app/services/generation_runner.py", "rule": rule, "reason": "probe",
             "owner": "probe", "issue": "#probe", "expires": "2999-12-31"}
            for rule in sorted(code_health.WAIVABLE_RULES)
        ]
        _, kept = code_health.apply_exceptions(failures, [], waivers)
        self.assertEqual(kept, failures, "the 1,200-line rule is not waivable")

    def test_c_small_move_into_a_router_passes(self):
        _, failures, _, _ = run(
            {LAUNCH: launch_with(COMIC_PLAN)},
            {LAUNCH: "import json\n\n\n" + COMIC_PLAN, "app/routers/favorites.py": small_helpers()},
        )
        self.assertNoFailures(failures)

    def test_d_a_dated_waiver_still_covers_a_new_hotspot_that_is_not_a_move(self):
        rewritten = COMIC_PLAN_MOVED.replace("value += 7\n", "value *= 7\n")
        warnings, failures, _, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            LAUNCH: launch_with(), "app/routers/comic_plan.py": rewritten,
        })
        waiver = {"path": "app/routers/comic_plan.py", "rule": "complexity_hotspot", "reason": "probe",
                  "owner": "probe", "issue": "#probe", "expires": "2999-12-31"}
        warnings, kept = code_health.apply_exceptions(failures, warnings, [waiver])
        self.assertEqual(kept, [])
        self.assertTrue(any(item.startswith("waived complexity_hotspot") for item in warnings))

    def test_a_waiver_for_the_base_file_does_not_cover_a_new_file(self):
        # The failure text names the base file; a waiver for that file must
        # not waive the new hotspot in another file.
        rewritten = COMIC_PLAN_MOVED.replace("value += 7\n", "value *= 7\n")
        waiver = {"path": LAUNCH, "rule": "complexity_hotspot", "reason": "probe",
                  "owner": "probe", "issue": "#probe", "expires": "2999-12-31"}
        for changes, reason in (
            ({LAUNCH: launch_with(), "app/routers/comic_plan.py": rewritten}, "different code"),
            ({"app/routers/comic_plan.py": COMIC_PLAN_MOVED}, "is a copy"),
        ):
            _, failures, _, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, changes)
            self.assertTrue(any(LAUNCH in item and reason in item for item in failures), failures)
            warnings, kept = code_health.apply_exceptions(failures, [], [waiver])
            self.assertEqual(kept, failures)
            self.assertEqual(warnings, [])

    def test_e_a_new_file_in_an_unmeasured_folder_fails(self):
        _, failures, current, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            LAUNCH: launch_with(), "app/features/comics/probe_plan.py": COMIC_PLAN_MOVED,
        })
        self.assertEqual(current["unmeasured"]["paths"], ["app/features/comics/probe_plan.py"])
        self.assertEqual(len(failures), 1, failures)
        self.assertTrue(failures[0].startswith("unmeasured product code app/features/comics/probe_plan.py"), failures)

    def test_vendored_engine_code_stays_out_of_scope(self):
        _, failures, current, _ = run({LAUNCH: launch_with(COMIC_PLAN)}, {
            "app/models/new_engine/pipeline.py": COMIC_PLAN, "app/shared/utils/extra.py": small_helpers(),
        })
        self.assertEqual(current["unmeasured"]["paths"], [])
        self.assertNoFailures(failures)

    def test_split_whose_parent_did_not_drop_enough_fails_the_budget(self):
        base = {LAUNCH: launch_with(branchy("_run_generation", 120))}
        children = [branchy(f"_run_generation_stage{k}", 15, start=1000 + 100 * k) for k in range(6)]
        # The parent loses 20 decisions; the six pieces hold 90.
        warnings, failures, _, _ = run(base, {LAUNCH: launch_with(branchy("_run_generation", 100), *children)})
        self.assertEqual(failures, ["high-complexity function count grew by 6; budget is 5"])
        self.assertIn(
            "split not credited: " + ", ".join(f"_run_generation_stage{k} (16)" for k in range(6))
            + " named after _run_generation, but _run_generation dropped 20 (121 -> 101) "
            "and their decisions sum to 90",
            warnings,
        )
        # Pieces next to an untouched parent get no credit either.
        _, failures, _, _ = run(base, {LAUNCH: launch_with(branchy("_run_generation", 120), *children)})
        self.assertEqual(failures, ["high-complexity function count grew by 6; budget is 5"])
        # A parent that falls below 15 is still measured: here it gained one
        # decision of its own during the split, so the pieces are not credited.
        warnings, failures, _, _ = run(*split_case(own_before=12, own_after=13, pieces=7))
        self.assertEqual(failures, ["high-complexity function count grew by 6; budget is 5"])
        self.assertTrue(any("_run_generation dropped 104 (118 -> 14)" in item for item in warnings), warnings)

    def test_valid_split_passes(self):
        # The parent stays complex: six pieces of 15 decisions each.
        warnings, failures, current, old = run(*split_case(own_before=15, own_after=15, pieces=6))
        self.assertEqual(current["summary"]["complex_functions"] - old["summary"]["complex_functions"], 6)
        self.assertNoFailures(failures)
        self.assertIn(
            "split: " + ", ".join(f"_run_generation_stage{k} (16)" for k in range(6))
            + " carved out of _run_generation (106 -> 16); not counted against the complex-function budget",
            warnings,
        )
        # A same-name function in another file is in both reports, so an
        # exact fit (drop 90, decisions 90) still holds.
        base, changed = split_case(own_before=15, own_after=15, pieces=6)
        sibling = {"app/services/other_runner.py": "def _run_generation(flag):\n    if flag:\n        return 1\n    return 0\n"}
        _, failures, _, _ = run({**base, **sibling}, changed)
        self.assertNoFailures(failures)
        # The parent falls below 15: seven pieces, growth 7 - 1 = 6.
        warnings, failures, current, old = run(*split_case(own_before=1, own_after=1, pieces=7))
        self.assertEqual(current["summary"]["complex_functions"] - old["summary"]["complex_functions"], 6)
        self.assertNoFailures(failures)
        self.assertTrue(any("carved out of _run_generation (107 -> 2)" in item for item in warnings), warnings)
        # Functions that are not carved out of anything still count.
        base, changed = split_case(own_before=15, own_after=15, pieces=6)
        unrelated = [branchy(f"brand_new_{k}", 15, start=5000 + 100 * k) for k in range(6)]
        changed[LAUNCH] += "\n\n" + "\n\n".join(unrelated)
        _, failures, _, _ = run(base, changed)
        self.assertEqual(
            failures,
            ["high-complexity function count grew by 12 (6 after 6 credited split pieces); budget is 5"],
        )


class RecordMatchingTests(unittest.TestCase):
    """compare() on hand-built reports: UI records, exclusions and old bases."""

    @staticmethod
    def report(records, hotspots, *, unmeasured=None):
        return {
            "summary": {"production_lines": 10_000, "complex_functions": len(records), "max_complexity": 200},
            "complexity_hotspots": hotspots,
            "fingerprints": records,
            **({"unmeasured": unmeasured} if unmeasured is not None else {}),
        }

    @staticmethod
    def ui(path, name, complexity, line=10):
        return {"path": path, "name": name, "line": line, "complexity": complexity, "hash": None}

    def test_ui_move_needs_the_same_name_and_no_higher_complexity(self):
        store, slice_ = "ui/src/stores/appStore.ts", "ui/src/stores/directorPipelineSlice.ts"
        base = self.report([self.ui(store, "startDirectorPipeline", 105)], {store: 105})
        moved = self.report(
            [self.ui(store, "other", 15), self.ui(slice_, "startDirectorPipeline", 105)],
            {store: 15, slice_: 105},
        )
        warnings, failures = code_health.compare(moved, base)
        self.assertEqual(failures, [])
        self.assertIn(f"moved: startDirectorPipeline (complexity 105) from {store} to {slice_}", warnings)

        rose = self.report([self.ui(slice_, "startDirectorPipeline", 106)], {slice_: 106})
        _, failures = code_health.compare(rose, base)
        self.assertEqual(len(failures), 1)
        self.assertIn("rose above its base ceiling", failures[0])

        anonymous = self.report([self.ui(slice_, "", 105)], {slice_: 105})
        _, failures = code_health.compare(anonymous, base)
        self.assertIn("has no name to match", failures[0])

    def test_a_move_does_not_cover_another_function_on_the_same_line(self):
        store, slice_ = "ui/src/stores/appStore.ts", "ui/src/stores/pipelineSlice.ts"
        base = self.report([self.ui(store, "startDirectorPipeline", 105)], {store: 105})
        # The moved method and an inner anonymous arrow start on the same line.
        moved = self.report(
            [self.ui(slice_, "startDirectorPipeline", 105, line=7), self.ui(slice_, "", 31, line=7)],
            {slice_: 105},
        )
        warnings, failures = code_health.compare(moved, base)
        self.assertIn(f"moved: startDirectorPipeline (complexity 105) from {store} to {slice_}", warnings)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("an anonymous function (31) has no name to match", failures[0])

    def test_ui_split_pieces_follow_the_camel_case_prefix(self):
        store = "ui/src/stores/appStore.ts"
        base = self.report([self.ui(store, "startGeneration", 347)], {store: 347})
        pieces = [self.ui("ui/src/features/studio/store/submit.ts", f"startGenerationPart{k}", 20, line=k) for k in range(6)]
        split = self.report([self.ui(store, "startGeneration", 347 - 6 * 19), *pieces], {store: 233})
        split["summary"]["complex_functions"] = 7
        warnings, failures = code_health.compare(split, base)
        self.assertEqual(failures, [])
        self.assertTrue(any(item.startswith("split: startGenerationPart0 (20)") for item in warnings))
        self.assertFalse(code_health._carved_from("startGenerations", "startGeneration"))
        self.assertTrue(code_health._carved_from("_run_generation.prepare", "_run_generation"))
        self.assertTrue(code_health._carved_from("Runner._run_generation_finalize", "_run_generation"))

    def test_exclusion_lists_cannot_grow_versus_the_base(self):
        scope = {"paths": [], "vendor_prefixes": ["app/models/"], "allowed": ["app/setup.py"]}
        base = self.report([], {}, unmeasured={**scope, "paths": ["app/setup.py"]})
        grown = self.report([], {}, unmeasured={
            "paths": ["app/setup.py", "app/features/x.py"],
            "vendor_prefixes": ["app/models/", "app/features/"],
            "allowed": ["app/setup.py", "app/features/x.py"],
        })
        _, failures = code_health.compare(grown, base)
        self.assertEqual(
            failures,
            [
                "unmeasured product code app/features/x.py is new versus the base",
                (
                    "unmeasured exclusions (vendor_prefixes) grew versus the base: app/features/; "
                    "code outside the ratchet needs owner review"
                ),
                (
                    "unmeasured exclusions (allowed) grew versus the base: app/features/x.py; "
                    "code outside the ratchet needs owner review"
                ),
            ],
        )

    def test_today_tree_passes_the_unmeasured_guard(self):
        tracked = code_health._tracked_files()
        paths = code_health._unmeasured_product(tracked)
        # Exactly the baseline: nothing unlisted and no stale entries.
        self.assertEqual(paths, sorted(code_health.UNMEASURED_BASELINE))
        scope = {
            "paths": paths,
            "vendor_prefixes": list(code_health.UNMEASURED_VENDOR_PREFIXES),
            "allowed": list(code_health.UNMEASURED_BASELINE),
        }
        self.assertEqual(code_health._unmeasured_findings({"unmeasured": scope}, {"unmeasured": scope}), ([], []))
        self.assertTrue(code_health._unmeasured_findings(
            {"unmeasured": {**scope, "paths": [*paths, "app/features/comics/plan.py"]}}, {"unmeasured": scope},
        )[1])

    def test_today_tree_compared_with_itself_has_no_moves_or_failures(self):
        tracked = code_health._tracked_files()
        product = sorted(path for path in tracked if code_health._is_product(path) and path.endswith(".py"))
        functions = code_health._python_complexity(product)
        records = code_health._fingerprint_records(functions)
        self.assertTrue(records)
        self.assertTrue(all(record["hash"] for record in records if record["complexity"] >= 15))
        hotspots = {}
        for item in functions:
            hotspots[item.path] = max(hotspots.get(item.path, 0), item.complexity)
        report = self.report(records, {path: value for path, value in hotspots.items() if value >= 15})
        self.assertEqual(code_health.verified_moves(report, report), {})
        self.assertEqual(code_health.compare(report, report), ([], []))
