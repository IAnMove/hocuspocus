import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createLipsPack } from '../../src/lib/lipsCreator'
import { CHARACTER_MOUTH_STATES } from '../../src/lib/characterMouthStates'
import type { CharacterKitLibrary } from '../../src/lib/characterKit'

function fixture() {
  const pack = createLipsPack('Ruby mouths')
  pack.base = { id: 'ref', name: 'Reference', source: '/character-kit-presets/mouths/ruby-ink/closed.png', kind: 'image', reviewState: 'approved', alphaStatus: 'transparent' }
  pack.mouth = Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, {
    id: state, name: state, source: `/character-kit-presets/mouths/ruby-ink/${state}.png`, kind: 'overlay', reviewState: 'approved', alphaStatus: 'transparent',
  }]))
  return pack
}

test('optional mouth deformation warps the outline, follows audio and leaves saved images intact', async ({ page }) => {
  const session = await gotoApp(page), pack = fixture(), original = structuredClone(pack)
  const mutations: string[] = []
  page.on('request', request => { if (['POST', 'PATCH'].includes(request.method())) mutations.push(request.url()) })
  await page.route('**/api/v1/character-kits/lips-creator/**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: pack.id, kits: { [pack.id]: pack } } }))
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  for (const state of ['closed', 'wide']) await page.route(`**/ruby-ink/${state}.png`, route => route.fulfill({ contentType: 'image/svg+xml', body:
    `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><ellipse cx="128" cy="128" rx="${state === 'closed' ? 90 : 55}" ry="${state === 'closed' ? 14 : 80}" fill="#ff3344"/></svg>` }))
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  const preview = panel.getByRole('region', { name: 'Speech preview', exact: true })
  const toggle = preview.getByRole('checkbox', { name: 'Deform between mouths · experimental', exact: true })
  await expect(toggle).not.toBeChecked()
  await toggle.check()
  const canvas = preview.getByTestId('lips-morph-canvas')
  await expect(canvas).toBeVisible()
  await preview.getByText('Compare two mouths without audio', { exact: true }).click()
  await expect(canvas).toHaveAttribute('data-progress', '0.5')
  const progress = preview.getByRole('slider', { name: 'Deformation', exact: true })
  const bounds = () => canvas.evaluate((element: HTMLCanvasElement) => {
    const pixels = element.getContext('2d')!.getImageData(0, 0, element.width, element.height).data
    let left = element.width, right = 0, top = element.height, bottom = 0
    for (let y = 0; y < element.height; y++) for (let x = 0; x < element.width; x++) {
      if (pixels[(y * element.width + x) * 4 + 3] > 128) { left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y) }
    }
    let interiorAlpha = 255
    for (let y = Math.ceil(top + (bottom - top) * .35); y < top + (bottom - top) * .65; y++) {
      for (let x = Math.ceil(left + (right - left) * .35); x < left + (right - left) * .65; x++) {
        interiorAlpha = Math.min(interiorAlpha, pixels[(y * element.width + x) * 4 + 3])
      }
    }
    return { width: right - left, height: bottom - top, interiorAlpha }
  })
  await progress.fill('0'); await expect(canvas).toHaveAttribute('data-progress', '0')
  const closed = await bounds()
  await progress.fill('100'); await expect(canvas).toHaveAttribute('data-progress', '1')
  const open = await bounds()
  await progress.fill('50'); await expect(canvas).toHaveAttribute('data-progress', '0.5')
  const halfway = await bounds()
  expect(halfway.height).toBeGreaterThan(closed.height + 10)
  expect(halfway.height).toBeLessThan(open.height - 10)
  expect(halfway.width).toBeGreaterThan(open.width + 10)
  expect(halfway.width).toBeLessThan(closed.width - 10)
  expect(halfway.interiorAlpha).toBeGreaterThan(245)
  await expect(canvas).toHaveAttribute('data-mode', 'warp')
  await canvas.evaluate(element => {
    element.dataset.animated = '0'
    new MutationObserver(() => {
      const value = Number(element.dataset.progress)
      if (value > 0 && value < 1) element.dataset.animated = String(Number(element.dataset.animated) + 1)
    }).observe(element, { attributes: true, attributeFilter: ['data-progress'] })
  })
  await preview.getByRole('button', { name: 'Play phrase', exact: true }).click()
  await expect.poll(() => canvas.getAttribute('data-animated')).not.toBe('0')
  await expect(progress).toBeDisabled()
  await preview.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(canvas).toHaveAttribute('data-progress', '1')
  await expect(progress).toBeEnabled()
  await toggle.uncheck()
  await expect(canvas).toHaveCount(0)
  expect(pack).toEqual(original)
  expect(mutations).toEqual([])
  await closeApp(page, session)
})

