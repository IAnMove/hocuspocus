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

test('navigation and queue registration is complete and idempotent', async () => {
  const { registerNavigationQueueCapabilities } = await import('../src/features/agent/navigationQueueCapabilities.ts')
  const definitions = []
  const registrar = definition => {
    definitions.push(definition)
    return definition
  }

  registerNavigationQueueCapabilities(registrar)
  registerNavigationQueueCapabilities(registrar)

  assert.deepEqual(definitions.map(definition => definition.name), [
    'open_story_section',
    'open_series_section',
    'inspect_queue',
    'cancel_task',
    'resume_task',
    'retry_task',
    'select_workspace',
    'create_workspace',
  ])
  for (const definition of definitions) {
    assert.ok(definition.title)
    assert.ok(definition.description)
    assert.ok(definition.useWhen)
    assert.ok(definition.inputSchema)
    assert.equal(typeof definition.resolve, 'function')
    assert.equal(typeof definition.validate, 'function')
    assert.equal(typeof definition.execute, 'function')
    assert.equal(typeof definition.correlate, 'function')
    assert.equal(typeof definition.track, 'function')
  }
})

test('registered resolvers preserve section, queue, confirmation and workspace contracts', async () => {
  const { registerNavigationQueueCapabilities } = await import('../src/features/agent/navigationQueueCapabilities.ts')
  const definitions = new Map()
  registerNavigationQueueCapabilities(definition => {
    definitions.set(definition.name, definition)
    return definition
  })

  const story = definitions.get('open_story_section')
  assert.deepEqual(story.resolve({ story_section: 'music' }), {
    type: 'open_story_section', section: 'music',
  })
  assert.equal(story.resolve({ story_section: 'unknown' }), null)
  assert.equal(story.validate({ type: 'open_story_section', section: 'assembly' }).length, 0)

  const series = definitions.get('open_series_section')
  assert.deepEqual(series.resolve({ series_section: 'review' }), {
    type: 'open_series_section', section: 'review',
  })
  assert.equal(series.resolve({ series_section: 'unknown' }), null)

  const queue = definitions.get('inspect_queue')
  assert.deepEqual(queue.resolve({}), { type: 'inspect_queue', scope: 'active' })
  assert.deepEqual(queue.resolve({ queue_scope: 'all' }), { type: 'inspect_queue', scope: 'all' })

  for (const type of ['cancel_task', 'resume_task', 'retry_task']) {
    const definition = definitions.get(type)
    assert.deepEqual(definition.resolve({ task_id: 'task-17', confirm: true }), {
      type, taskId: 'task-17', confirm: true,
    })
    assert.equal(definition.resolve({ task_id: 'task-17', confirm: false }), null)
    assert.equal(definition.confirmation, 'required')
  }

  const select = definitions.get('select_workspace')
  assert.deepEqual(select.resolve({ workspace_name: '  Faro  ' }), {
    type: 'select_workspace', workspaceName: 'Faro',
  })
  assert.equal(select.resolve({ workspace_name: '   ' }), null)

  const create = definitions.get('create_workspace')
  assert.deepEqual(create.resolve({ workspace_name: 'Nuevo taller' }), {
    type: 'create_workspace', workspaceName: 'Nuevo taller',
  })
})

test('section capabilities retain the visible lab navigation effect', async () => {
  const { registerNavigationQueueCapabilities } = await import('../src/features/agent/navigationQueueCapabilities.ts')
  const definitions = new Map()
  registerNavigationQueueCapabilities(definition => {
    definitions.set(definition.name, definition)
    return definition
  })
  const events = []
  const onStory = event => events.push(['story', event.detail.section])
  const onSeries = event => events.push(['series', event.detail.section])
  window.addEventListener('hocuspocus:story-section', onStory)
  window.addEventListener('hocuspocus:series-section', onSeries)

  const context = {
    adapters: {
      storyLab: {
        async open() {
          return { message: 'Story Lab abierto', target: { kind: 'application_section', id: 'story_lab', title: 'Story Lab' } }
        },
      },
      seriesLab: {
        async open() {
          return { message: 'Series Lab abierto', target: { kind: 'application_section', id: 'series_lab', title: 'Series Lab' } }
        },
      },
    },
  }

  const storyResult = await definitions.get('open_story_section').execute(
    { type: 'open_story_section', section: 'music' }, context,
  )
  const seriesResult = await definitions.get('open_series_section').execute(
    { type: 'open_series_section', section: 'shots' }, context,
  )
  assert.equal(storyResult.message, 'He abierto Story Lab → music.')
  assert.equal(seriesResult.message, 'He abierto Series Lab → shots.')
  assert.deepEqual(events, [['story', 'music'], ['series', 'shots']])

  window.removeEventListener('hocuspocus:story-section', onStory)
  window.removeEventListener('hocuspocus:series-section', onSeries)
})
