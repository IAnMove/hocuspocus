import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

type Task = import('../src/features/activity/lineage.ts').ActivityTaskLike

function task(overrides: Partial<Task> & Pick<Task, 'id'>): Task {
  return {
    root_id: overrides.id, parent_id: null, kind: 'image', title: overrides.id, workflow: 'generation',
    status: 'completed', phase: 'completed', message: 'Done', created_at: 10, updated_at: 10, attempt: 1, max_attempts: 1,
    ...overrides,
  }
}

const agentChange = task({
  id: 'task-agent-1', kind: 'agent', workflow: 'world3d.scene.publish', title: 'Agent · Duelo', created_at: 5, updated_at: 50,
  message: 'world3d.scene.instantiate · world3d.scene.patch ×3 · world3d.scene.publish',
  result_refs: ['w3d-abc-1.world3d.scene.json'],
  metadata: {
    adapter: 'agent', actor: 'agent', tool: 'external_agent', capability: 'world3d.scene.publish', command_id: 'pub-1',
    operations: { 'world3d.scene.instantiate': 1, 'world3d.scene.patch': 3, 'world3d.scene.publish': 1 },
    targets: [
      { kind: 'world3d_scene', id: 'w3d-abc', title: 'Duelo' },
      { kind: 'scene_file', id: 'w3d-abc-1.world3d.scene.json', file: 'w3d-abc-1.world3d.scene.json', editor: 'video3d' },
      { kind: 'not-a-kind', id: 'ignored' },
    ],
  },
})

test('task origin tells agent, Wizard and Studio work apart', async () => {
  const { taskOrigin, taskCapability, isAgentChange } = await import('../src/features/activity/agentOrigin.ts')
  assert.equal(taskOrigin(agentChange), 'agent')
  assert.equal(isAgentChange(agentChange), true)
  assert.equal(taskCapability(agentChange), 'world3d.scene.publish')
  assert.equal(taskOrigin(task({ id: 'gen', metadata: { tool: 'external_agent', actor: 'user', capability: 'generation.image' } })), 'agent')
  assert.equal(taskOrigin(task({ id: 'wiz', metadata: { tool: 'studio', actor: 'wizard' } })), 'wizard')
  assert.equal(taskOrigin(task({ id: 'ui', metadata: { tool: 'studio', actor: 'user' } })), '')
})

test('agent targets keep only known kinds and their operations are counted', async () => {
  const { agentTargets, agentOperations } = await import('../src/features/activity/agentOrigin.ts')
  assert.deepEqual(agentTargets(agentChange).map(item => item.kind), ['world3d_scene', 'scene_file'])
  assert.deepEqual(agentOperations(agentChange), [
    ['world3d.scene.instantiate', 1], ['world3d.scene.patch', 3], ['world3d.scene.publish', 1],
  ])
})

test('the Agents view keeps agent and Wizard groups, newest change first, beyond the default 12', async () => {
  const { groupActivityTasks } = await import('../src/features/activity/lineage.ts')
  const { filterGroupsByOrigin } = await import('../src/features/activity/agentOrigin.ts')
  const many = Array.from({ length: 20 }, (_, index) => task({
    id: `task-agent-${index}`, kind: 'agent', created_at: index, updated_at: 100 - index,
    metadata: { adapter: 'agent', tool: 'external_agent', command_id: `intent-${index}` },
  }))
  const studio = task({ id: 'studio', created_at: 200, updated_at: 200, metadata: { tool: 'studio', actor: 'user' } })
  assert.equal(groupActivityTasks([...many, studio]).length, 12)
  const groups = filterGroupsByOrigin(groupActivityTasks([...many, studio], { terminalLimit: 100, order: 'updated' }), 'agents')
  assert.equal(groups.length, 20)
  assert.equal(groups[0].primary.id, 'task-agent-0')
  assert.ok(!groups.some(group => group.primary.id === 'studio'))
})

test('task snapshots merge with the newer copy winning', async () => {
  const { mergeTaskSnapshots, taskFeedKey } = await import('../src/features/activity/useAgentActivityTasks.ts')
  type Canonical = import('../src/api/client').CanonicalTask
  const older = { ...agentChange, updated_at: 10 } as unknown as Canonical
  const newer = { ...agentChange, updated_at: 60, message: 'newer' } as unknown as Canonical
  const merged = mergeTaskSnapshots([older], [newer])
  assert.equal(merged.length, 1)
  assert.equal(merged[0].message, 'newer')
  assert.equal(taskFeedKey([older, newer]), '2:60')
})

test('an agent change shows its origin, the tools it used and one open button per result', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { groupActivityTasks } = await import('../src/features/activity/lineage.ts')
  const { ActivityExecutionDetail } = await import('../src/features/activity/executionDetail.tsx')
  const group = groupActivityTasks([agentChange])[0]
  try {
    render(
      <ActivityExecutionDetail group={group} clock={60_000} selected={false} expanded={false} busyIds={new Set()} controlFailures={{}}
        onSelect={() => undefined} onToggleExpand={() => undefined} onInspectPrevious={() => undefined} onControl={() => undefined}
        onCopyId={() => undefined} onCopyPrompt={() => undefined} onOpenArtifact={() => undefined} onOpenProject={() => undefined} />,
    )
    assert.ok(document.querySelector('[data-origin="agent"]'))
    assert.equal(screen.getAllByText(/world3d\.scene\.patch ×3/).length, 1)
    assert.ok(screen.getByText('Video 3D scene · Duelo'))
    assert.ok(document.querySelector('[data-target-kind="world3d_scene"]'))
    assert.ok(document.querySelector('[data-target-kind="scene_file"]'))
    // The published file opens in its editor through the agent target, not twice as a gallery artifact.
    assert.equal(screen.queryAllByText(/w3d-abc-1\.world3d\.scene\.json/).length, 1)
  } finally {
    cleanup()
  }
})
