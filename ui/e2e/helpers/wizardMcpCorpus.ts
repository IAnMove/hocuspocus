import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, type Page } from '@playwright/test'

export interface WizardMcpCorpusCase {
  id: string
  lang: 'en' | 'es'
  kind: string
  surface: 'wizard' | 'mcp' | 'both'
  request?: string
  proposal?: { reply?: string; actions: unknown[] }
  expect: {
    action_types?: string[]
    forbidden_action_types?: string[]
    creates_task?: boolean
    promise_success?: boolean
    unpublished?: boolean
    mcp_is_error?: boolean
    reply_must_not_match?: string[]
  }
}

export interface WizardMcpCorpus {
  published_operations: string[]
  unpublished_operations: string[]
  cases: WizardMcpCorpusCase[]
}

const corpusPath = join(dirname(fileURLToPath(import.meta.url)), '../../../tests/fixtures/wizard_mcp_corpus.json')

export function loadWizardMcpCorpus(): WizardMcpCorpus {
  return JSON.parse(readFileSync(corpusPath, 'utf8')) as WizardMcpCorpus
}

export function wizardPanel(page: Page) {
  return page.locator('.hp-agent-panel')
}

export async function openWizard(page: Page) {
  await page.evaluate(() => window.dispatchEvent(new Event('hocuspocus:wizard-open')))
  const panel = wizardPanel(page)
  await expect(panel).toBeVisible()
  return panel
}

export async function mockWizardLlm(page: Page, corpus: WizardMcpCorpus) {
  const proposals = Object.fromEntries(
    corpus.cases
      .filter(item => item.request && item.proposal)
      .map(item => [item.request, item.proposal]),
  )
  await page.route('**/api/v1/llm/generate', async route => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    const body = route.request().postDataJSON() as { prompt?: string }
    const prompt = String(body.prompt || '')
    const matched = Object.entries(proposals).find(([request]) => prompt.includes(request))
    const proposal = matched?.[1] || { reply: 'No action.', actions: [] }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ text: JSON.stringify(proposal) }),
    })
  })
}

export async function mockPublishedCatalog(page: Page, corpus: WizardMcpCorpus) {
  const operations = corpus.published_operations.map(name => ({
    name,
    version: name === 'generation.image' ? 2 : 1,
    mutation: name !== 'generation.receipt',
    description: name,
    inputSchema: { type: 'object', properties: {}, required: [] },
  }))
  const admissions = new Map<string, { job_id: string; task_id: string; intent_id: string }>()
  await page.route('**/api/v1/generation/commands', async route => {
    const method = route.request().method()
    if (method === 'GET') {
      await route.fulfill({ json: { version: 2, operations } })
      return
    }
    if (method === 'POST') {
      const body = route.request().postDataJSON() as { operation?: string; intent_id?: string }
      if (body.operation === 'generation.video') {
        await route.fulfill({ status: 422, json: { detail: { code: 'invalid_command', message: 'Unknown command operation' } } })
        return
      }
      const intent = String(body.intent_id || 'missing')
      const existing = admissions.get(intent)
      const job_id = existing?.job_id || `job-${intent}`
      const task_id = existing?.task_id || `task-${intent}`
      admissions.set(intent, { job_id, task_id, intent_id: intent })
      await route.fulfill({
        json: {
          receipt: {
            version: 1,
            commandId: intent,
            operation: body.operation,
            status: 'queued',
            entities: [],
            artifacts: [],
            taskIds: [task_id],
            pipelineIds: [],
            result: { job_id, task_id, workspace: 'default', status: 'queued' },
          },
          replayed: Boolean(existing),
        },
      })
      return
    }
    await route.fallback()
  })
  await page.route('**/api/v1/wangp/mcp', async route => {
    if (route.request().method() !== 'POST') {
      await route.fulfill({ status: 405, json: { detail: 'POST only' } })
      return
    }
    const message = route.request().postDataJSON() as {
      id?: number
      method?: string
      params?: { name?: string; arguments?: { intent_id?: string; version?: number; input?: { intent_id?: string } } }
    }
    const auth = route.request().headers()['authorization']
    if (auth !== 'Bearer test-token') {
      await route.fulfill({ status: 401, json: { detail: 'Invalid MCP credentials' } })
      return
    }
    if (message.method === 'tools/list') {
      await route.fulfill({
        json: {
          jsonrpc: '2.0',
          id: message.id,
          result: {
            tools: [
              ...corpus.published_operations.map(name => ({ name, description: name })),
              { name: 'models', description: 'Discover models' },
            ],
          },
        },
      })
      return
    }
    if (message.method === 'tools/call' && message.params?.name === 'generation.video') {
      await route.fulfill({
        json: {
          jsonrpc: '2.0',
          id: message.id,
          result: { isError: true, content: [{ type: 'text', text: 'Unknown tool or invalid arguments' }] },
        },
      })
      return
    }
    if (message.method === 'tools/call' && message.params?.name === 'generation.image') {
      const intent = String(message.params.arguments?.intent_id || 'mcp-intent')
      const existing = admissions.get(intent)
      const job_id = existing?.job_id || `job-${intent}`
      const task_id = existing?.task_id || `task-${intent}`
      admissions.set(intent, { job_id, task_id, intent_id: intent })
      await route.fulfill({
        json: {
          jsonrpc: '2.0',
          id: message.id,
          result: {
            isError: false,
            structuredContent: {
              receipt: { result: { job_id }, taskIds: [task_id], status: 'queued' },
              replayed: Boolean(existing),
            },
          },
        },
      })
      return
    }
    if (message.method === 'tools/call' && message.params?.name === 'generation.receipt') {
      const intent = String(message.params.arguments?.input?.intent_id || '')
      const existing = admissions.get(intent)
      if (!existing) {
        await route.fulfill({
          json: {
            jsonrpc: '2.0',
            id: message.id,
            result: { isError: true, content: [{ type: 'text', text: 'receipt_not_found' }] },
          },
        })
        return
      }
      await route.fulfill({
        json: {
          jsonrpc: '2.0',
          id: message.id,
          result: {
            isError: false,
            structuredContent: { receipt: { result: { job_id: existing.job_id }, taskIds: [existing.task_id] } },
          },
        },
      })
      return
    }
    await route.fulfill({
      json: { jsonrpc: '2.0', id: message.id, result: { isError: true, content: [{ type: 'text', text: 'Unhandled' }] } },
    })
  })
}

export async function askWizard(page: Page, request: string) {
  const panel = wizardPanel(page)
  const input = panel.getByPlaceholder('Ask HocusPocus for a spell…')
  await input.fill(request)
  await panel.getByRole('button', { name: 'Ask to the Wizard', exact: true }).click()
  await expect(input).toBeEnabled({ timeout: 20_000 })
  return (await panel.textContent()) || ''
}
