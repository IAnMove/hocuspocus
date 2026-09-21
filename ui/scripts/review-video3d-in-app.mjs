import { chromium } from 'playwright'
import { readFile, mkdir } from 'node:fs/promises'
import assert from 'node:assert/strict'
import path from 'node:path'

// Real app shell + real local assets. No page route interception or alternate UI.
const shotPath = path.resolve(process.argv[2] ?? '../.codex-tmp/speech-review/portrait.world3d.json')
const output = path.resolve('../.codex-tmp/speech-review')
await mkdir(output, { recursive: true })
const shot = JSON.parse(await readFile(shotPath, 'utf8'))
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce' })
const errors = [], failedRequests = []
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => { if (response.status() >= 400) failedRequests.push(response.status() + ' ' + response.url()) })
try {
  await page.addInitScript(() => {
    localStorage.setItem('hocuspocus-ui-language', 'es')
    localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    localStorage.setItem('hocuspocus_welcome_seen_v2', '453')
  })
  await page.goto('http://127.0.0.1:8788/')
  await page.getByRole('button', { name: 'Estudios', exact: true }).click({ timeout: 30000 })
  await page.getByRole('tab', { name: 'Vídeo 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Cerrar Pregunta al mago', exact: true }).click()
  await page.getByLabel('Abrir plano JSON', { exact: true }).setInputFiles(shotPath)
  const workspace = page.getByTestId('scene3d-workspace')
  const toggle = page.getByTestId('world3d-speech-toggle')
  await page.waitForFunction(slots => window.__world3dStage?.ready(slots), shot.slots, { timeout: 30000 })
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true')
  assert.equal(await page.getByRole('checkbox', { name: 'Activar cara animada', exact: true }).isChecked(), true)
  await toggle.click()
  assert.equal(await page.getByTestId('scene3d-speech').count(), 0)
  await toggle.click()
  assert.equal(await page.getByRole('checkbox', { name: 'Activar cara animada', exact: true }).isChecked(), true)
  await page.getByRole('button', { name: 'Reproducir', exact: true }).click()
  await page.waitForFunction(() => Number(document.querySelector('[aria-label="Posición en la escena"]')?.value) > 1)
  await page.getByRole('button', { name: 'Pausar', exact: true }).click()
  await page.getByRole('heading', { name: 'Estudio de escenas 3D', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'video3d-integrado.jpg'), type: 'jpeg', quality: 88 })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Guardar plano JSON', exact: true }).click()
  const roundtripPath = path.join(output, 'integrated-roundtrip.world3d.json')
  await (await download).saveAs(roundtripPath)
  const roundtrip = JSON.parse(await readFile(roundtripPath, 'utf8'))
  assert.deepEqual(roundtrip.slots.map(slot => slot.speech), shot.slots.map(slot => slot.speech))
  await page.getByLabel('Abrir plano JSON', { exact: true }).setInputFiles(roundtripPath)
  assert.equal(await workspace.getByTestId('scene3d-roundtrip').textContent(), 'ok')
  assert.equal(new URL(page.url()).pathname, '/')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ url: page.url(), template: roundtrip.templateId,
    nativeDocumentPreserved: true, cues: roundtrip.slots[0].speech.cues.length,
    screenshot: path.join(output, 'video3d-integrado.jpg'), errors, failedRequests }, null, 2))
} catch (error) {
  console.log((await page.locator('body').innerText()).slice(0,6000))
  console.log({ errors, failedRequests })
  await page.screenshot({ path: path.join(output, 'video3d-app-failure.jpg'), type: 'jpeg' })
  throw error
} finally { await browser.close() }
