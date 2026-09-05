import assert from 'node:assert/strict'
import test from 'node:test'

import {
  classifyFrontendFailures,
  deriveRunStatus,
  interpretRunnerOutcome,
  isUnreadableLog,
  junitXml,
  parseLevels,
  parseNodeTestSummary,
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

test('mock or fixture text containing failed is not a suite failure', () => {
  const mockNoise = classifyFrontendFailures(
    'mock provider: generation failed as expected\n# tests 1\n# pass 1\n# fail 0\n',
    baseline,
  )
  assert.deepEqual(mockNoise, { baselineHits: [], newFailures: [] })

  const wordOnly = classifyFrontendFailures('the fixture said failed without a runner summary', baseline)
  assert.deepEqual(wordOnly, { baselineHits: [], newFailures: [] })
})

test('run status distinguishes baseline, incomplete and regression states', () => {
  assert.equal(deriveRunStatus([{ classification: 'pass' }]), 'PASS')
  assert.equal(deriveRunStatus([{ classification: 'expected_failure' }]), 'PASS_WITH_BASELINE')
  assert.equal(deriveRunStatus([{ classification: 'skipped' }]), 'INCOMPLETE')
  assert.equal(deriveRunStatus([{ classification: 'failure' }]), 'REGRESSION')
  assert.equal(deriveRunStatus([{ classification: 'timeout' }]), 'INFRASTRUCTURE FAILURE')
  assert.equal(deriveRunStatus([{ classification: 'infrastructure_failure' }]), 'INFRASTRUCTURE FAILURE')
  assert.equal(deriveRunStatus([]), 'INFRASTRUCTURE FAILURE')
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

test('level 8 local ACE smoke is fail-closed until GPU, URL, and confirmation are explicit', () => {
  assert.deepEqual(smokeOptInMissing(), [
    'RUN_GPU_TESTS=1', 'HOCUSPOCUS_SMOKE_BASE_URL',
    'HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA',
  ])
  assert.deepEqual(smokeOptInMissing({ runGpu: true, runExternal: false }), [
    'HOCUSPOCUS_SMOKE_BASE_URL', 'HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA',
  ])
  assert.deepEqual(smokeOptInMissing({
    runGpu: true, runExternal: false, baseUrl: 'http://127.0.0.1:8000', confirm: 'GENERATE_REAL_MEDIA',
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

test('structured node:test summary is preferred over mock failed text', () => {
  assert.deepEqual(parseNodeTestSummary('# tests 2\n# pass 2\n# fail 0\n'), {
    tests: 2, pass: 2, fail: 0, skipped: 0, cancelled: 0,
  })
  assert.deepEqual(parseNodeTestSummary('ℹ tests 2\nℹ pass 2\nℹ fail 0\n'), {
    tests: 2, pass: 2, fail: 0, skipped: 0, cancelled: 0,
  })
  const specReporter = interpretRunnerOutcome({
    code: 0,
    stdout: [
      '✔ example (1ms)',
      'mock HTTP 500: generation failed',
      'ℹ tests 1',
      'ℹ pass 1',
      'ℹ fail 0',
    ].join('\n'),
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI' })
  assert.equal(specReporter.classification, 'pass')
  assert.equal(specReporter.summary.fail, 0)
  const passed = interpretRunnerOutcome({
    code: 0,
    stdout: [
      'mock HTTP 500: generation failed',
      'Error: expected fixture failure recorded',
      '# tests 3',
      '# pass 3',
      '# fail 0',
    ].join('\n'),
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI' })
  assert.equal(passed.classification, 'pass')
  assert.equal(passed.reason, null)
})

test('real node:test failures remain regressions', () => {
  const failed = interpretRunnerOutcome({
    code: 1,
    stdout: [
      'test at ui/tests/new.test.mjs:4:1',
      '✖ actual regression (2.0ms)',
      '# tests 1',
      '# pass 0',
      '# fail 1',
    ].join('\n'),
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI', baseline })
  assert.equal(failed.classification, 'failure')
  assert.equal(failed.reason, 'actual regression')
})

test('timeouts and interrupted processes are infrastructure, not suite failures', () => {
  const timedOut = interpretRunnerOutcome({
    code: 1,
    stdout: '# tests 1\n# pass 1\n# fail 0\n',
    stderr: 'failed to flush',
    timedOut: true,
    signal: 'SIGTERM',
  }, { label: 'UI' })
  assert.equal(timedOut.classification, 'timeout')
  assert.match(timedOut.reason, /timed out/)

  const interrupted = interpretRunnerOutcome({
    code: 1,
    stdout: 'tests still running; later log said failed',
    stderr: '',
    timedOut: false,
    signal: 'SIGINT',
  }, { label: 'UI' })
  assert.equal(interrupted.classification, 'infrastructure_failure')
  assert.match(interrupted.reason, /interrupted \(SIGINT\)/)
})

test('unreadable or undetermined results are not evaluable and never invent PASS', () => {
  const garbage = `${'\u0001'.repeat(24)}\uFFFD\uFFFD\uFFFD\uFFFD\uFFFD\uFFFD\uFFFD\uFFFD`
  assert.equal(isUnreadableLog(garbage), true)
  const unreadable = interpretRunnerOutcome({
    code: 0,
    stdout: garbage,
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI' })
  assert.equal(unreadable.classification, 'infrastructure_failure')
  assert.match(unreadable.reason, /not evaluable/)

  const undetermined = interpretRunnerOutcome({
    code: 1,
    stdout: 'npm wrapped the process and printed nothing useful',
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI' })
  assert.equal(undetermined.classification, 'infrastructure_failure')
  assert.match(undetermined.reason, /not evaluable|without an evaluable/)
  assert.notEqual(undetermined.classification, 'pass')
})

test('known baseline failures stay expected_failure when no new tests fail', () => {
  const expected = interpretRunnerOutcome({
    code: 1,
    stdout: [
      'test at ui/tests/known.test.mjs:10:1',
      '✖ the exact known failure (1.2ms)',
      '# tests 1',
      '# pass 0',
      '# fail 1',
    ].join('\n'),
    stderr: '',
    timedOut: false,
    signal: null,
  }, { label: 'UI', baseline })
  assert.equal(expected.classification, 'expected_failure')
  assert.deepEqual(expected.baselineMatches, ['known-one'])
})

test('Python file selection is exact and cannot escape the discovered suite', () => {
  const available = ['tests/test_a.py', 'tests/test_b.py']
  assert.deepEqual(selectPythonTestFiles('', available), available)
  assert.deepEqual(selectPythonTestFiles('tests/test_b.py,tests/test_b.py', available), ['tests/test_b.py'])
  assert.throws(() => selectPythonTestFiles('../test_a.py', available), /Unknown NIGHTLY_PYTEST_FILES/)
})
