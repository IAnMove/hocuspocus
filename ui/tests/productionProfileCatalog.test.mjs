import test from 'node:test'
import assert from 'node:assert/strict'
import {
  defaultImageModel,
  defaultModel3dModel,
  defaultTextModel,
  keepCurrentOption,
  listedTextModels,
  model3dProfileOptions,
  textModelOptions,
} from '../src/lib/productionProfileCatalog.ts'

test('text model options keep the current value and filter by provider', () => {
  const models = [
    { id: 'gemma-local', label: 'Gemma', size_hint: 'local', provider: 'local' },
    { id: 'qwen3:32b', label: 'qwen3:32b (Ollama)', size_hint: 'ollama', provider: 'ollama' },
  ]
  const ollama = textModelOptions(models, 'ollama', 'MiniMax-M3')
  assert.deepEqual(ollama.map(option => option.id), ['MiniMax-M3', 'qwen3:32b'])
  const local = textModelOptions(models, 'local', 'gemma-local')
  assert.deepEqual(local.map(option => option.id), ['gemma-local'])
})

test('keepCurrentOption does not duplicate an id that is already listed', () => {
  const options = keepCurrentOption([{ id: 'a', label: 'A' }], 'a')
  assert.equal(options.length, 1)
})

test('switching text provider drops a model that belongs to another API', () => {
  const models = [
    { id: 'gemma-local', label: 'Gemma', size_hint: 'local', provider: 'local' },
  ]
  assert.equal(defaultTextModel('deepseek', 'MiniMax-M3', models), 'deepseek-v4-pro')
  assert.equal(defaultTextModel('minimax', 'deepseek-v4-pro', models), 'MiniMax-M3')
  assert.equal(defaultTextModel('ollama', 'MiniMax-M3', models), '')
  assert.deepEqual(listedTextModels(models, 'deepseek').map(option => option.id), [
    'deepseek-v4-pro',
    'deepseek-v4-flash',
  ])
})

test('3D catalog is provider-specific so Meshy/Hi3D never inherit Hunyuan ids', () => {
  const hunyuan = [{ id: 'hunyuan3d-2mini-turbo', label: 'Hunyuan 2 Mini Turbo' }]
  assert.deepEqual(model3dProfileOptions('meshy', hunyuan).map(option => option.id), ['latest'])
  assert.deepEqual(model3dProfileOptions('hi3d', hunyuan).map(option => option.id), ['hitem3dv2.1'])
  assert.deepEqual(model3dProfileOptions('local', hunyuan).map(option => option.id), [
    'hunyuan3d-2mini-turbo',
  ])
  assert.equal(defaultModel3dModel('meshy'), 'latest')
  assert.equal(defaultModel3dModel('hi3d'), 'hitem3dv2.1')
})

test('local image defaults off image-01 when that id is not installed', () => {
  const local = [{ id: 'qwen_image', label: 'Qwen Image' }]
  assert.equal(defaultImageModel('minimax', local, 'qwen_image'), 'image-01')
  assert.equal(defaultImageModel('local', local, 'image-01'), 'qwen_image')
  assert.equal(defaultImageModel('local', local, 'qwen_image'), 'qwen_image')
})
