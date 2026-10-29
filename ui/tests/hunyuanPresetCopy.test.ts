import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { hunyuanPresetCopy } from '../src/components/Sidebar/hunyuanPresetCopy.ts'
import { resources } from '../src/i18n/resources.ts'

async function sceneT(language: 'en' | 'es') {
  const instance = i18n.createInstance()
  await instance.use(initReactI18next).init({
    resources,
    lng: language,
    fallbackLng: 'en',
    ns: ['scene3d'],
    defaultNS: 'scene3d',
    interpolation: { escapeValue: false },
    returnNull: false,
  })
  return instance.getFixedT(language, 'scene3d')
}

test('Hunyuan preset copy is keyed by preset id', async () => {
  const spanish = await sceneT('es')
  const balanced = hunyuanPresetCopy(spanish, {
    id: 'balanced',
    label: 'Balanced',
    description: 'Full-size Turbo geometry with standard texture support.',
  })
  assert.equal(balanced.label, 'Equilibrado')
  assert.equal(balanced.description, 'Geometría Turbo a tamaño completo, con textura estándar.')

  const english = await sceneT('en')
  const eco = hunyuanPresetCopy(english, {
    id: 'eco',
    label: 'Low VRAM',
    description: 'Mini Turbo, CPU offload, 128 octree, no texture.',
  })
  assert.equal(eco.label, 'Low VRAM')
  assert.equal(eco.description, 'Mini Turbo, CPU offload, 128 octree, no texture.')

  const unknown = hunyuanPresetCopy(spanish, {
    id: 'future-preset',
    label: 'Future',
    description: 'Server text',
  })
  assert.equal(unknown.label, 'Future')
  assert.equal(unknown.description, 'Server text')
})
