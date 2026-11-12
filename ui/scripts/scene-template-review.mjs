import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs/promises'
import { startReviewServer } from './sceneTemplateReview/server.mjs'
import { parseArgs, usage } from './sceneTemplateReview/args.mjs'
import { buildReviewUi } from './sceneTemplateReview/build.mjs'
import { prepareShowcase, registerShowcaseInputs } from './sceneTemplateReview/showcase.mjs'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const uiRoot = path.resolve(scriptDir, '..')
const repoRoot = path.resolve(uiRoot, '..')

async function holdServer(server) {
  let stopped = false
  let resolveStop
  const stoppedPromise = new Promise(resolve => { resolveStop = resolve })
  const shutdown = async signal => {
    if (stopped) return
    stopped = true
    console.log(`Stopping review sandbox (${signal}).`)
    await server.close()
    resolveStop()
  }
  const onInterrupt = () => { void shutdown('interrupt') }
  const onTerminate = () => { void shutdown('terminate') }
  process.once('SIGINT', onInterrupt)
  process.once('SIGTERM', onTerminate)
  await stoppedPromise
  process.off('SIGINT', onInterrupt)
  process.off('SIGTERM', onTerminate)
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help) { console.log(usage()); return }
  const outputDir = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-scene-template-review-'))
  let server = null
  try {
    const uiDist = await buildReviewUi({ uiRoot, outputDir })
    // This must complete before startReviewServer indexes static files. A
    // malformed or tampered package therefore cannot leave a half-published
    // showcase reachable from the sandbox.
    const showcase = options.showcaseDir
      ? await prepareShowcase({ showcaseDir: options.showcaseDir, uiDist, outputDir })
      : null
    server = await startReviewServer({ uiDist, outputDir, host: options.host, port: options.port })
    if (showcase) await registerShowcaseInputs(server, showcase)

    console.log(`REVIEW_OUTPUT_DIR=${outputDir}`)
    if (showcase) {
      console.log(`REVIEW_SHOWCASE_DIR=${showcase.showcaseDir}`)
      console.log(`REVIEW_SHOWCASE_REFERENCES=${showcase.referenceCount}; bytes=${showcase.bytes}; hashes=verified-at-startup`)
      console.log(`REVIEW_SHOWCASE_INPUTS=${showcase.inputNames.length}; input-bytes=${showcase.inputs.reduce((total, input) => total + input.size, 0)}`)
      console.log('REVIEW_SHOWCASE_VIDEO=local compositor only; no AI video generation')
    }
    // Keep all URL output after input registration. The editor must never be
    // advertised before its canonical sources are indexed.
    console.log(`REVIEW_URL_LOCAL=${server.localOrigin}/scene-template-review`)
    if (server.lanOrigin) console.log(`REVIEW_URL_LAN=${server.lanOrigin}/scene-template-review`)
    console.log('REVIEW_PROVIDERS=blocked')
    console.log('REVIEW_PERSISTENCE=in-memory index; fresh temporary directory; no restart recovery')
    console.log('REVIEW_LIMITS=128 outputs / 256 MiB write budget / one concurrent write; LAN is read-only, unauthenticated and for trusted networks only')

    if (options.render) {
      try {
        const { renderTemplates } = await import('./sceneTemplateReview/render.mjs')
        const result = await renderTemplates({ server, repoRoot, templateIds: options.templateIds, assetsFile: options.assetsFile })
        console.log(`REVIEW_RENDERED=${result.results.length}`)
        console.log(`REVIEW_INDEX=${result.index}`)
        if (result.failures.length) {
          process.exitCode = 1
          console.error(`REVIEW_RENDER_FAILED=${result.failures.length}; no placeholder previews were created.`)
        } else {
          console.log('REVIEW_RENDER_STATUS=rendered-not-approved')
        }
      } catch (error) {
        process.exitCode = 1
        console.error(`REVIEW_RENDER_ERROR=${error instanceof Error ? error.message : String(error)}`)
        throw error
      }
    }
    console.log('REVIEW_SERVER=running; press Ctrl-C to stop.')
    await holdServer(server)
  } catch (error) {
    if (server) await server.close().catch(() => undefined)
    throw error
  }
}

try {
  await main()
} catch (error) {
  process.exitCode = 1
  console.error(`SCENE_TEMPLATE_REVIEW_ERROR=${error instanceof Error ? error.message : String(error)}`)
  console.error(usage())
}
