import assert from 'node:assert/strict'
import test from 'node:test'
import { explainAvailability, modelsOf, operationsOf } from '../src/features/diagnostics/availability.ts'
import { packContainsSecret } from '../src/features/diagnostics/redact.ts'
import { fetchReportPack, fetchSnapshot } from '../src/features/diagnostics/api.ts'
import { parsePack, reportFilename, serializeReportPack } from '../src/features/diagnostics/report.ts'
import { DIAGNOSTICS_SCHEMA, type AvailabilityItem, type ReportPack } from '../src/features/diagnostics/types.ts'

const SECRETS = [
  'sk-test-h18-secret-9f3a2c1b',
  'h18-cookie-value-do-not-export',
  'h18-token-xyz-private',
  'PRIVATE_PROMPT_do_not_include_in_pack',
  'secret-lyrics-never-export',
]

function sampleItem(overrides: Partial<AvailabilityItem> = {}): AvailabilityItem {
  return {
    kind: 'operation',
    id: 'generation.image',
    available: false,
    component: 'wangp',
    driver: null,
    backend: 'none',
    ram_gb_observed: 32,
    vram_gb_observed: null,
    version: { app: '0.9.0', recipe: 'linux-x64-nvidia-wangp', python: '3.10', torch: '2.7.0', cuda: '12.8' },
    repair_path: {
      id: 'cpu_amd_recipe',
      summary: 'Local AI installation currently requires NVIDIA; CPU/AMD/Intel/MPS recipes are not enabled.',
    },
    reasons: ['No NVIDIA driver/backend was observed; local generation recipes require NVIDIA.'],
    weights: 'not_probed',
    ...overrides,
  }
}

function samplePack(overrides: Partial<ReportPack> = {}): ReportPack {
  return {
    schema: DIAGNOSTICS_SCHEMA,
    schema_version: 1,
    generated_at: '2026-09-11T00:00:00Z',
    build: { app_version: '0.9.0', git_revision: 'deadbeef', ui_build_id: 'missing' },
    platform: { os: 'linux', architecture: 'x64', python: '3.10.12', gpu: 'unknown', gpu_name: null, driver: null, backend: 'none' },
    observed: { ram_gb: 32, vram_gb: null, cpu_count: 8 },
    capabilities: { engines: [] },
    availability: [sampleItem(), sampleItem({ kind: 'model', id: 'flux2_klein_4b' })],
    error: null,
    ...overrides,
  }
}

test('explainAvailability states facts and the existing repair path', () => {
  const text = explainAvailability(sampleItem())
  assert.match(text, /component=wangp/)
  assert.match(text, /driver=unverified/)
  assert.match(text, /backend=none/)
  assert.match(text, /ram_gb_observed=32/)
  assert.match(text, /vram_gb_observed=n\/a/)
  assert.match(text, /version=linux-x64-nvidia-wangp/)
  assert.match(text, /repair_path=cpu_amd_recipe/)
  assert.match(text, /requires NVIDIA/)
})

test('sanitizePack drops prompts cookies and synthetic secrets', () => {
  const dirty = {
    schema: DIAGNOSTICS_SCHEMA,
    schema_version: 1,
    prompt: 'PRIVATE_PROMPT_do_not_include_in_pack',
    lyrics: 'secret-lyrics-never-export',
    api_key: 'sk-test-h18-secret-9f3a2c1b',
    cookie: 'session=h18-cookie-value-do-not-export',
    authorization: 'Bearer h18-token-xyz-private',
    message: 'failed Cookie: session=h18-cookie-value-do-not-export api_key=sk-test-h18-secret-9f3a2c1b',
    availability: [],
    build: {},
    platform: { os: 'linux', architecture: 'x64', backend: 'none' },
    observed: { ram_gb: 1, vram_gb: null },
    capabilities: { engines: [] },
    error: { task_id: 'task-h18', intent_id: 'intent-h18' },
  }
  const pack = parsePack(dirty)
  const blob = serializeReportPack(pack)
  for (const secret of SECRETS) {
    assert.equal(packContainsSecret(pack, secret), false, secret)
    assert.equal(blob.includes(secret), false, secret)
  }
  assert.equal('prompt' in pack, false)
  assert.equal(pack.error?.task_id, 'task-h18')
  assert.equal(pack.error?.intent_id, 'intent-h18')
})

test('report filename and operation/model split stay small', () => {
  const pack = samplePack()
  assert.equal(reportFilename('2026-09-11'), 'hocuspocus-diagnostics-2026-09-11.json')
  assert.equal(operationsOf(pack.availability).length, 1)
  assert.equal(modelsOf(pack.availability).length, 1)
})

test('fetch helpers post correlation ids and parse the pack', async () => {
  const pack = samplePack({
    error: { task_id: 'task-h18', intent_id: 'intent-h18', operation: 'generation.image' },
  })
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const fetcher: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return new Response(JSON.stringify(pack), { headers: { 'Content-Type': 'application/json' } })
  }
  const snapshot = await fetchSnapshot(fetcher)
  const report = await fetchReportPack(
    { task_id: 'task-h18', intent_id: 'intent-h18', workspace: 'ws' },
    fetcher,
  )
  assert.equal(snapshot.schema, DIAGNOSTICS_SCHEMA)
  assert.equal(report.error?.task_id, 'task-h18')
  assert.equal(calls[0].url, '/api/v1/diagnostics')
  assert.equal(calls[1].url, '/api/v1/diagnostics/report')
  assert.equal(calls[1].init?.method, 'POST')
  assert.equal(JSON.parse(String(calls[1].init?.body)).intent_id, 'intent-h18')
})

test('sanitizePack is a defense in depth on already-clean packs', () => {
  const blob = serializeReportPack(samplePack())
  for (const secret of SECRETS) assert.equal(blob.includes(secret), false)
})
