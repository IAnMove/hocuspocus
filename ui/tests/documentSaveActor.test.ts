import assert from 'node:assert/strict'
import { test } from 'node:test'
import { documentSaveHeaders } from '../src/lib/documentSaveActor.ts'
import { listenForAgentSceneControl, listenForAgentSceneWorkflow, requestAgentSceneControl, requestAgentSceneWorkflow } from '../src/lib/uiBus.ts'

test('a wizard scene action marks the document save and a later save does not', async () => {
  const previous = (globalThis as { window?: EventTarget }).window
  ;(globalThis as { window?: EventTarget }).window = new EventTarget()
  try {
    assert.deepEqual(documentSaveHeaders(), {})
    const stopWorkflow = listenForAgentSceneWorkflow(async () => {
      assert.deepEqual(documentSaveHeaders(), { 'X-Hocus-UI-Surface': 'wizard' })
      return { message: 'saved' }
    })
    await requestAgentSceneWorkflow({
      type: 'create_3d_scene', sceneName: 'Plaza', durationSeconds: 4, width: 1280, height: 720, fps: 24,
    })
    assert.deepEqual(documentSaveHeaders(), {})
    stopWorkflow()

    const stopControl = listenForAgentSceneControl(async () => {
      assert.deepEqual(documentSaveHeaders(), { 'X-Hocus-UI-Surface': 'wizard' })
      return 'saved'
    })
    await requestAgentSceneControl({ type: 'save_3d_scene', sceneName: 'Plaza' })
    assert.deepEqual(documentSaveHeaders(), {})
    stopControl()
  } finally {
    if (previous === undefined) delete (globalThis as { window?: EventTarget }).window
    else (globalThis as { window?: EventTarget }).window = previous
  }
})
