import assert from 'node:assert/strict'
import test from 'node:test'
import { getCapability, registeredCapabilitySchemas } from '../src/features/agent/capabilityRegistry.ts'
import { runRegisteredCapability } from '../src/features/agent/capabilityRunner.ts'
import type { AgentAction } from '../src/features/agent/agentActions.ts'
import {
  ACE_STEP_MUSIC_MODEL,
  normalizeStoryMusicChoice,
  resolveStoryMusicModel,
  storyMusicGenerationReady,
  storyMusicSelection,
  storyPaidMusicModel,
  storyUsesLocalMusicGeneration,
} from '../src/features/stories/musicModel.ts'
import { createStoryProject, normalizeStoryProject } from '../src/features/stories/model.ts'
import { confirmPaidStoryMusic } from '../src/features/stories/paidMusicConfirm.ts'

const PAID = /Paid MiniMax music is disabled \(music-3\.0\); use a local model: ace_step_v1_5_xl_sft_lm_4b, minimax_music3/

test('Wizard capabilities offer no paid MiniMax music id', () => {
  const schemas = JSON.stringify(registeredCapabilitySchemas())
  assert.equal(schemas.includes('music-3.0'), false)
  assert.equal(schemas.includes('music-2.6'), false)
  const song = getCapability('configure_story_song')!
  const properties = (song.inputSchema as { properties: Record<string, { enum?: string[] }> }).properties
  assert.deepEqual(properties.model_type.enum, ['ace_step_v1_5_xl_sft_lm_4b', 'minimax_music3'])
})

test('an explicit paid request through the Wizard is refused before the Story Lab adapter runs', async () => {
  const song = getCapability('configure_story_song')!
  const action = song.resolve({
    type: 'configure_story_song', music_style: 'synthwave', instrumental: true, model_type: 'music-3.0',
  })
  assert.ok(action)
  assert.equal('model' in action, false)
  let called = false
  const adapters = { storyLab: { configureSong: async () => { called = true; return { message: 'ran' } } } }
  await assert.rejects(
    runRegisteredCapability(action as AgentAction, { adapters, workspace: 'show' } as never),
    PAID,
  )
  assert.equal(called, false)
  const local = song.resolve({
    type: 'configure_story_song', music_style: 'synthwave', instrumental: true, model_type: 'minimax_music3',
  })
  assert.equal((local as { model?: string }).model, 'minimax_music3')
  assert.equal(await song.prepare(local!, {} as never), local)
})

test('the Wizard model resolver refuses paid ids and reads a saved paid id as no model', () => {
  const installed = [{ model_type: ACE_STEP_MUSIC_MODEL, family: 'tts', is_downloaded: true }]
  assert.throws(() => resolveStoryMusicModel('music-3.0', ACE_STEP_MUSIC_MODEL, installed), PAID)
  assert.throws(() => resolveStoryMusicModel('music-cover', ACE_STEP_MUSIC_MODEL, installed), /Paid MiniMax music/)
  assert.equal(resolveStoryMusicModel(undefined, 'music-3.0', installed), ACE_STEP_MUSIC_MODEL)
})

test('an old story saved with music-3.0 reads as the local model and says so, without a rewrite', () => {
  const base = createStoryProject('music_video')
  const saved = { ...base, music: { ...base.music, model: 'music-3.0' } }
  const before = JSON.stringify(saved)
  const project = normalizeStoryProject(saved)
  assert.equal(JSON.stringify(saved), before)
  assert.equal(project.music.model, ACE_STEP_MUSIC_MODEL)
  assert.equal(project.music.replacedPaidModel, 'music-3.0')
  assert.equal(project.music.paidModelChosen, undefined)
  // The notice stays until the person dismisses it or picks a model.
  assert.equal(normalizeStoryProject(project).music.replacedPaidModel, 'music-3.0')
  assert.deepEqual(normalizeStoryMusicChoice({ model: 'music-2.6' }), { model: ACE_STEP_MUSIC_MODEL, replacedPaidModel: 'music-2.6' })
})

test('a paid model picked in the Story Lab selector stays chosen', () => {
  assert.deepEqual(storyMusicSelection('music-3.0'), { model: 'music-3.0', paidModelChosen: true, replacedPaidModel: undefined })
  assert.deepEqual(storyMusicSelection('minimax_music3'), { model: 'minimax_music3', paidModelChosen: undefined, replacedPaidModel: undefined })
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({ ...base, music: { ...base.music, ...storyMusicSelection('music-2.6') } })
  assert.equal(project.music.model, 'music-2.6')
  assert.equal(project.music.paidModelChosen, true)
  assert.equal(project.music.replacedPaidModel, undefined)
})

