import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

// Real sandbox, real Worker/OffscreenCanvas, real three.js and WebCodecs.
// Only the HocusPocus API (LLM and recording upload) is simulated.

async function openVideoJs(page: Page) {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video JS', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  const workspace = page.getByTestId('videojs-workspace')
  await expect(workspace).toBeVisible()
  await expect(workspace.getByRole('button', { name: 'Play', exact: true })).toBeEnabled({ timeout: 30_000 })
  return { session, workspace }
}

function importDocument(page: Page, document: unknown) {
  return page.locator('input[type="file"][accept=".json,application/json"]').setInputFiles({
    name: 'scene.videojs.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(document)),
  })
}

async function seek(workspace: Locator, seconds: number) {
  await workspace.getByRole('slider', { name: 'Video position' }).fill(String(seconds))
}

async function litSamples(page: Page) {
  return page.getByTestId('videojs-canvas').evaluate((canvas: HTMLCanvasElement) => {
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height)
    let lit = 0
    let samples = 0
    for (let index = 0; index < data.length; index += 4 * 101) {
      samples += 1
      if (data[index] + data[index + 1] + data[index + 2] > 40) lit += 1
    }
    return lit / samples
  })
}

const scene = (id: string, title: string, code: string, duration = 1) => ({ id, title, kind: '2d', duration, transition: 'none', code })

test('demo renders 2D and 3D scenes in the isolated sandbox', async ({ page }) => {
  test.setTimeout(90_000)
  const { session, workspace } = await openVideoJs(page)
  await expect.poll(() => litSamples(page), { timeout: 15_000 }).toBeGreaterThan(0.2)
  await expect(workspace.getByText('5 scenes', { exact: true })).toBeVisible()
  // 13.5 s is where the 3D showcase starts; 16 s is well inside it.
  await seek(workspace, 16)
  await expect(page.getByTestId('videojs-time')).toContainText('0:16.00')
  await page.waitForTimeout(1500)
  await expect(workspace.getByLabel('This scene has an error')).toHaveCount(0)
  await expect(workspace.getByRole('alert')).toHaveCount(0)
  expect(await litSamples(page)).toBeGreaterThan(0.05)
  const sandbox = page.locator('iframe[title="Video JS sandbox"]')
  await expect(sandbox).toHaveAttribute('sandbox', 'allow-scripts')
  await closeApp(page, session)
})

