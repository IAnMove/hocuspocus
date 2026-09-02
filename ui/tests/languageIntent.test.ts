import assert from 'node:assert/strict'
import test from 'node:test'
import {
  compileProviderPrompt,
  extractVerbatimSegments,
  mergeLanguageIntent,
  normalizeConversationLanguageTag,
  normalizeLanguageIntent,
} from '../src/lib/languageIntent'
import { buildAgentTurnPrompt } from '../src/features/agent/agentKnowledge'
import {
  HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  parseAgentTurn,
  protectUserVerbatimSegments,
  type AgentAppSnapshot,
} from '../src/features/agent/agentActions'
import {
  executeRegisteredCapability,
  listCapabilities,
  parseRegisteredCapability,
} from '../src/features/agent/capabilityRegistry'
import { changedSections, createStoryProject, normalizeStoryProject } from '../src/features/stories/model'
import { applyLegacyStoryLanguage, seedStoryLanguageIntent } from '../src/features/stories/languageIntent'
import { createComicProject, normalizeComicProject } from '../src/features/comics/model'
import { normalizeSeriesProject } from '../src/features/series/model'
import {
  resolveSeriesLanguageIntent,
  seriesLanguageIntentAffectsCanon,
} from '../src/features/series/languageIntent'

const mixedIntent = normalizeLanguageIntent({
  conversation_language: 'fr',
  content_language: 'English',
  spoken_language: 'Español de España',
  technical_prompt_language: 'en',
  verbatim_segments: [{
    kind: 'dialogue',
    text: '¡Hola, mundo!',
    language: 'es',
    speaker: 'Ada',
  }, {
    kind: 'lyrics',
    text: 'Nunca cae el servidor',
    language: 'es',
  }],
})

test('normalizes both LLM snake_case and persisted camelCase language contracts', () => {
  assert.equal(mixedIntent.conversationLanguage, 'fr')
  assert.equal(normalizeLanguageIntent(mixedIntent).spokenLanguage, 'Español de España')
  assert.deepEqual(normalizeLanguageIntent(mixedIntent).verbatimSegments, mixedIntent.verbatimSegments)
  assert.equal(normalizeConversationLanguageTag('Español'), 'es')
  assert.equal(normalizeConversationLanguageTag('pt-BR'), 'pt-BR')
  assert.equal(normalizeConversationLanguageTag('not a language'), '')
  const spaced = normalizeLanguageIntent({
    verbatim_segments: [{ kind: 'dialogue', text: '  exact spacing  ', language: 'en' }],
  })
  assert.equal(spaced.verbatimSegments[0]?.text, '  exact spacing  ')
})

test('provider compiler uses English direction and preserves only medium-relevant literals', () => {
  const video = compileProviderPrompt('Animated fantasy city at night.', mixedIntent, { medium: 'video' })
  assert.match(video, /Technical direction language: English/)
  assert.match(video, /Spoken or sung language: Español de España/)
  assert.match(video, /"¡Hola, mundo!"/)
  assert.doesNotMatch(video, /Nunca cae el servidor/)
  assert.match(video, /remain metadata only/)
  assert.equal(compileProviderPrompt(video, mixedIntent, { medium: 'video' }), video)

  const music = compileProviderPrompt('Driving 1980s heavy metal anthem.', mixedIntent, { medium: 'music' })
  assert.match(music, /"Nunca cae el servidor"/)
  assert.doesNotMatch(music, /¡Hola, mundo!/)

  const image = compileProviderPrompt('One clean comic panel.', mixedIntent, { medium: 'image' })
  assert.doesNotMatch(image, /¡Hola, mundo!|Nunca cae el servidor/)
})

test('quoted user dialogue is protected deterministically while a quoted style is not', () => {
  const request = 'Use style "classic painted animation" y haz que los protagonistas digan "¡Hola, mundo!" en español.'
  assert.deepEqual(extractVerbatimSegments(request), [{
    kind: 'dialogue', text: '¡Hola, mundo!', language: 'es',
  }])
  const protectedTurn = protectUserVerbatimSegments(request, {
    reply: 'Je prépare la scène.', conversationLanguage: 'fr',
    actions: [{
      type: 'prepare_video', prompt: 'Two protagonists greet each other.',
      languageIntent: normalizeLanguageIntent({
        spoken_language: 'en', technical_prompt_language: 'auto',
      }),
    }],
  })
  const action = protectedTurn.actions[0]
  assert.equal(action.type, 'prepare_video')
  assert.equal(action.type === 'prepare_video' && action.languageIntent?.verbatimSegments[0]?.text, '¡Hola, mundo!')
  assert.equal(action.type === 'prepare_video' && action.languageIntent?.technicalPromptLanguage, 'auto')
  assert.equal(action.type === 'prepare_video' && action.languageIntent?.spokenLanguage, 'es')
})

