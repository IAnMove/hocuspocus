import ast
import importlib.util
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

    def test_line_count_reports_physical_and_non_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text("one\n\nthree\n", encoding="utf-8")
            self.assertEqual(code_health._line_count(path), (3, 2))


if __name__ == "__main__":
    unittest.main()
