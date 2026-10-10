import assert from 'node:assert/strict'
import test from 'node:test'
import type { Hunyuan3DModel } from '../src/api/model3d'
import { model3dInputState } from '../src/lib/model3dInputState'

const model: Hunyuan3DModel = {
  id: 'pixal3d', label: 'Pixal3D', engine: 'pixal3d', repo: 'TencentARC/Pixal3D',
  subfolder: '', parameters: '', multiview: false, turbo: false,
  supports_text: false, recommended_vram_gb: null, description: '',
  runtime: { installed: false, install_hint: 'Configure runtime' },
}
const input = { model, provider: 'local', operation: 'generate' as const,
  runtimeInstalled: true, hasSource: false, hasFront: false,
  hasPrompt: true, textureMode: 'native-pbr' }

test('TRELLIS cannot run before explicit weights download or on incompatible hardware', () => {
  for (const runtime of [
    { installed: true, compatible: true, weights_downloaded: false, install_hint: 'Download weights' },
    { installed: true, compatible: false, weights_downloaded: true, install_hint: 'Linux NVIDIA 24GB required' },
    { installed: false, compatible: true, weights_downloaded: true, install_hint: 'Install optional runtime' },
  ]) {
    const state = model3dInputState({ ...input, hasFront: true, model: { ...model, id: 'trellis2', engine: 'trellis2', runtime } })
    assert.equal(state.canRun, false)
  }
  const state = model3dInputState({ ...input, hasFront: true, model: { ...model, id: 'trellis2', engine: 'trellis2',
    runtime: { installed: true, compatible: true, weights_downloaded: true, install_hint: null } } })
  assert.equal(state.canRun, true)
})

test('a Hunyuan installation cannot enable Pixal3D and text cannot replace its image', () => {
  const state = model3dInputState(input)
  assert.equal(state.installed, false)
  assert.equal(state.hasInput, false)
  assert.equal(state.canRun, false)
  assert.equal(state.isMultiview, false)
})

test('an external runtime can be configured without Hunyuan installed', () => {
  const state = model3dInputState({ ...input, runtimeInstalled: false, hasFront: true,
    model: { ...model, runtime: { installed: true, install_hint: null } } })
  assert.equal(state.installed, true)
  assert.equal(state.hasInput, true)
  assert.equal(state.canRun, true)
})

test('a loaded Hunyuan image cannot enable generate when the runtime is missing', () => {
  const hunyuan = { ...model, id: 'hunyuan3d-2-turbo', engine: 'v2' as const, label: 'Hunyuan3D 2 Turbo' }
  const state = model3dInputState({ ...input, model: hunyuan, runtimeInstalled: false, hasFront: true, hasPrompt: false })
  assert.equal(state.installed, false)
  assert.equal(state.hasInput, true)
  assert.equal(state.canRun, false)
})

test('Hunyuan multiview and retexture retain their input requirements', () => {
  const local = { ...model, engine: 'v2' as const, multiview: true }
  assert.equal(model3dInputState({ ...input, model: local }).hasInput, false)
  assert.equal(model3dInputState({ ...input, model: local, hasFront: true }).hasInput, true)
  assert.equal(model3dInputState({ ...input, model: local, operation: 'retexture' }).hasInput, false)
  assert.equal(model3dInputState({ ...input, model: local, operation: 'retexture', hasSource: true }).hasInput, true)
})
