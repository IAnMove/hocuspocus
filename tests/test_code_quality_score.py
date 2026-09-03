import unittest

from scripts.code_quality_score import quality_score, score_delta


def _report(*, lines, files, functions, complex_functions, maximum, hotspots):
    return {
        "summary": {
            "production_lines": lines,
            "production_files": files,
            "functions_measured": functions,
            "complex_functions": complex_functions,
            "max_complexity": maximum,
        },
        "hotspots": hotspots,
    }


class CodeQualityScoreTests(unittest.TestCase):
    def test_score_is_bounded_and_exposes_auditable_components(self):
        result = quality_score(_report(
            lines=10_000,
            files=50,
            functions=500,
            complex_functions=5,
            maximum=20,
            hotspots={},
        ))
        self.assertEqual(result["score"], 100.0)
        self.assertEqual(set(result["components"]), {
            "cyclomatic", "concentration", "oversized_files", "modularity",
        })
        self.assertEqual(result["signals"]["largest_file_share"], 0.0)

    def test_score_falls_when_complexity_and_file_concentration_worsen(self):
        healthy = quality_score(_report(
            lines=100_000,
            files=300,
            functions=2_000,
            complex_functions=60,
            maximum=50,
            hotspots={"app/largest.py": 6_000, "app/second.py": 4_000},
        ))
        concentrated = quality_score(_report(
            lines=100_000,
            files=150,
            functions=2_000,
            complex_functions=180,
            maximum=500,
            hotspots={"app/largest.py": 30_000, "app/second.py": 20_000},
        ))
        self.assertGreater(healthy["score"], concentrated["score"])
        self.assertGreater(healthy["components"]["cyclomatic"], concentrated["components"]["cyclomatic"])
        self.assertGreater(healthy["components"]["concentration"], concentrated["components"]["concentration"])

    def test_delta_uses_the_rounded_public_scores(self):
        self.assertEqual(score_delta({"score": 51.2}, {"score": 49.9}), 1.3)


if __name__ == "__main__":
    unittest.main()
