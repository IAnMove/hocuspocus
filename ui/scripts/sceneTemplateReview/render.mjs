import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { chromium } from '@playwright/test'
import { LANGUAGE_STORAGE_KEY } from '../../src/i18n/storageKey.ts'
import { animatorLabels } from '../../src/i18n/animatorLabels.ts'

const catalog = await import(new URL('../../src/features/sceneTemplates/catalog.ts', import.meta.url))
const demos = await import(new URL('../../src/features/sceneTemplates/demoScenes.ts', import.meta.url))
const copy = animatorLabels('en')

const renderTimeout = 300_000

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')

function gitSnapshot(repoRoot) {
  const headSha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' }).trim()
  const dirty = execFileSync('git', ['status', '--porcelain', '--untracked-files=all'], { cwd: repoRoot, encoding: 'utf8' }).trim().length > 0
  const diff = execFileSync('git', ['diff', 'HEAD', '--binary'], { cwd: repoRoot, maxBuffer: 20 * 1024 * 1024 })
  return { headSha, dirty, trackedDiffSha256: sha256(diff) }
}

function runtimeVersions(browser) {
  const require = createRequire(import.meta.url)
  const version = executable => execFileSync(executable, ['-version'], { encoding: 'utf8' }).split('\n')[0]
  return { node: process.version, playwright: require('@playwright/test/package.json').version,
    chromium: browser.version(), ffmpeg: version('ffmpeg'), ffprobe: version('ffprobe') }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForImages(page, scene) {
  const expected = scene.layers.filter(layer => layer.type === 'image').length
  if (expected === 0) return
  await page.waitForFunction(expectedCount => {
    const images = [...document.querySelectorAll('img[data-layer-id]')]
    return images.length >= expectedCount
      && images.every(image => image.complete && image.naturalWidth > 0)
  }, expected, { timeout: 60_000 })
}

async function waitForModels(page, scene) {
  const expected = scene.layers.filter(layer => layer.type === 'model3d').length
  if (expected === 0) return
  await page.waitForFunction(expectedCount => {
    const viewers = [...document.querySelectorAll('model-viewer')]
    return viewers.length >= expectedCount && viewers.every(viewer => viewer.loaded === true)
  }, expected, { timeout: 60_000 })
}

async function saveEditableScene(page, server, template) {
  const responsePromise = page.waitForResponse(response => (
    response.url().endsWith('/api/v1/scenes') && response.request().method() === 'POST'
  ), { timeout: 60_000 })
  await page.getByRole('button', { name: copy.saveScene, exact: true }).first().click()
  const response = await responsePromise
  assert(response.ok(), `Editable scene save failed for ${template.id}: ${await response.text()}`)
  const saved = await response.json()
  assert(typeof saved.name === 'string' && /^review-[0-9a-f-]+\.maestro-scene\.json$/.test(saved.name), `Sandbox returned an unsafe scene name for ${template.id}.`)
  const filename = path.join(server.exportsDir, saved.name)
  const bytes = await fs.readFile(filename)
  const snapshot = JSON.parse(bytes.toString('utf8'))
  assert(snapshot.version === 1 && Array.isArray(snapshot.layers), `Saved scene ${template.id} is not editable JSON.`)
  assert(snapshot.narrative?.templateId === template.id, `Saved scene ${template.id} lost its template identity.`)
  const roundTrip = await fetch(`${server.localOrigin}/api/v1/file/${encodeURIComponent(saved.name)}?workspace=default`)
  assert(roundTrip.ok, `Saved scene ${template.id} could not be read from the sandbox index.`)
  assert(Buffer.from(await roundTrip.arrayBuffer()).equals(bytes), `Saved scene ${template.id} changed during server-index round trip.`)
  return { name: saved.name, snapshot }
}

async function renderOne({ browser, server, repoRoot, template, runtime }) {
  const source = gitSnapshot(repoRoot)
  const scene = demos.candidateDemoScene(template.id, 'coral')
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: 'en-US',
    serviceWorkers: 'block',
  })
  const page = await context.newPage()
  page.setDefaultTimeout(60_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  await page.route('**/*', route => {
    const requestUrl = new URL(route.request().url())
    if (requestUrl.origin === server.localOrigin || requestUrl.protocol === 'data:' || requestUrl.protocol === 'blob:') return route.continue()
    return route.abort('blockedbyclient')
  })
  await page.addInitScript(({ snapshot, languageKey }) => {
    localStorage.setItem(languageKey, 'en')
    localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    localStorage.setItem('hocuspocus_welcome_seen_v2', '453')
    sessionStorage.setItem('maestro_scene_animator_pending_scene', JSON.stringify(snapshot))
  }, { snapshot: scene, languageKey: LANGUAGE_STORAGE_KEY })

  try {
    await page.goto(`${server.localOrigin}/scene-template-review?editor=1`, { waitUntil: 'domcontentloaded' })
    await page.getByLabel(copy.sceneNameAria, { exact: true }).waitFor()
    await page.getByLabel(copy.sceneNameAria, { exact: true }).fill(scene.name)
    await page.getByLabel(copy.sceneNameAria, { exact: true }).blur()
    await waitForImages(page, scene)
    await waitForModels(page, scene)
    const savedScene = await saveEditableScene(page, server, template)
    await page.waitForFunction(templateId => {
      const raw = localStorage.getItem('maestro-scene-animator-autosave-v1')
      if (!raw) return false
      try {
        const snapshot = JSON.parse(raw)
        return snapshot?.version === 1
          && Array.isArray(snapshot.layers)
          && snapshot.narrative?.templateId === templateId
      } catch {
        return false
      }
    }, template.id, { timeout: 60_000 })

    const responsePromise = page.waitForResponse(response => (
      response.url().endsWith('/api/v1/scenes/recordings') && response.request().method() === 'POST'
    ), { timeout: renderTimeout })
    console.log(`RENDER ${template.id} ${scene.layers.length} layers`)
    await page.getByRole('button', { name: copy.exportMp4, exact: true }).click()
    const response = await responsePromise
    assert(response.ok(), `MP4 export failed for ${template.id}: ${await response.text()}`)
    const saved = await response.json()
    assert(typeof saved.name === 'string' && /^review-[0-9a-f-]+_3d_scene\.mp4$/.test(saved.name), `Sandbox returned an unsafe MP4 name for ${template.id}.`)
    const sourcePath = path.join(server.exportsDir, saved.name)
    const bytes = await fs.readFile(sourcePath)
    assert(bytes.subarray(4, 8).toString('ascii') === 'ftyp', `Export for ${template.id} is not an MP4.`)
    const recordingMetadataPath = path.join(server.exportsDir, `${saved.name}.metadata.json`)
    const recordingMetadata = JSON.parse(await fs.readFile(recordingMetadataPath, 'utf8'))
    const recordedScene = recordingMetadata.params?.scene
    assert(recordedScene?.narrative?.templateId === template.id, `MP4 metadata for ${template.id} lost its template identity.`)
    assert(JSON.stringify(recordedScene) === JSON.stringify(savedScene.snapshot), `MP4 metadata for ${template.id} changed the editable scene snapshot.`)

    assert(pageErrors.length === 0, `${template.id} page errors:\n${pageErrors.join('\n')}`)
    const previewPath = path.join(server.previewsDir, `${template.id}.mp4`)
    await fs.writeFile(previewPath, bytes, { flag: 'wx' })
    const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', previewPath], { cwd: repoRoot, encoding: 'utf8' }))
    const stream = probe.streams.find(item => item.codec_type === 'video')
    assert(stream && Number(stream.width) === scene.width && Number(stream.height) === scene.height, `MP4 dimensions mismatch for ${template.id}.`)
    const frameRateValue = [stream.avg_frame_rate, stream.r_frame_rate]
      .map(value => {
        const [numerator, denominator] = String(value || '').split('/').map(Number)
        return denominator > 0 ? numerator / denominator : Number(value)
      })
      .find(value => Number.isFinite(value) && value > 0)
    const observedFps = frameRateValue
    assert(Number.isFinite(observedFps) && observedFps > 0, `MP4 FPS is missing for ${template.id}.`)
    assert(Math.abs(observedFps - scene.fps) <= .1, `MP4 FPS mismatch for ${template.id}: expected ${scene.fps}, got ${observedFps}.`)
    const duration = Number(probe.format.duration)
    assert(Number.isFinite(duration) && Math.abs(duration - scene.duration) <= .08, `MP4 duration mismatch for ${template.id}.`)
    const posterPath = path.join(server.previewsDir, `${template.id}.png`)
    execFileSync('ffmpeg', ['-y', '-v', 'error', '-ss', '1.5', '-i', previewPath, '-frames:v', '1', posterPath], { cwd: repoRoot })

    assert(JSON.stringify(gitSnapshot(repoRoot)) === JSON.stringify(source), 'Source changed during rendering; refusing to label this preview as reproducible.')
    const reviewMetadata = {
      catalogVersion: catalog.templateCatalogVersion(template),
      templateId: template.id,
      templateVersion: template.version,
      variant: 'coral',
      status: 'rendered-not-approved',
      generator: 'real SceneAnimatorPanel MP4 exporter',
      sourceCommit: source.headSha,
      headSha: source.headSha,
      dirty: source.dirty,
      trackedDiffSha256: source.trackedDiffSha256,
      sourceState: source.dirty ? 'dirty local tree; untracked files are not content-addressed' : 'clean local commit; merge/release status not inferred',
      runtime,
      renderer: 'layer-compositor-v1',
      duration,
      width: scene.width,
      height: scene.height,
      fps: observedFps,
      sha256: sha256(bytes),
      bytes: bytes.length,
      posterSha256: sha256(await fs.readFile(posterPath)),
      inputReferences: scene.layers.filter(layer => layer.source).map(layer => ({ layerId: layer.id, referenceSha256: sha256(Buffer.from(layer.source)), inlineContent: layer.source.startsWith('data:') })),
      editableSceneFile: savedScene.name,
      editableSceneSha256: sha256(await fs.readFile(path.join(server.exportsDir, savedScene.name))),
      sceneSha256: sha256(Buffer.from(JSON.stringify(recordedScene))),
      scene: recordedScene,
    }
    const metadataPath = path.join(server.previewsDir, `${template.id}.json`)
    await fs.writeFile(metadataPath, JSON.stringify(reviewMetadata, null, 2), { flag: 'wx' })
    assert(pageErrors.length === 0, `${template.id} page errors before publication:\n${pageErrors.join('\n')}`)
    server.registerPreview(`${template.id}.mp4`)
    server.registerPreview(`${template.id}.png`)
    server.registerPreview(`${template.id}.json`)
    console.log(`SAVED ${template.id} ${bytes.length} bytes ${probe.format.duration} seconds`)
    return { id: template.id, status: 'rendered-not-approved', preview: previewPath, metadata: metadataPath }
  } finally {
    await context.close()
  }
}

