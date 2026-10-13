import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { episode, series, shot } from './seriesReviewFixtures'
import { installDom } from './seriesInspectorServer'
import type { SeriesProject } from '../src/features/series/types'

installDom()

function project(changes: Partial<SeriesProject> = {}, videoSettings: Record<string, unknown> = {}): SeriesProject {
  const value = series(episode([shot('s1', 1)]))
  return { ...value, ...changes, provider: { ...value.provider, videoModel: 'minimax_h3_legacy', videoSettings } }
}

test('a shot inherits the Series Lab size or the script video shot size, 480p when nothing is set', async () => {
  const { inheritedShotResolution, shotHasVideoSize } = await import('../src/features/series/videoResolution')
  const lab = shot('s1', 1, { productionMethod: 'generated_video' })
  const scripted = shot('s2', 2, { productionMethod: 'imported_video', video: { prompt: 'x' } })
  assert.equal(shotHasVideoSize(lab), true)
  assert.equal(shotHasVideoSize(scripted), true)
  assert.equal(shotHasVideoSize(shot('s3', 3, { productionMethod: 'imported_video' })), false, 'an imported clip is not made here')
  assert.equal(shotHasVideoSize(shot('s4', 4, { productionMethod: 'animation_2d' })), false)
  assert.equal(inheritedShotResolution(project(), lab), '480p')
  assert.equal(inheritedShotResolution(project(), scripted), '480p')
  const saved = project({ videoShotResolution: '720p' }, { resolution: '540p' })
  assert.equal(inheritedShotResolution(saved, lab), '540p', 'a Series Lab render follows the provider settings')
  assert.equal(inheritedShotResolution(saved, scripted), '720p', 'a script video shot follows videoShotResolution')
})

test('Series setup shows 480p by default and patches the video shot size apart from the provider', async t => {
  const { render, cleanup, fireEvent, within } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n')
  const { SeriesSetupVideoFields, SeriesVideoShotResolutionField } = await import('../src/features/series/SeriesSetupVideoFields')
  t.after(cleanup)
  const translate = ensureUiI18n().getFixedT('en', 'seriesLab')
  const patches: Array<Partial<SeriesProject>> = []
  const videoPatches: Array<Record<string, unknown>> = []
  const value = project()
  const view = render(<>
    <SeriesVideoShotResolutionField series={value} t={translate} patch={patch => patches.push(patch)} />
    <SeriesSetupVideoFields series={value} t={translate} patchProvider={() => {}} patchVideo={patch => videoPatches.push(patch)} />
  </>)
  const shots = within(view.container).getByLabelText(/Video shot resolution/) as HTMLSelectElement
  const lab = within(view.container).getByLabelText(/^Resolution/) as HTMLSelectElement
  assert.equal(shots.value, '480p')
  assert.equal(lab.value, '480p')
  fireEvent.change(shots, { target: { value: '768p' } })
  fireEvent.change(lab, { target: { value: '540p' } })
  assert.deepEqual(patches, [{ videoShotResolution: '768p' }])
  assert.deepEqual(videoPatches, [{ resolution: '540p' }])
})
