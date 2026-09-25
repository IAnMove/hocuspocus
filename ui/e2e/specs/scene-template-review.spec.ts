import { readFile } from 'node:fs/promises'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { closeApp } from '../helpers/gotoApp'
import { installApiRoutes, type ApiRouteSession } from '../helpers/apiRoutes'
import { lockUiLanguage } from '../helpers/lockUiLanguage'
import { CATALOG_VERSION, EXPANDED_CATALOG_VERSION } from '../../src/features/sceneTemplates/catalog'
import { CATALOG_REVIEW_STORAGE_KEY } from '../../src/features/sceneTemplates/catalogReview'
import { candidateDemoScene } from '../../src/features/sceneTemplates/demoScenes'

const PENDING_SCENE_KEY = 'maestro_scene_animator_pending_scene'
const REVIEW_STORAGE_KEY = CATALOG_REVIEW_STORAGE_KEY
const SAVED_OUTPUT = {
  name: 'review.scene.json',
  type: 'scene',
  mode: 'scene',
  favorite: false,
  size: 2_048,
  created_at: 1_700_000_000,
  completed_at: 1_700_000_001,
  completion_time_source: 'metadata',
  url: '/api/v1/file/review.scene.json?workspace=default',
  thumbnail_url: null,
} as const

type SceneLike = Record<string, unknown>

type ReviewRouteState = {
  postedPayloads: Array<Record<string, unknown>>
  savedScene: SceneLike | null
  outputRequests: string[]
  fileRequests: string[]
  recordingRequests: string[]
  referenceRequests: string[]
  referenceMode: 'valid' | 'missing' | 'mismatch'
}

const referenceScene = (): SceneLike => {
  const scene = JSON.parse(JSON.stringify(candidateDemoScene('cinema-establishing', 'coral'))) as SceneLike
  scene.name = 'Referencia coral guardada'
  scene.duration = 5
  return scene
}

const referencePayload = (mode: ReviewRouteState['referenceMode']): Record<string, unknown> | null => {
  if (mode === 'missing') return null
  const scene = referenceScene()
  if (mode === 'mismatch') {
    const narrative = scene.narrative as SceneLike
    scene.narrative = { ...narrative, templateId: 'music-pulse' }
  }
  return {
    catalogVersion: CATALOG_VERSION,
    templateId: 'cinema-establishing',
    templateVersion: 1,
    variant: 'coral',
    status: 'rendered-not-approved',
    scene,
  }
}

function reviewRouteState(): ReviewRouteState {
  return {
    postedPayloads: [],
    savedScene: null,
    outputRequests: [],
    fileRequests: [],
    recordingRequests: [],
    referenceRequests: [],
    referenceMode: 'valid',
  }
}

async function prepareReviewPage(page: Page): Promise<ApiRouteSession> {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const session = await installApiRoutes(page)
  await lockUiLanguage(page, 'en')
  await page.addInitScript(() => {
    const originalSetItem = Storage.prototype.setItem
    Storage.prototype.setItem = function setItem(key: string, value: string) {
      if (this === window.sessionStorage && key === 'maestro_scene_animator_pending_scene') {
        originalSetItem.call(this, '__scene_template_test_handoff', value)
      }
      return originalSetItem.call(this, key, value)
    }
  })
  return session
}

async function installReviewRoutes(page: Page, state: ReviewRouteState): Promise<void> {
  await page.route('**/api/v1/character-kits/library**', async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: 1, revision: 0, activeId: '', kits: {} }),
    })
  })

  await page.route('**/scene-template-previews/cinema-establishing.json', async route => {
    state.referenceRequests.push(route.request().url())
    const payload = referencePayload(state.referenceMode)
    if (!payload) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'reference not found' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })

  await page.route('**/api/v1/scenes', async route => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    const payload = route.request().postDataJSON() as Record<string, unknown>
    state.postedPayloads.push(payload)
    state.savedScene = payload.scene as SceneLike
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SAVED_OUTPUT),
    })
  })

  await page.route('**/api/v1/outputs**', async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }
    const url = new URL(route.request().url())
    state.outputRequests.push(url.href)
    if (url.searchParams.get('media_type') !== 'scene') {
      await route.fallback()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ outputs: state.savedScene ? [SAVED_OUTPUT] : [], total: state.savedScene ? 1 : 0 }),
    })
  })

  await page.route('**/api/v1/file/review.scene.json**', async route => {
    state.fileRequests.push(route.request().url())
    if (!state.savedScene) {
      await route.fulfill({ status: 404, contentType: 'text/plain', body: 'scene not saved' })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(state.savedScene),
    })
  })

  await page.route('**/api/v1/scenes/recordings**', async route => {
    state.recordingRequests.push(route.request().url())
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'MP4 export is not part of this E2E test.' }) })
  })
}