test('merge keeps persisted literals when a later action only changes spoken language', () => {
  const merged = mergeLanguageIntent(mixedIntent, normalizeLanguageIntent({ spoken_language: 'Català' }))
  assert.equal(merged.spokenLanguage, 'Català')
  assert.deepEqual(merged.verbatimSegments, mixedIntent.verbatimSegments)
})

test('Wizard turn keeps conversation language independent from interface and action languages', () => {
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Je prépare la scène.',
    conversation_language: 'French',
    actions: [{
      type: 'prepare_video',
      prompt: 'A magician greets the audience in a candlelit observatory.',
      language_intent: {
        conversation_language: 'fr',
        content_language: 'English',
        spoken_language: 'Español',
        technical_prompt_language: 'en',
        verbatim_segments: [{ kind: 'dialogue', text: 'hola', language: 'es' }],
      },
    }],
  }))
  assert.equal(turn.conversationLanguage, 'fr')
  assert.equal(turn.actions[0].type, 'prepare_video')
  assert.equal('languageIntent' in turn.actions[0] && turn.actions[0].languageIntent?.spokenLanguage, 'Español')

  const app = {
    interface_language: 'de',
    current: {},
    available_video_models: [],
    context: {},
  } as unknown as AgentAppSnapshot
  const prompt = buildAgentTurnPrompt('demo', [{ role: 'user', text: 'Haz que diga "hola" en español.' }], [], app)
  assert.match(prompt, /Interface language: de \(presentation only/)
  assert.match(prompt, /Haz que diga/)
})

test('every creative language-aware capability publishes and parses the shared contract', () => {
  const expected = new Set([
    'prepare_video', 'prepare_image', 'prepare_audio', 'queue_sfx_pack', 'prepare_3d',
    'create_story', 'update_story', 'generate_story_section', 'stage_story_comic',
    'stage_story_video', 'configure_story_song', 'stage_story_music_video',
    'create_series_episode', 'update_series_episode', 'generate_series_plan',
    'create_rhythmic_3d_video', 'create_comic',
  ])
  for (const capability of listCapabilities()) {
    if (!expected.has(capability.name)) continue
    assert.ok(capability.parameters.includes('language_intent'), capability.name)
    assert.ok((capability.inputSchema.properties as Record<string, unknown>).language_intent, capability.name)
  }
  const generic = HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as {
    properties: { actions: { items: { properties: Record<string, unknown> } } }
  }
  assert.ok(generic.properties.actions.items.properties.language_intent)

  const action = parseRegisteredCapability('prepare_video', {
    type: 'prepare_video', prompt: 'A quiet room.', language_intent: {
      spoken_language: 'Español', technical_prompt_language: 'en',
      verbatim_segments: [{ kind: 'dialogue', text: 'hola', language: 'es' }],
    },
  })
  assert.equal(action?.type, 'prepare_video')
  assert.equal(action && 'languageIntent' in action && action.languageIntent?.verbatimSegments[0].text, 'hola')
})

test('Studio capability fills the visible form with the compiled auditable prompt', async () => {
  const action = parseRegisteredCapability('prepare_video', {
    type: 'prepare_video',
    prompt: 'A wizard faces the camera.',
    language_intent: {
      content_language: 'English', spoken_language: 'Español', technical_prompt_language: 'en',
      verbatim_segments: [{ kind: 'dialogue', text: 'hola', language: 'es' }],
    },
  })
  assert.ok(action)
  let received = ''
  const outcome = await executeRegisteredCapability(action!, {
    adapters: {
      studio: {
        async prepareVideo(prepared) {
          received = prepared.prompt
          return { message: 'Prepared', target: { kind: 'studio_form', id: 'video', title: 'Video' } }
        },
      },
    },
  })
  assert.equal(outcome?.message, 'Prepared')
  assert.match(received, /HOCUSPOCUS LANGUAGE CONTRACT/)
  assert.match(received, /"hola"/)
})

