import { paintSceneFx } from '../sceneFx/paint'
import { sceneAudioWav, supportsSceneAac } from '../sceneFx/audioExport'
import { ensureTextFonts, paintKineticTexts, paintSceneLyrics } from '../../lib/kineticText.ts'
import { mixSceneSpeech } from './speech/audio'
import { scene3dOutputDuration, scene3dPlaybackSpeed } from './clock.ts'
import { heldFrameTime, holdBlock, motionStepOf, shiftHeldFrame, stopMotionJitterOf, stopMotionOffset } from '../stopMotion.ts'
import { scene3dCopy } from './copy.ts'
import { paintClipNumber } from './performance.ts'
import { finishWorld3DExport, paintWorld3DExportFrame, startWorld3DExport } from './exportLock.ts'
import { encodeWorld3DFrames, throwIfAborted, world3dExportSize } from './exportMp4.ts'
import { publishWorld3DRecording } from './publish.ts'
import type { Scene3DStageHandle } from './Scene3DStage.tsx'
import type { Scene3DDocument } from './types.ts'

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export async function waitForWorld3DAssets(
  handle: Scene3DStageHandle,
  document: Scene3DDocument,
  timeoutMs = 25000,
  signal?: AbortSignal,
) {
  const deadline = Date.now() + timeoutMs
  while (!handle.ready(document.slots)) {
    throwIfAborted(signal)
    if (Date.now() > deadline) throw new Error(scene3dCopy('stage.assetsNotReady'))
    await sleep(200)
  }
}

export async function exportWorld3DDocument(
  handle: Scene3DStageHandle,
  document: Scene3DDocument,
  workspace?: string,
  onProgress?: (index: number, count: number) => void,
  signal?: AbortSignal,
) {
  const size = world3dExportSize(document.width, document.height)
  const snapshot = startWorld3DExport(handle, document, size)
  try {
    throwIfAborted(signal)
    await waitForWorld3DAssets(handle, snapshot, 25000, signal)
    throwIfAborted(signal)
    await ensureTextFonts(snapshot.texts)
    const audio = await mixSceneSpeech(snapshot)
    throwIfAborted(signal)
    const serverAudio = audio && !(await supportsSceneAac(audio.numberOfChannels >= 2 ? 2 : 1)) ? sceneAudioWav(audio) : undefined
    const speed = scene3dPlaybackSpeed(snapshot.playbackSpeed)
    const step = motionStepOf(snapshot.motionStep)
    const picture = (seconds: number) => {
      const played = seconds * speed
      return step ? heldFrameTime(played, snapshot.fps, step) : played
    }
    const jitter = stopMotionJitterOf(snapshot.stopMotionJitter)
    const blob = await encodeWorld3DFrames({
      audio: serverAudio ? undefined : audio,
      width: size.width,
      height: size.height,
      fps: snapshot.fps,
      duration: scene3dOutputDuration(snapshot),
      paint: async seconds => {
        throwIfAborted(signal)
        const time = picture(seconds)
        await handle.prepareFrame?.(time, snapshot)
        return paintWorld3DExportFrame(handle, snapshot, time)
      },
      overlay: (context, width, height, seconds) => {
        const time = picture(seconds)
        paintSceneFx(context, width, height, time, snapshot.sfx)
        paintKineticTexts(context, width, height, time, snapshot.texts)
        paintSceneLyrics(context, width, height, time, snapshot.lyrics)
        paintClipNumber(context, width, height, snapshot.clipNumber)
      },
      ...(step && jitter > 0 ? {
        decorate: (context: CanvasRenderingContext2D, width: number, height: number, seconds: number) => {
          shiftHeldFrame(context, width, height, stopMotionOffset(holdBlock(picture(seconds), snapshot.fps, step), jitter))
        },
      } : {}),
      onProgress,
      signal,
    })
    try {
      const saved = await publishWorld3DRecording(blob, snapshot, workspace, serverAudio)
      if (serverAudio) {
        const url = new URL(saved.url, window.location.origin)
        if (workspace) url.searchParams.set('workspace', workspace)
        const response = await fetch(url)
        if (!response.ok) throw new Error('The voiced MP4 was saved but could not be downloaded. Open it from Videos.')
        return { blob: await response.blob(), saved }
      }
      return { blob, saved }
    } catch (error) {
      if (serverAudio) throw error // Never offer the intermediate silent frames as a finished voiced MP4.
      return { blob, saved: null, error: error instanceof Error ? error : new Error(String(error)) }
    }
  } finally {
    finishWorld3DExport(handle)
  }
}