async function openGallery(page: Page): Promise<void> {
  await page.goto('/scene-template-review')
  await expect(page.locator('section[aria-label="Galería de plantillas candidatas de Video3D"]')).toBeVisible()
  await expect(page.locator('[data-template-id]')).toHaveCount(48)
}

async function readAutosave(page: Page): Promise<SceneLike | null> {
  return page.evaluate(() => {
    const raw = localStorage.getItem('maestro-scene-animator-autosave-v1')
    return raw ? JSON.parse(raw) as SceneLike : null
  })
}

async function confirmLibraryScene(dialog: Locator, title: string): Promise<void> {
  await dialog.getByText(title, { exact: true }).first().click()
  await dialog.getByRole('button', { name: 'Open scene', exact: true }).click()
}

async function chooseComposerLibraryFile(page: Page, composer: Locator, filename: string): Promise<void> {
  await composer.getByRole('button', { name: 'From HocusPocus' }).click()
  const explorer = page.getByRole('dialog').filter({ has: page.getByTestId('asset-explorer') }).last()
  await expect(explorer).toBeVisible()
  const card = explorer.locator(`button[title="${filename}"]`)
  await expect(card).toBeVisible()
  await card.click()
  await explorer.getByRole('button', { name: 'Choose', exact: true }).click()
  await expect(composer.getByText(filename).first()).toBeVisible()
}

test('opens cinema-establishing in the real editor, saves exact scene JSON, and reopens the saved scene', async ({ page }) => {
  const session = await prepareReviewPage(page)
  const state = reviewRouteState()
  await installReviewRoutes(page, state)

  try {
    await openGallery(page)
    const handoffCard = page.locator('[data-template-id="cinema-establishing"]')
    await handoffCard.getByTestId('open-scene-cinema-establishing').click()
    await expect(page).toHaveURL(/\/scene-template-review\?editor=1$/)

    const sceneName = page.getByLabel('Scene name', { exact: true })
    await expect(sceneName).toBeVisible()
    await expect(sceneName).toHaveValue('Referencia coral guardada')
    await expect(page.locator('model-viewer')).toHaveCount(0)
    expect(state.referenceRequests).toHaveLength(1)

    const handoff = await page.evaluate(() => sessionStorage.getItem('__scene_template_test_handoff'))
    expect(handoff).toBeTruthy()
    const handedScene = JSON.parse(handoff!) as SceneLike
    expect(handedScene.narrative).toMatchObject({ templateId: 'cinema-establishing' })
    expect(handedScene.name).toBe('Referencia coral guardada')
    expect(handedScene.duration).toBe(5)
    expect(handedScene.generationPolicy).toBe('provided_only')
    expect(handedScene).toEqual(referenceScene())
    await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), PENDING_SCENE_KEY)).toBeNull()

    await sceneName.fill('Ajuste prueba')
    await page.getByRole('button', { name: 'Save scene', exact: true }).first().click()
    await expect.poll(() => state.postedPayloads.length).toBe(1)
    const postedPayload = state.postedPayloads[0]
    const postedScene = postedPayload.scene as SceneLike
    expect(postedPayload.workspace).toBe('default')
    expect(postedScene.name).toBe('Ajuste prueba')
    expect(postedScene.generationPolicy).toBe('provided_only')
    expect(postedScene.narrative).toMatchObject({
      templateId: 'cinema-establishing',
      controls: expect.objectContaining({
        catalogVersion: CATALOG_VERSION,
        templateVersion: 1,
        reviewStatus: 'candidate',
      }),
    })
    expect(SAVED_OUTPUT).toMatchObject({ name: 'review.scene.json', type: 'scene', url: expect.stringContaining('/api/v1/file/review.scene.json') })
    expect(state.recordingRequests).toHaveLength(0)

    // A later unsaved edit must not replace the persisted scene when reopening.
    await sceneName.fill('Nombre temporal no guardado')
    await page.getByRole('button', { name: 'Open scene', exact: true }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Open 3D Video scene' })
    await expect(dialog).toBeVisible()
    await confirmLibraryScene(dialog, 'review')

    await expect(sceneName).toHaveValue('Ajuste prueba')
    await expect.poll(() => state.fileRequests.length).toBeGreaterThan(0)
    expect(state.outputRequests.some(url => new URL(url).searchParams.get('media_type') === 'scene')).toBe(true)
    const recovered = await expect.poll(() => readAutosave(page)).toEqual(expect.objectContaining({
      name: 'Ajuste prueba',
      generationPolicy: 'provided_only',
    }))
    void recovered
    const recoveredScene = await readAutosave(page)
    expect(recoveredScene?.narrative).toMatchObject({
      templateId: 'cinema-establishing',
      controls: expect.objectContaining({ catalogVersion: CATALOG_VERSION, templateVersion: 1, reviewStatus: 'candidate' }),
    })
    expect(recoveredScene).toEqual(postedScene)
  } finally {
    await closeApp(page, session)
  }
})

