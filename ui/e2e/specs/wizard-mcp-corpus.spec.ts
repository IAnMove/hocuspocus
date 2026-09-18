import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import {
  askWizard,
  loadWizardMcpCorpus,
  mockPublishedCatalog,
  mockWizardLlm,
  openWizard,
  wizardPanel,
} from '../helpers/wizardMcpCorpus'

const corpus = loadWizardMcpCorpus()
const evidenceDir = process.env.HOCUS_WIZARD_MCP_EVIDENCE || ''

async function snap(page: Page, name: string) {
  const dest = test.info().outputPath(name)
  await page.screenshot({ path: dest, fullPage: true })
  if (evidenceDir) {
    mkdirSync(evidenceDir, { recursive: true })
    await page.screenshot({ path: `${evidenceDir}/${name}`, fullPage: true })
  }
}

test('Wizard refusal does not POST a generation command', async ({ page }) => {
  const session = await gotoApp(page)
  const posts: string[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/generation/commands') {
      posts.push(request.postData() || '')
    }
  })
  try {
    await mockPublishedCatalog(page, corpus)
    await mockWizardLlm(page, corpus)
    const panel = await openWizard(page)
    await snap(page, '01-wizard-open.png')
    const refusal = corpus.cases.find(item => item.id === 'en-negation-do-not-generate')
    const transcript = await askWizard(page, refusal!.request!)
    await expect(panel).toContainText(/No action was executed|Actions not executed|No se ha ejecutado/)
    expect(transcript).not.toContain('invented-boat.png')
    expect(posts).toEqual([])
    await snap(page, '02-wizard-refusal.png')
  } finally {
    await closeApp(page, session)
  }
})

test('unpublished Wizard tool shows a rejection instead of success', async ({ page }) => {
  const session = await gotoApp(page)
  try {
    await mockPublishedCatalog(page, corpus)
    await mockWizardLlm(page, corpus)
    const panel = await openWizard(page)
    const unpublished = corpus.cases.find(item => item.id === 'es-unpublished-unknown-action')
    const transcript = await askWizard(page, unpublished!.request!)
    await expect(panel).toContainText('Actions not executed')
    await expect(panel).toContainText('generation_video')
    expect(transcript).not.toMatch(/invented\.mp4/)
    await snap(page, '03-wizard-unpublished.png')
  } finally {
    await closeApp(page, session)
  }
})

test('queued receipt stays queued and is not a finished movie', async ({ page }) => {
  const session = await gotoApp(page)
  const messages = [
    { id: 'user-1', role: 'user', text: 'Prepare a Flux image of a lantern and generate it now.', createdAt: 1 },
    {
      id: 'asst-1',
      role: 'assistant',
      text: '### Execution results\n- **Queued.** Submitted job-corpus-1. Task task-corpus-1.',
      createdAt: 2,
    },
  ]
  try {
    await page.addInitScript(values => {
      localStorage.setItem('hocuspocus-agent-chat-v2:default', JSON.stringify(values))
      localStorage.setItem('hocuspocus-wizard-sidebar-collapsed', 'false')
    }, messages)
    await page.reload()
    await openWizard(page)
    const panel = wizardPanel(page)
    await expect(panel).toContainText('Queued')
    await expect(panel).toContainText('job-corpus-1')
    await expect(panel).not.toContainText('invented.mp4')
    await snap(page, '04-wizard-queued-receipt.png')
  } finally {
    await closeApp(page, session)
  }
})

test('MCP client tour: published tools, replayed ID, unpublished error', async ({ page }) => {
  const session = await gotoApp(page)
  try {
    await mockPublishedCatalog(page, corpus)
    await mockWizardLlm(page, corpus)
    await openWizard(page)
    const report = await page.evaluate(async published => {
      const headers = { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' }
      const listed = await (await fetch('/api/v1/wangp/mcp', {
        method: 'POST', headers,
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      })).json()
      const tools = (listed.result.tools as Array<{ name: string }>).map(item => item.name)
      const command = {
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/call',
        params: {
          name: 'generation.image',
          arguments: {
            version: 1,
            intent_id: 'e2e-timeout',
            input: { workspace: 'default', model_type: 'pi_flux2', prompt: 'a lantern', resolution: '512x512', num_inference_steps: 1, seed: 1, guidance_scale: 1 },
          },
        },
      }
      const first = await (await fetch('/api/v1/wangp/mcp', { method: 'POST', headers, body: JSON.stringify(command) })).json()
      const second = await (await fetch('/api/v1/wangp/mcp', { method: 'POST', headers, body: JSON.stringify({ ...command, id: 3 }) })).json()
      const unpublished = await (await fetch('/api/v1/wangp/mcp', {
        method: 'POST', headers,
        body: JSON.stringify({
          jsonrpc: '2.0', id: 4, method: 'tools/call',
          params: { name: 'generation.video', arguments: { version: 2, intent_id: 'e2e-video', input: { workspace: 'default' } } },
        }),
      })).json()
      const denied = await fetch('/api/v1/wangp/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 5, method: 'tools/list' }),
      })
      return {
        tools,
        published: published.every((name: string) => tools.includes(name)),
        videoListed: tools.includes('generation.video'),
        firstId: first.result.structuredContent.receipt.result.job_id,
        secondId: second.result.structuredContent.receipt.result.job_id,
        replayed: second.result.structuredContent.replayed,
        unpublishedError: unpublished.result.isError,
        unauthorized: denied.status,
      }
    }, corpus.published_operations)
    expect(report.published).toBe(true)
    expect(report.videoListed).toBe(false)
    expect(report.firstId).toBe(report.secondId)
    expect(report.replayed).toBe(true)
    expect(report.unpublishedError).toBe(true)
    expect(report.unauthorized).toBe(401)
    await page.evaluate(result => {
      const pre = document.createElement('pre')
      pre.dataset.testid = 'mcp-corpus-report'
      pre.textContent = JSON.stringify(result, null, 2)
      document.body.appendChild(pre)
    }, report)
    await expect(page.locator('[data-testid="mcp-corpus-report"]')).toContainText(report.firstId)
    await snap(page, '05-mcp-client-tour.png')
  } finally {
    await closeApp(page, session)
  }
})