test('mouth deformation reports an opaque sprite and falls back to the direct preview', async ({ page }) => {
  const session = await gotoApp(page), pack = fixture()
  pack.mouth.closed = { ...pack.mouth.closed!, source: '/opaque-mouth.svg', alphaStatus: 'opaque' }
  await page.route('**/opaque-mouth.svg', route => route.fulfill({ contentType: 'image/svg+xml', body:
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="white"/><ellipse cx="128" cy="128" rx="90" ry="14" fill="red"/></svg>' }))
  await page.route('**/api/v1/character-kits/lips-creator/**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: pack.id, kits: { [pack.id]: pack } } }))
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  const preview = panel.getByRole('region', { name: 'Speech preview', exact: true })
  await preview.getByRole('checkbox', { name: 'Deform between mouths · experimental', exact: true }).check()
  await expect(preview.getByRole('status')).toContainText('Use a transparent image')
  await expect(preview.getByTestId('lips-morph-canvas')).toBeVisible()
  await expect(preview.getByTestId('lips-morph-canvas')).toHaveAttribute('data-mode', 'direct')
  await closeApp(page, session)
})

test('Lips Creator opens beside Character Creator, saves vowel changes and previews a phrase without inference', async ({ page }) => {
  const session = await gotoApp(page)
  const pack = fixture()
  let library: CharacterKitLibrary = { version: 1, revision: 0, activeId: pack.id, kits: { [pack.id]: pack } }
  const inference: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && /generate|speech\/analyze/.test(request.url())) inference.push(request.url()) })
  await page.route('**/api/v1/character-kits/lips-creator/**', async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.baseRevision).toBe(library.revision)
      library = { ...library, revision: library.revision + 1, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    await route.fulfill({ json: library })
  })
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await expect(panel.getByTestId('lips-collection-grid').getByRole('button').first()).toHaveText(/New/)
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  await panel.getByRole('combobox', { name: 'Mouth for A', exact: true }).selectOption('round')
  await panel.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => library.kits[pack.id].mouthMapping?.A).toBe('round')
  await panel.getByRole('button', { name: 'Collection', exact: true }).click()
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  await expect(panel.getByRole('combobox', { name: 'Mouth for A', exact: true })).toHaveValue('round')
  await panel.getByRole('button', { name: 'Play phrase', exact: true }).click()
  await expect.poll(() => panel.locator('audio').evaluate((element: HTMLAudioElement) => element.currentTime)).toBeGreaterThan(.15)
  await panel.getByRole('button', { name: 'Pause', exact: true }).click()
  await panel.getByRole('button', { name: 'Restore defaults', exact: true }).click()
  await expect(panel.getByRole('combobox', { name: 'Mouth for A', exact: true })).toHaveValue('wide')
  await panel.getByRole('button', { name: 'Collection', exact: true }).click()
  await panel.getByRole('button', { name: /New/ }).click()
  await panel.getByRole('textbox', { name: 'Collection name', exact: true }).fill('New test collection')
  await panel.getByRole('button', { name: 'Save', exact: true }).click()
  await panel.getByRole('button', { name: 'Collection', exact: true }).click()
  await expect(panel.getByRole('button', { name: /New test collection/ })).toBeVisible()
  await expect(panel.getByRole('button', { name: /Ruby mouths/ })).toBeVisible()
  expect(inference).toEqual([])
  await page.screenshot({ path: '/tmp/hocus-lips-collection.png' })
  await closeApp(page, session)
})