test('Library template bindings survive the real editor save and reopen without generation', async ({ page }) => {
  const session = await prepareReviewPage(page)
  const state = reviewRouteState()
  await installReviewRoutes(page, state)
  const catalogRequests: string[] = []
  const assets = ['hero', 'plate'].map(name => ({
    id: `canonical-${name}`, filename: `${name}(1).svg`, kind: 'image', metadata_status: 'canonical',
    size_bytes: 100, created_at: 1, completed_at: 2, workspace_ids: ['default'],
    locations: [{ workspace_id: 'default', filename: `${name}(1).svg`, url: `/api/v1/file/${name}%281%29.svg?workspace=default` }],
    url: `/api/v1/file/${name}%281%29.svg?workspace=default`, origin: { tool: 'fixture' },
    execution: { run_id: `run-${name}` }, model: { provider: 'fixture', id: 'no-model' }, prompt_preview: '',
  }))
  await page.route('**/api/v1/assets**', async route => {
    const url = new URL(route.request().url())
    catalogRequests.push(url.pathname)
    const id = url.pathname.split('/assets/')[1]
    await route.fulfill({ json: id ? assets.find(item => item.id === id) : { assets, total: assets.length } })
  })
  await page.route('**/api/v1/file/*.svg*', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#5577aa"/></svg>' }))
  await page.route('**/api/v1/outputs/thumbnail/*.svg*', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#5577aa"/></svg>' }))
  try {
    await page.goto('/scene-template-review?editor=1')
    await page.getByRole('button', { name: 'Templates · create with my Library assets' }).click()
    const composer = page.getByRole('dialog', { name: 'Create scene from Library' })
    await expect(composer.getByLabel('Visual BPM')).toBeDisabled()
    await chooseComposerLibraryFile(page, composer, 'hero(1).svg')
    await composer.getByRole('button', { name: 'Background (required)', exact: true }).click()
    await chooseComposerLibraryFile(page, composer, 'plate(1).svg')
    await composer.getByRole('checkbox').check()
    await composer.getByRole('button', { name: 'Create and open in editor', exact: true }).click()
    await expect(composer).toHaveCount(0)
    expect(catalogRequests).toContain('/api/v1/assets/canonical-hero')
    expect(catalogRequests).toContain('/api/v1/assets/canonical-plate')
    const name = page.getByLabel('Scene name', { exact: true })
    await name.fill('Library binding roundtrip')
    await page.getByRole('button', { name: 'Save scene', exact: true }).first().click()
    await expect.poll(() => state.postedPayloads.length).toBe(1)
    const saved = state.postedPayloads[0].scene as SceneLike
    expect(saved.generationPolicy).toBe('provided_only')
    expect(saved.narrative).toMatchObject({ assets: [
      { slot: 'hero', catalogAtAssignment: { assetId: 'canonical-hero', workspaceId: 'default', runId: 'run-hero' } },
      { slot: 'plate', catalogAtAssignment: { assetId: 'canonical-plate', workspaceId: 'default', runId: 'run-plate' } },
    ] })
    await name.fill('Not saved')
    await page.getByRole('button', { name: 'Open scene', exact: true }).first().click()
    const library = page.getByRole('dialog', { name: 'Open 3D Video scene' })
    await confirmLibraryScene(library, 'review')
    await expect(name).toHaveValue('Library binding roundtrip')
    await expect.poll(() => readAutosave(page)).toEqual(saved)
    expect(state.recordingRequests).toHaveLength(0)
  } finally { await closeApp(page, session) }
})

test('shows a visible error and keeps the gallery when the saved reference is missing', async ({ page }) => {
  const session = await prepareReviewPage(page)
  const state = reviewRouteState()
  state.referenceMode = 'missing'
  await installReviewRoutes(page, state)

  try {
    await openGallery(page)
    const card = page.locator('[data-template-id="cinema-establishing"]')
    await card.getByTestId('open-scene-cinema-establishing').click()
    await expect(page).toHaveURL(/\/scene-template-review$/)
    await expect(card.getByRole('alert').filter({ hasText: 'No está disponible el snapshot' })).toBeVisible()
    await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), PENDING_SCENE_KEY)).toBeNull()
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('__scene_template_test_handoff'))).toBeNull()
    expect(state.referenceRequests).toHaveLength(1)
  } finally {
    await closeApp(page, session)
  }
})