test('a cover story saved with an unchosen music-3.0 is remapped to ACE and still routes to music-cover', () => {
  const base = createStoryProject('music_video')
  const saved = {
    ...base,
    music: {
      ...base.music,
      mode: 'cover' as const,
      model: 'music-3.0',
      coverReferenceFilename: 'ref.mp3',
    },
  }
  const project = normalizeStoryProject(saved)
  // The unchosen paid id is not kept in cover mode: it reads as the local default and says so.
  assert.equal(project.music.mode, 'cover')
  assert.equal(project.music.model, ACE_STEP_MUSIC_MODEL)
  assert.equal(project.music.paidModelChosen, undefined)
  assert.equal(project.music.replacedPaidModel, 'music-3.0')
  // Generate still reads the cover route, never the local one, and asks for music-cover.
  assert.equal(storyUsesLocalMusicGeneration(project.music), false)
  assert.equal(storyPaidMusicModel(project.music), 'music-cover')
  assert.equal(storyMusicGenerationReady(project.music.model, false, project.music.mode), false)
  assert.equal(storyMusicGenerationReady(project.music.model, true, project.music.mode), true)
})

test('cover mode never takes the local ACE path even after a remapped model', () => {
  assert.equal(storyUsesLocalMusicGeneration({ model: ACE_STEP_MUSIC_MODEL, mode: 'original' }), true)
  assert.equal(storyUsesLocalMusicGeneration({ model: ACE_STEP_MUSIC_MODEL, mode: 'cover' }), false)
  assert.equal(storyPaidMusicModel({ model: ACE_STEP_MUSIC_MODEL, mode: 'cover' }), 'music-cover')
  assert.equal(storyMusicGenerationReady(ACE_STEP_MUSIC_MODEL, false, 'cover'), false)
})

async function manualGenerateButton(mode: 'original' | 'cover', minimaxConfigured: boolean): Promise<string> {
  const { createElement } = await import('react')
  const { renderToStaticMarkup } = await import('react-dom/server')
  const { ManualSongPanel } = await import('../src/features/stories/ManualSongPanel.tsx')
  const base = createStoryProject('music_video')
  const html = renderToStaticMarkup(createElement(ManualSongPanel, {
    project: { ...base, music: { ...base.music, mode } },
    patch: () => {}, productionBusy: null, minimaxConfigured, workspace: 'default',
    musicVersionStyle: {}, musicVersionLanguage: {}, lyricsTranslationLanguage: {},
  } as never))
  const button = html.match(/<button[^>]*>(?:(?!<\/button>).)*Generate manual candidates<\/button>/)
  assert.ok(button, 'the Manual song Generate button renders')
  return button[0]
}

test('Manual song Generate needs the MiniMax key in cover mode even on the local default model', async () => {
  const base = createStoryProject('music_video')
  assert.equal(base.music.model, ACE_STEP_MUSIC_MODEL)
  assert.match(await manualGenerateButton('cover', false), /disabled=""/)
  assert.doesNotMatch(await manualGenerateButton('cover', true), /disabled=""/)
  // An original song on the local default needs no key.
  assert.doesNotMatch(await manualGenerateButton('original', false), /disabled=""/)
})

async function musicReadinessLine(mode: 'original' | 'cover', minimaxConfigured: boolean): Promise<string> {
  const { createElement } = await import('react')
  const { renderToStaticMarkup } = await import('react-dom/server')
  const { StoryMusicSettingsBar } = await import('../src/features/stories/StoryMusicSettingsBar.tsx')
  const base = createStoryProject('music_video')
  return renderToStaticMarkup(createElement(StoryMusicSettingsBar, {
    project: { ...base, music: { ...base.music, mode } },
    patch: () => {}, busy: null, musicQueue: null, musicCueBusy: false, minimaxConfigured,
    musicVersionStyle: {}, musicVersionLanguage: {},
  } as never))
}

test('the music readiness line names MiniMax in cover mode and ACE only for an original song', async () => {
  const coverNoKey = await musicReadinessLine('cover', false)
  assert.match(coverNoKey, /Configure the shared MiniMax key/)
  assert.doesNotMatch(coverNoKey, /Local ACE-Step selected/)
  assert.match(await musicReadinessLine('cover', true), /MiniMax is configured/)
  assert.match(await musicReadinessLine('original', false), /Local ACE-Step selected/)
})

test('Story Lab asks before a paid MiniMax request and never for a local one', () => {
  const asked: string[] = []
  const ask = (message: string) => { asked.push(message); return false }
  assert.equal(confirmPaidStoryMusic(ACE_STEP_MUSIC_MODEL, 3, ask), true)
  assert.equal(confirmPaidStoryMusic('minimax_music3', 1, ask), true)
  assert.deepEqual(asked, [])
  assert.equal(confirmPaidStoryMusic('music-3.0', 2, ask), false)
  assert.equal(confirmPaidStoryMusic('music-cover', 1, () => true), true)
  assert.equal(asked.length, 1)
  assert.match(asked[0], /music-3\.0 runs on the paid MiniMax API\. This sends 2 request/)
})
