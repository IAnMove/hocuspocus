#!/usr/bin/env node
/**
 * Nightly Wizard validation runner.
 * Default: no GPU, no external provider APIs.
 * Writes artifacts/nightly/<stamp>/ and exits 1 on new regressions.
 */
import { spawn } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { appendFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const GLOBAL_TIMEOUT_MS = Number(process.env.NIGHTLY_TIMEOUT_MS || 6 * 60 * 60 * 1000)
const JOB_TIMEOUT_MS = Number(process.env.NIGHTLY_JOB_TIMEOUT_MS || 10 * 60 * 1000)
const PYTEST_FILE_TIMEOUT_MS = Number(process.env.NIGHTLY_PYTEST_FILE_TIMEOUT_MS || 3 * 60 * 1000)
const RUN_EXTERNAL = process.env.RUN_EXTERNAL_PROVIDER_TESTS === '1'
const RUN_GPU = process.env.RUN_GPU_TESTS === '1'
const SMOKE_BASE_URL = String(process.env.HOCUSPOCUS_SMOKE_BASE_URL || '').trim()
const SMOKE_WORKSPACE = String(process.env.HOCUSPOCUS_SMOKE_WORKSPACE || 'default').trim() || 'default'
const SMOKE_CONFIRM = String(process.env.HOCUSPOCUS_SMOKE_CONFIRM || '').trim()
const LEVEL_CATALOG = Object.freeze({
  '1': { title: 'Static contracts and build', implemented: true },
  '2': { title: 'Wizard unit and schema tests', implemented: true },
  '3': { title: 'Browser interaction tests', implemented: true },
  '4': { title: 'Full UI test suite', implemented: true },
  '5': { title: 'Workflow recovery and persistence tests', implemented: true },
  '6': { title: 'Python backend test suite', implemented: true },
  '7': { title: 'Presentation and reduced-motion tests', implemented: true },
  '8': { title: 'Real GPU/provider smoke', implemented: true, optional: true },
})

export function parseLevels(raw = '1,2,4,6') {
  const levels = [...new Set(String(raw).split(',').map(value => value.trim()).filter(Boolean))]
  const unknown = levels.filter(level => !LEVEL_CATALOG[level])
  if (unknown.length) throw new Error(`Unknown NIGHTLY_LEVELS: ${unknown.join(', ')}`)
  if (!levels.length) throw new Error('NIGHTLY_LEVELS must select at least one level')
  return levels
}

export function selectPythonTestFiles(raw, available) {
  if (!raw) return available
  const selected = [...new Set(String(raw).split(',').map(value => value.trim()).filter(Boolean))]
  const unknown = selected.filter(file => !available.includes(file))
  if (unknown.length) throw new Error(`Unknown NIGHTLY_PYTEST_FILES: ${unknown.join(', ')}`)
  if (!selected.length) throw new Error('NIGHTLY_PYTEST_FILES must select at least one file')
  return selected
}

export function smokeOptInMissing({
  runGpu = false,
  runExternal = false,
  baseUrl = '',
  confirm = '',
} = {}) {
  const missing = []
  if (runGpu !== true) missing.push('RUN_GPU_TESTS=1')
  if (!String(baseUrl || '').trim()) missing.push('HOCUSPOCUS_SMOKE_BASE_URL')
  if (confirm !== 'GENERATE_REAL_MEDIA') missing.push('HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA')
  return missing
}

export function parseSmokeResult(output) {
  const match = [...String(output || '').matchAll(/^SMOKE_RESULT\s+(\{.*\})\s*$/gm)].at(-1)
  if (!match) return null
  try {
    const result = JSON.parse(match[1])
    return result && typeof result === 'object' ? result : null
  } catch {
    return null
  }
}

let levelConfigurationError = null
let REQUESTED_LEVELS = []
try {
  REQUESTED_LEVELS = parseLevels(process.env.NIGHTLY_LEVELS || '1,2,3,4,5,6,7')
} catch (error) {
  levelConfigurationError = error
}
const LEVELS = new Set(REQUESTED_LEVELS)

const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
const outDir = path.join(ROOT, 'artifacts', 'nightly', stamp)
const startedAt = Date.now()
const results = []
const children = new Set()
let abortRequested = false
let globalTimedOut = false
let interrupted = false

function pythonBin() {
  const local = process.platform === 'win32'
    ? path.join(ROOT, 'app', 'env', 'Scripts', 'python.exe')
    : path.join(ROOT, 'app', 'env', 'bin', 'python')
  return process.env.NIGHTLY_PYTHON || local
}

function npmCmd() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

async function gitHead() {
  try {
    const { stdout } = await runCaptured('git', ['rev-parse', 'HEAD'], { timeoutMs: 15_000 })
    return stdout.trim()
  } catch {
    return 'unknown'
  }
}

function snapshotResources() {
  const memory = process.memoryUsage()
  return {
    rssMb: Math.round(memory.rss / 1024 / 1024),
    heapMb: Math.round(memory.heapUsed / 1024 / 1024),
    freeMemMb: Math.round(os.freemem() / 1024 / 1024),
    totalMemMb: Math.round(os.totalmem() / 1024 / 1024),
    load: os.loadavg(),
  }
}

function runCaptured(command, args, options = {}) {
  const timeoutMs = options.timeoutMs ?? JOB_TIMEOUT_MS
  const cwd = options.cwd || ROOT
  const env = { ...process.env, RUN_EXTERNAL_PROVIDER_TESTS: RUN_EXTERNAL ? '1' : '0', RUN_GPU_TESTS: RUN_GPU ? '1' : '0', ...(options.env || {}) }
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, shell: process.platform === 'win32' })
    children.add(child)
    let stdout = ''
    let stderr = ''
    const log = options.logPath ? createWriteStream(options.logPath) : null
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      child.killed = true
      child.kill('SIGTERM')
      setTimeout(() => child.kill('SIGKILL'), 2_000)
    }, timeoutMs)
    child.stdout?.on('data', chunk => {
      stdout += chunk
      log?.write(chunk)
    })
    child.stderr?.on('data', chunk => {
      stderr += chunk
      log?.write(chunk)
    })
    const closeLog = () => new Promise(done => {
      if (!log) return done()
      log.end(done)
    })
    child.on('error', async error => {
      clearTimeout(timer)
      children.delete(child)
      await closeLog()
      reject(error)
    })
    child.on('close', async (code, signal) => {
      clearTimeout(timer)
      children.delete(child)
      await closeLog()
      resolve({ code: code ?? 1, stdout, stderr, timedOut, signal: signal || null })
    })
  })
}