test('language-only Story and Series updates survive capability resolution', () => {
  const story = parseRegisteredCapability('update_story', {
    type: 'update_story',
    target_story_title: 'The Observatory',
    language_intent: {
      spoken_language: 'es',
      verbatim_segments: [{ kind: 'dialogue', text: '¡Hola, mundo!', language: 'es' }],
    },
  })
  assert.equal(story?.type, 'update_story')
  assert.equal(story && 'languageIntent' in story && story.languageIntent?.spokenLanguage, 'es')

  const technicalOnly = parseRegisteredCapability('update_story', {
    type: 'update_story',
    target_story_title: 'The Observatory',
    language_intent: { technical_prompt_language: 'auto' },
  })
  assert.equal(technicalOnly?.type, 'update_story')
  assert.equal(technicalOnly && 'languageIntent' in technicalOnly && technicalOnly.languageIntent?.technicalPromptLanguage, 'auto')

  const episode = parseRegisteredCapability('update_series_episode', {
    type: 'update_series_episode',
    series_title: 'Night Shift',
    target_episode_title: 'The Pager',
    language_intent: {
      content_language: 'fr',
      verbatim_segments: [{ kind: 'subtitle', text: 'À suivre', language: 'fr' }],
    },
  })
  assert.equal(episode?.type, 'update_series_episode')
  assert.equal(episode && 'languageIntent' in episode && episode.languageIntent?.contentLanguage, 'fr')
})

test('legacy Story, Series and Comics documents migrate to a persistent language intent', () => {
  const story = normalizeStoryProject({ ...createStoryProject(), languageIntent: undefined, language: 'Italiano', spokenLanguage: 'Italiano' })
  assert.equal(story.languageIntent.contentLanguage, 'Italiano')
  assert.equal(story.languageIntent.technicalPromptLanguage, 'en')

  const comic = createComicProject()
  const migratedComic = normalizeComicProject({ ...comic, languageIntent: undefined, language: 'Français' })
  assert.equal(migratedComic.languageIntent.contentLanguage, 'Français')

  const series = normalizeSeriesProject({
    id: 'series_1', title: 'Demo', language: 'Deutsch', spokenLanguage: 'Deutsch',
  })
  assert.equal(series?.languageIntent.contentLanguage, 'Deutsch')
  assert.equal(series?.languageIntent.technicalPromptLanguage, 'en')
})

test('a legacy Story language selection seeds the durable contract', () => {
  const base = createStoryProject()
  const selected = seedStoryLanguageIntent(base, 'Français', undefined)
  assert.equal(selected.languageIntent.contentLanguage, 'Français')
  assert.equal(selected.languageIntent.spokenLanguage, 'Français')
})

test('a legacy Story language update keeps legacy fields and the durable contract synchronized', () => {
  const base = createStoryProject()
  const selected = applyLegacyStoryLanguage(base, 'Français', undefined)
  assert.equal(selected.language, 'Français')
  assert.equal(selected.spokenLanguage, 'Français')
  assert.equal(selected.languageIntent.contentLanguage, 'Français')
  assert.equal(selected.languageIntent.spokenLanguage, 'Français')

  const explicitSpeech = applyLegacyStoryLanguage(base, 'English', normalizeLanguageIntent({
    spoken_language: 'Español',
  }))
  assert.equal(explicitSpeech.languageIntent.contentLanguage, 'English')
  assert.equal(explicitSpeech.languageIntent.spokenLanguage, 'Español')
})

test('Series language resolution invalidates canon only for production-relevant changes', () => {
  const series = normalizeSeriesProject({
    id: 'series-language', title: 'Night Shift', language: 'Español', spokenLanguage: 'Español',
  })
  assert.ok(series)

  const conversationOnly = resolveSeriesLanguageIntent(series!, '', normalizeLanguageIntent({
    conversation_language: 'fr',
  }))
  assert.equal(seriesLanguageIntentAffectsCanon(series!, conversationOnly), false)

  const protectedDialogue = resolveSeriesLanguageIntent(series!, '', normalizeLanguageIntent({
    verbatim_segments: [{ kind: 'dialogue', text: '¡Hola!', language: 'es' }],
  }))
  assert.equal(seriesLanguageIntentAffectsCanon(series!, protectedDialogue), true)

  const legacySelection = resolveSeriesLanguageIntent(series!, 'Français', undefined)
  assert.equal(legacySelection.contentLanguage, 'Français')
  assert.equal(legacySelection.spokenLanguage, 'Français')
  assert.equal(seriesLanguageIntentAffectsCanon(series!, legacySelection), true)
})

test('changing only protected Story literals is a real persisted overview change', () => {
  const before = createStoryProject()
  const after = normalizeStoryProject({
    ...before,
    languageIntent: mergeLanguageIntent(before.languageIntent, normalizeLanguageIntent({
      verbatim_segments: [{ kind: 'dialogue', text: 'hola', language: 'es' }],
    })),
  })
  assert.deepEqual(changedSections(before, after), ['overview'])
})
