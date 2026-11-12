import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createCharacterKit, type CharacterKitLibrary } from '../../src/lib/characterKit'
import type { SeriesLibrary, SeriesProject, SeriesShot } from '../../src/features/series/types'

/** The example series with three shots in its first episode: a 2D dialogue shot with a cast, a 2D insert and a 3D shot. */
function fixture() {
  const series = (JSON.parse(readFileSync(new URL('../../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')) as SeriesLibrary)
    .seriesById.series_signal as SeriesProject
  series.allowedProductionMethods = ['animation_2d', 'animation_3d']
  const episode = Object.values(series.episodesById)[0]
  const template = episode.shots[0]
  const library: CharacterKitLibrary = { version: 1, revision: 1, activeId: '', kits: {} }
  for (const character of series.characters) {
    const kit = createCharacterKit(character.name)
    kit.base = { id: 'base', name: 'Base', source: '/fixture-body.svg', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
    kit.poses = { wave: { ...kit.base, id: 'wave', name: 'Wave' } }
    library.kits[kit.id] = kit
    character.voiceProfile = { characterKitRef: { workspace: 'default', id: kit.id } }
  }
  const mara = series.characters[0]
  episode.shots = [
    { ...template, id: 'shot-1', order: 1, productionMethod: 'animation_2d', attempts: [], approvedAttemptId: undefined,
      dialogueBeats: [{ id: 'shot-1_b0', characterId: mara.id, text: 'Record this.', emotion: '', delivery: 'quiet' }],
      layout2d: { cast: [{ characterId: mara.id, poseId: 'wave', x: 40 }], sfx: [{ file: 'sfx-beep.wav', at: 0.5, volume: 0.8 }] } },
    { ...template, id: 'shot-2', order: 2, productionMethod: 'animation_2d', attempts: [], approvedAttemptId: undefined, dialogueBeats: [], layout2d: {} },
    { ...template, id: 'shot-3', order: 3, productionMethod: 'animation_3d', attempts: [], approvedAttemptId: undefined, dialogueBeats: [],
      scene3d: { template: 'user-dock', cast: [], objects: [{ objectId: 'rifle', file: 'rifle.glb', add: true, hold: { carrier: 'guard', hand: 'right' } }] } },
  ] as SeriesShot[]
  return { series, episode, library, mara }
}

function scriptOf(shot: SeriesShot) {
  const layout = shot.layout2d || {}
  const lines = shot.dialogueBeats.map(beat => ({ who: beat.characterId, english: beat.text, ...(beat.delivery ? { delivery: beat.delivery } : {}) }))
  return { scene: shot.sceneId, location: shot.locationId, ...layout, ...(lines.length ? { lines } : { duration: shot.durationSeconds }),
    ...(shot.scene3d ? { scene3d: shot.scene3d, kind: '3d' } : {}) }
}

async function routes(page: Page) {
  const { series, episode, library } = fixture()
  const posts: Array<{ path: string; body: Record<string, unknown> }> = []
  await page.route('**/api/v1/series/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postData() ? JSON.parse(request.postData()!) : {}
    if (request.method() !== 'GET') posts.push({ path, body })
    const shotRoute = path.match(/\/episodes\/[^/]+\/shots\/([^/]+)(\/.*)?$/)
    if (path.endsWith('/shots/edit')) {
      const shot = episode.shots.find(item => item.id === body.shot)!
      const lines = (body.changes?.lines || []) as Array<{ who: string; english: string }>
      if (lines.length) shot.dialogueBeats = lines.map((line, index) => ({ id: `${shot.id}_b${index}`, characterId: line.who, text: line.english, emotion: '', delivery: '' }))
      series.revision += 1
      return route.fulfill({ json: { shotId: shot.id, number: shot.order, changed: Object.keys(body.changes || {}), approvalReset: false, missingLines: {},
        revision: series.revision, shot: { shotId: shot.id, number: shot.order, takes: [], script: scriptOf(shot) },
        stored: { episodeId: episode.id, shot, review: undefined } } })
    }
    if (shotRoute?.[2] === '/voices' && request.method() === 'POST') return route.fulfill({ json: { jobId: 'voice-1', shotId: 'shot-1', beatId: 'shot-1_b0', status: 'queued' } })
    if (shotRoute?.[2] === '/voices') {
      const shot = episode.shots.find(item => item.id === shotRoute[1])!
      return route.fulfill({ json: { shotId: shot.id, language: 'english', recording: [], lines: shot.dialogueBeats.map((beat, index) => ({
        beatId: beat.id, number: index + 1, characterId: beat.characterId, text: beat.text, voice: true, recorded: false })) } })
    }
    if (shotRoute) {
      const shot = episode.shots.find(item => item.id === shotRoute[1])!
      return route.fulfill({ json: { shotId: shot.id, number: shot.order, takes: [], script: scriptOf(shot) } })
    }
    if (path.includes('/voice-jobs/')) return route.fulfill({ json: { jobId: 'voice-1', shotId: 'shot-1', beatId: 'shot-1_b0', status: 'running' } })
    if (path.endsWith('/shot-files')) return route.fulfill({ json: { kind: 'audio', files: ['sfx-beep.wav'] } })
    return route.fulfill({ json: path.endsWith('/library')
      ? { schemaVersion: 1, workspace: 'default', seriesOrder: [series.id], seriesById: { [series.id]: series } }
      : path.endsWith('/recovery') || path.endsWith('/native-render/recovery') ? { jobs: [] } : series })
  })
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: library }))
  await page.route('**/fixture-body.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="400"><rect width="200" height="400" fill="#fab"/></svg>' }))
  return posts
}