test('redoing one mouth stages a candidate and preserves the approved collection until accepted', async ({ page }) => {
  const session = await gotoApp(page)
  const pack = fixture(), original = structuredClone(pack.mouth)
  let library: CharacterKitLibrary = { version: 1, revision: 0, activeId: pack.id, kits: { [pack.id]: pack } }
  await page.route('**/api/v1/models', route => route.fulfill({ json: { families: [{ id: 'qwen', label: 'Qwen', order: 1 }],
    models: [{ model_type: 'qwen_image_edit_20b', name: 'Qwen Image Edit', family: 'qwen', architecture: 'qwen_image_edit', is_downloaded: true, supports_ref_images: true, is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 0 }] } }))
  await page.route('**/api/v1/character-kits/lips-creator/**', route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      library = { ...library, revision: library.revision + 1, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    return route.fulfill({ json: library })
  })
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { url: '/api/v1/uploads/reference.png', filename: 'reference.png', path: 'reference.png' } }))
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/v1/generate', async route => { requests.push(route.request().postDataJSON()); await route.fulfill({ json: { job_id: 'mouth-job', status: 'queued' } }) })
  await page.route('**/api/v1/status/mouth-job', route => route.fulfill({ json: { job_id: 'mouth-job', status: 'completed', output_files: ['new-mouth.png'], progress: 1 } }))
  const image = await readFile(new URL('../../public/character-kit-presets/mouths/ruby-ink/round.png', import.meta.url))
  await page.route('**/api/v1/file/new-mouth.png**', route => route.fulfill({ body: image, contentType: 'image/png' }))
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Lips Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  await panel.getByRole('button', { name: /^Open A$/ }).click()
  await panel.getByRole('button', { name: 'Redo this mouth', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Accept mouth', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  expect(requests[0].model_type).toBe('qwen_image_edit_20b')
  expect(requests[0].workspace).toBe('default')
  expect(requests[0].image_refs).toEqual(['reference.png'])
  expect(pack.mouth).toEqual(original)
  await panel.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => library.kits[pack.id].mouthCandidates?.wide?.source).toContain('new-mouth.png')
  expect(library.kits[pack.id].mouth.wide).toEqual(original.wide)
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Lips Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  await panel.getByRole('button', { name: /Ruby mouths/ }).click()
  await panel.getByRole('button', { name: /^Open A$/ }).click()
  await expect(panel.getByRole('button', { name: 'Accept mouth', exact: true })).toBeEnabled()
  await page.screenshot({ path: '/tmp/hocus-lips-editor.png', fullPage: true })
  await panel.getByRole('button', { name: 'Discard', exact: true }).click()
  await expect(panel.getByText('New version', { exact: true })).toHaveCount(0)
  await closeApp(page, session)
})

const imageModels = {
  families: [{ id: 'qwen', label: 'Qwen', order: 1 }],
  models: ['qwen_image_edit_20b', 'qwen_image_21'].map(model_type => ({ model_type,
    name: model_type === 'qwen_image_21' ? 'Qwen Image 2.1' : 'Qwen Image Edit', family: 'qwen', architecture: model_type,
    is_downloaded: true, supports_ref_images: true, is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 0 })),
}

