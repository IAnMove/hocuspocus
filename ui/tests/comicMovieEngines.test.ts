import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import type { TFunction } from 'i18next'
import type { ModelDef } from '../src/types/index.ts'
import {
  comicDirectorResolutionFields,
  comicMovieEngineCompatible,
  comicMovieResolutions,
  selectableComicMovieEngines,
} from '../src/features/comics/movieEngines.ts'

const translate = (language: 'en' | 'es'): TFunction<'comics'> => (
  ((key: string, options?: object) => String(i18n.t(key, {
    ns: 'comics',
    lng: language,
    ...(options || {}),
  }))) as TFunction<'comics'>
)

const capability = (compatible: boolean) => ({ compatible, reason: '' })

function model(partial: Partial<ModelDef> & Pick<ModelDef, 'model_type' | 'name' | 'is_i2v'>): ModelDef {
  return {
    family: 'video',
    architecture: '',
    is_t2v: !partial.is_i2v,
    guidance_max_phases: 1,
    fps: 24,
    is_downloaded: true,
    ...partial,
  }
}

const ltx = model({
  model_type: 'ltx2_22B_distilled_1_1',
  name: 'LTX-2 Distilled',
  architecture: 'ltx2_22B',
  is_i2v: false,
  is_t2v: true,
  director: {
    image: capability(false),
    video: {
      music_video: capability(true),
      short_film_audio: capability(true),
      short_film_story: capability(true),
      comic_movie: capability(true),
      seamless: capability(true),
    },
    supports_audio_input: true,
    generates_audio: true,
    supports_voice_reference: true,
    max_image_refs: null,
  },
})

test('LTX-2 stays in the comic film selector when the catalog marks it compatible', () => {
  assert.equal(comicMovieEngineCompatible(ltx), true)
  const enabled = new Set([ltx.model_type])
  assert.deepEqual(
    selectableComicMovieEngines([ltx], enabled).map(item => item.model_type),
    [ltx.model_type],
  )
  const hidden = model({
    model_type: 'ltx2_22B_distilled_1_1',
    name: 'LTX-2 Distilled',
    is_i2v: false,
  })
  assert.equal(comicMovieEngineCompatible(hidden), false)
  assert.deepEqual(selectableComicMovieEngines([hidden], enabled), [])
})

test('an H3 family id offers the 720p canvas the comic film label names', () => {
  const spanish = comicMovieResolutions(
    translate('es'),
    'minimax_h3_fl2va',
    'landscape',
    'minimax_h3',
  )
  const recommended = spanish.find(option => option.recommended)
  assert.equal(recommended?.quality, '720p')
  assert.equal(recommended?.value, '1280x704')
  assert.match(recommended?.label || '', /1280×704/)
  assert.match(recommended?.label || '', /recomendada/)
  assert.deepEqual(comicDirectorResolutionFields(recommended!), {
    director_resolution_preset: '720p',
    director_aspect_ratio: '16:9',
  })
})
