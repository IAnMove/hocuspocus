import assert from 'node:assert/strict'
import test from 'node:test'

const context = await import('../src/features/agent/wizardContext.ts')

test('normalizes a versioned context without turning labels into identities', () => {
  const snapshot = context.normalizeWizardContextSnapshot({
    schema: 'old.schema',
    version: 99,
    captured_at: '2026-08-31T20:00:00.000Z',
    workspace: { id: 'workspace-main', name: 'Main', path: '/tmp/main' },
    active: {
      workspace_id: 'workspace-main',
      location: { area: 'story_lab', tab: 'story_lab', section: 'music' },
      // A title is display metadata, not a durable reference.
      entity: { title: 'El Himno del Sysadmin' },
      project: { id: 'story-42', kind: 'story_project', title: 'El Himno del Sysadmin', version: 7 },
      cue: { id: 'cue-42', kind: 'story_music_cue', title: 'El Himno del Sysadmin · Español' },
      production: { id: 'production-42', kind: 'story_production', title: 'Videoclip' },
      output: {
        id: 'song-output-42.wav', type: 'output', name: 'El Himno del Sysadmin · Español · v2',
        source: '/outputs/song-output-42.wav', task_id: 'task-42', metadata: { duration: 75 },
      },
      job: { id: 'task-42', kind: 'job', status: 'running', phase: 'music', progress: 0.5, message: 'Generando' },
      pipeline: { id: 'pipeline-42', status: 'queued', phase: 'planning', progress: 0, output_files: ['clip-1.mp4'] },
    },
    selection: { page_id: 'page-1', clip_index: 2 },
    drafts: {
      story_lab: { dirty: true, version: 7, schema_version: 1, library_revision: 12, source: 'store' },
    },
    workflow: {
      workflow_id: 'workflow-42', type: 'music_video', state: 'waiting', current_step: 2,
      steps: [{ id: 'step-a' }, { id: 'step-b' }, { id: 'step-c' }],
      task_ids: ['task-42'], pipeline_ids: ['pipeline-42'], output_refs: ['song-output-42.wav'],
      resolved_entity_ids: { project: 'story-42', cue: 'cue-42' }, attempts: 1, updated_at: 123,
    },
    pending_question: {
      id: 'question-42', workflow_id: 'workflow-42', step_id: 'step-c', reason: 'Elige formato',
      fields: ['aspect_ratio'], options: [{ value: '16:9', label: 'Horizontal' }],
      recommended_value: '16:9', resolved_entity_ids: { project: 'story-42' }, answer: { ok: true }, version: 1,
    },
    capabilities: { available: ['open_tab', 'open_tab', 'stage_story_music_video'], blocked: [{ name: 'generate', reason: 'missing audio' }] },
    labs: { story: { project_id: 'story-42', title: 'El Himno del Sysadmin', state: 'ready' } },
  }, 'default')

  assert.equal(snapshot.schema, 'hocuspocus.wizard_context')
  assert.equal(snapshot.version, 1)
  assert.equal(snapshot.workspace.id, 'workspace-main')
  assert.equal(snapshot.active.project?.id, 'story-42')
  assert.equal(snapshot.active.cue?.id, 'cue-42')
  assert.equal(snapshot.active.production?.id, 'production-42')
  assert.equal(snapshot.active.output?.id, 'song-output-42.wav')
  assert.equal(snapshot.active.job?.id, 'task-42')
  assert.equal(snapshot.active.pipeline?.id, 'pipeline-42')
  assert.equal(snapshot.active.entity, null)
  assert.equal(snapshot.workflow?.id, 'workflow-42')
  assert.equal(snapshot.workflow?.step_id, 'step-c')
  assert.equal(snapshot.workflow?.total_steps, 3)
  assert.equal(snapshot.pending_question?.workflow_id, 'workflow-42')
  assert.deepEqual(snapshot.capabilities.available, ['open_tab', 'stage_story_music_video'])
  assert.equal(snapshot.drafts.story_lab.dirty, true)
  assert.equal(snapshot.drafts.story_lab.version, 7)
  assert.equal(snapshot.selection.page_id, 'page-1')
  assert.equal(snapshot.selection.clip_index, 2)
})