test('scene code cannot reach the network or HocusPocus', async ({ page }) => {
  test.setTimeout(90_000)
  let hits = 0
  const server: Server = createServer((request, response) => {
    hits += 1
    response.writeHead(200, { 'access-control-allow-origin': '*' })
    response.end('self.postMessage("escaped")')
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const probe = `http://127.0.0.1:${(server.address() as AddressInfo).port}/probe`
  try {
    const { session, workspace } = await openVideoJs(page)
    // Chromium reports CSP-blocked requests as request + requestfailed('csp');
    // only a response or a finished request would mean the call escaped.
    const apiHits: string[] = []
    const blocked: string[] = []
    page.on('requestfinished', request => { if (request.url().includes('videojs-probe')) apiHits.push(request.url()) })
    page.on('response', response => { if (response.url().includes('videojs-probe')) apiHits.push(response.url()) })
    page.on('requestfailed', request => { if (request.url().includes('videojs-probe')) blocked.push(request.failure()?.errorText ?? '') })
    const origin = new URL(page.url()).origin
    await importDocument(page, {
      title: 'Escape attempt',
      scenes: [scene('escape', 'Escape', `return {
  setup() {
    const targets = [${JSON.stringify(probe)}, ${JSON.stringify(`${origin}/api/v1/videojs-probe`)}]
    for (const url of targets) {
      try { importScripts(url + '?import') } catch (error) {}
      try { const xhr = new XMLHttpRequest(); xhr.open('GET', url + '?xhr', false); xhr.send() } catch (error) {}
      try { WorkerGlobalScope.prototype.fetch.call(self, url + '?fetch').catch(() => {}) } catch (error) {}
      try { new WebSocket(url.replace('http', 'ws') + '?ws') } catch (error) {}
      try { new EventSource(url + '?sse') } catch (error) {}
    }
    return {}
  },
  render({ ctx, kit }) { kit.draw.background(ctx, '#2255aa') },
}`, 2)],
    })
    await expect(workspace.getByText('1 scene', { exact: true })).toBeVisible()
    await expect(workspace.getByRole('button', { name: 'Play', exact: true })).toBeEnabled()
    await page.waitForTimeout(2000)
    expect(hits).toBe(0)
    expect(apiHits).toEqual([])
    expect(blocked.every(reason => reason === 'csp')).toBe(true)
    await expect(workspace.getByLabel('This scene has an error')).toHaveCount(0)
    await closeApp(page, session)
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
})

test('LLM creates a video, fixes a failing scene and the MP4 is published', async ({ page }) => {
  test.setTimeout(150_000)
  const { session, workspace } = await openVideoJs(page)
  const llmBodies: Array<{ prompt: string; system_prompt: string }> = []
  const intro = 'return { render({ ctx, t, width, height, kit }) { kit.draw.background(ctx, [kit.theme.primary, kit.theme.background]); kit.draw.text(ctx, "Hola", width / 2, height / 2, { size: height * 0.2, align: "center", alpha: kit.tween(t, 0, 0.3) }) } }'
  const broken = 'return {\n  render({ ctx, t, kit }) {\n    kit.draw.background(ctx, kit.theme.accent)\n    if (t > 0.2) notDefined.call()\n  },\n}'
  const fixed = 'return {\n  render({ ctx, kit }) {\n    kit.draw.background(ctx, kit.theme.accent)\n  },\n}'
  await page.route('**/api/v1/llm/generate', async route => {
    const body = route.request().postDataJSON()
    llmBodies.push(body)
    const text = llmBodies.length === 1
      ? `<video title="Demo LLM">\n<scene title="Intro" kind="2d" duration="1" transition="none">\n${intro}\n</scene>\n<scene title="Broken" kind="2d" duration="1" transition="fade">\n${broken}\n</scene>\n</video>`
      : `<video><scene id="${body.prompt.match(/id="([^"]+)"/)[1]}">\n${fixed}\n</scene></video>`
    await route.fulfill({ json: { text } })
  })
  let upload: Buffer | null = null
  await page.route('**/api/v1/scenes/recordings', async route => {
    upload = route.request().postDataBuffer()
    await route.fulfill({ json: { name: 'videojs-demo-llm.mp4', url: '/api/v1/file/videojs-demo-llm.mp4', type: 'video', size: upload?.length ?? 0, created_at: 0 } })
  })

  await workspace.getByLabel('Describe the video').fill('Una presentación corta')
  await workspace.getByRole('button', { name: 'Create video', exact: true }).click()
  await expect(workspace.getByText('2 scenes', { exact: true })).toBeVisible()
  expect(llmBodies[0].system_prompt).toContain('OUTPUT FORMAT')
  expect(llmBodies[0].prompt).toContain('Una presentación corta')

  await workspace.getByRole('button', { name: /Broken/ }).click()
  await seek(workspace, 1.6)
  const error = workspace.getByTestId('videojs-scene-error')
  await expect(error).toContainText('render() failed')
  await expect(error).toContainText('line 4')
  await expect(workspace.getByRole('button', { name: 'Render MP4' })).toBeDisabled()

  await error.getByRole('button', { name: 'Fix with LLM' }).click()
  await expect(error).toHaveCount(0)
  expect(llmBodies[1].prompt).toContain('FIX THIS ERROR (render, line 4)')
  await expect(workspace.getByTestId('videojs-code')).toHaveValue(fixed)
  await seek(workspace, 1.7)
  await page.waitForTimeout(800)
  await expect(workspace.getByTestId('videojs-scene-error')).toHaveCount(0)

  // Undo restores the failing version, redo is simply fixing again.
  await workspace.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(workspace.getByTestId('videojs-code')).toHaveValue(broken)
  await workspace.getByTestId('videojs-code').fill(fixed)
  await workspace.getByRole('button', { name: 'Apply code' }).click()

  const exportButton = workspace.getByRole('button', { name: 'Render MP4' })
  await expect(exportButton).toBeEnabled({ timeout: 15_000 })
  await exportButton.click()
  await expect(page.getByTestId('videojs-export-done')).toContainText('videojs-demo-llm.mp4', { timeout: 60_000 })
  expect(upload).not.toBeNull()
  const payload = upload!.toString('latin1')
  expect(payload).toContain('ftyp')
  expect(payload).toContain('"engine":"videojs"')
  expect(payload).toContain('"schema":"hocuspocus.videojs/v1"')
  expect(upload!.length).toBeGreaterThan(2000)
  await closeApp(page, session)
})

test('a hung scene is stopped without freezing the app and recovers after editing', async ({ page }) => {
  test.setTimeout(120_000)
  const { session, workspace } = await openVideoJs(page)
  await importDocument(page, {
    title: 'Hang',
    scenes: [scene('loop', 'Loop', 'return {\n  render() {\n    while (true) {}\n  },\n}', 2)],
  })
  await expect(workspace.getByText('1 scene', { exact: true })).toBeVisible()
  // The main thread must stay responsive while the scene worker spins.
  const started = Date.now()
  await workspace.getByLabel('Video title').fill('Still responsive')
  expect(Date.now() - started).toBeLessThan(5_000)
  await expect(workspace.getByText('The scene sandbox stopped', { exact: false })).toBeVisible({ timeout: 45_000 })
  await expect(workspace.getByTestId('videojs-scene-error')).toContainText('The scene took too long')
  await workspace.getByTestId('videojs-code').fill('return { render({ ctx, kit }) { kit.draw.background(ctx, "#335577") } }')
  await workspace.getByRole('button', { name: 'Apply code' }).click()
  await expect(workspace.getByRole('button', { name: 'Play', exact: true })).toBeEnabled({ timeout: 20_000 })
  await expect(workspace.getByText('The scene sandbox stopped', { exact: false })).toHaveCount(0)
  await expect.poll(() => litSamples(page), { timeout: 10_000 }).toBeGreaterThan(0.5)
  await closeApp(page, session)
})
