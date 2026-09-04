import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeLanguageIntent } from '../src/lib/languageIntent'
import {
  evaluateSongSemanticFidelity,
  extractRequestedSongLanguage,
  extractSongSemanticAnchors,
  resolveSongLyricsLanguage,
} from '../src/features/stories/songLanguage'
import { protectUserVerbatimSegments, reconcileAgentTurnWithRequest } from '../src/features/agent/agentActions'
import { resolveStoryMusicModel } from '../src/features/stories/musicModel'

test('Wizard resolves Story music models from explicit choice, selected install, then sole install', () => {
  const inventory = [
    { model_type: 'ace_step_v1_5_xl_sft_lm_4b', family: 'tts', is_downloaded: false },
    { model_type: 'minimax_music3', family: 'tts', is_downloaded: true },
  ]
  assert.equal(resolveStoryMusicModel('ace_step_v1_5_xl_sft_lm_4b', 'minimax_music3', inventory), 'ace_step_v1_5_xl_sft_lm_4b')
  assert.equal(resolveStoryMusicModel(undefined, 'ace_step_v1_5_xl_sft_lm_4b', inventory), 'minimax_music3')
  assert.equal(resolveStoryMusicModel(undefined, undefined, inventory), 'minimax_music3')
  assert.equal(resolveStoryMusicModel(undefined, 'ace_step_v1_5_xl_sft_lm_4b', [inventory[0]]), 'ace_step_v1_5_xl_sft_lm_4b')
})

test('lyrics language follows the user request, not the UI or conversation language', () => {
  const intent = normalizeLanguageIntent({
    conversation_language: 'fr',
    content_language: 'Français',
    spoken_language: 'Français',
    technical_prompt_language: 'en',
  })

  assert.equal(extractRequestedSongLanguage('Write a vocal song with lyrics in Spanish.'), 'Español')
  assert.equal(extractRequestedSongLanguage('Escribe una canción vocal en español.'), 'Español')
  assert.equal(extractRequestedSongLanguage('Escribe una canción en de madrugada con un estribillo heroico.'), '')
  assert.equal(extractRequestedSongLanguage('Escribe una canción; idioma: de.'), 'Deutsch')
  assert.equal(extractRequestedSongLanguage('Escribe una canción; idioma en de.'), 'Deutsch')
  assert.equal(resolveSongLyricsLanguage({
    request: 'Écris une chanson avec la letra en español.',
    languageIntent: intent,
    fallback: 'Français',
  }), 'Español')
  assert.equal(resolveSongLyricsLanguage({
    languageIntent: intent,
    fallback: 'English',
  }), 'Français')
})

test('Spanish lyrics can use an English technical prompt without losing their language contract', () => {
  const report = evaluateSongSemanticFidelity({
    lyrics: '[Verse]\nEn la red despierta el sysadmin.\n[Chorus]\nLa noche y el código cantan.',
    lyricsLanguage: 'Español',
    requiredTerms: ['sysadmin', 'red'],
    requireStructuredLyrics: true,
  })
  assert.equal(report.ok, true)
  assert.equal(report.languageMismatch, false)
  assert.equal(report.score, 100)
  assert.deepEqual(extractSongSemanticAnchors('Linus Torvalds lucha contra software propietario', 4), [
    'linus', 'torvalds', 'lucha', 'software',
  ])
})

test('quoted lyric text remains literal even when it is in a different language', () => {
  const request = 'Escribe una canción en español y conserva la letra "Hello, world" en inglés.'
  const protectedTurn = protectUserVerbatimSegments(request, {
    reply: 'Je prépare la chanson.',
    conversationLanguage: 'fr',
    actions: [{
      type: 'configure_story_song',
      targetStoryTitle: 'Cross-language song',
      songTitle: 'Cross-language song',
      brief: 'A bilingual refrain',
      style: 'English technical direction: heavy metal',
      lyrics: '',
      writeLyrics: true,
      lyricsLanguage: 'Français',
      instrumental: false,
      model: 'ace_step_v1_5_xl_sft_lm_4b',
    }],
  })
  const action = protectedTurn.actions[0]
  assert.equal(action.type, 'configure_story_song')
  assert.equal(action.type === 'configure_story_song' && action.lyricsLanguage, 'Español')
  assert.equal(action.type === 'configure_story_song' && action.languageIntent?.conversationLanguage, 'fr')
  assert.equal(action.type === 'configure_story_song' && action.languageIntent?.spokenLanguage, 'Español')
  assert.equal(action.type === 'configure_story_song' && action.languageIntent?.verbatimSegments[0]?.text, 'Hello, world')
  assert.equal(action.type === 'configure_story_song' && action.languageIntent?.verbatimSegments[0]?.language, 'en')

  const preserved = evaluateSongSemanticFidelity({
    lyrics: '[Chorus]\nHello, world\nLa noche nos verá.',
    lyricsLanguage: 'Español',
    protectedSegments: [{ kind: 'lyrics', text: 'Hello, world', language: 'en' }],
    requireStructuredLyrics: true,
  })
  assert.equal(preserved.ok, true)
  const foreignRefrain = evaluateSongSemanticFidelity({
    lyrics: '[Verse]\nEn la red despierta el sysadmin y la noche canta.\n[Chorus]\nThe server fights through the night and we sing for our network.',
    lyricsLanguage: 'Español',
    protectedSegments: [{
      kind: 'lyrics',
      text: 'The server fights through the night and we sing for our network.',
      language: 'en',
    }],
    requireStructuredLyrics: true,
  })
  assert.equal(foreignRefrain.ok, true)
  assert.equal(foreignRefrain.languageMismatch, false)
  const translated = evaluateSongSemanticFidelity({
    lyrics: '[Chorus]\nHola, mundo\nLa noche nos verá.',
    lyricsLanguage: 'Español',
    protectedSegments: [{ kind: 'lyrics', text: 'Hello, world', language: 'en' }],
    requireStructuredLyrics: true,
  })
  assert.equal(translated.ok, false)
  assert.deepEqual(translated.missingProtectedSegments, ['Hello, world'])
})

test('a semantic smoke failure is detectable before any provider call', () => {
  const report = evaluateSongSemanticFidelity({
    lyrics: '[Verse]\nThe server fights through the night.\n[Chorus]\nWe sing for proprietary software.',
    lyricsLanguage: 'Español',
    requiredTerms: ['sysadmin', 'red'],
    requireStructuredLyrics: true,
  })
  assert.equal(report.ok, false)
  assert.equal(report.languageMismatch, true)
  assert.deepEqual(report.missingTerms, ['sysadmin', 'red'])
  assert.match(report.reasons.join(' '), /requested language/i)
})

test('Story Lab song requests stay on the Story song chain', async () => {
  const request = 'Crea en Story Lab un videoclip de una canción vocal en español sobre Linus Torvalds y ejecútalo.'
  const reconciled = await reconcileAgentTurnWithRequest(request, {
    reply: 'I will open Studio Audio.',
    conversationLanguage: 'fr',
    actions: [{
      type: 'prepare_audio',
      subMode: 'music',
      prompt: 'generic instrumental song',
    }],
  })
  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'create_story', 'configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production',
  ])
  const configure = reconciled.actions.find(action => action.type === 'configure_story_song')
  assert.equal(configure?.type, 'configure_story_song')
  assert.equal(configure?.lyricsLanguage, 'Español')
  assert.equal(reconciled.actions.some(action => action.type === 'prepare_audio'), false)
})