test('rejects a mismatched saved reference without navigating or handing it to the editor', async ({ page }) => {
  const session = await prepareReviewPage(page)
  const state = reviewRouteState()
  state.referenceMode = 'mismatch'
  await installReviewRoutes(page, state)

  try {
    await openGallery(page)
    const card = page.locator('[data-template-id="cinema-establishing"]')
    await card.getByTestId('open-scene-cinema-establishing').click()
    await expect(page).toHaveURL(/\/scene-template-review$/)
    await expect(card.getByRole('alert').filter({ hasText: 'La escena guardada no coincide' })).toBeVisible()
    await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), PENDING_SCENE_KEY)).toBeNull()
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('__scene_template_test_handoff'))).toBeNull()
    expect(state.referenceRequests).toHaveLength(1)
  } finally {
    await closeApp(page, session)
  }
})

test('keeps review decisions across reload and exports catalog/template versions', async ({ page }) => {
  const session = await prepareReviewPage(page)
  try {
    await openGallery(page)
    const card = page.locator('[data-template-id="cinema-establishing"]')
    const keep = card.getByRole('button', { name: 'Conservar', exact: true })
    await keep.click()
    await expect(keep).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => page.evaluate(key => {
      const value = localStorage.getItem(key)
      return value ? JSON.parse(value) : null
    }, REVIEW_STORAGE_KEY)).toMatchObject({
      catalogVersion: EXPANDED_CATALOG_VERSION,
      choices: { 'cinema-establishing': { decision: 'keep', templateVersion: 1 } },
    })

    await page.reload()
    const reloadedKeep = page.locator('[data-template-id="cinema-establishing"]').getByRole('button', { name: 'Conservar', exact: true })
    await expect(reloadedKeep).toHaveAttribute('aria-pressed', 'true')

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Exportar revisión JSON', exact: true }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(`scene-template-review-${EXPANDED_CATALOG_VERSION}.json`)
    const downloadPath = await download.path()
    expect(downloadPath).toBeTruthy()
    const exported = JSON.parse(await readFile(downloadPath!, 'utf8')) as {
      catalogVersion: string
      templates: Array<{ id: string; templateVersion: number; decision: string }>
    }
    expect(exported.catalogVersion).toBe(EXPANDED_CATALOG_VERSION)
    expect(exported.templates).toHaveLength(48)
    expect(exported.templates.find(template => template.id === 'cinema-establishing')).toMatchObject({
      templateVersion: 1,
      decision: 'keep',
    })
    expect(exported.templates.find(template => template.id === 'music-spiral-exit')).toMatchObject({
      templateVersion: 1,
      decision: 'pending',
    })
  } finally {
    await closeApp(page, session)
  }
})