async function sequentialMouthFixture(page: Page, pack?: ReturnType<typeof fixture>) {
  const session = await gotoApp(page)
  let library: CharacterKitLibrary = { version: 1, revision: 0, activeId: pack?.id || '', kits: pack ? { [pack.id]: pack } : {} }
  const savedCounts: number[] = []
  await page.route('**/api/v1/models', route => route.fulfill({ json: imageModels }))
  await page.route('**/api/v1/character-kits/lips-creator/**', route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.baseRevision).toBe(library.revision)
      savedCounts.push(Object.keys(body.kit.mouthCandidates || {}).length)
      library = { ...library, revision: library.revision + 1, activeId: body.kit.id, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    return route.fulfill({ json: library })
  })
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { url: '/api/v1/uploads/reference.png', filename: 'reference.png', path: 'reference.png' } }))
  const image = await readFile(new URL('../../public/character-kit-presets/mouths/ruby-ink/round.png', import.meta.url))
  await page.route('**/api/v1/file/sequence-*.png**', route => route.fulfill({ body: image, contentType: 'image/png' }))
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Lips Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await panel.getByRole('button', { name: pack ? /Ruby mouths/ : /New/ }).click()
  return { session, panel, savedCounts, library: () => library }
}

test('missing mouths saves all nine sequentially and continues while another studio tab is open', async ({ page }) => {
  test.setTimeout(60000)
  const flow = await sequentialMouthFixture(page)
  const requests: Record<string, unknown>[] = []
  let finished = 0
  await page.route('**/api/v1/generate', route => {
    // The previous image must be both finished and saved before the next POST.
    expect(finished).toBe(requests.length)
    expect(flow.savedCounts.length).toBe(requests.length)
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { job_id: `sequence-${requests.length}`, status: 'queued' } })
  })
  await page.route('**/api/v1/status/sequence-*', route => {
    const id = route.request().url().split('/').pop()!
    finished = Math.max(finished, Number(id.split('-').pop()))
    return route.fulfill({ json: { job_id: id, status: 'completed', output_files: [`${id}.png`], progress: 1 } })
  })
  await flow.panel.getByRole('textbox', { name: 'Collection name', exact: true }).fill('Sequential mouths')
  await flow.panel.getByRole('button', { name: 'Create missing mouths (9)', exact: true }).click()
  await expect(flow.panel.getByTestId('lips-batch-progress')).toContainText('1 / 9')
  await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2)
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  await expect.poll(() => flow.savedCounts.length, { timeout: 30000 }).toBe(9)
  expect(flow.savedCounts).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
  expect(requests).toHaveLength(9)
  expect(Object.keys(flow.library().kits)).toHaveLength(1)
  const saved = Object.values(flow.library().kits)[0]
  expect(Object.keys(saved.mouthCandidates || {})).toEqual([...CHARACTER_MOUTH_STATES])
  expect(saved.mouth).toEqual({})
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const card = flow.panel.getByRole('button', { name: /Sequential mouths/ })
  await expect(card).toContainText('9 mouths created')
  await card.click()
  await expect(flow.panel.getByRole('button', { name: 'Create missing mouths (0)', exact: true })).toBeDisabled()
  await closeApp(page, flow.session)
})

test('a failed mouth does not stop the remaining sequence and retry only creates the missing drawing', async ({ page }) => {
  const pack = fixture(), original = structuredClone(pack.mouth)
  delete pack.mouth.closed; delete pack.mouth.small; delete pack.mouth.wide
  const flow = await sequentialMouthFixture(page, pack)
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/v1/generate', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { job_id: `sequence-${requests.length}`, status: 'queued' } })
  })
  await page.route('**/api/v1/status/sequence-*', route => {
    const id = route.request().url().split('/').pop()!
    return route.fulfill({ json: { job_id: id, status: id === 'sequence-2' ? 'failed' : 'completed',
      error: id === 'sequence-2' ? 'Temporary model failure' : undefined, output_files: id === 'sequence-2' ? [] : [`${id}.png`], progress: 1 } })
  })
  await flow.panel.getByRole('button', { name: 'Create missing mouths (3)', exact: true }).click()
  await expect(flow.panel.getByRole('button', { name: 'Create missing mouths (1)', exact: true })).toBeEnabled()
  await expect(flow.panel.getByTestId('lips-batch-progress')).toContainText('Small failed: Temporary model failure')
  expect(requests).toHaveLength(3)
  expect(flow.savedCounts).toEqual([1, 2])
  await flow.panel.getByRole('button', { name: 'Create missing mouths (1)', exact: true }).click()
  await expect(flow.panel.getByRole('button', { name: 'Create missing mouths (0)', exact: true })).toBeDisabled()
  await expect(flow.panel.getByText('1 mouth created and saved. Review it before accepting.', { exact: true })).toBeVisible()
  expect(requests).toHaveLength(4)
  expect(requests[3].prompt).toContain('narrow horizontal mouth for I')
  const saved = flow.library().kits[pack.id]
  expect(Object.keys(saved.mouthCandidates || {})).toHaveLength(3)
  for (const state of CHARACTER_MOUTH_STATES.filter(state => !['closed', 'small', 'wide'].includes(state))) expect(saved.mouth[state]).toEqual(original[state])
  await closeApp(page, flow.session)
})