async function openValidation(page: Page) {
  await page.getByRole('tab', { name: 'Series Lab', exact: true }).click()
  await page.getByRole('button', { name: '5 · Validation', exact: true }).click()
}

test('a shot opens from its tile, its line is edited in place and its voice is recorded alone', async ({ page }) => {
  const session = await gotoApp(page)
  const posts = await routes(page)
  await openValidation(page)
  const tile = page.getByTestId('series-approval-shot-1')
  await expect(tile.getByText('#1')).toBeVisible()
  await expect(page.getByTestId('series-approval-shot-3').getByText('3D', { exact: true })).toBeVisible()
  await tile.getByRole('button', { name: 'Open', exact: true }).click()
  const inspector = page.getByTestId('series-shot-inspector')
  await expect(inspector.getByRole('heading', { name: /Shot #1/ })).toBeVisible()
  const lines = inspector.getByTestId('series-inspector-shot-1-lines')
  await expect(lines.getByText('Record this.')).toBeVisible()
  await lines.getByRole('button', { name: 'Edit' }).click()
  await lines.getByLabel('Text (English)').fill('Record this. Every second of it.')
  await lines.getByRole('button', { name: 'Save' }).click()
  await expect(lines.getByText(/^Saved \(Dialogue\)/)).toBeVisible()
  const edit = posts.find(item => item.path.endsWith('/shots/edit'))!
  expect(edit.body).toEqual({ workspace: 'default', shot: 'shot-1', stored: true,
    changes: { lines: [{ who: fixture().mara.id, english: 'Record this. Every second of it.', delivery: 'quiet' }] } })
  await expect(inspector.getByTestId('series-inspector-regenerate')).toContainText('records the voice of 1 line')
  await lines.getByRole('button', { name: 'Record voice' }).click()
  await expect(lines.getByText('Recording…')).toBeVisible()
  expect(posts.find(item => item.path.endsWith('/voices'))!.body).toEqual({ workspace: 'default', line: 'shot-1_b0', retake: false })
  await page.keyboard.press('ArrowRight')
  await expect(inspector.getByRole('heading', { name: /Shot #2/ })).toBeVisible()
  await page.keyboard.press('ArrowRight')
  const scene = inspector.getByTestId('series-inspector-shot-3-scene3d')
  await expect(scene.getByText(/in guard's right hand/)).toBeVisible()
  await expect(scene.getByRole('button', { name: 'Edit in Video 3D' })).toBeVisible()
  await inspector.getByRole('button', { name: 'All shots' }).click()
  await expect(page.getByTestId('series-approval-shot-2')).toBeVisible()
  await closeApp(page, session)
})

test('on a phone the grid has two columns and the inspector fits the screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => localStorage.setItem('hocuspocus-wizard-sidebar-collapsed', 'true'))
  const session = await gotoApp(page)
  await routes(page)
  await openValidation(page)
  const first = await page.getByTestId('series-approval-shot-1').boundingBox()
  const second = await page.getByTestId('series-approval-shot-2').boundingBox()
  expect(first && second && Math.abs(first.y - second.y) < 2 && second.x > first.x).toBeTruthy()
  await page.getByTestId('series-approval-shot-1').getByRole('button', { name: 'Open', exact: true }).click()
  const lines = page.getByTestId('series-inspector-shot-1-lines')
  await lines.getByRole('button', { name: 'Edit' }).click()
  await expect(lines.getByLabel('Text (English)')).toBeVisible()
  const overflow = await page.getByTestId('series-shot-inspector').evaluate(element => element.scrollWidth - element.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  const box = await lines.boundingBox()
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy()
  await page.screenshot({ path: test.info().outputPath('inspector-phone.png') })
  await closeApp(page, session)
})
