import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveSupportedVideoFormat } from '../src/lib/productionProfile.ts'

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

test('chooses the nearest advertised tier without flipping orientation', () => {
  assert.deepEqual(resolveSupportedVideoFormat(options, '1080p', '9:16'), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: true,
  })
})
