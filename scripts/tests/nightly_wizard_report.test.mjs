import assert from 'node:assert/strict'
import test from 'node:test'

import {
  classifyFrontendFailures,
  deriveRunStatus,
  junitXml,
  parseLevels,
  parseSmokeResult,
  requireTestDiagnostics,
  selectPythonTestFiles,
  smokeOptInMissing,
} from '../nightly_wizard_report.mjs'

const baseline = {
  failures: [{
    id: 'known-one',
    file: 'ui/tests/known.test.mjs',
    test: 'the exact known failure',
  }],
}

test('frontend baseline matching requires the exact test title and file', () => {
  const known = classifyFrontendFailures([
    'test at ui/tests/known.test.mjs:10:1',
    '✖ the exact known failure (1.2ms)',
  ].join('\n'), baseline)
  assert.deepEqual(known, { baselineHits: ['known-one'], newFailures: [] })

  const differentTest = classifyFrontendFailures([
    'test at ui/tests/known.test.mjs:20:1',
    '✖ a new failure in the old file (1.2ms)',
  ].join('\n'), baseline)
  assert.deepEqual(differentTest.baselineHits, [])
  assert.deepEqual(differentTest.newFailures, ['a new failure in the old file'])

  const wrongFile = classifyFrontendFailures([
    'test at ui/tests/another.test.mjs:10:1',
    '✖ the exact known failure (1.2ms)',
  ].join('\n'), baseline)
  assert.deepEqual(wrongFile.baselineHits, [])
  assert.deepEqual(wrongFile.newFailures, ['the exact known failure'])

  const titleWithoutBoundFile = classifyFrontendFailures('✖ the exact known failure (1.2ms)', baseline)
  assert.deepEqual(titleWithoutBoundFile.baselineHits, [])
  assert.deepEqual(titleWithoutBoundFile.newFailures, ['the exact known failure'])
})

test('unparsed non-zero-looking runner output cannot become a baseline pass', () => {
  const classified = classifyFrontendFailures('npm ERR! command failed without test details', baseline)
  assert.deepEqual(classified.baselineHits, [])
  assert.deepEqual(classified.newFailures, ['unclassified test runner failure'])
})

test('run status distinguishes baseline, incomplete and regression states', () => {
  assert.equal(deriveRunStatus([{ classification: 'pass' }]), 'PASS')
  assert.equal(deriveRunStatus([{ classification: 'expected_failure' }]), 'PASS_WITH_BASELINE')
  assert.equal(deriveRunStatus([{ classification: 'skipped' }]), 'INCOMPLETE')
  assert.equal(deriveRunStatus([{ classification: 'failure' }]), 'REGRESSION')
  assert.equal(deriveRunStatus([{ classification: 'timeout' }]), 'INFRASTRUCTURE FAILURE')
  assert.equal(deriveRunStatus([{ classification: 'infrastructure_failure' }]), 'INFRASTRUCTURE FAILURE')
})

test('JUnit records expected failures as skipped rather than passed', () => {
  const xml = junitXml([{
    id: 'ui', level: 4, title: 'UI', durationMs: 12,
    classification: 'expected_failure', baselineMatches: ['known-one'],
  }], 12)
  assert.match(xml, /failures="0"/)
  assert.match(xml, /skipped="1"/)
  assert.match(xml, /<skipped message="known baseline failure">known-one<\/skipped>/)
})

test('level parsing rejects empty and unknown coverage requests', () => {
  assert.deepEqual(parseLevels('1,2,2,6,8'), ['1', '2', '6', '8'])
  assert.throws(() => parseLevels(''), /at least one/)
  assert.throws(() => parseLevels('1,99'), /Unknown NIGHTLY_LEVELS: 99/)
})

test('level 8 smoke is fail-closed until both flags and the base URL are explicit', () => {
  assert.deepEqual(smokeOptInMissing(), [
    'RUN_GPU_TESTS=1', 'RUN_EXTERNAL_PROVIDER_TESTS=1', 'HOCUSPOCUS_SMOKE_BASE_URL',
    'HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA',
  ])
  assert.deepEqual(smokeOptInMissing({ runGpu: true, runExternal: true }), [
    'HOCUSPOCUS_SMOKE_BASE_URL', 'HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA',
  ])
  assert.deepEqual(smokeOptInMissing({
    runGpu: true, runExternal: true, baseUrl: 'http://127.0.0.1:8000', confirm: 'GENERATE_REAL_MEDIA',
  }), [])
})

test('nightly runner can recover explicit smoke identifiers from the child contract', () => {
  assert.deepEqual(parseSmokeResult('noise\nSMOKE_RESULT {"identifiers":{"taskIds":["task-1"],"pipelineIds":[],"outputIds":[]}}\n'), {
    identifiers: { taskIds: ['task-1'], pipelineIds: [], outputIds: [] },
  })
  assert.equal(parseSmokeResult('SMOKE_RESULT not-json'), null)
})

test('empty or sandbox-blocked test output is an infrastructure failure', () => {
  const empty = requireTestDiagnostics({ code: 0, stdout: '', stderr: '' }, 'UI')
  assert.equal(empty.code, 1)
  assert.equal(empty.classification, 'infrastructure_failure')

  const blocked = requireTestDiagnostics({
    code: 1,
    stdout: '',
    stderr: 'Error: listen EPERM: operation not permitted /tmp/tsx-1000/1.pipe',
  }, 'UI')
  assert.equal(blocked.classification, 'infrastructure_failure')
  assert.match(blocked.reason, /IPC socket/)
})

test('Python file selection is exact and cannot escape the discovered suite', () => {
  const available = ['tests/test_a.py', 'tests/test_b.py']
  assert.deepEqual(selectPythonTestFiles('', available), available)
  assert.deepEqual(selectPythonTestFiles('tests/test_b.py,tests/test_b.py', available), ['tests/test_b.py'])
  assert.throws(() => selectPythonTestFiles('../test_a.py', available), /Unknown NIGHTLY_PYTEST_FILES/)
})