async function recordJob(job) {
  const started = Date.now()
  let outcome
  try {
    outcome = await job.run()
  } catch (error) {
    outcome = { code: 1, stdout: '', stderr: String(error?.stack || error), timedOut: false }
  }
  const record = {
    id: job.id,
    level: job.level,
    title: job.title,
    code: outcome.code,
    classification: outcome.classification || (
      outcome.code === 0 ? 'pass'
        : outcome.timedOut ? 'timeout'
          : outcome.signal ? 'infrastructure_failure' : 'failure'
    ),
    baselineMatches: outcome.baselineMatches || [],
    identifiers: outcome.identifiers || null,
    reason: outcome.reason || null,
    timedOut: outcome.timedOut === true,
    signal: outcome.signal || null,
    classifiedAsBaseline: outcome.classifiedAsBaseline === true,
    durationMs: Date.now() - started,
    log: job.logName || null,
  }
  results.push(record)
  if (job.logName && record.classification !== 'pass') {
    try {
      const source = path.join(outDir, job.logName)
      const destName = `${job.id}.${record.classification.replace(/_/g, '-')}.log`
      await writeFile(path.join(outDir, 'failures', destName), await readFile(source, 'utf8').catch(() => outcome.stderr || outcome.stdout || ''))
    } catch {
      // Keep the run going even if a failure copy cannot be written.
    }
  }
  const status = record.classification === 'pass' ? 'PASS'
    : record.classification === 'expected_failure' ? 'EXPECTED-FAILURE'
      : record.classification === 'skipped' ? 'SKIP'
        : record.classification === 'timeout' ? 'TIMEOUT'
          : ['infrastructure_failure', 'configuration_error'].includes(record.classification) ? 'INFRA' : 'FAIL'
  process.stdout.write(`[${status}] L${job.level} ${job.id} (${record.durationMs}ms)\n`)
  return record
}

