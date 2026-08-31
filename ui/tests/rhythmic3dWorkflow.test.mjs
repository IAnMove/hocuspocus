import assert from 'node:assert/strict'
import test from 'node:test'

const clone = value => JSON.parse(JSON.stringify(value))

function memoryPersistence() {
  let collection = { version: 1, revision: 0, workflows: [] }
  return {
    async load() { return clone(collection) },
    async save(_workspace, next) {
      collection = { ...clone(next), revision: collection.revision + 1 }
      return clone(collection)
    },
  }
}

const action = {
  type: 'create_rhythmic_3d_video', sceneName: 'Arcane pulse', musicPrompt: 'dark synth pulse',
  audioOutputName: '', visualOutputName: 'wizard.glb', layerName: 'Wizard', durationSeconds: 8,
  cueSource: 'beats', profile: 'pulse', intensity: .7, confirm: true,
}

test('a failed song prevents every Video3D mutation', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const { createRhythmic3dWorkflowDefinition } = await import('../src/features/agent/rhythmic3dWorkflow.ts')
  let sceneCalls = 0
  const adapters = {
    studio: { async queueMusic() { throw new Error('song failed') } },
    video3d: { async run() { sceneCalls += 1; throw new Error('must not run') } },
  }
  const runtime = new WizardWorkflowRuntime(memoryPersistence())
  runtime.register(createRhythmic3dWorkflowDefinition(adapters, async () => 'song.wav'))
  await runtime.open('demo')
  const workflow = await runtime.start({ type: 'create_rhythmic_3d_video', workspace: 'demo', userRequest: 'make it', inputSnapshot: action })
  assert.equal(workflow.state, 'failed')
  assert.equal(workflow.currentStep, 0)
  assert.equal(sceneCalls, 0)
})

test('export failure preserves the saved scene and resume retries only export', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const { createRhythmic3dWorkflowDefinition } = await import('../src/features/agent/rhythmic3dWorkflow.ts')
  const calls = []
  let exportCalls = 0
  const adapters = {
    studio: { async queueMusic() { throw new Error('existing audio must not queue') } },
    video3d: { async run(request) {
      calls.push(request.type)
      if (request.type === 'add_3d_scene_layer') return { message: 'layer', target: {}, layerIds: [`id-${request.layerName}`] }
      if (request.type === 'attach_3d_scene_audio') return { message: 'audio', target: {}, audioTrackId: 'track-1', outputNames: ['song.wav'] }
      if (request.type === 'analyze_3d_scene_audio') return { message: 'analyzed', target: {}, analysisId: 'track-1', bpm: 120, beatCount: 4, downbeatCount: 1, rhythmGrid: { duration: 8, bpm: 120, beats: [{ time: 0, strength: 1 }, { time: .5, strength: .8 }], downbeats: [0] } }
      if (request.type === 'save_3d_scene') return { message: 'saved', target: {}, outputNames: ['arcane.scene.json'] }
      if (request.type === 'export_3d_scene') {
        exportCalls += 1
        if (exportCalls === 1) throw new Error('encoder unavailable')
        return { message: 'exported', target: {}, outputNames: ['arcane.mp4'] }
      }
      return { message: request.type, target: {} }
    } },
  }
  const runtime = new WizardWorkflowRuntime(memoryPersistence())
  runtime.register(createRhythmic3dWorkflowDefinition(adapters, async () => 'song.wav'))
  await runtime.open('demo')
  const existingAudio = { ...action, audioOutputName: 'song.wav', musicPrompt: '' }
  const failed = await runtime.start({ workflowId: 'rhythm-1', type: 'create_rhythmic_3d_video', workspace: 'demo', userRequest: 'use song', inputSnapshot: existingAudio })
  assert.equal(failed.state, 'partial')
  assert.ok(failed.outputRefs.includes('arcane.scene.json'))
  assert.equal(calls.filter(type => type === 'analyze_3d_scene_audio').length, 1)
  assert.equal(calls.filter(type => type === 'apply_3d_choreography').length, 2)

  const completed = await runtime.resume('rhythm-1')
  assert.equal(completed.state, 'completed')
  assert.ok(completed.outputRefs.includes('arcane.mp4'))
  assert.equal(calls.filter(type => type === 'save_3d_scene').length, 1)
  assert.equal(calls.filter(type => type === 'analyze_3d_scene_audio').length, 1)
  assert.equal(exportCalls, 2)
})
