export type MicrophoneCallbacks = {
  onRecording: () => void
  onComplete: (audio: Blob) => void
  onError: (error: unknown) => void
}
/** Owns only this recording's stream. Aborting also handles late permission grants. */
export async function recordMicrophone(signal: AbortSignal, callbacks: MicrophoneCallbacks, maxSeconds = 90): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
  const stopTracks = () => stream.getTracks().forEach(track => track.stop())
  if (signal.aborted) { stopTracks(); return () => {} }
  let recorder: MediaRecorder
  try { recorder = new MediaRecorder(stream) } catch (error) { stopTracks(); throw error }
  let bytes = 0, failed = false, cleaned = false, timer: ReturnType<typeof setTimeout> | undefined
  const chunks: Blob[] = []
  const cleanup = () => { if (cleaned) return; cleaned = true; clearTimeout(timer); signal.removeEventListener('abort', cancel); stopTracks() }
  const stop = () => { if (recorder.state !== 'inactive') recorder.stop() }
  const cancel = () => { failed = true; stop(); cleanup() }
  const fail = (error: unknown) => { failed = true; stop(); cleanup(); if (!signal.aborted) callbacks.onError(error) }
  signal.addEventListener('abort', cancel, { once: true })
  recorder.ondataavailable = event => {
    if (failed || signal.aborted) return
    bytes += event.data.size
    if (bytes > 8 * 1024 * 1024) { fail(new Error('recordingTooLarge')); return }
    if (!failed && !signal.aborted && event.data.size) chunks.push(event.data)
  }
  recorder.onerror = () => fail(new Error('recordingFailed'))
  recorder.onstop = () => {
    cleanup()
    if (!signal.aborted && !failed) callbacks.onComplete(new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || 'audio/webm' }))
  }
  try {
    recorder.start(250)
    timer = setTimeout(stop, Math.min(90, Math.max(1, maxSeconds)) * 1000)
    callbacks.onRecording()
  } catch (error) { cleanup(); throw error }
  return stop
}
