// Paint a Video 2D contact sheet with the export bridge (window.__scene2dExport).
// Same page and CPU Chromium flags as ui/scripts/scene2d-frame-hash.mjs.
// Stdin is JSON {base, document, times, width, height, fps, columns}. Stdout is one PNG.
import { chromium } from 'playwright'
import fs from 'node:fs'

const LAUNCH_ARGS = [
  '--disable-gpu',
  '--font-render-hinting=none',
  '--disable-lcd-text',
  '--disable-font-subpixel-positioning',
  '--force-device-scale-factor=1',
]

function readPayload() {
  const payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  if (!payload || typeof payload.base !== 'string' || !Array.isArray(payload.times) || payload.times.length < 1) {
    throw new Error('preview payload is incomplete')
  }
  return payload
}

function pngFromDataUrl(dataUrl) {
  const marker = 'base64,'
  const index = String(dataUrl).indexOf(marker)
  if (!String(dataUrl).startsWith('data:image/png') || index < 0) throw new Error('painter did not return a PNG')
  return Buffer.from(String(dataUrl).slice(index + marker.length), 'base64')
}

async function loadFrames(page, payload) {
  const size = { width: payload.width, height: payload.height, fps: payload.fps }
  await page.evaluate(async ({ document, size: frame }) => {
    await window.__scene2dExport.load(document, frame)
  }, { document: payload.document, size })
  const frames = []
  for (const second of payload.times) {
    frames.push(await page.evaluate(async (value) => window.__scene2dExport.frame(Number(value)), second))
  }
  return frames
}

async function composite(page, frames, columns) {
  return page.evaluate(async ({ frames: urls, columns: across }) => {
    const load = (url) => new Promise((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve(image)
      image.onerror = () => reject(new Error('frame decode failed'))
      image.src = url
    })
    const images = []
    for (const url of urls) images.push(await load(url))
    const cellWidth = images[0].naturalWidth
    const cellHeight = images[0].naturalHeight
    const rows = Math.ceil(images.length / across)
    const canvas = document.createElement('canvas')
    canvas.width = across * cellWidth
    canvas.height = rows * cellHeight
    const context = canvas.getContext('2d')
    context.imageSmoothingEnabled = false
    images.forEach((image, index) => {
      context.drawImage(image, (index % across) * cellWidth, Math.floor(index / across) * cellHeight)
    })
    return canvas.toDataURL('image/png')
  }, { frames, columns })
}

async function main() {
  const payload = readPayload()
  const browser = await chromium.launch({ headless: true, args: LAUNCH_ARGS })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 })
    page.setDefaultTimeout(60_000)
    await page.goto(new URL('/scene2d-render.html', payload.base).href, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => window.__scene2dExport)
    const frames = await loadFrames(page, payload)
    const dataUrl = await composite(page, frames, Number(payload.columns) || frames.length)
    await page.evaluate(() => { window.__scene2dExport.dispose() }).catch(() => {})
    process.stdout.write(pngFromDataUrl(dataUrl))
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  process.stderr.write(`${String(error?.message || error).slice(0, 400)}\n`)
  process.exit(1)
})
