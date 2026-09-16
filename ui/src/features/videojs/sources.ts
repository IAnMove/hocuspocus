import hostSource from './runtime/videojsHost.js?raw'
import runtimeSource from './runtime/videojsWorker.js?raw'
import type { VideoJsRenderSpec } from './sandbox.ts'

export { hostSource, runtimeSource }

let threeSource: Promise<string> | null = null

/** three.js is sent to the sandbox as text (the sandbox has no network).
 *  It is a separate lazy chunk that only loads when a 3D scene exists. */
export async function videoJsSandboxSources(document: Pick<VideoJsRenderSpec, 'scenes'>): Promise<{ runtime: string; three: string | null }> {
  if (!document.scenes.some(scene => scene.kind === '3d')) return { runtime: runtimeSource, three: null }
  threeSource ??= import('../../../node_modules/three/build/three.cjs?raw').then(module => module.default)
  try {
    return { runtime: runtimeSource, three: await threeSource }
  } catch (error) {
    threeSource = null
    throw error
  }
}
