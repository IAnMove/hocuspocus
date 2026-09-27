// Paint Video 2D fixtures through scene2d-render.html and hash each frame.
// Same painter as the editor and the headless export (__scene2dExport).
//
//   node scripts/scene2d-frame-hash.mjs --update
//   node scripts/scene2d-frame-hash.mjs --check
//   node scripts/scene2d-frame-hash.mjs --scene tests/fixtures/scene2d/texts-v1/scene.json --seconds 0.2,1.2 --width 1920 --height 1080
//
// Exact SHA-256 of the PNG bytes is the default. Pass --repeat 2 to paint each
// second twice. If those paints differ, a sample counts as changed when any
// channel differs by more than the manifest channelEpsilon (default 2). The run
// still passes when the fraction of RGBA samples stays within maxChangedRatio.
// A ratio of 0 requires the two paints to be identical.
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fixtureRoot = path.join(uiRoot, 'tests', 'fixtures', 'scene2d')

function readArgs(argv) {
  const args = { update: false, check: false, measure: false, repeat: 1, seconds: [], width: 0, height: 0, fps: 0 }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const next = argv[i + 1]
    if (flag === '--update') args.update = true
    else if (flag === '--check') args.check = true
    else if (flag === '--measure') args.measure = true
    else if (flag === '--scene') { args.scene = next; i += 1 }
    else if (flag === '--seconds') { args.seconds = next.split(',').map(item => item.trim()).filter(Boolean); i += 1 }
    else if (flag === '--width') { args.width = Number(next); i += 1 }
    else if (flag === '--height') { args.height = Number(next); i += 1 }
    else if (flag === '--fps') { args.fps = Number(next); i += 1 }
    else if (flag === '--repeat') { args.repeat = Math.max(1, Number(next) || 1); i += 1 }
    else if (flag === '--base') { args.base = next; i += 1 }
    else throw new Error(`Unknown argument ${flag}`)
  }
  if (!args.update && !args.check && !args.measure && !args.scene) args.check = true
  return args
}

function pngHash(dataUrl) {
  const body = dataUrl.slice(dataUrl.indexOf(',') + 1)
  return createHash('sha256').update(Buffer.from(body, 'base64')).digest('hex')
}

function listFixtures() {
  return fs.readdirSync(fixtureRoot)
    .map(name => path.join(fixtureRoot, name))
    .filter(dir => fs.existsSync(path.join(dir, 'scene.json')) && fs.existsSync(path.join(dir, 'manifest.json')))
    .sort()
}

async function serve(base) {
  if (base) return { base, stop() {} }
  const port = 41973
  const child = spawn('npx', ['vite', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: uiRoot, stdio: ['ignore', 'pipe', 'pipe'],
  })
  const url = `http://127.0.0.1:${port}`
  let log = ''
  child.stdout.on('data', chunk => { log += chunk })
  child.stderr.on('data', chunk => { log += chunk })
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    if (child.exitCode != null) throw new Error(`Vite exited before it was ready\n${log.slice(-800)}`)
    try {
      const response = await fetch(`${url}/scene2d-render.html`)
      if (response.ok) {
        return {
          base: url,
          stop() {
            child.kill('SIGTERM')
            child.stdout.destroy()
            child.stderr.destroy()
            child.unref()
            setTimeout(() => { if (child.exitCode == null) child.kill('SIGKILL') }, 1000).unref()
          },
        }
      }
    } catch { /* still booting */ }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  child.kill('SIGKILL')
  throw new Error(`Vite did not serve scene2d-render.html\n${log.slice(-800)}`)
}

