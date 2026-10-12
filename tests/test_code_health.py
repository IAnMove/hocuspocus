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

    def test_main_sync_keeps_actual_fork_and_every_development_checkpoint(self):
        import subprocess

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', folder, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', *args],
                    text=True,
                ).strip()
            git('init', '-q')
            (root / 'base').write_text('base')
            git('add', '.')
            git('commit', '-qm', 'base')
            fork = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'development')
            (root / 'feature').write_text('feature')
            git('add', '.')
            git('commit', '-qm', 'feature')
            feature = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'release-main', fork)
            (root / 'hotfix').write_text('hotfix')
            git('add', '.')
            git('commit', '-qm', 'main hotfix')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-q', 'development')
            git('merge', '--no-ff', '-qm', 'sync main', base)
            head = git('rev-parse', 'HEAD')
            with self.patch.object(self.release, 'ROOT', root):
                self.assertEqual(self.release.release_chain(base, head), [base, fork, feature, head])
            # A larger release base must not conceal oversized feature growth.
            reports = [self.report(lines=4000), self.report(lines=1000),
                       self.report(lines=3001), self.report(lines=4000)]
            _, failures, _ = self.release.compare_release(
                reports[-1], reports[0], [base, fork, feature, head], reports)
            self.assertTrue(any(feature in finding and 'production LOC grew' in finding for finding in failures))

    def test_changed_or_missing_historical_measurement_inputs_fail_closed(self):
        rows = [('100644', 'blob', 'a' * 40, path) for path in self.release.MEASUREMENT_INPUTS]
        changed_rows = [[(mode, kind, 'b' * 40 if path == changed else blob, path)
                         for mode, kind, blob, path in rows]
                        for changed in ('scripts/code_health.py', 'scripts/code_quality_score.py', 'ui/eslint.config.js')]
        for second in (rows[:-1], *changed_rows):
            with self.patch.object(self.release, 'tree_entries', side_effect=[rows, second]), \
                 self.patch.object(self.release, "git", side_effect=lambda _, path: self.measurement_sources()[path.split(':', 1)[1]]):
                with self.assertRaisesRegex(ValueError, "measurement inputs|measurement inputs changed"):
                    self.release.read_trees(["base", "head"])

    def measurement_fixture(self):
        dependencies = {'eslint': '1', '@typescript-eslint/parser': '1', 'typescript': '1', '@types/dompurify': '1'}
        manifest = {'name': 'ui', 'scripts': {'test': 'old'}, 'devDependencies': dependencies}
        packages = {'': {'name': 'ui', 'devDependencies': dict(dependencies)}}
        for name in (*dependencies, 'parser-helper'):
            packages[f'node_modules/{name}'] = {
                'version': '1', 'resolved': f'https://registry.example/{name}/1', 'integrity': 'sha512-fixture',
            }
        packages['node_modules/eslint']['bin'] = {'eslint': 'bin/eslint.js'}
        packages['node_modules/@typescript-eslint/parser'].update(
            dependencies={'parser-helper': '1'}, peerDependencies={'typescript': '*'},
        )
        return manifest, {'lockfileVersion': 3, 'packages': packages}, "import parser from '@typescript-eslint/parser'\n"

    def fingerprint(self, fixture):
        manifest, lock, config = fixture
        return self.release.measurement_manifest(json.dumps(manifest), json.dumps(lock), config)

    def measurement_sources(self):
        manifest, lock, config = self.measurement_fixture()
        return {'ui/package.json': json.dumps(manifest), 'ui/package-lock.json': json.dumps(lock),
                'ui/eslint.config.js': config}

    def read_fixture_chain(self, *fixtures):
        import hashlib
        from types import SimpleNamespace

        sources, rows = {}, {}
        for index, (manifest, lock, config) in enumerate(fixtures):
            sha = str(index)
            sources[sha] = dict.fromkeys(self.release.MEASUREMENT_INPUTS, '')
            sources[sha].update({'ui/package.json': json.dumps(manifest), 'ui/package-lock.json': json.dumps(lock),
                                 'ui/eslint.config.js': config})
            rows[sha] = [('100644', 'blob', hashlib.sha1(value.encode()).hexdigest(), path)
                         for path, value in sources[sha].items()]
        with self.patch.object(self.release, 'tree_entries', side_effect=lambda sha: rows[sha]), \
             self.patch.object(self.release, 'git', side_effect=lambda _, spec: sources[spec.split(':', 1)[0]][spec.split(':', 1)[1]]), \
             self.patch.object(self.release.subprocess, 'run', return_value=SimpleNamespace(stdout=b'')):
            return self.release.read_trees(list(sources))

    def test_unrelated_types_removal_and_non_install_scripts_do_not_change_measurement(self):
        fixture = self.measurement_fixture()
        original = self.fingerprint(fixture)
        manifest, lock, _ = fixture
        manifest['scripts']['test'] = 'new'
        manifest['scripts']['atmos:capture'] = 'tsx scripts/capture.mjs'
        del manifest['devDependencies']['@types/dompurify']
        del lock['packages']['']['devDependencies']['@types/dompurify']
        del lock['packages']['node_modules/@types/dompurify']
        self.assertEqual(original, self.fingerprint(fixture))

    def test_analyzer_transitives_peers_and_resolution_paths_are_measurement_inputs(self):
        for name in ('eslint', 'parser-helper', 'typescript'):
            for field in ('version', 'resolved', 'integrity'):
                with self.subTest(name=name, field=field):
                    fixture = self.measurement_fixture()
                    original = self.fingerprint(fixture)
                    fixture[1]['packages'][f'node_modules/{name}'][field] = 'changed'
                    self.assertNotEqual(original, self.fingerprint(fixture))
        fixture = self.measurement_fixture()
        original = self.fingerprint(fixture)
        packages = fixture[1]['packages']
        packages['node_modules/@typescript-eslint/parser/node_modules/parser-helper'] = packages.pop('node_modules/parser-helper')
        self.assertNotEqual(original, self.fingerprint(fixture))

    def test_analyzer_ranges_bin_overrides_and_install_hooks_remain_protected(self):
        for mutate in (
            lambda m, p: m['devDependencies'].update(eslint='2'),
            lambda m, p: m.update(overrides={'parser-helper': '2'}),
            lambda m, p: m['scripts'].update(postinstall='npm run test'),
            lambda m, p: p['node_modules/eslint']['bin'].update(eslint='other.js'),
        ):
            fixture = self.measurement_fixture()
            original = self.fingerprint(fixture)
            mutate(fixture[0], fixture[1]['packages'])
            self.assertNotEqual(original, self.fingerprint(fixture))
        fixture = self.measurement_fixture()
        fixture[0]['scripts']['postinstall'] = 'npm run test'
        original = self.fingerprint(fixture)
        fixture[0]['scripts']['test'] = 'mutate-eslint'
        self.assertNotEqual(original, self.fingerprint(fixture))
        original = self.fingerprint(fixture)
        fixture[1]['packages']['node_modules/@types/dompurify']['integrity'] = 'changed'
        self.assertNotEqual(original, self.fingerprint(fixture))

    def test_unrelated_install_hook_and_its_transitives_are_measurement_inputs(self):
        fixture = self.measurement_fixture()
        original = self.fingerprint(fixture)
        packages = fixture[1]['packages']
        packages['node_modules/@types/dompurify'].update(hasInstallScript=True, dependencies={'hook-helper': '1'})
        packages['node_modules/hook-helper'] = dict(packages['node_modules/parser-helper'])
        hooked = self.fingerprint(fixture)
        self.assertNotEqual(original, hooked)
        packages['node_modules/hook-helper']['integrity'] = 'changed'
        self.assertNotEqual(hooked, self.fingerprint(fixture))

    def test_unmeasured_packages_and_root_ranges_allow_only_removal_across_history(self):
        before, removed = self.measurement_fixture(), self.measurement_fixture()
        del removed[0]['devDependencies']['@types/dompurify']
        del removed[1]['packages']['']['devDependencies']['@types/dompurify']
        del removed[1]['packages']['node_modules/@types/dompurify']
        self.read_fixture_chain(before, removed)
        for mutate in (
            lambda m, p: p['node_modules/@types/dompurify'].update(integrity='changed'),
            lambda m, p: m['devDependencies'].update({'@types/dompurify': '2'}),
            lambda m, p: p['']['devDependencies'].update({'@types/dompurify': '2'}),
        ):
            changed = self.measurement_fixture()
            mutate(changed[0], changed[1]['packages'])
            with self.assertRaisesRegex(ValueError, 'Unmeasured UI dependencies'):
                self.read_fixture_chain(before, changed)
        # A later restoration must not hide an intermediate introduction.
        with self.assertRaisesRegex(ValueError, 'Unmeasured UI dependencies'):
            self.read_fixture_chain(before, removed, before)

    def test_new_native_and_lock_script_packages_without_install_flag_fail_closed(self):
        before = self.measurement_fixture()
        for explicit_script in (False, True):
            with self.subTest(explicit_script=explicit_script):
                changed = self.measurement_fixture()
                manifest, lock, _ = changed
                manifest['devDependencies']['native-addon'] = '1'
                lock['packages']['']['devDependencies']['native-addon'] = '1'
                node = dict(lock['packages']['node_modules/parser-helper'])
                # binding.gyp is inside the tarball, absent from the lock metadata;
                # alternatively npm can execute scripts supplied by the lock itself.
                if explicit_script:
                    node['scripts'] = {'postinstall': 'node setup.js'}
                lock['packages']['node_modules/native-addon'] = node
                previous = self.release.unmeasured_inputs(json.dumps(before[0]), json.dumps(before[1]), self.fingerprint(before))
                current = self.release.unmeasured_inputs(json.dumps(manifest), json.dumps(lock), self.fingerprint(changed))
                if not explicit_script:
                    self.assertEqual(self.fingerprint(before), self.fingerprint(changed))
                    self.assertFalse(self.release.removed_only(previous, current))
                with self.assertRaisesRegex(ValueError, 'measurement inputs changed|Unmeasured UI dependencies'):
                    self.read_fixture_chain(before, changed)

    def test_missing_required_nodes_links_and_invalid_lock_fail_closed(self):
        for mutate in (
            lambda lock: lock.clear(),
            lambda lock: lock.update(lockfileVersion=1),
            lambda lock: lock['packages'].pop(''),
            lambda lock: lock['packages'].pop('node_modules/parser-helper'),
            lambda lock: lock['packages'].pop('node_modules/typescript'),
            lambda lock: lock['packages']['node_modules/eslint'].pop('integrity'),
            lambda lock: lock['packages']['node_modules/@types/dompurify'].update(link=True),
        ):
            fixture = self.measurement_fixture()
            mutate(fixture[1])
            with self.subTest(lock=fixture[1]), self.assertRaises(ValueError):
                self.fingerprint(fixture)

    def test_optional_absence_is_explicit_and_config_imports_are_checked(self):
        fixture = self.measurement_fixture()
        packages = fixture[1]['packages']
        packages['node_modules/eslint'].update(peerDependencies={'optional-peer': '*'},
                                             peerDependenciesMeta={'optional-peer': {'optional': True}})
        original = self.fingerprint(fixture)
        packages['node_modules/optional-peer'] = dict(packages['node_modules/parser-helper'])
        self.assertNotEqual(original, self.fingerprint(fixture))
        packages['node_modules/eslint']['optionalDependencies'] = {'optional-package': '*'}
        original = self.fingerprint(fixture)
        packages['node_modules/optional-package'] = dict(packages['node_modules/parser-helper'])
        self.assertNotEqual(original, self.fingerprint(fixture))
        for config in ("import x from 'missing-plugin'", "const x = await import('eslint')", "import './local.js'",
                       "import x from /* c */ 'plugin-extra'", "import/* c */('plugin-extra')",
                       "import /* c */ './local.js'", "import x from// c\n'plugin-extra'"):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.fingerprint((*fixture[:2], config))

    def test_main_push_requires_exact_unchanged_two_parent_development_merge(self):
        import subprocess

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', folder, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', *args],
                    text=True,
                ).strip()
            git('init', '-q')
            (root / 'file').write_text('base')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'development')
            (root / 'file').write_text('development')
            git('commit', '-qam', 'feature')
            source = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'published', base)
            git('merge', '--no-ff', '-qm', 'release', source)
            head = git('rev-parse', 'HEAD')
            with self.patch.object(self.release, 'ROOT', root):
                self.assertEqual(self.release.main_push_source(base, head, source), source)
                self.assertIsNone(self.release.main_push_source(source, head, source))
                self.assertIsNone(self.release.main_push_source(base, source, source))
                git('checkout', '-q', '--detach', source)
                self.assertIsNone(self.release.main_push_source(base, source, source))
                git('checkout', '-q', '--detach', head)
                self.assertIsNone(self.release.main_push_source(base, head, base))
                self.assertIsNone(self.release.main_push_source(base, 'HEAD', source))
                # A conflict resolution that changes the published tree is not a release passthrough.
                changed = git('commit-tree', f'{base}^{{tree}}', '-p', base, '-p', source, '-m', 'changed merge')
                git('checkout', '-q', '--detach', changed)
                self.assertIsNone(self.release.main_push_source(base, changed, source))
                third = git('commit-tree', f'{source}^{{tree}}', '-p', base, '-m', 'third')
                octopus = git('commit-tree', f'{source}^{{tree}}', '-p', base, '-p', source, '-p', third, '-m', 'octopus')
                git('checkout', '-q', '--detach', octopus)
                self.assertIsNone(self.release.main_push_source(base, octopus, source))

    def test_intermediate_unicode_product_cannot_disappear_from_history(self):
        import subprocess

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', folder, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', *args],
                    text=True,
                ).strip()
            git('init', '-q')
            for name in self.release.MEASUREMENT_INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.measurement_sources().get(name, ''), encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'base')
            chain = [git('rev-parse', 'HEAD')]
            name = 'app/services/épisode.py'
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_text('pass\n' * 4001, encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'temporary growth')
            chain.append(git('rev-parse', 'HEAD'))
            path.unlink()
            git('add', '-u')
            git('commit', '-qm', 'remove temporary growth')
            chain.append(git('rev-parse', 'HEAD'))
            with self.patch.object(self.release, 'ROOT', root):
                trees, sources = self.release.read_trees(chain)
            self.assertNotIn(name, trees[0])
            self.assertNotIn(name, trees[-1])
            self.assertEqual(len(sources[trees[1][name]].splitlines()), 4001)


if __name__ == "__main__":
    unittest.main()
