import { deleteOutput, moveOutput, toggleFavorite } from '../../api/outputs'
import { galleryWorkspaceName } from '../../stores/gallerySlice'
import { useStore } from '../../stores/useStore'
import type { OutputFile } from '../../types'

export type GalleryBatchAction =
  | { kind: 'favorite'; favorite: boolean }
  | { kind: 'delete' }
  | { kind: 'move'; workspace: string }

const CONCURRENCY = 4

async function eachLimited(names: string[], task: (name: string) => Promise<void>): Promise<string[]> {
  const failed: string[] = []
  let next = 0
  const worker = async () => {
    while (next < names.length) {
      const name = names[next++]
      try {
        await task(name)
      } catch {
        failed.push(name)
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, names.length) }, worker))
  return failed
}

/** Apply one action to several outputs and reflect the result in the store.
 *  Items that fail stay as they were and are reported back by name. */
export async function runGalleryBatch(action: GalleryBatchAction, files: OutputFile[]): Promise<{ failed: string[] }> {
  if (action.kind === 'favorite') {
    // The API toggles, so only touch the items not already in the wanted state.
    const targets = files.filter(file => file.favorite !== action.favorite).map(file => file.name)
    const done = new Set<string>()
    const failed = await eachLimited(targets, async name => {
      const result = await toggleFavorite(name)
      if (result.favorite !== action.favorite) throw new Error('favorite did not change')
      done.add(name)
    })
    useStore.setState(state => ({
      outputs: state.outputs.map(file => (done.has(file.name) ? { ...file, favorite: action.favorite } : file)),
    }))
    return { failed }
  }

  const sourceWorkspace = galleryWorkspaceName(useStore.getState())
  const names = files.map(file => file.name)
  const failed = await eachLimited(names, name => (
    action.kind === 'delete'
      ? deleteOutput(name, sourceWorkspace)
      : moveOutput(name, action.workspace, sourceWorkspace)
  ))
  const removed = new Set(names.filter(name => !failed.includes(name)))
  // A workspace switch (this tab or another) replaced the list. The files
  // were still removed from the folder we listed; do not rewrite the new list.
  if (galleryWorkspaceName(useStore.getState()) !== sourceWorkspace) {
    return { failed }
  }
  useStore.setState(state => {
    if (galleryWorkspaceName(state) !== sourceWorkspace) return state
    const outputs = state.outputs.filter(file => !removed.has(file.name))
    return {
      outputs,
      outputsTotal: Math.max(outputs.length, state.outputsTotal - removed.size),
      selectedOutput: Math.min(state.selectedOutput, Math.max(0, outputs.length - 1)),
    }
  })
  return { failed }
}
