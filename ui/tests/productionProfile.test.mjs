import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applySeriesGlobalProvider,
  DEFAULT_PRODUCTION_PROFILE,
  resolveSupportedVideoFormat,
  seriesProviderFieldsFromProfile,
  seriesProviderMatchesGlobal,
  writingBaseUrlFromProfile,
  writingProviderFromText,
} from '../src/lib/productionProfile.ts'

const options = {
  resolution_preset_order: ['480p', '540p', '720p', '768p'],
  resolution_presets: {
    '480p': { values: { '16:9': '864x480', '9:16': '480x864' } },
    '540p': { values: { '16:9': '960x544', '9:16': '544x960' } },
    '720p': { values: { '16:9': '1280x704', '9:16': '704x1280' } },
    '768p': { values: { '16:9': '1344x768', '9:16': '768x1344' } },
  },
  supports_auto_aspect: false,
}

test('keeps an exact H3 Legacy tier and portrait orientation', () => {
  assert.deepEqual(resolveSupportedVideoFormat(options, '768p', '9:16'), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: false,
  })
})

test('series global profile compares every copied field including shifts', () => {
  const fields = seriesProviderFieldsFromProfile({
    ...DEFAULT_PRODUCTION_PROFILE,
    video: {
      ...DEFAULT_PRODUCTION_PROFILE.video,
      model: 'minimax_h3_fused_turbo',
      settings: {
        ...DEFAULT_PRODUCTION_PROFILE.video.settings,
        steps: 4,
        flowShift: 7,
        audioShift: 1,
        profile: 'fast',
      },
    },
  })
  const provider = applySeriesGlobalProvider({
    useGlobalProfile: true,
    writingProvider: 'minimax',
    writingModel: 'old',
    writingBaseUrl: '',
    imageProvider: 'maestro',
    imageModel: '',
    videoModel: 'minimax_h3',
    videoSettings: { resolution: '540p', orientation: 'landscape', numInferenceSteps: 20, flowShift: 12, audioShift: 3, modelProfile: 'quality' },
  }, fields)
  assert.equal(provider.videoModel, 'minimax_h3_fused_turbo')
  assert.equal(provider.videoSettings.flowShift, 7)
  assert.equal(provider.videoSettings.audioShift, 1)
  assert.equal(provider.videoSettings.modelProfile, 'fast')
  assert.equal(provider.writingBaseUrl, 'https://api.minimax.io')
  assert.equal(seriesProviderMatchesGlobal(provider, fields), true)
  assert.equal(seriesProviderMatchesGlobal({
    ...provider,
    videoSettings: { ...provider.videoSettings, flowShift: 12 },
  }, fields), false)
})

test('chooses the nearest advertised tier without flipping orientation', () => {
  assert.deepEqual(resolveSupportedVideoFormat(options, '1080p', '9:16'), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: true,
  })
})

test('Ollama and Grok text profiles keep their own writing provider', () => {
  for (const [provider, url] of [['ollama', 'http://127.0.0.1:11434'], ['grok', 'https://api.x.ai/v1']]) {
    const profile = { ...DEFAULT_PRODUCTION_PROFILE, text: { ...DEFAULT_PRODUCTION_PROFILE.text, provider, base_url: '' } }
    assert.equal(writingProviderFromText(provider), provider)
    assert.equal(writingBaseUrlFromProfile(profile), url)
  }
  assert.equal(writingProviderFromText('local'), 'maestro')
})
