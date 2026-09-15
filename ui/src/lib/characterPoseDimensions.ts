import type { CharacterKit } from './characterKit'

const sizes = new Map<string, Promise<{ width: number; height: number }>>()

/** Resolve only the pose being mounted; old saved kits need no manual migration. */
export async function withCharacterPoseDimensions(kit: CharacterKit, workspace: string, poseId = 'base'): Promise<CharacterKit> {
  const pose = poseId === 'base' ? kit.base : kit.poses[poseId]
  if (!pose) return kit
  const sourceWorkspace = pose.workspace || workspace
  let url = /^(https?:|\/)/.test(pose.source) ? pose.source
    : `/api/v1/file/${encodeURIComponent(pose.source)}?workspace=${encodeURIComponent(sourceWorkspace)}`
  if (url.startsWith('/api/v1/file/')) {
    const [path, query] = url.split('?'), params = new URLSearchParams(query)
    if (!params.has('workspace')) params.set('workspace', sourceWorkspace)
    url = `${path}?${params}`
  }
  let pending = sizes.get(url)
  if (!pending) {
    pending = (async () => {
      const response = await fetch(url)
      if (!response.ok) throw new Error(`Could not load the character pose: ${pose.name}`)
      const bitmap = await createImageBitmap(await response.blob())
      try { return { width: bitmap.width, height: bitmap.height } } finally { bitmap.close() }
    })()
    if (sizes.size >= 64) sizes.delete(sizes.keys().next().value!)
    sizes.set(url, pending)
    void pending.catch(() => { if (sizes.get(url) === pending) sizes.delete(url) })
  }
  const asset = { ...pose, ...await pending }
  return poseId === 'base' ? { ...kit, base: asset } : { ...kit, poses: { ...kit.poses, [poseId]: asset } }
}