test('cancelling a sequence stops pending mouths and keeps the completed mouth after a reload', async ({ page }) => {
  const flow = await sequentialMouthFixture(page)
  let submitted = 0
  const cancelled: string[] = []
  await page.route('**/api/v1/generate', route => route.fulfill({ json: { job_id: `sequence-${++submitted}`, status: 'queued' } }))
  await page.route('**/api/v1/status/sequence-*', route => {
    const id = route.request().url().split('/').pop()!
    return route.fulfill({ json: { job_id: id, status: id === 'sequence-1' ? 'completed' : 'running', output_files: id === 'sequence-1' ? ['sequence-1.png'] : [], progress: .5 } })
  })
  await page.route('**/api/v1/cancel/sequence-*', route => { cancelled.push(route.request().url().split('/').pop()!); return route.fulfill({ json: { status: 'cancelled' } }) })
  await flow.panel.getByRole('button', { name: 'Create missing mouths (9)', exact: true }).click()
  await expect.poll(() => submitted).toBe(2)
  await flow.panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(flow.panel.getByRole('button', { name: 'Create missing mouths (8)', exact: true })).toBeEnabled()
  await expect.poll(() => cancelled).toEqual(['sequence-2'])
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Lips Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  await flow.panel.getByRole('button', { name: /New mouths.*1 mouth created/ }).click()
  await expect(flow.panel.getByRole('button', { name: 'Create missing mouths (8)', exact: true })).toBeEnabled()
  expect(submitted).toBe(2)
  expect(flow.savedCounts).toEqual([1])
  await closeApp(page, flow.session)
})

