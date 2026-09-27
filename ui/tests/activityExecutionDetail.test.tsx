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

test('execution detail distinguishes result from progress and can open artifacts and previous attempts', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { groupActivityTasks } = await import('../src/features/activity/lineage.ts')
  const { ActivityExecutionDetail } = await import('../src/features/activity/executionDetail.tsx')
  const artifacts: string[] = []
  const projects: string[] = []
  const group = groupActivityTasks([{
    id: 'task-root',
    root_id: 'task-root',
    parent_id: null,
    kind: 'generation',
    title: 'Videoclip request',
    workflow: 'generation',
    status: 'failed',
    phase: 'failed',
    message: 'Provider stopped',
    created_at: 10,
    updated_at: 20,
    attempt: 2,
    max_attempts: 3,
    resumable: true,
    recoverable: true,
    cancelable: false,
    error: { message: 'Provider stopped', retryable: true },
    result_refs: ['clip.mp4'],
    metadata: {
      intent_id: 'intent-clip',
      receipt_id: 'intent-clip',
      entity_type: 'story',
      project_id: 'story-1',
      previous_attempts: [{ attempt: 1, status: 'failed', error: 'Seed rejected', created_at: 10 }],
    },
  }])[0]

  try {
    render(
      <ActivityExecutionDetail
        group={group}
        clock={30_000}
        selected
        expanded
        inspectedAttemptId={group.previousAttempt?.id}
        busyIds={new Set()}
        controlFailures={{}}
        onSelect={() => undefined}
        onToggleExpand={() => undefined}
        onInspectPrevious={() => undefined}
        onControl={() => undefined}
        onCopyId={() => undefined}
        onCopyPrompt={() => undefined}
        onOpenArtifact={name => artifacts.push(name)}
        onOpenProject={() => projects.push(group.project?.id || '')}
      />,
    )
    const node = screen.getByRole('group', { name: /Videoclip request/ })
    assert.equal(node.getAttribute('data-reading-state'), 'failed')
    assert.match(node.textContent || '', /Progress/)
    assert.match(node.textContent || '', /Result/)
    assert.match(node.textContent || '', /Failed/)
    assert.match(node.textContent || '', /Provider stopped/)
    fireEvent.click(screen.getByRole('button', { name: 'Open artifact clip.mp4' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open project' }))
    assert.deepEqual(artifacts, ['clip.mp4'])
    assert.deepEqual(projects, ['story-1'])
    assert.ok(screen.getByTestId('activity-previous-attempt'))
    assert.match(screen.getByTestId('activity-previous-attempt').textContent || '', /Seed rejected/)
  } finally {
    cleanup()
  }
})

test('admitted groups expose waiting copy instead of a completed result', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { groupActivityTasks } = await import('../src/features/activity/lineage.ts')
  const { ActivityExecutionDetail } = await import('../src/features/activity/executionDetail.tsx')
  const group = groupActivityTasks([{
    id: 'task-admitted',
    root_id: 'task-admitted',
    kind: 'generation',
    title: 'Queued image',
    workflow: 'generation',
    status: 'queued',
    phase: 'queued',
    message: 'Admitted to the queue',
    created_at: 1,
    updated_at: 1,
    attempt: 1,
    max_attempts: 1,
    backend_job_id: 'job-1',
    metadata: { intent_id: 'intent-q', receipt: { commandId: 'intent-q' } },
  }])[0]
  try {
    render(
      <ActivityExecutionDetail
        group={group}
        clock={1000}
        selected={false}
        expanded={false}
        busyIds={new Set()}
        controlFailures={{}}
        onSelect={() => undefined}
        onToggleExpand={() => undefined}
        onInspectPrevious={() => undefined}
        onControl={() => undefined}
        onCopyId={() => undefined}
        onCopyPrompt={() => undefined}
        onOpenArtifact={() => undefined}
        onOpenProject={() => undefined}
      />,
    )
    assert.equal(screen.getByRole('group').getAttribute('data-reading-state'), 'admitted')
    assert.ok(screen.getByText('Admitted — waiting to run'))
    assert.equal(screen.queryByText('Completed'), null)
  } finally {
    cleanup()
  }
})