test('keeps one active preview player when switching candidate previews', async ({ page }) => {
  const session = await prepareReviewPage(page)
  await page.route('**/scene-template-previews/*.mp4', route => route.fulfill({ status: 404, contentType: 'text/plain', body: 'preview stub' }))
  await page.route('**/scene-template-previews/*.png', route => route.fulfill({ status: 404, contentType: 'text/plain', body: 'poster stub' }))

  try {
    await openGallery(page)
    const first = page.locator('[data-template-id="cinema-establishing"]')
    const second = page.locator('[data-template-id="music-pulse"]')
    await first.getByRole('button', { name: /Ver escena/ }).click()
    await expect(page.locator('video')).toHaveCount(1)
    await expect(first.locator('video')).toHaveCount(1)
    await second.getByRole('button', { name: /Ver escena/ }).click()
    await expect(page.locator('video')).toHaveCount(1)
    await expect(first.locator('video')).toHaveCount(0)
    await expect(second.locator('video')).toHaveCount(1)
  } finally {
    await closeApp(page, session)
  }
})

test('opens an expanded music template with explicit component roles without inventing a published reference', async ({ page }) => {
  const session = await prepareReviewPage(page)
  await installReviewRoutes(page, reviewRouteState())
  try {
    await openGallery(page)
    const card = page.locator('[data-template-id="music-orbit-duel"]')
    await expect(card.getByText('subject_1', { exact: true })).toBeVisible()
    await expect(card.getByText('subject_2', { exact: true })).toBeVisible()
    await expect(card.getByText('background', { exact: true })).toBeVisible()
    await expect(card.getByTestId('open-scene-music-orbit-duel')).toBeDisabled()
    await card.getByTestId('open-scene-variant-music-orbit-duel').click()
    await expect(page).toHaveURL(/\/scene-template-review\?editor=1$/)
    await expect(page.getByLabel('Scene name', { exact: true })).toBeVisible()
    const handoff = await page.evaluate(() => JSON.parse(sessionStorage.getItem('__scene_template_test_handoff')!))
    expect(handoff.generationPolicy).toBe('provided_only')
    expect(handoff.narrative.controls.catalogVersion).toBe(EXPANDED_CATALOG_VERSION)
    expect(handoff.narrative.assets.map((asset: { slot: string }) => asset.slot)).toEqual(['subject_1', 'subject_2', 'background'])
  } finally {
    await closeApp(page, session)
  }
})

test('migrates legacy decisions without overwriting them or approving the new music pack', async ({ page }) => {
  const session = await prepareReviewPage(page)
  const legacyKey = 'hocuspocus.scene-template-review.v1'
  const legacy = JSON.stringify({ schemaVersion: 1, catalogVersion: CATALOG_VERSION, choices: {
    'cinema-establishing': { id: 'cinema-establishing', templateVersion: 1, decision: 'keep', notes: 'original' },
    'music-spiral-exit': { id: 'music-spiral-exit', templateVersion: 1, decision: 'keep', notes: 'invalid legacy approval' },
  } })
  try {
    await openGallery(page)
    await page.evaluate(({ key, raw, expanded }) => {
      localStorage.removeItem(expanded)
      localStorage.setItem(key, raw)
    }, { key: legacyKey, raw: legacy, expanded: CATALOG_REVIEW_STORAGE_KEY })
    await page.reload()
    await expect(page.locator('[data-template-id="cinema-establishing"]').getByRole('button', { name: 'Conservar', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('[data-template-id="music-spiral-exit"]').getByRole('button', { name: 'Pendiente', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(await page.evaluate(key => localStorage.getItem(key), legacyKey)).toBe(legacy)
  } finally {
    await closeApp(page, session)
  }
})
