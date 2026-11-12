import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ACE_STEP_MUSIC_MODEL,
  MINIMAX_MUSIC3_LOCAL_MODEL,
  normalizeStoryMusicModel,
  songWriteTarget,
  storyMusicReadyMessageKey,
  storyPaidMusicModel,
  storyUsesLocalMusicGeneration,
} from '../src/features/stories/musicModel.ts'
import { LOCAL_PROMPT_LIMIT, REMOTE_PROMPT_LIMIT } from '../src/lib/musicGenerationSpec.ts'
import { compiledMusicCuePrompt, miniMaxCuePayload, musicCueBlock, musicPromptLimit, musicRequiresLyricSections } from '../src/features/stories/storyLabMusic.ts'

test('cover never uses the local Generate shortcut, even with a local model', () => {
  for (const model of [ACE_STEP_MUSIC_MODEL, MINIMAX_MUSIC3_LOCAL_MODEL] as const) {
    assert.equal(storyUsesLocalMusicGeneration({ model, mode: 'original' }), true)
    assert.equal(storyUsesLocalMusicGeneration({ model, mode: 'cover' }), false)
    assert.equal(storyPaidMusicModel({ model, mode: 'cover' }), 'music-cover')
  }
  assert.equal(storyUsesLocalMusicGeneration({ model: 'music-3.0', mode: 'original' }), false)
  assert.equal(storyUsesLocalMusicGeneration({ model: 'music-3.0', mode: 'cover' }), false)
  assert.equal(storyPaidMusicModel({ model: 'music-3.0', mode: 'original' }), 'music-3.0')
  assert.equal(storyPaidMusicModel({ model: 'music-3.0', mode: 'cover' }), 'music-cover')
})

test('new stories default to ACE-Step and keep MiniMax only when chosen', () => {
  assert.equal(normalizeStoryMusicModel(''), ACE_STEP_MUSIC_MODEL)
  assert.equal(normalizeStoryMusicModel('ace_step_v1_5_xl_sft_lm_4b'), ACE_STEP_MUSIC_MODEL)
  // A saved paid id is a choice only when a person picked it in the selector.
  assert.equal(normalizeStoryMusicModel('music-3.0'), ACE_STEP_MUSIC_MODEL)
  assert.equal(normalizeStoryMusicModel('music-2.6'), ACE_STEP_MUSIC_MODEL)
  assert.equal(normalizeStoryMusicModel('music-3.0', true), 'music-3.0')
  assert.equal(normalizeStoryMusicModel('music-2.6', true), 'music-2.6')
  assert.equal(songWriteTarget(ACE_STEP_MUSIC_MODEL), 'ace-step')
  assert.equal(songWriteTarget('music-3.0'), 'minimax')
})

test('ready copy names ACE, MiniMax local and MiniMax API separately', () => {
  assert.equal(storyMusicReadyMessageKey(ACE_STEP_MUSIC_MODEL, false), 'music.aceLocalReady')
  assert.equal(storyMusicReadyMessageKey(MINIMAX_MUSIC3_LOCAL_MODEL, false), 'music.minimaxLocalReady')
  assert.equal(storyMusicReadyMessageKey('music-3.0', true), 'music.minimaxReady')
  assert.equal(storyMusicReadyMessageKey('music-3.0', false), 'music.minimaxMissing')
  assert.equal(storyMusicReadyMessageKey(ACE_STEP_MUSIC_MODEL, false, 'cover'), 'music.minimaxMissing')
  assert.equal(storyMusicReadyMessageKey(ACE_STEP_MUSIC_MODEL, true, 'cover'), 'music.minimaxReady')
})

test('prompt limits come from the adapter catalog and ACE is not sliced to 300', () => {
  const longStyle = 'cinematic folk with close Spanish vocals and a wide final chorus. '.repeat(8)
  const cue = {
    id: 'cue-1', kind: 'story', targetId: 'story-1', title: 'Theme', purpose: '',
    referenceSong: '', brief: '', style: longStyle, lyrics: 'free verse without tags',
    lyriaPrompt: '', instrumental: false, durationSeconds: 90, candidates: [],
  }
  assert.equal(musicPromptLimit(ACE_STEP_MUSIC_MODEL), LOCAL_PROMPT_LIMIT)
  assert.equal(musicPromptLimit('music-3.0'), REMOTE_PROMPT_LIMIT)
  assert.equal(musicRequiresLyricSections(ACE_STEP_MUSIC_MODEL), false)
  assert.equal(musicRequiresLyricSections('music-3.0'), true)
  assert.equal(compiledMusicCuePrompt(cue, ACE_STEP_MUSIC_MODEL), longStyle.trim())
  assert.equal(compiledMusicCuePrompt(cue, 'music-3.0').length, REMOTE_PROMPT_LIMIT)
  assert.equal(JSON.parse(miniMaxCuePayload(cue, ACE_STEP_MUSIC_MODEL)).prompt.length > REMOTE_PROMPT_LIMIT, true)
  assert.equal(musicCueBlock(cue, ACE_STEP_MUSIC_MODEL), null)
  assert.equal(musicCueBlock(cue, 'music-3.0')?.key, 'music.promptOverLimit')
})
