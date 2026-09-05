import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ACE_DEFAULT_MODEL,
  MUSIC_GUIDE_REVISION,
  REMOTE_PROMPT_LIMIT,
  buildMusicGenerationSpec,
  comparableMusicSpec,
  inspectMusicModel,
  storyCueToMusicDraft,
  studioParamsToMusicDraft,
  wizardSongToMusicDraft,
} from '../src/lib/musicGenerationSpec.ts'

const LONG_CAPTION = (
  '### Global Metadata\n'
  + 'Warm acoustic folk in C major at 92 BPM with close Spanish vocals, '
  + 'fingerpicked guitar, brushed drums and a wide final chorus. '
).repeat(8)

test('Story, Wizard and UI ports compile equivalent specs from the same song', () => {
  const shared = {
    model: ACE_DEFAULT_MODEL,
    style: LONG_CAPTION,
    lyrics: '[Verse]\nLa noche canta\n[Chorus]\nSigue el río',
    durationSeconds: 96,
    lyricsLanguage: 'es',
  }
  const story = buildMusicGenerationSpec(storyCueToMusicDraft({
    model: shared.model, style: shared.style, lyrics: shared.lyrics,
    durationSeconds: shared.durationSeconds, lyricsLanguage: shared.lyricsLanguage,
  }))
  const wizard = buildMusicGenerationSpec(wizardSongToMusicDraft({
    model: shared.model, style: shared.style, lyrics: shared.lyrics,
    durationSeconds: shared.durationSeconds, lyricsLanguage: shared.lyricsLanguage,
  }))
  const ui = buildMusicGenerationSpec(studioParamsToMusicDraft({
    modelType: shared.model, altPrompt: shared.style, prompt: shared.lyrics,
    durationSeconds: shared.durationSeconds,
  }))
  assert.equal(story.guide_revision, MUSIC_GUIDE_REVISION)
  assert.deepEqual(comparableMusicSpec(story), comparableMusicSpec(wizard))
  assert.equal(ui.compiled.prompt, story.compiled.prompt)
  assert.equal(story.prompt.length > REMOTE_PROMPT_LIMIT, true)
  assert.equal(story.compiled.truncated_prompt, false)
  assert.equal(story.compiled.backend, 'generateMusic')
})

test('remote compile truncates the backend prompt, not the frozen caption', () => {
  const spec = buildMusicGenerationSpec(storyCueToMusicDraft({
    model: 'music-3.0',
    style: LONG_CAPTION,
    lyrics: '[Verse]\nLa noche canta',
    durationSeconds: 90,
  }))
  assert.equal(spec.prompt, LONG_CAPTION.trim())
  assert.equal(spec.compiled.prompt, LONG_CAPTION.trim().slice(0, REMOTE_PROMPT_LIMIT))
  assert.equal(spec.compiled.truncated_prompt, true)
  assert.equal(spec.compiled.backend, 'minimax_api')
})

test('zero remote count uses the default of two; garbage count throws', () => {
  const zero = buildMusicGenerationSpec({
    source: 'story',
    model: 'music-3.0',
    caption: 'cinematic dream pop',
    lyrics: '[Verse]\nLa noche canta',
    count: 0,
  })
  assert.equal(zero.count, 2)
  assert.throws(() => buildMusicGenerationSpec({
    source: 'story',
    model: 'music-3.0',
    caption: 'cinematic dream pop',
    lyrics: '[Verse]\nLa noche canta',
    count: Number.NaN,
  }))
})

test('inspect distinguishes known community ports from available backends', () => {
  const community = inspectMusicModel('minimax_music3_gguf')
  assert.equal(community.known, true)
  assert.equal(community.available, false)
  const local = inspectMusicModel('minimax_music3', { installed: false })
  assert.equal(local.incomplete, true)
  assert.equal(local.available, false)
  const ready = inspectMusicModel('music-3.0', { configured: true })
  assert.equal(ready.available, true)
})
