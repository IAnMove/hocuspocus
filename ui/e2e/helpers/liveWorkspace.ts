import { createHash } from 'node:crypto'
import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import { isOwnedWorkspace, liveQueryViolation, liveTaskTarget, liveWriteViolation } from './liveWorkspacePolicy'
import { liveJson } from './liveRead'

export interface LiveSystemConfig {
  execution_mode?: string
  execution_workspace?: string
  execution_simulation_step_delay?: number
}

const workspaces = new WeakMap<TestInfo, string>()
const expectedMode = process.env.HOCUSPOCUS_E2E_PROFILE || 'simulate'
const runPrefix = process.env.HOCUSPOCUS_E2E_WORKSPACE || `e2e_acceptance_${Date.now().toString(36)}`

export async function liveConfig(request: APIRequestContext, info: TestInfo): Promise<LiveSystemConfig> {
  const response = await request.get('/api/v1/system-config')
  expect(response.ok(), `system-config HTTP ${response.status()}`).toBeTruthy()
  const config = await response.json() as LiveSystemConfig
  expect(config.execution_mode).toBe(expectedMode)
  if (!workspaces.has(info)) {
    const suffix = createHash('sha256').update(info.testId).digest('hex').slice(0, 8)
    const chosen = expectedMode === 'real' ? `${runPrefix}_${suffix}_${Date.now().toString(36)}` : config.execution_workspace
    if (!chosen || !/^e2e[_-][a-zA-Z0-9_-]+$/.test(chosen)) throw Error('Acceptance needs an e2e_ test workspace')
    workspaces.set(info, chosen)
  }
  return { ...config, execution_workspace: workspaces.get(info) }
}

export async function isolateLiveWorkspace(page: Page, request: APIRequestContext, info: TestInfo) {
  const config = await liveConfig(request, info)
  if (expectedMode === 'real') expect(process.env.HOCUSPOCUS_E2E_CONFIRM_REAL).toBe('YES')
  const workspace = config.execution_workspace!
  const listingResponse = await request.get('/api/v1/workspaces')
  expect(listingResponse.ok()).toBeTruthy()
  const listing = await listingResponse.json() as { active: string; workspaces: Array<{ name: string }> }
  if (!listing.workspaces.some(item => item.name === workspace)) {
    const created = await request.post('/api/v1/workspaces', { data: { name: workspace } })
    expect(created.ok(), `create workspace HTTP ${created.status()}`).toBeTruthy()
  }
  let selected = workspace
  const intercepted: Array<{ method: string; path: string; reason: string }> = []
  const nativeWrites: Array<{ method: string; path: string }> = []
  const browserPreferences = new Map<string, Record<string, unknown>>()
  const preferencePaths = new Set(['/api/v1/model-selections', '/api/v1/model-visibility', '/api/v1/production-profile'])
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method()
    if (url.pathname === '/api/v1/jobs/recovery' && method === 'GET') {
      const response = await route.fetch()
      const data = await response.json()
      intercepted.push({ method, path: url.pathname, reason: 'recovery listing restricted to this test workspace; saved queue preserved' })
      await route.fulfill({ response, json: { ...data, jobs: data.jobs.filter((job: { workspace?: string }) => isOwnedWorkspace(job.workspace, workspace)) } })
      return
    }
    if (url.pathname === '/api/v1/workspaces' && method === 'GET') {
      const response = await route.fetch()
      const data = await response.json()
      await route.fulfill({ response, json: { ...data, active: selected } })
      return
    }
    let payload: unknown
    try { payload = req.postDataJSON() } catch { /* upload/form requests retain their original body */ }
    if (preferencePaths.has(url.pathname)) {
      if (method === 'PUT') {
        const baseline = browserPreferences.get(url.pathname) ?? await (await request.get(url.pathname)).json()
        const value = { ...baseline, ...payload as object, configured: true }
        browserPreferences.set(url.pathname, value)
        intercepted.push({ method, path: url.pathname, reason: 'browser-only test preference; global preference preserved' })
        await route.fulfill({ json: value })
        return
      }
      if (method === 'GET' && browserPreferences.has(url.pathname)) {
        await route.fulfill({ json: browserPreferences.get(url.pathname) })
        return
      }
    }
    if (url.pathname === '/api/v1/workspaces/active' && method === 'PUT') {
      const name = (payload as { name?: unknown })?.name
      if (isOwnedWorkspace(name, workspace)) {
        const response = await request.get('/api/v1/workspaces')
        const data = await response.json() as { workspaces: Array<{ name: string }> }
        if (data.workspaces.some(item => item.name === name)) {
          selected = name
          intercepted.push({ method, path: url.pathname, reason: 'browser-only test selection; server active folder preserved' })
          await route.fulfill({ json: { status: 'ok', active: selected } })
          return
        }
      }
    }
    let reason = liveWriteViolation(method, url.pathname, payload, workspace) || liveQueryViolation(method, url.searchParams, workspace)
    const id = liveTaskTarget(method, url.pathname)
    if (!reason && id) {
      const response = await request.get(`/api/v1/tasks?workspace=${encodeURIComponent(selected)}&status=all`)
      const data = await response.json() as { tasks: Array<{ id: string; backend_job_id?: string; pipeline_id?: string; workspace?: string }> }
      if (!response.ok() || !data.tasks?.some(task => isOwnedWorkspace(task.workspace, workspace) && [task.id, task.backend_job_id, task.pipeline_id].includes(id))) reason = 'task mutation outside the selected test workspace'
    }
    if (reason) {
      intercepted.push({ method, path: url.pathname, reason })
      await route.fulfill({ status: 409, json: { detail: `Acceptance isolation: ${reason}` } })
      return
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) nativeWrites.push({ method, path: url.pathname })
    await route.continue()
  })
  await page.addInitScript(() => {
    localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    localStorage.setItem('hocuspocus_welcome_seen_v2', '453')
    localStorage.setItem('hocuspocus-ui-language', 'en')
  })
  return {
    workspace,
    selected: () => selected,
    async evidence() {
      const current = await liveJson(request, '/api/v1/workspaces').catch(error => ({ observationError: String(error) }))
      await info.attach('workspace-isolation', { body: JSON.stringify({ workspace, serverActiveBefore: listing.active, serverActiveAfter: current.active ?? null, observationError: current.observationError, selectedInBrowser: selected, intercepted, nativeWrites, note: 'Workspace selection and shared model/profile preferences are confined to this browser. Their server persistence is not tested. Model inference, Wizard LLM, queue, project persistence and media are live. Test outputs are preserved.' }, null, 2), contentType: 'application/json' })
    },
  }
}
