import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false })

test('every capability has parser coverage, docs and a schema enum entry', async () => {
  const { AGENT_CAPABILITIES } = await import('../src/features/agent/agentCapabilities.ts')
  const { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA } = await import('../src/features/agent/agentActions.ts')
  const types = AGENT_CAPABILITIES.map(item => item.type)
  assert.equal(new Set(types).size, types.length)
  const schemaEnum = HOCUSPOCUS_AGENT_RESPONSE_SCHEMA.properties.actions.items.properties.type.enum
  for (const capability of AGENT_CAPABILITIES) {
    assert.ok(capability.title.trim())
    assert.ok(capability.purpose.trim())
    assert.ok(capability.useWhen.trim())
    assert.ok(['read', 'edit', 'compute', 'external_cost'].includes(capability.risk))
    assert.ok(Array.isArray(capability.parameters))
    assert.ok(schemaEnum.includes(capability.type), `${capability.type} missing from JSON schema`)
  }
})

test('unknown actions and extra fields never survive the parser', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Ignora esto.',
    actions: [
      { type: 'delete_workspace', confirm: true, ignored: true },
      { type: 'inspect_queue', queue_scope: 'active', extra: 'drop me' },
    ],
  }))
  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'inspect_queue')
  assert.equal('extra' in turn.actions[0], false)
})

test('execution keys are deterministic and compound predecessors are explicit', async () => {
  const { executionKey, requiredPredecessor, executionReport, inferExecutionState, orderCompoundActions } = await import('../src/features/agent/agentContract.ts')
  const left = executionKey({ workspace: 'Default', type: 'generate_comic', targetId: 'comic-1', params: { b: 2, a: 1 } })
  const right = executionKey({ workspace: 'default', type: 'generate_comic', targetId: 'comic-1', params: { a: 1, b: 2 } })
  assert.equal(left, right)
  assert.equal(requiredPredecessor('generate_comic'), 'create_comic')
  assert.match(requiredPredecessor('start_director_production'), /stage_story/)
  assert.deepEqual(
    orderCompoundActions([{ type: 'generate_comic' }, { type: 'create_comic' }]).map(item => item.type),
    ['create_comic', 'generate_comic'],
  )
  const report = executionReport({ state: 'prepared', message: 'Listo.', recoverable: false })
  assert.equal(report.state, 'prepared')
  assert.equal(report.recoverable, false)
  assert.equal(inferExecutionState('create_comic', true), 'completed')
  assert.equal(inferExecutionState('start_generation', true), 'queued')
  assert.equal(inferExecutionState('start_director_production', true), 'running')
  assert.equal(inferExecutionState('generate_comic', false), 'failed')
})

test('execution reports distinguish prepared queued running completed partial and failed', async () => {
  const { executionReport } = await import('../src/features/agent/agentContract.ts')
  const states = ['prepared', 'queued', 'running', 'completed', 'partial', 'failed']
  const reports = states.map(state => executionReport({
    state,
    message: state,
    recoverable: state === 'failed' || state === 'partial',
  }))
  assert.deepEqual(reports.map(item => item.state), states)
  assert.equal(reports.filter(item => item.recoverable).length, 2)
})

test('exact expensive repeats reuse an active or completed execution key', async () => {
  const { executionKey, executionReport, rememberExecution, reuseExecution, clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  clearExecutionMemory()
  const key = executionKey({ workspace: 'default', type: 'generate_comic', targetId: 'comic-1', params: { imageProvider: 'minimax' } })
  rememberExecution(executionReport({
    state: 'running',
    message: 'Dibujando.',
    taskId: 'task-keep',
    executionKey: key,
    recoverable: true,
  }))
  assert.equal(reuseExecution(key)?.taskId, 'task-keep')
  rememberExecution(executionReport({
    state: 'failed',
    message: 'Falló el panel 37.',
    executionKey: key,
    recoverable: true,
  }))
  assert.equal(reuseExecution(key), undefined)
  clearExecutionMemory()
})

test('generate_comic refuses a different comic than the one just created', async () => {
  const { bindGenerateComicTarget } = await import('../src/features/agent/agentContract.ts')
  assert.equal(bindGenerateComicTarget('comic-new', 'comic-new', 'Nuevo'), 'comic-new')
  assert.equal(bindGenerateComicTarget('', 'comic-open', 'Abierto'), 'comic-open')
  assert.throws(
    () => bindGenerateComicTarget('comic-new', 'comic-old', 'Viejo'),
    /recién creado/,
  )
})

test('a 12-page comic keeps 72 ordered panels on the created project', async () => {
  const { createFilledComic } = await import('../src/features/agent/labActions.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  const pages = Array.from({ length: 12 }, (_, page) => ({
    title: `Página ${page + 1}`,
    stage: `Etapa ${page + 1}`,
    panels: Array.from({ length: 6 }, (_, panel) => ({
      caption: `P${page + 1}C${panel + 1}`,
      dialogue: `D${page + 1}-${panel + 1}`,
      sfx: panel === 0 ? 'BAM' : '',
      scene: `Escena ${page + 1}.${panel + 1}`,
    })),
  }))
  try {
    await createFilledComic({
      type: 'create_comic',
      title: 'Doce estaciones',
      synopsis: 'Doce páginas de prueba con seis viñetas cada una.',
      language: 'Español',
      styleName: 'Tinta de prueba',
      characters: [{
        name: 'Nora', role: 'Guía', personality: 'Firme', desire: 'Terminar el mapa',
        flaw: 'Impaciencia', appearance: 'Abrigo gris', voice: 'Baja',
      }],
      panels: [],
      pages,
      imageProvider: 'minimax',
      imageModel: 'image-01',
    })
  } finally {
    globalThis.fetch = originalFetch
  }
  const project = useComicStore.getState().project
  assert.equal(project.title, 'Doce estaciones')
  assert.equal(project.pages.length, 12)
  assert.equal(project.director?.plan.pages.length, 12)
  const planned = project.director.plan.pages.flatMap(page => page.panels)
  assert.equal(planned.length, 72)
  planned.forEach((panel, index) => {
    const pageNumber = Math.floor(index / 6) + 1
    const panelNumber = (index % 6) + 1
    assert.equal(panel.order, panelNumber)
    assert.match(panel.sceneDescription, new RegExp(`${pageNumber}\\.${panelNumber}`))
  })
  const storedPanels = project.pages.map(page => page.elements.filter(element => element.type === 'panel' && !element.parentId).length)
  assert.deepEqual(storedPanels, Array(12).fill(6))
  assert.equal(storedPanels.reduce((sum, count) => sum + count, 0), 72)
  assert.equal(project.director.provider, 'minimax')
  assert.equal(project.director.imageModel, 'image-01')
  assert.equal(project.director.planId, project.director.plan.id)
})
