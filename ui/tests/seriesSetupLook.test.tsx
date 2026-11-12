import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { episode, series, shot } from './seriesReviewFixtures'
import { installDom } from './seriesInspectorServer'
import type { SeriesProject } from '../src/features/series/types'

installDom()

async function mount(t: { after: (fn: () => void) => void }, changes: Partial<SeriesProject> = {}) {
  const { render, cleanup, within } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n')
  const { SeriesEpisodeFormatField, SeriesFinishField } = await import('../src/features/series/SeriesSetupLookFields')
  t.after(cleanup)
  const translate = ensureUiI18n().getFixedT('en', 'seriesLab')
  const patches: Array<Partial<SeriesProject>> = []
  const value: SeriesProject = { ...series(episode([shot('s1', 1)])), ...changes }
  const view = within(render(<>
    <SeriesFinishField series={value} t={translate} patch={patch => patches.push(patch)} />
    <SeriesEpisodeFormatField series={value} t={translate} patch={patch => patches.push(patch)} />
  </>).container)
  return { patches, finish: view.getByLabelText(/^Finish/) as HTMLSelectElement, format: view.getByLabelText(/^Episode format/) as HTMLTextAreaElement }
}

test('Series setup shows the paper finish and the default episode format, and patches what the user chooses', async t => {
  const { fireEvent } = await import('@testing-library/react')
  const { patches, finish, format } = await mount(t)
  assert.equal(finish.value, 'paper', 'a series that chose nothing has the paper finish')
  assert.deepEqual([...finish.options].slice(0, 3).map(option => option.textContent), ['Paper (default)', 'None', 'Warm cinema'])
  assert.equal(format.value, '')
  assert.match(format.placeholder, /cold open .* 45–55 shots/, 'the default agents follow is shown, not hidden')
  fireEvent.change(finish, { target: { value: 'none' } })
  fireEvent.change(format, { target: { value: 'Two acts and a tag.' } })
  assert.deepEqual(patches, [{ look: { finish: 'none' } }, { episodeFormat: 'Two acts and a tag.' }])
  assert.equal(format.maxLength, 2000)
})

test('an agent\'s own amounts show as such and stay until the user picks another finish; paper clears the choice', async t => {
  const { fireEvent } = await import('@testing-library/react')
  const own = { grain: { amount: 0.1, size: 2 } }
  const { patches, finish } = await mount(t, { look: { finish: own, palette: 'ochre' } })
  assert.equal(finish.value, 'custom')
  assert.equal(finish.selectedOptions[0].textContent, 'Own amounts (set by an agent)')
  fireEvent.change(finish, { target: { value: 'custom' } })
  assert.deepEqual(patches, [], 'choosing them again changes nothing')
  fireEvent.change(finish, { target: { value: 'paper' } })
  assert.deepEqual(patches, [{ look: { palette: 'ochre' } }], 'paper is the default: the choice is cleared, the rest of look kept')
})