function xmlEscape(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function junitXml(rows, durationMs = Date.now() - startedAt) {
  const failed = rows.filter(row => ['failure', 'timeout', 'infrastructure_failure', 'configuration_error'].includes(row.classification))
  const skipped = rows.filter(row => ['expected_failure', 'skipped'].includes(row.classification))
  const cases = rows.map(row => {
    const body = row.classification === 'pass' ? ''
      : row.classification === 'expected_failure'
        ? `<skipped message="known baseline failure">${xmlEscape(row.baselineMatches?.join(', ') || row.reason || '')}</skipped>`
        : row.classification === 'skipped'
          ? `<skipped message="not implemented">${xmlEscape(row.reason || '')}</skipped>`
          : `<failure message="${xmlEscape(row.id)}">${xmlEscape(row.reason || row.log || row.title)}</failure>`
    return `<testcase name="${xmlEscape(row.id)}" classname="nightly.L${row.level}" time="${(row.durationMs / 1000).toFixed(3)}">${body}</testcase>`
  }).join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?><testsuite name="nightly-wizard" tests="${rows.length}" failures="${failed.length}" skipped="${skipped.length}" time="${(durationMs / 1000).toFixed(3)}">${cases}</testsuite>`
}

function normalizedTestTitle(value) {
  return String(value || '').replace(/\s+\([\d.]+ms\)\s*$/, '').trim().toLowerCase()
}

function normalizedTestFile(value) {
  return String(value || '').replace(/\\/g, '/').replace(/^.*?ui\//, '').replace(/^ui\//, '')
}

export function classifyFrontendFailures(logText, baseline) {
  const newFailures = []
  const baselineHits = []
  const summaryEntries = [...logText.matchAll(/(?:^|\n)test at ([^\n]+)\n✖\s+([^\n]+)\s*/gm)]
    .map(match => ({ file: match[1].trim(), title: match[2].trim() }))
  const failBlocks = summaryEntries.length
    ? summaryEntries
    : [...new Set(
        [...logText.matchAll(/(?:^|\n)✖\s+(.+?)\s*$/gm)].map(match => match[1].trim()),
      )].map(title => ({ file: '', title }))
  for (const entry of failBlocks) {
    const { title } = entry
    const normalized = normalizedTestTitle(title)
    const known = baseline.failures.find(item => (
      normalizedTestTitle(item.test) === normalized
      && entry.file
      && normalizedTestFile(entry.file).includes(normalizedTestFile(item.file))
    ))
    if (known) baselineHits.push(known.id)
    else newFailures.push(title.replace(/\s+\([\d.]+ms\)\s*$/, ''))
  }
  if (!failBlocks.length && /(?:^|\n)(?:npm ERR!|Error:|not ok|failed)/im.test(logText)) {
    newFailures.push('unclassified test runner failure')
  }
  return { baselineHits: [...new Set(baselineHits)], newFailures: [...new Set(newFailures)] }
}

export function deriveRunStatus(rows) {
  if (rows.some(row => ['timeout', 'infrastructure_failure', 'configuration_error'].includes(row.classification))) return 'INFRASTRUCTURE FAILURE'
  if (rows.some(row => ['failure', 'configuration_error'].includes(row.classification))) return 'REGRESSION'
  if (rows.some(row => row.classification === 'skipped')) return 'INCOMPLETE'
  if (rows.some(row => row.classification === 'expected_failure')) return 'PASS_WITH_BASELINE'
  return 'PASS'
}

export function requireTestDiagnostics(outcome, label) {
  const logText = `${outcome.stdout || ''}\n${outcome.stderr || ''}`
  if (/listen EPERM:[\s\S]*tsx-/i.test(logText)) {
    return {
      ...outcome,
      classification: 'infrastructure_failure',
      reason: `${label} could not start because the environment blocks the tsx IPC socket`,
    }
  }
  if (!logText.trim()) {
    return {
      ...outcome,
      code: outcome.code || 1,
      classification: 'infrastructure_failure',
      reason: `${label} exited without test diagnostics`,
    }
  }
  return outcome
}

async function main() {
  await mkdir(outDir, { recursive: true })
  await mkdir(path.join(outDir, 'failures'), { recursive: true })
  if (levelConfigurationError) throw levelConfigurationError
  const head = await gitHead()
  const before = snapshotResources()
  const baseline = JSON.parse(await readFile(path.join(ROOT, 'scripts', 'nightly_baseline.json'), 'utf8'))
  const ui = path.join(ROOT, 'ui')
  const availablePythonTestFiles = (await readdir(path.join(ROOT, 'tests')))
    .filter(name => /^test_.+\.py$/.test(name))
    .sort()
    .map(name => `tests/${name}`)
  const pythonTestFiles = selectPythonTestFiles(
    process.env.NIGHTLY_PYTEST_FILES || '', availablePythonTestFiles,
  )
  const jobs = []

  if (LEVELS.has('1')) {
    jobs.push({
      id: 'git-diff-check', level: 1, title: 'git diff --check', logName: 'git-diff.log',
      run: () => runCaptured('git', ['diff', '--check'], { logPath: path.join(outDir, 'git-diff.log'), timeoutMs: 30_000 }),
    })
    jobs.push({
      id: 'eslint', level: 1, title: 'ESLint', logName: 'eslint.log',
      run: () => runCaptured(npmCmd(), ['run', 'lint', '--', '--max-warnings=0'], {
        cwd: ui, logPath: path.join(outDir, 'eslint.log'),
      }),
    })
    jobs.push({
      id: 'tsc', level: 1, title: 'TypeScript', logName: 'tsc.log',
      run: () => runCaptured(path.join(ui, 'node_modules', '.bin', process.platform === 'win32' ? 'tsc.cmd' : 'tsc'), ['-b', '--pretty', 'false'], { cwd: ui, logPath: path.join(outDir, 'tsc.log') }),
    })
    jobs.push({
      id: 'vite-build', level: 1, title: 'Vite build', logName: 'ui-build.log',
      run: () => runCaptured(path.join(ui, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite'), ['build'], { cwd: ui, logPath: path.join(outDir, 'ui-build.log') }),
    })
    jobs.push({
      id: 'budget', level: 1, title: 'Chunk budget', logName: 'budget.log',
      run: () => runCaptured(process.execPath, ['scripts/check-build-budget.mjs'], { cwd: ui, logPath: path.join(outDir, 'budget.log') }),
    })
    jobs.push({
      id: 'docs', level: 1, title: 'Documentation contract', logName: 'docs.log',
      run: () => runCaptured(pythonBin(), ['scripts/check_documentation_links.py'], { logPath: path.join(outDir, 'docs.log'), timeoutMs: 60_000 }),
    })
    jobs.push({
      id: 'brand', level: 1, title: 'Visible brand contract', logName: 'brand.log',
      run: () => runCaptured(pythonBin(), ['scripts/check_brand_contract.py'], { logPath: path.join(outDir, 'brand.log'), timeoutMs: 60_000 }),
    })
    jobs.push({
      id: 'nightly-runner-unit', level: 1, title: 'Nightly runner contracts', logName: 'nightly-runner-unit.log',
      run: async () => requireTestDiagnostics(await runCaptured(process.execPath, ['scripts/tests/nightly_wizard_report.test.mjs'], {
        logPath: path.join(outDir, 'nightly-runner-unit.log'), timeoutMs: 60_000,
      }), 'Nightly runner contract tests'),
    })
    jobs.push({
      id: 'agent-contract', level: 1, title: 'Wizard schema and capabilities', logName: 'agent-contract.log',
      run: async () => requireTestDiagnostics(await runCaptured(
        process.execPath, ['--import', 'tsx', '--test', 'tests/agentContract.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'agent-contract.log') },
      ), 'Wizard contract tests'),
    })
  }

  if (LEVELS.has('2')) {
    jobs.push({
      id: 'agent-unit', level: 2, title: 'Wizard unit tests', logName: 'frontend-tests.log',
      run: async () => requireTestDiagnostics(await runCaptured(
        process.execPath, ['--import', 'tsx', '--test', 'tests/agentActions.test.mjs', 'tests/agentContract.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'frontend-tests.log') },
      ), 'Wizard unit tests'),
    })
  }

  if (LEVELS.has('4')) {
    jobs.push({
      id: 'frontend-suite', level: 4, title: 'Full UI test suite', logName: 'frontend-suite.log',
      run: async () => {
        let outcome = await runCaptured(npmCmd(), ['test'], {
          cwd: ui,
          logPath: path.join(outDir, 'frontend-suite.log'),
        })
        outcome = requireTestDiagnostics(outcome, 'Full UI tests')
        if (outcome.classification === 'infrastructure_failure') return outcome
        const logText = `${outcome.stdout}\n${outcome.stderr}`
        const classified = classifyFrontendFailures(logText, baseline)
        if (outcome.code !== 0 && !classified.baselineHits.length && !classified.newFailures.length) {
          classified.newFailures.push('frontend test process exited without diagnostics')
        }
        await writeFile(path.join(outDir, 'frontend-classification.json'), JSON.stringify(classified, null, 2))
        const onlyBaseline = outcome.code !== 0 && classified.newFailures.length === 0 && classified.baselineHits.length > 0
        return {
          ...outcome,
          classification: onlyBaseline ? 'expected_failure' : undefined,
          classifiedAsBaseline: onlyBaseline,
          baselineMatches: classified.baselineHits,
          reason: classified.newFailures.join('; ') || null,
        }
      },
    })
  }

  if (LEVELS.has('5')) {
    jobs.push({
      id: 'workflow-recovery', level: 5, title: 'Durable workflow recovery and rhythm tests', logName: 'workflow-recovery.log',
      run: async () => requireTestDiagnostics(await runCaptured(
        process.execPath, ['--import', 'tsx', '--test', 'tests/wizardWorkflowRuntime.test.mjs', 'tests/rhythmic3dWorkflow.test.mjs', 'tests/sceneRhythm.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'workflow-recovery.log') },
      ), 'Workflow recovery tests'),
    })
  }

  if (LEVELS.has('6')) {
    jobs.push({
      id: 'backend-pytest', level: 6, title: 'Python tests', logName: 'backend-tests.log',
      run: async () => {
        const logPath = path.join(outDir, 'backend-tests.log')
        await writeFile(logPath, '')
        let code = 0
        let timedOut = false
        let signal = null
        const failedFiles = []
        const timedOutFiles = []
        let executedFiles = 0
        for (const [index, file] of pythonTestFiles.entries()) {
          if (abortRequested) break
          process.stdout.write(`[RUN] L6 ${index + 1}/${pythonTestFiles.length} ${file}\n`)
          const part = await runCaptured(
            pythonBin(), ['-m', 'pytest', '-q', '--maxfail=20', file],
            { timeoutMs: PYTEST_FILE_TIMEOUT_MS },
          )
          executedFiles += 1
          await appendFile(
            logPath,
            `\n===== ${file} (${part.code === 0 ? 'PASS' : part.timedOut ? 'TIMEOUT' : 'FAIL'}) =====\n${part.stdout}${part.stderr}`,
          )
          if (part.code !== 0) {
            code = 1
            failedFiles.push(file)
          }
          if (part.timedOut) {
            timedOut = true
            timedOutFiles.push(file)
          }
          signal ||= part.signal
        }
        return {
          code,
          stdout: `Executed ${executedFiles}/${pythonTestFiles.length} Python test files; failed: ${failedFiles.join(', ') || 'none'}\n`,
          stderr: '',
          timedOut,
          signal,
          reason: timedOutFiles.length
            ? `Python test files timed out: ${timedOutFiles.join(', ')}`
            : failedFiles.length ? `Python test files failed: ${failedFiles.join(', ')}` : null,
        }
      },
    })
  }

  if (LEVELS.has('3')) {
    jobs.push({
      id: 'wizard-browser-contracts', level: 3, title: LEVEL_CATALOG['3'].title, logName: 'wizard-browser-contracts.log',
      run: async () => requireTestDiagnostics(await runCaptured(
        process.execPath,
        ['--import', 'tsx', '--test',
          'tests/agentActions.test.mjs',
          'tests/agentContract.test.mjs',
          'tests/wizardPendingAnswer.test.mjs',
          'tests/wizardWorkflowRuntime.test.mjs',
          'tests/wizardInteractionDom.test.tsx'],
        { cwd: ui, logPath: path.join(outDir, 'wizard-browser-contracts.log') },
      ), 'Wizard browser interaction contracts'),
    })
  }

  if (LEVELS.has('7')) {
    jobs.push({
      id: 'wizard-presentation-contracts', level: 7, title: LEVEL_CATALOG['7'].title, logName: 'wizard-presentation-contracts.log',
      run: async () => requireTestDiagnostics(await runCaptured(
        process.execPath,
        ['--import', 'tsx', '--test', 'tests/wizardPresentationContract.test.mjs', 'tests/wizardPresentation.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'wizard-presentation-contracts.log') },
      ), 'Wizard presentation contracts'),
    })
  }

  if (LEVELS.has('8')) {
    jobs.push({
      id: 'optional-smoke', level: 8, title: 'Optional real smoke (explicit)', logName: 'smoke.log',
      run: async () => {
        const missing = smokeOptInMissing({
          runGpu: RUN_GPU,
          runExternal: RUN_EXTERNAL,
          baseUrl: SMOKE_BASE_URL,
          confirm: SMOKE_CONFIRM,
        })
        if (missing.length) {
          return {
            code: 1,
            stdout: '',
            stderr: `Level 8 is fail-closed; explicit opt-in is missing: ${missing.join(', ')}\n`,
            timedOut: false,
            classification: 'configuration_error',
            reason: `Level 8 requires ${missing.join(', ')}`,
          }
        }
        const outcome = await runCaptured(
          process.execPath,
          ['scripts/nightly_wizard_smoke.mjs'],
          {
            env: {
              HOCUSPOCUS_SMOKE_BASE_URL: SMOKE_BASE_URL,
              HOCUSPOCUS_SMOKE_WORKSPACE: SMOKE_WORKSPACE,
              HOCUSPOCUS_SMOKE_CONFIRM: SMOKE_CONFIRM,
            },
            logPath: path.join(outDir, 'smoke.log'),
            timeoutMs: Number(process.env.NIGHTLY_SMOKE_TIMEOUT_MS || JOB_TIMEOUT_MS),
          },
        )
        const smoke = parseSmokeResult(outcome.stdout)
        if (outcome.code !== 0) return outcome
        if (!smoke?.identifiers) {
          return {
            ...outcome,
            code: 1,
            classification: 'infrastructure_failure',
            reason: 'Smoke probe exited successfully without a machine-readable result or identifiers',
          }
        }
        return {
          ...outcome,
          identifiers: smoke.identifiers,
          reason: `Song ${smoke.songStatus}; videoclip pipeline ${smoke.pipelineStatus}`,
        }
      },
    })
  }

  const watchdog = setTimeout(() => {
    globalTimedOut = true
    abortRequested = true
    for (const child of children) {
      child.kill('SIGTERM')
    }
  }, GLOBAL_TIMEOUT_MS)

  for (const job of jobs) {
    if (abortRequested) break
    await recordJob(job)
  }
  clearTimeout(watchdog)

  const after = snapshotResources()
  if (globalTimedOut && deriveRunStatus(results) !== 'INFRASTRUCTURE FAILURE') {
    results.push({
      id: 'global-timeout', level: 0, title: 'Global nightly timeout', code: 1,
      classification: 'timeout', baselineMatches: [], reason: 'The global nightly timeout elapsed',
      timedOut: true, signal: null, classifiedAsBaseline: false,
      durationMs: Date.now() - startedAt, log: null,
    })
  }
  if (interrupted && deriveRunStatus(results) !== 'INFRASTRUCTURE FAILURE') {
    results.push({
      id: 'interrupted', level: 0, title: 'Nightly interrupted', code: 1,
      classification: 'infrastructure_failure', baselineMatches: [], reason: 'The nightly run received SIGINT',
      timedOut: false, signal: 'SIGINT', classifiedAsBaseline: false,
      durationMs: Date.now() - startedAt, log: null,
    })
  }
  const finalStatus = deriveRunStatus(results)
  const regressions = results.filter(row => row.classification === 'failure')
  const infrastructureFailures = results.filter(row => ['timeout', 'infrastructure_failure', 'configuration_error'].includes(row.classification))
  const expected = results.filter(row => row.classification === 'expected_failure')
  const durationMs = Date.now() - startedAt
  const baselineJobs = results.filter(row => row.classifiedAsBaseline).map(row => row.id)
  const executedLevels = [...new Set(results.filter(row => row.classification !== 'skipped').map(row => String(row.level)))].sort()
  const missingLevels = REQUESTED_LEVELS.filter(level => !executedLevels.includes(level))
  const payload = {
    status: finalStatus,
    commit: head,
    durationMs,
    gpuUsed: RUN_GPU,
    externalProvidersUsed: RUN_EXTERNAL,
    requestedLevels: REQUESTED_LEVELS,
    executedLevels,
    missingLevels,
    levelCatalog: LEVEL_CATALOG,
    resources: { before, after },
    results,
    baseline: baseline.failures.map(item => item.id),
    classifiedBaselineJobs: baselineJobs,
  }
  await writeFile(path.join(outDir, 'results.json'), JSON.stringify(payload, null, 2))
  await writeFile(path.join(outDir, 'junit.xml'), junitXml(results, durationMs))
  const summary = [
    `Estado: ${finalStatus}`,
    `Commit probado: ${head}`,
    `Duración: ${(durationMs / 1000).toFixed(1)}s`,
    `Jobs pasados: ${results.filter(row => row.classification === 'pass').length}`,
    `Fallos esperados observados: ${expected.flatMap(row => row.baselineMatches).join(', ') || 'ninguno'}`,
    `Regresiones: ${regressions.map(row => row.id).join(', ') || 'ninguna'}`,
    `Fallos de infraestructura: ${infrastructureFailures.map(row => row.id).join(', ') || 'ninguno'}`,
    `Niveles solicitados: ${REQUESTED_LEVELS.join(', ')}`,
    `Niveles ejecutados: ${executedLevels.join(', ') || 'ninguno'}`,
    `Niveles sin implementar/omitidos: ${missingLevels.join(', ') || 'ninguno'}`,
    `GPU utilizada: ${RUN_GPU ? 'sí' : 'no'}`,
    `Proveedores externos utilizados: ${RUN_EXTERNAL ? 'sí' : 'no'}`,
    `Artefactos: ${path.relative(ROOT, outDir)}`,
    '',
    'Jobs:',
    ...results.map(row => `- L${row.level} ${row.id}: ${row.classification.toUpperCase()} (${row.durationMs}ms)${row.reason ? ` — ${row.reason}` : ''}`),
  ].join('\n')
  await writeFile(path.join(outDir, 'summary.md'), `${summary}\n`)
  process.stdout.write(`\n${summary}\n`)
  process.exitCode = finalStatus === 'PASS' || finalStatus === 'PASS_WITH_BASELINE' ? 0 : 1
}

process.on('SIGINT', () => {
  interrupted = true
  abortRequested = true
  for (const child of children) child.kill('SIGTERM')
})

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    await main()
  } catch (error) {
    await mkdir(outDir, { recursive: true })
    await mkdir(path.join(outDir, 'failures'), { recursive: true })
    const detail = String(error?.stack || error)
    const row = {
      id: 'nightly-runner', level: 0, title: 'Nightly runner', code: 1,
      classification: 'configuration_error', baselineMatches: [], reason: detail,
      timedOut: false, classifiedAsBaseline: false, durationMs: Date.now() - startedAt, log: 'runner-error.log',
    }
    await writeFile(path.join(outDir, 'runner-error.log'), `${detail}\n`)
    await writeFile(path.join(outDir, 'results.json'), JSON.stringify({
      status: 'INFRASTRUCTURE FAILURE', requestedLevels: REQUESTED_LEVELS, results: [row],
    }, null, 2))
    await writeFile(path.join(outDir, 'junit.xml'), junitXml([row]))
    await writeFile(path.join(outDir, 'summary.md'), `Estado: INFRASTRUCTURE FAILURE\n\n${detail}\n`)
    process.stderr.write(`${detail}\n`)
    process.exitCode = 1
  }
}
