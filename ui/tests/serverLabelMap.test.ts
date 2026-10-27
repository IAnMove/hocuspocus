import assert from 'node:assert/strict'
import test from 'node:test'
import { setUiLanguage } from '../src/i18n/index.ts'
import { resolutionPresetLabel } from '../src/lib/resolutionPresetLabel.ts'
import { workflowStateLabel, workflowStepLabel, workflowTypeLabel } from '../src/features/agent/workflowLabels.ts'

test('resolution presets and workflow codes map to the active language', async () => {
  await setUiLanguage('en')
  assert.equal(resolutionPresetLabel('720p', '720p · aligned'), '720p · aligned')
  assert.equal(resolutionPresetLabel('auto', 'Auto'), 'Auto')
  assert.equal(resolutionPresetLabel('1440p', '1440p · experimental'), '1440p · experimental')
  assert.equal(resolutionPresetLabel('480p'), '480p')
  assert.equal(workflowTypeLabel('create_rhythmic_3d_video'), 'Rhythmic 3D video')
  assert.equal(workflowTypeLabel('wf-unknown'), 'wf-unknown')
  assert.equal(workflowStateLabel('awaiting_input'), 'Needs input')
  assert.equal(workflowStateLabel('not-a-state'), 'not-a-state')
  assert.equal(workflowStepLabel('generation.image'), 'Generate image')
  assert.equal(workflowStepLabel('custom step'), 'custom step')

  await setUiLanguage('es')
  assert.equal(resolutionPresetLabel('768p', '768p · maximum Base canvas'), '768p · lienzo Base máximo')
  assert.equal(resolutionPresetLabel('auto'), 'Auto')
  assert.equal(workflowTypeLabel('image_then_upscale'), 'Imagen y luego ampliar')
  assert.equal(workflowStateLabel('running'), 'En curso')
  assert.equal(workflowStepLabel('export and publish MP4'), 'Exportar y publicar el MP4')
  await setUiLanguage('en')
})