export async function renderTemplates({ server, repoRoot, templateIds = [] }) {
  const knownIds = new Set(catalog.ALL_SCENE_TEMPLATES.map(template => template.id))
  const unknownIds = [...new Set(templateIds.filter(templateId => !knownIds.has(templateId)))]
  if (unknownIds.length) throw new Error(`Unknown candidate scene template ID(s): ${unknownIds.join(', ')}`)
  // Keep the default legacy batch within its established disk/output quota.
  // New pack IDs are opt-in; do not silently double a user's render batch.
  const candidates = templateIds.length ? catalog.ALL_SCENE_TEMPLATES : catalog.CANDIDATE_SCENE_TEMPLATES
  const selected = candidates.filter(template => !templateIds.length || templateIds.includes(template.id))
  if (!selected.length) throw new Error('No matching candidate scene templates were requested.')
  assert(selected.every(template => /^[a-z0-9][a-z0-9-]*$/.test(template.id)), 'Unsafe template ID; no paths were created.')
  const browser = await chromium.launch({ args: ['--disable-gpu', '--disable-dev-shm-usage'] })
  const results = []
  const failures = []
  try {
    const runtime = runtimeVersions(browser)
    for (const template of selected) {
      try {
        results.push(await renderOne({ browser, server, repoRoot, template, runtime }))
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        failures.push({ id: template.id, error: message })
        const failureMetadata = {
          catalogVersion: catalog.templateCatalogVersion(template),
          templateId: template.id,
          templateVersion: template.version,
          variant: 'coral',
          status: 'render-failed',
          generator: 'real SceneAnimatorPanel MP4 exporter',
          ...gitSnapshot(repoRoot),
          error: message,
          note: 'No placeholder preview was created; rerun after fixing the real failure.',
        }
        const failureName = `${template.id}.failure-${randomUUID()}.json`
        const failurePath = path.join(server.previewsDir, failureName)
        try {
          await fs.writeFile(failurePath, JSON.stringify(failureMetadata, null, 2), { flag: 'wx' })
          server.registerPreview(failureName)
          console.error(`FAILED ${template.id}: ${message}; failure metadata=${failureName}`)
        } catch (publicationError) {
          console.error(`FAILED ${template.id}: ${message}; failure metadata publication failed: ${publicationError instanceof Error ? publicationError.message : String(publicationError)}`)
        }
      }
    }
  } finally {
    await browser.close()
  }
  return { results, failures }
}