async function openRenderer(base) {
  const browser = await chromium.launch({
    headless: true,
    args: [
      '--disable-gpu',
      '--font-render-hinting=none',
      '--disable-lcd-text',
      '--disable-font-subpixel-positioning',
      '--force-device-scale-factor=1',
    ],
  })
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 })
  await page.goto(`${base}/scene2d-render.html`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => window.__scene2dExport, null, { timeout: 60_000 })
  return {
    browser,
    async paint(scene, size, seconds) {
      await page.evaluate(async ({ scene: next, size: frame }) => {
        await window.__scene2dExport.load(next, frame)
      }, { scene, size })
      const paints = []
      for (const second of seconds) {
        const started = Date.now()
        try {
          const dataUrl = await page.evaluate(async second => window.__scene2dExport.frame(Number(second)), second)
          paints.push({ second, hash: pngHash(dataUrl), ms: Date.now() - started, dataUrl })
        } catch (error) {
          paints.push({ second, hash: '', ms: Date.now() - started, dataUrl: '', error: String(error?.message || error).slice(0, 400) })
        }
      }
      return paints
    },
    async changedRatio(first, second, epsilon) {
      return page.evaluate(async ({ first: a, second: b, epsilon: limit }) => {
        const load = url => new Promise((resolve, reject) => {
          const image = new Image()
          image.onload = () => resolve(image)
          image.onerror = () => reject(new Error('frame decode failed'))
          image.src = url
        })
        const [left, right] = await Promise.all([load(a), load(b)])
        const canvas = document.createElement('canvas')
        canvas.width = left.naturalWidth
        canvas.height = left.naturalHeight
        const context = canvas.getContext('2d')
        context.drawImage(left, 0, 0)
        const leftData = context.getImageData(0, 0, canvas.width, canvas.height).data
        context.drawImage(right, 0, 0)
        const rightData = context.getImageData(0, 0, canvas.width, canvas.height).data
        let changed = 0
        for (let i = 0; i < leftData.length; i += 1) if (Math.abs(leftData[i] - rightData[i]) > limit) changed += 1
        return changed / leftData.length
      }, { first, second, epsilon })
    },
  }
}

function jobsFromArgs(args) {
  if (args.scene) {
    const scene = JSON.parse(fs.readFileSync(path.resolve(uiRoot, args.scene), 'utf8'))
    return [{
      name: path.basename(path.dirname(args.scene)),
      scene,
      manifestPath: '',
      width: args.width || scene.width || 640,
      height: args.height || scene.height || 360,
      fps: args.fps || scene.fps || 30,
      seconds: args.seconds.length ? args.seconds : ['0.5'],
      tolerance: { maxChangedRatio: 0, channelEpsilon: 2 },
      hashes: {},
    }]
  }
  return listFixtures().map(dir => {
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'))
    return {
      name: path.basename(dir),
      dir,
      scene: JSON.parse(fs.readFileSync(path.join(dir, 'scene.json'), 'utf8')),
      manifest,
      manifestPath: path.join(dir, 'manifest.json'),
      width: manifest.width,
      height: manifest.height,
      fps: manifest.fps,
      seconds: manifest.seconds,
      tolerance: manifest.tolerance ?? { maxChangedRatio: 0, channelEpsilon: 2 },
      hashes: manifest.hashes ?? {},
    }
  })
}

async function main() {
  const args = readArgs(process.argv.slice(2))
  const jobs = jobsFromArgs(args)
  const server = await serve(args.base || process.env.HOCUS_SCENE2D_URL)
  const renderer = await openRenderer(server.base)
  const report = []
  let failed = false
  try {
    for (const job of jobs) {
      const size = { width: job.width, height: job.height, fps: job.fps }
      const first = await renderer.paint(job.scene, size, job.seconds)
      let second = first
      if (args.repeat > 1) second = await renderer.paint(job.scene, size, job.seconds)
      const frames = []
      for (let index = 0; index < first.length; index += 1) {
        const painted = first[index]
        const again = second[index]
        let changedRatio = 0
        if (painted.error || again.error) {
          if (args.check || args.update) failed = true
        } else if (painted.hash !== again.hash && painted.dataUrl && again.dataUrl) {
          changedRatio = await renderer.changedRatio(painted.dataUrl, again.dataUrl, job.tolerance.channelEpsilon ?? 2)
          if (changedRatio > (job.tolerance.maxChangedRatio ?? 0)) failed = true
        }
        const expected = job.hashes[painted.second]
        const hashMatch = !painted.error && (!args.check || !expected || expected === painted.hash)
        if (args.check && (painted.error || (expected && expected !== painted.hash) || (!expected && !args.update))) failed = true
        frames.push({
          second: painted.second, hash: painted.hash, ms: painted.ms, changedRatio,
          expected: expected || null, hashMatch, ...(painted.error ? { error: painted.error } : {}),
        })
      }
      if (args.update && job.manifestPath && frames.every(frame => frame.hash && !frame.error)) {
        const next = { ...job.manifest, hashes: Object.fromEntries(frames.map(frame => [frame.second, frame.hash])) }
        fs.writeFileSync(job.manifestPath, `${JSON.stringify(next, null, 2)}\n`)
      }
      report.push({
        name: job.name, width: job.width, height: job.height,
        frames: frames.map(({ dataUrl, ...frame }) => frame),
      })
    }
  } finally {
    await renderer.browser.close()
    server.stop()
  }
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
  if (failed) process.exit(1)
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
