import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { ensureUiI18n } from '../src/i18n'
import { initiatorText } from '../src/features/activity/agentOrigin'
import { generationInitiator, generationRecipe } from '../src/features/activity/taskPresentation'
import type { ActivityTaskLike } from '../src/features/activity/lineage'

ensureUiI18n()

const task = (extra: Partial<ActivityTaskLike>): ActivityTaskLike => ({
  id: 'task-1',
  root_id: 'task-1',
  status: 'succeeded',
  created_at: 1,
  updated_at: 1,
  ...extra,
})

const translate = (language: 'en' | 'es') => (key: string, options?: object) => (
  i18n.t(key, { ns: 'activity', lng: language, ...(options || {}) })
)

test('composed activity footer stays English and translates in Spanish', async () => {
  const sample = task({
    provider: 'local',
    model: 'demo',
    workflow: 'generation',
    kind: 'image',
    metadata: {
      generation_details: {
        seed: 7,
        steps: 20,
        guidance: 4,
        cache: true,
        lora_count: 0,
        simulated: true,
      },
    },
  })
  assert.equal(generationRecipe(sample), 'local · demo · SIMULATED · seed 7 · 20 steps · guidance 4 · Cache on · LoRAs off')
  await i18n.changeLanguage('es')
  assert.equal(
    generationRecipe(sample),
    'local · demo · SIMULADO · semilla 7 · 20 pasos · guía 4 · Caché activada · LoRAs desactivadas',
  )
  assert.equal(generationInitiator(sample), 'Studio · Imagen')
  assert.equal(generationInitiator(task({
    workflow: 'director',
    metadata: { generation_details: { generation_mode: 'music video' } },
  })), 'Director · Videoclip')
  const stored = task({
    workflow: 'generation',
    metadata: { initiator: 'Director · Music video' },
  })
  assert.equal(generationInitiator(stored), 'Director · Music video')
  assert.equal(initiatorText(translate('es'), stored), 'Iniciado por Director · Music video')
  await i18n.changeLanguage('en')
  assert.equal(generationInitiator(task({ workflow: 'generation', kind: 'image' })), 'Studio · Image')
  assert.equal(i18n.t('faceRig.promptUsed', { ns: 'characters', lng: 'en' }), 'What is sent to the model')
  assert.equal(i18n.t('faceRig.promptUsed', { ns: 'characters', lng: 'es' }), 'Qué se envía al modelo')
  assert.equal(i18n.t('catalog.status.missing', { ns: 'activity', lng: 'es' }), 'ausente')
  assert.equal(i18n.t('catalog.status.canonical', { ns: 'activity', lng: 'en' }), 'canonical')
})
