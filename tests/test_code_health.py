import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("code_health", ROOT / "scripts" / "code_health.py")
code_health = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = code_health
SPEC.loader.exec_module(code_health)


class CodeHealthTests(unittest.TestCase):
    def test_python_complexity_does_not_charge_nested_function_to_parent(self):
        source = """
def outer(a, b):
    if a and b:
        return True
    def inner(value):
        for item in value:
            if item:
                return item
        return None
    return inner([])
"""
        collector = code_health._PythonFunctionCollector("sample.py")
        collector.visit(ast.parse(source))
        values = {metric.name: metric.complexity for metric in collector.metrics}
        self.assertEqual(values, {"outer": 3, "outer.inner": 3})

    def test_product_scope_excludes_tests_and_vendored_models(self):
        self.assertTrue(code_health._is_product("app/_launch_runtime.py"))
        self.assertTrue(code_health._is_product("app/services/example.py"))
        self.assertTrue(code_health._is_product("ui/src/App.tsx"))
        self.assertFalse(code_health._is_product("tests/test_example.py"))
        self.assertFalse(code_health._is_product("app/models/vendor/model.py"))
        self.assertFalse(code_health._is_product("ui/tests/App.test.tsx"))
        self.assertFalse(code_health._is_product("README.md"))
        self.assertFalse(code_health._is_product("docs/HOWUSEIT.md"))
        self.assertFalse(code_health._is_product("docs/character-kits/HOWUSEIT.md"))

    def test_ratchet_warns_on_small_growth_and_fails_on_large_growth(self):
        baseline = {
            "summary": {
                "production_lines": 100_000,
                "complex_functions": 10,
                "max_complexity": 30,
            },
            "hotspots": {"app/big.py": 10_000},
            "complexity_hotspots": {"app/big.py": 30},
        }
        small = {
            "summary": {
                "production_lines": 100_100,
                "complex_functions": 11,
                "max_complexity": 31,
            },
            "hotspots": {"app/big.py": 10_050},
            "complexity_hotspots": {"app/big.py": 31},
        }
        warnings, failures = code_health.compare(small, baseline)
        self.assertGreaterEqual(len(warnings), 3)
        self.assertEqual(failures, [])

        large = {
            "summary": {
                "production_lines": 104_000,
                "complex_functions": 16,
                "max_complexity": 34,
            },
            "hotspots": {"app/big.py": 10_400, "app/new_giant.py": 1_500},
            "complexity_hotspots": {"app/big.py": 36, "app/new_giant.py": 40},
        }
        _, failures = code_health.compare(large, baseline)
        self.assertGreaterEqual(len(failures), 5)

    def test_markdown_report_is_a_github_table(self):
        report = {
            "summary": {
                "production_lines": 10,
                "production_files": 2,
                "test_lines": 4,
                "functions_measured": 3,
                "complex_functions": 1,
                "max_complexity": 20,
            },
            "top_complexity": [{
                "path": "ui/src/App.tsx", "line": 1, "name": "App", "complexity": 20,
            }],
        }
        markdown = code_health._markdown_report(report, report, [], [])
        self.assertIn("<!-- code-health-report -->", markdown)
        self.assertIn("Quality score:", markdown)
        self.assertIn("Change vs comparison base:", markdown)
        self.assertIn("| Production LOC |", markdown)
        self.assertIn("**Ratchet passed.**", markdown)
        self.assertNotIn("**Ratchet not evaluated.**", markdown)

        preview = code_health._markdown_report(report)
        self.assertIn("**Ratchet not evaluated.**", preview)
        self.assertNotIn("**Ratchet passed.**", preview)
        self.assertNotIn("**Ratchet failed.**", preview)

        failed = code_health._markdown_report(report, report, [], ["new complexity hotspot ui/src/App.tsx is 40; limit is 25"])
        self.assertIn("**Ratchet failed.**", failed)
        self.assertIn("new complexity hotspot", failed)
        self.assertNotIn("**Ratchet passed.**", failed)
        self.assertNotIn("**Ratchet not evaluated.**", failed)

    def test_incomplete_baseline_is_not_a_pass(self):
        current = {
            "summary": {
                "production_lines": 10,
                "complex_functions": 1,
                "max_complexity": 10,
            },
        }
        warnings, failures = code_health.compare(current, {"summary": {}})
        self.assertEqual(warnings, [])
        self.assertTrue(any("incomplete" in item for item in failures))

    def test_missing_ui_measurement_fails_closed(self):
        summary = {
            "production_lines": 100,
            "complex_functions": 1,
            "max_complexity": 10,
        }
        current = {
            "summary": summary,
            "measurement": {"ui": "missing", "python": "complete"},
        }
        baseline = {
            "summary": summary,
            "measurement": {"ui": "complete", "python": "complete"},
        }
        _, failures = code_health.compare(current, baseline)
        self.assertTrue(any("not measured" in item or "disappeared" in item for item in failures))

    def test_policy_change_fails_closed(self):
        summary = {
            "production_lines": 100,
            "complex_functions": 1,
            "max_complexity": 10,
        }
        current = {
            "summary": summary,
            "policy_version": "code-health-policy-v2",
            "policy": {**code_health.POLICY, "complex_growth_budget": 99},
        }
        baseline = {
            "summary": summary,
            "policy_version": code_health.POLICY_VERSION,
            "policy": dict(code_health.POLICY),
        }
        _, failures = code_health.compare(current, baseline)
        self.assertTrue(any("policy changed" in item for item in failures))

    def test_excluding_a_still_present_product_file_fails(self):
        summary = {
            "production_lines": 100,
            "complex_functions": 1,
            "max_complexity": 10,
        }
        current = {
            "summary": summary,
            "product_paths": ["app/launch.py"],
        }
        baseline = {
            "summary": summary,
            "product_paths": ["app/launch.py", "app/wgp.py"],
        }
        _, failures = code_health.compare(current, baseline)
        self.assertTrue(any("product scope excluded" in item for item in failures))
        self.assertTrue(any("app/wgp.py" in item for item in failures))

    def test_empty_current_product_scope_fails_closed(self):
        summary = {
            "production_lines": 0,
            "complex_functions": 0,
            "max_complexity": 0,
        }
        current = {"summary": summary, "product_paths": []}
        baseline = {
            "summary": {
                "production_lines": 100,
                "complex_functions": 1,
                "max_complexity": 10,
            },
            "product_paths": ["app/launch.py"],
        }
        _, failures = code_health.compare(current, baseline)
        self.assertTrue(any("empty" in item for item in failures))

    def test_quality_score_gain_does_not_hide_loc_failure(self):
        baseline = {
            "summary": {
                "production_lines": 10_000,
                "complex_functions": 50,
                "max_complexity": 100,
            },
            "hotspots": {},
        }
        current = {
            "summary": {
                "production_lines": 20_000,
                "complex_functions": 10,
                "max_complexity": 40,
            },
            "hotspots": {},
        }
        _, failures = code_health.compare(current, baseline)
        self.assertTrue(any("production LOC grew" in item for item in failures))

    def test_exception_requires_full_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exceptions.json"
            path.write_text('[{"path": "app/foo.py", "rule": "hotspot_growth"}]\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                code_health.load_exceptions(path)

    def test_complete_exception_waives_matching_hotspot_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exceptions.json"
            path.write_text(
                json.dumps([{
                    "path": "app/big.py",
                    "rule": "hotspot_growth",
                    "reason": "cohesive extract in progress",
                    "owner": "IAnMove",
                    "issue": "https://github.com/IAnMove/hocuspocus/issues/1",
                    "expires": "2099-01-01",
                }]),
                encoding="utf-8",
            )
            exceptions = code_health.load_exceptions(path)
        warnings, failures = code_health.apply_exceptions(
            ["hotspot app/big.py grew 900 lines; budget is 75"],
            [],
            exceptions,
        )
        self.assertEqual(failures, [])
        self.assertTrue(any("waived hotspot_growth" in item for item in warnings))

    def test_line_count_reports_physical_and_non_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text("one\n\nthree\n", encoding="utf-8")
            self.assertEqual(code_health._line_count(path), (3, 2))




class ReleaseIntegrationHealthTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        import code_health_integration
        self.release = code_health_integration
        self.patch = patch

    def report(self, lines=100_000, complex_count=100, file_complexity=20):
        return {
            "policy": dict(code_health.POLICY),
            "measurement": {"ui": "complete"},
            "product_paths": ["app/services/example.py"],
            "summary": {
                "production_lines": lines, "complex_functions": complex_count,
                "max_complexity": 50, "functions_measured": 1000,
            },
            "hotspots": {},
            "complexity_hotspots": {"app/services/example.py": file_complexity},
        }

    def compare(self, *reports):
        return self.release.compare_release(
            reports[-1], reports[0], [str(i) for i in range(len(reports))], list(reports),
        )

    def test_cumulative_growth_passes_only_when_each_integration_fits(self):
        first = self.report()
        middle = self.report(103_000, 105)
        last = self.report(106_000, 110)
        _, ordinary_failures = code_health.compare(last, first)
        self.assertEqual(len(ordinary_failures), 2)
        _, failures, _ = self.compare(first, middle, last)
        self.assertEqual(failures, [])

    def test_later_reduction_cannot_hide_an_aggregate_budget_failure(self):
        for middle in (self.report(104_000), self.report(complex_count=106)):
            with self.subTest(summary=middle["summary"]):
                _, failures, _ = self.compare(self.report(), middle, self.report())
                self.assertTrue(any(item.startswith("Integration 1:") for item in failures))

    def test_current_hotspot_still_compares_with_release_base(self):
        _, failures, _ = self.compare(
            self.report(), self.report(file_complexity=25), self.report(file_complexity=30),
        )
        self.assertTrue(any("complexity hotspot" in item for item in failures))

    def test_repaired_historical_hotspot_is_reported_and_final_limit_remains(self):
        _, failures, historical = self.compare(
            self.report(), self.report(file_complexity=40), self.report(),
        )
        self.assertEqual(failures, [])
        self.assertEqual(len(historical), 1)
        self.assertIn("complexity hotspot", historical[0]["local_findings"][0])

    def test_policy_and_missing_measurement_failures_are_not_relaxed(self):
        last = self.report()
        last["policy"]["line_growth_pct"] = 1
        self.assertTrue(any("policy changed" in item for item in self.compare(self.report(), last)[1]))
        last = self.report()
        last["measurement"]["ui"] = "missing"
        self.assertTrue(any("not measured" in item for item in self.compare(self.report(), last)[1]))

    def test_missing_or_disagreeing_checkpoints_fail_closed(self):
        baseline = self.report()
        for measured in ({**baseline, "product_paths": []}, self.report(complex_count=99)):
            with self.subTest(measured=measured):
                with self.assertRaisesRegex(ValueError, "disagree"):
                    self.release.compare_release(baseline, baseline, ["base", "head"], [baseline, measured])
        with self.assertRaisesRegex(ValueError, "Missing integration"):
            self.release.compare_release(baseline, baseline, ["base", "head"], [baseline])

    def chain_git(self, overrides=None):
        base, head, common = "a" * 40, "b" * 40, "c" * 40
        answers = {
            ("rev-parse", "--is-shallow-repository"): "false",
            ("merge-base", base, head): common,
            ("rev-parse", f"{base}^{{tree}}"): "base-tree",
            ("rev-parse", f"{common}^{{tree}}"): "base-tree",
            ("rev-parse", "HEAD^{tree}"): "head-tree",
            ("rev-parse", f"{head}^{{tree}}"): "head-tree",
            ("diff", "HEAD", "--name-only", "--", "app", "ui/src", *self.release.MEASUREMENT_INPUTS): "",
            ("rev-list", "--first-parent", "--reverse", f"{common}..{head}"): head,
            ("rev-parse", f"{head}^1"): common,
        }
        answers.update(overrides or {})
        return base, head, lambda *args: answers[args]

    def test_chain_requires_full_history_matching_trees_and_contiguous_parents(self):
        base, head, fake_git = self.chain_git()
        with self.patch.object(self.release, "git", fake_git):
            self.assertEqual(self.release.release_chain(base, head), [base, head])
        cases = [
            ({("rev-parse", "--is-shallow-repository"): "true"}, "complete history"),
            ({("rev-parse", f"{base}^{{tree}}"): "other"}, "merge-base"),
            ({("rev-parse", "HEAD^{tree}"): "other"}, "candidate tree"),
            ({("rev-parse", f"{head}^1"): "other"}, "gap"),
        ]
        for overrides, expected in cases:
            with self.subTest(expected=expected):
                _, _, fake_git = self.chain_git(overrides)
                with self.patch.object(self.release, "git", fake_git):
                    with self.assertRaisesRegex(ValueError, expected):
                        self.release.release_chain(base, head)
        with self.assertRaisesRegex(ValueError, "exact commit"):
            self.release.release_chain("origin/main", head)

    def test_changed_or_missing_historical_measurement_inputs_fail_closed(self):
        rows = [f"100644 blob {'a' * 40}\t{path}" for path in self.release.MEASUREMENT_INPUTS]
        for second in (rows[:-1], [row.replace('a' * 40, 'b' * 40) for row in rows]):
            with self.patch.object(self.release, "git", side_effect=["\n".join(rows), "\n".join(second)]):
                with self.assertRaisesRegex(ValueError, "measurement inputs|measurement inputs changed"):
                    self.release.read_trees(["base", "head"])


if __name__ == "__main__":
    unittest.main()
