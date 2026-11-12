export async function extractEditFrames(
  clipPath: string,
  state: { params: { model_type?: string }; activeWorkspace: string },
  which: 'start' | 'end' | 'recast' | 'repaint',
  tStart: number,
) {
  const res = await fetch('/api/v1/extract-frames', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_path: clipPath,
      ...(state.params.model_type === 'viggle_animate' ? { wangp_media: true, workspace: state.activeWorkspace } : {}),
      ...(which === 'end' ? { end_time: tStart } : { start_time: tStart }),
    }),
  })
  if (!res.ok) throw new Error(`extract-frames failed: ${res.status}`)
  const data = await res.json()
  return data
}