test('keeps only references in the snapshot workspace and normalizes task/pipeline/artifact lists', () => {
  const snapshot = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1', name: 'Main' },
    active: { project: { id: 'foreign-project', workspace_id: 'workspace-2' } },
    artifacts: [
      { output_id: 'audio-1', type: 'audio', workspace_id: 'workspace-1', source: '/audio-1.wav' },
      { id: 'audio-1', type: 'audio', workspace_id: 'workspace-1', source: '/duplicate.wav' },
      { id: 'foreign-output', workspace_id: 'workspace-2', source: '/foreign.wav' },
    ],
    tasks: [
      { task_id: 'task-1', workspace_id: 'workspace-1', status: 'running', progress: 1.4 },
      { id: 'task-1', workspace_id: 'workspace-1', status: 'queued' },
      { id: 'foreign-task', workspace_id: 'workspace-2', status: 'running' },
    ],
    pipelines: [
      { pipeline_id: 'pipeline-1', workspace_id: 'workspace-1', status: 'queued' },
      { id: 'foreign-pipeline', workspace_id: 'workspace-2', status: 'running' },
    ],
  })

  assert.equal(snapshot.active.project, null)
  assert.deepEqual(snapshot.artifacts.map(item => item.id), ['audio-1'])
  assert.equal(snapshot.artifacts[0].uri, '/audio-1.wav')
  assert.deepEqual(snapshot.tasks.map(item => item.id), ['task-1'])
  assert.equal(snapshot.tasks[0].progress, 1)
  assert.deepEqual(snapshot.pipelines.map(item => item.id), ['pipeline-1'])
})

test('serializes context read models and removes non-JSON values safely', () => {
  const cyclic = { id: 'entity-1', label: 'Visible label', count: Number.POSITIVE_INFINITY, callback: () => 'nope' }
  cyclic.self = cyclic
  const snapshot = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    active: { entity: cyclic },
  })
  const json = context.serializeWizardContextSnapshot(snapshot)
  const parsed = JSON.parse(json)
  assert.equal(parsed.active.entity.id, 'entity-1')
  assert.equal(parsed.active.entity.count, undefined)
  assert.equal('self' in parsed.active.entity, false)
  assert.equal('callback' in parsed.active.entity, false)
  assert.equal(context.isWizardContextSnapshot(parsed), true)

  const shared = { id: 'shared-output' }
  const sharedSerialized = context.toWizardSerializable({ first: shared, second: shared })
  assert.deepEqual(sharedSerialized, { first: { id: 'shared-output' }, second: { id: 'shared-output' } })
})

test('pending question identity is derived only from canonical workflow and step IDs', () => {
  const snapshot = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    pending_question: {
      workflow_id: 'workflow-1', step_id: 'step-2', title: 'Pregunta humana', reason: 'Falta una opción',
    },
  })
  assert.equal(snapshot.pending_question?.id, 'question:workflow-1:step-2')

  const noIdentity = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' }, pending_question: { title: 'Sólo un título' },
  })
  assert.equal(noIdentity.pending_question, null)

  const nested = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    workflow: {
      workflowId: 'workflow-2', type: 'music_video', state: 'waiting', currentStep: 0,
      steps: [{ stepId: 'step-song' }], resolvedEntityIds: { project: 'project-2' },
      pendingInput: {
        reason: 'Falta el audio', fields: ['audio'],
        options: [{ value: 'song-1', label: 'Canción 1' }, { value: 'song-1', label: 'Duplicada' }],
      },
    },
  })
  assert.equal(nested.workflow?.state, 'awaiting_input')
  assert.equal(nested.pending_question?.id, 'question:workflow-2:step-song')
  assert.deepEqual(nested.pending_question?.resolved_entity_ids, { project: 'project-2' })
  assert.deepEqual(nested.pending_question?.options.map(item => item.value), ['song-1'])
  assert.equal(nested.pending_question?.answer, null)

  const malformed = context.normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    pending_question: { id: 'q-only', reason: 'No owner' },
  })
  assert.equal(malformed.pending_question, null)
})

test('rejects malformed values as canonical snapshots', () => {
  assert.equal(context.isWizardContextSnapshot(null), false)
  assert.equal(context.isWizardContextSnapshot({
    schema: 'hocuspocus.wizard_context', version: 1, workspace: null, active: {},
  }), false)
})