test('New mouths generate from a description with no character, upload or reference', async ({ page }) => {
  const session = await gotoApp(page)
  await page.route('**/api/v1/models', route => route.fulfill({ json: imageModels }))
  await page.route('**/api/v1/character-kits/lips-creator/**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  const requests: Record<string, unknown>[] = []
  let uploads = 0
  await page.route('**/api/v1/upload', route => { uploads++; return route.fulfill({ json: {} }) })
  await page.route('**/api/v1/generate', route => { requests.push(route.request().postDataJSON()); return route.fulfill({ json: { job_id: 'text-mouth', status: 'queued' } }) })
  await page.route('**/api/v1/status/text-mouth', route => route.fulfill({ json: { job_id: 'text-mouth', status: 'completed', output_files: ['text-mouth.png'], progress: 1 } }))
  const image = await readFile(new URL('../../public/character-kit-presets/mouths/ruby-ink/closed.png', import.meta.url))
  await page.route('**/api/v1/file/text-mouth.png**', route => route.fulfill({ body: image, contentType: 'image/png' }))
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Lips Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Lips Creator', exact: true }).click()
  const panel = page.getByTestId('lips-creator')
  await panel.getByRole('button', { name: /New/ }).click()
  await expect(panel.getByRole('radio', { name: 'Description only', exact: true })).toBeChecked()
  await expect(panel.getByRole('combobox', { name: 'Use a character as reference', exact: true })).toHaveCount(0)
  const model = panel.getByRole('combobox', { name: 'Image model', exact: true })
  await expect(model).toHaveValue('qwen_image_21')
  await expect(model.locator('option[value="qwen_image_edit_20b"]')).toHaveCount(0)
  await panel.getByRole('textbox', { name: 'Description and style', exact: true }).fill('Thin burgundy watercolor lips')
  await panel.getByRole('button', { name: 'Create this mouth', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Accept mouth', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  expect(requests[0].model_type).toBe('qwen_image_21')
  expect(requests[0].image_refs).toBeUndefined()
  expect(requests[0].prompt).toContain('Thin burgundy watercolor lips')
  expect(requests[0].prompt).not.toContain('Use the reference')
  expect(uploads).toBe(0)
  await panel.getByRole('radio', { name: 'With a reference', exact: true }).check()
  await expect(model).toHaveValue('qwen_image_edit_20b')
  await expect(panel.getByRole('button', { name: 'Redo this mouth', exact: true })).toBeDisabled()
  await panel.getByRole('radio', { name: 'Description only', exact: true }).check()
  await expect(panel.getByRole('button', { name: 'Redo this mouth', exact: true })).toBeEnabled()
  await page.screenshot({ path: '/tmp/hocus-lips-description.png', fullPage: true })
  await closeApp(page, session)
})

test('Character Creator generates and saves an initial image that Lips Creator can select', async ({ page }) => {
  const session = await gotoApp(page)
  let library: CharacterKitLibrary = { version: 1, revision: 0, activeId: '', kits: {} }
  await page.route('**/api/v1/models', route => route.fulfill({ json: imageModels }))
  await page.route('**/api/v1/character-kits/library**', route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.baseRevision).toBe(library.revision)
      library = { ...library, revision: library.revision + 1, activeId: body.kit.id, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    return route.fulfill({ json: library })
  })
  await page.route('**/api/v1/character-kits/lips-creator/**', route => route.fulfill({ json: { version: 1, revision: 0, activeId: '', kits: {} } }))
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/v1/generate', route => { requests.push(route.request().postDataJSON()); return route.fulfill({ json: { job_id: 'new-character', status: 'queued' } }) })
  await page.route('**/api/v1/status/new-character', route => route.fulfill({ json: { job_id: 'new-character', status: 'completed', output_files: ['new-character.png'], progress: 1 } }))
  const image = await readFile(new URL('../../public/character-kit-presets/mouths/ruby-ink/closed.png', import.meta.url))
  await page.route('**/api/v1/file/new-character.png**', route => route.fulfill({ body: image, contentType: 'image/png' }))
  await page.route('**/api/v1/outputs/thumbnail/character-reference.png**', route => route.fulfill({ body: image, contentType: 'image/png' }))
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { url: '/api/v1/uploads/character-reference.png', path: 'character-reference.png', filename: 'character-reference.png' } }))
  await page.reload()
  if (!await page.getByRole('tab', { name: 'Character Creator', exact: true }).isVisible()) await page.getByRole('button', { name: 'Studios', exact: true }).click()
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  const creator = page.getByTestId('character-image-creator')
  await creator.getByRole('textbox', { name: 'Character name', exact: true }).fill('Elder magician')
  await creator.getByRole('textbox', { name: 'Character description', exact: true }).fill('Silver-haired magician in a burgundy coat, watercolor style')
  await expect(creator.getByRole('combobox', { name: 'Image model', exact: true })).toHaveValue('qwen_image_21')
  await creator.getByRole('button', { name: 'Generate character image', exact: true }).click()
  await expect(creator.getByRole('button', { name: 'Save character', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  expect(requests[0].image_refs).toBeUndefined()
  expect(requests[0].prompt).toContain('Silver-haired magician')
  expect(library.kits).toEqual({})
  await creator.getByRole('button', { name: 'Use for 360 views', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Generate 360 orbit', exact: true })).toBeEnabled()
  await expect(page.getByPlaceholder('Empty = MiniMax or the internal LLM describe the photos. Other providers require an A Prompt.')).toHaveValue('Silver-haired magician in a burgundy coat, watercolor style')
  await creator.getByRole('button', { name: 'Save character', exact: true }).click()
  await expect(creator.getByRole('button', { name: 'Create its mouths', exact: true })).toBeVisible()
  const kit = Object.values(library.kits)[0]
  expect(kit.name).toBe('Elder magician')
  expect(kit.base?.reviewState).toBe('approved')
  expect(kit.identityReference?.source).toContain('new-character.png')
  await page.screenshot({ path: '/tmp/hocus-character-description.png', fullPage: true })
  await creator.getByRole('button', { name: 'Create its mouths', exact: true }).click()
  const lips = page.getByTestId('lips-creator')
  await lips.getByRole('button', { name: /New/ }).click()
  await lips.getByRole('radio', { name: 'With a reference', exact: true }).check()
  await lips.getByRole('combobox', { name: 'Use a character as reference', exact: true }).selectOption(kit.id)
  await expect(lips.getByRole('img', { name: 'Reference image', exact: true })).toBeVisible()
  await expect(lips.getByRole('button', { name: 'Create this mouth', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  await closeApp(page, session)
})

test('a saved Lips collection can be selected, placed and saved in the character workshop without generation', async ({ page }) => {
  const session = await gotoApp(page), pack = fixture()
  const { createCharacterKit } = await import('../../src/lib/characterKit')
  const kit = createCharacterKit('Linked actor')
  kit.base = { id: 'actor-base', name: 'Actor', source: '/character-kit-presets/mouths/ruby-ink/small.png', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
  kit.anchors = { base: { mouth: { offsetX: 7, offsetY: -20, scale: .1, rotation: 0 } } }
  pack.mouthMapping = { rest: 'round', A: 'tongue' }
  let library: CharacterKitLibrary = { version: 1, revision: 4, activeId: kit.id, kits: { [kit.id]: kit } }
  const inference: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && /\/(generate|generation|cleanup|remove-background)(\b|\/)/.test(new URL(request.url()).pathname)) inference.push(request.url()) })
  await page.route('**/api/v1/character-kits/lips-creator/library**', route => route.fulfill({ json: { version: 1, revision: 3, activeId: pack.id, kits: { [pack.id]: pack } } }))
  await page.route('**/api/v1/character-kits/library**', route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.baseRevision).toBe(library.revision)
      library = { ...library, revision: library.revision + 1, kits: { [body.kit.id]: body.kit } }
    }
    return route.fulfill({ json: library })
  })
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { filename: 'rest.png', url: '/api/v1/uploads/rest.png' } }))
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  await page.locator('summary').filter({ hasText: 'Prepare 2D speech' }).click()
  const workshop = page.getByRole('region', { name: 'Prepare 2D speech', exact: true })
  await expect(workshop.getByRole('combobox', { name: 'Saved character' })).toHaveValue(kit.id)
  await workshop.locator('summary').filter({ hasText: 'Use my Lips Creator mouths' }).click()
  await workshop.getByRole('combobox', { name: 'Use my Lips Creator mouths' }).selectOption(pack.id)
  await workshop.getByRole('button', { name: 'Apply this collection', exact: true }).click()
  await expect(workshop.getByText(/Unsaved changes\./)).toBeVisible()
  await workshop.getByRole('button', { name: 'Apply placement to all mouths', exact: true }).first().click()
  await workshop.getByRole('button', { name: 'Save speech character', exact: true }).click()
  await expect(workshop.getByText(/Character saved to this workspace/)).toBeVisible()
  expect(library.kits[kit.id].mouthMapping).toEqual(pack.mouthMapping)
  expect(library.kits[kit.id].mouth.tongue!.source).toBe(pack.mouth.tongue!.source)
  expect(library.kits[kit.id].base!.source).toBe(kit.base.source)
  expect(library.kits[kit.id].anchors.base.mouth).toEqual(kit.anchors.base.mouth)
  expect(inference).toEqual([])
  await closeApp(page, session)
})
