#!/usr/bin/env node
/**
 * Nightly Wizard validation runner.
 * Default: no GPU, no external provider APIs.
 * Writes artifacts/nightly/<stamp>/ and exits 1 on new regressions.
 */
import { spawn } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const GLOBAL_TIMEOUT_MS = Number(process.env.NIGHTLY_TIMEOUT_MS || 6 * 60 * 60 * 1000)
const JOB_TIMEOUT_MS = Number(process.env.NIGHTLY_JOB_TIMEOUT_MS || 10 * 60 * 1000)
const RUN_EXTERNAL = process.env.RUN_EXTERNAL_PROVIDER_TESTS === '1'
const RUN_GPU = process.env.RUN_GPU_TESTS === '1'
const LEVELS = new Set(
  String(process.env.NIGHTLY_LEVELS || '1,2,4,6')
    .split(',')
    .map(value => value.trim())
    .filter(Boolean),
)

const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
const outDir = path.join(ROOT, 'artifacts', 'nightly', stamp)
const startedAt = Date.now()
const results = []
const children = new Set()

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
    const timer = setTimeout(() => {
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
    child.on('error', error => {
      clearTimeout(timer)
      children.delete(child)
      log?.end()
      reject(error)
    })
    child.on('close', code => {
      clearTimeout(timer)
      children.delete(child)
      log?.end()
      resolve({ code: code ?? 1, stdout, stderr, timedOut: Boolean(child.killed) })
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
    timedOut: outcome.timedOut === true,
    classifiedAsBaseline: outcome.classifiedAsBaseline === true,
    durationMs: Date.now() - started,
    log: job.logName || null,
  }
  results.push(record)
  if (job.logName && (record.code !== 0 || record.classifiedAsBaseline)) {
    try {
      const source = path.join(outDir, job.logName)
      const destName = record.classifiedAsBaseline ? `${job.id}.baseline.log` : `${job.id}.log`
      await writeFile(path.join(outDir, 'failures', destName), await readFile(source, 'utf8').catch(() => outcome.stderr || outcome.stdout || ''))
    } catch {
      // Keep the run going even if a failure copy cannot be written.
    }
  }
  const status = record.code === 0
    ? (record.classifiedAsBaseline ? 'BASELINE' : 'PASS')
    : record.timedOut ? 'TIMEOUT' : 'FAIL'
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

function junitXml(rows) {
  const failed = rows.filter(row => row.code !== 0)
  const cases = rows.map(row => {
    const body = row.code === 0
      ? ''
      : `<failure message="${xmlEscape(row.id)}">${xmlEscape(row.log || row.title)}</failure>`
    return `<testcase name="${xmlEscape(row.id)}" classname="nightly.L${row.level}" time="${(row.durationMs / 1000).toFixed(3)}">${body}</testcase>`
  }).join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?><testsuite name="nightly-wizard" tests="${rows.length}" failures="${failed.length}" time="${((Date.now() - startedAt) / 1000).toFixed(3)}">${cases}</testsuite>`
}

function eslintFailingFiles(logText) {
  const matches = [
    ...logText.matchAll(/(?:^|\n)((?:[A-Za-z]:)?[^\s:]+\.(?:tsx|ts|jsx|js))\s*$/gm),
  ].map(match => path.basename(match[1].replace(/\\/g, '/')))
  return [...new Set(matches.filter(name => /\.(?:tsx|ts|jsx|js)$/.test(name)))]
}

function onlyKnownStaticFailures(logText, baseline) {
  const known = new Set((baseline.static || []).map(item => path.basename(item.file)))
  if (!known.size) return false
  const failingFiles = eslintFailingFiles(logText)
  if (!failingFiles.length) return false
  return failingFiles.every(name => known.has(name))
}

function classifyFrontendFailures(logText, baseline) {
  const ids = baseline.failures.map(item => item.id)
  const newFailures = []
  const baselineHits = []
  for (const item of baseline.failures) {
    if (logText.includes(item.file) || logText.includes(item.match) || logText.includes(item.id)) {
      baselineHits.push(item.id)
    }
  }
  const failBlocks = [...logText.matchAll(/✖\s+(.+?)(?:\s+\([\d.]+ms\))?$/gm)].map(match => match[1])
  for (const title of failBlocks) {
    const known = ids.some(id => title.toLowerCase().includes(id.toLowerCase()))
    if (!known) newFailures.push(title)
  }
  return { baselineHits, newFailures }
}

async function main() {
  await mkdir(outDir, { recursive: true })
  await mkdir(path.join(outDir, 'failures'), { recursive: true })
  const head = await gitHead()
  const before = snapshotResources()
  const baseline = JSON.parse(await readFile(path.join(ROOT, 'scripts', 'nightly_baseline.json'), 'utf8'))
  const ui = path.join(ROOT, 'ui')
  const jobs = []

  if (LEVELS.has('1')) {
    jobs.push({
      id: 'git-diff-check', level: 1, title: 'git diff --check', logName: 'git-diff.log',
      run: () => runCaptured('git', ['diff', '--check'], { logPath: path.join(outDir, 'git-diff.log'), timeoutMs: 30_000 }),
    })
    jobs.push({
      id: 'eslint', level: 1, title: 'ESLint', logName: 'eslint.log',
      run: async () => {
        const outcome = await runCaptured(npmCmd(), ['run', 'lint', '--', '--max-warnings=0'], { cwd: ui, logPath: path.join(outDir, 'eslint.log') })
        const logText = `${outcome.stdout}\n${outcome.stderr}`
        if (outcome.code !== 0 && onlyKnownStaticFailures(logText, baseline)) {
          return { ...outcome, code: 0, classifiedAsBaseline: true }
        }
        return outcome
      },
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
      id: 'agent-contract', level: 1, title: 'Wizard schema and capabilities', logName: 'agent-contract.log',
      run: () => runCaptured(
        path.join(ui, 'node_modules', '.bin', process.platform === 'win32' ? 'tsx.cmd' : 'tsx'),
        ['--tsconfig', 'tsconfig.app.json', '--test', 'tests/agentContract.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'agent-contract.log') },
      ),
    })
  }

  if (LEVELS.has('2')) {
    jobs.push({
      id: 'agent-unit', level: 2, title: 'Wizard unit tests', logName: 'frontend-tests.log',
      run: () => runCaptured(
        path.join(ui, 'node_modules', '.bin', process.platform === 'win32' ? 'tsx.cmd' : 'tsx'),
        ['--tsconfig', 'tsconfig.app.json', '--test', 'tests/agentActions.test.mjs', 'tests/agentContract.test.mjs'],
        { cwd: ui, logPath: path.join(outDir, 'frontend-tests.log') },
      ),
    })
  }

  if (LEVELS.has('4')) {
    jobs.push({
      id: 'frontend-suite', level: 4, title: 'Full UI test suite', logName: 'frontend-suite.log',
      run: async () => {
        const outcome = await runCaptured(npmCmd(), ['test'], { cwd: ui, logPath: path.join(outDir, 'frontend-suite.log') })
        const logText = `${outcome.stdout}\n${outcome.stderr}`
        const classified = classifyFrontendFailures(logText, baseline)
        await writeFile(path.join(outDir, 'frontend-classification.json'), JSON.stringify(classified, null, 2))
        const onlyBaseline = outcome.code !== 0 && classified.newFailures.length === 0 && classified.baselineHits.length > 0
        return { ...outcome, code: onlyBaseline ? 0 : outcome.code, classified }
      },
    })
  }

  if (LEVELS.has('6')) {
    jobs.push({
      id: 'backend-pytest', level: 6, title: 'Python tests', logName: 'backend-tests.log',
      run: () => runCaptured(pythonBin(), ['-m', 'pytest', '-q', '--maxfail=20'], {
        logPath: path.join(outDir, 'backend-tests.log'),
        timeoutMs: Math.min(JOB_TIMEOUT_MS * 3, 30 * 60 * 1000),
      }),
    })
  }

  if (LEVELS.has('8') && (RUN_EXTERNAL || RUN_GPU)) {
    jobs.push({
      id: 'optional-smoke', level: 8, title: 'Optional real smoke (explicit)', logName: 'smoke.log',
      run: async () => ({ code: 1, stdout: '', stderr: 'Optional smoke is not implemented; keep RUN_*_TESTS=0.\n', timedOut: false }),
    })
  }

  const watchdog = setTimeout(() => {
    for (const child of children) {
      child.kill('SIGTERM')
    }
  }, GLOBAL_TIMEOUT_MS)

  for (const job of jobs) {
    await recordJob(job)
  }
  clearTimeout(watchdog)

  const after = snapshotResources()
  const failed = results.filter(row => row.code !== 0)
  const status = failed.length === 0
    ? 'PASS'
    : failed.some(row => row.timedOut) ? 'INFRASTRUCTURE FAILURE'
      : 'REGRESSION'
  const durationMs = Date.now() - startedAt
  const staticHits = results.filter(row => row.classifiedAsBaseline).map(row => row.id)
  const payload = {
    status,
    commit: head,
    durationMs,
    gpuUsed: RUN_GPU,
    externalProvidersUsed: RUN_EXTERNAL,
    resources: { before, after },
    results,
    baseline: baseline.failures.map(item => item.id),
    staticBaseline: (baseline.static || []).map(item => item.id),
    classifiedStatic: staticHits,
  }
  await writeFile(path.join(outDir, 'results.json'), JSON.stringify(payload, null, 2))
  await writeFile(path.join(outDir, 'junit.xml'), junitXml(results))
  const summary = [
    `Estado: ${status}`,
    `Commit probado: ${head}`,
    `Duración: ${(durationMs / 1000).toFixed(1)}s`,
    `Tests pasados: ${results.filter(row => row.code === 0 && !row.classifiedAsBaseline).length}`,
    `Fallos nuevos: ${failed.map(row => row.id).join(', ') || 'ninguno'}`,
    `Fallos baseline: ${baseline.failures.map(item => item.id).join(', ')}`,
    `Avisos estáticos conocidos: ${(baseline.static || []).map(item => item.id).join(', ') || 'ninguno'}`,
    `GPU utilizada: ${RUN_GPU ? 'sí' : 'no'}`,
    `Proveedores externos utilizados: ${RUN_EXTERNAL ? 'sí' : 'no'}`,
    `Artefactos: ${path.relative(ROOT, outDir)}`,
    '',
    'Jobs:',
    ...results.map(row => `- L${row.level} ${row.id}: ${row.code === 0 ? (row.classifiedAsBaseline ? 'BASELINE' : 'PASS') : 'FAIL'} (${row.durationMs}ms)`),
  ].join('\n')
  await writeFile(path.join(outDir, 'summary.md'), `${summary}\n`)
  process.stdout.write(`\n${summary}\n`)
  process.exitCode = status === 'PASS' ? 0 : 1
}

process.on('SIGINT', () => {
  for (const child of children) child.kill('SIGTERM')
  process.exit(130)
})

await main()
