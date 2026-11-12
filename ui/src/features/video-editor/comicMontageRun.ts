import { comicMontageBody, type ComicMontageMode } from '../scene3d/comicTransition'
import { loadMontageIntoEditor } from './montageLoader'

type LoadedMontage = Awaited<ReturnType<typeof loadMontageIntoEditor>>

/** Persist the editor first so `between` and the reload land on the same clips the user sees. */
export async function applyComicMontageTransition(input: {
  workspace: string
  file: string
  between: number
  mode: ComicMontageMode
  intentId: string
  prepare?: () => Promise<string>
  run: (body: ReturnType<typeof comicMontageBody>) => Promise<{ montage?: { file?: string } }>
  load: typeof loadMontageIntoEditor
}): Promise<LoadedMontage> {
  const file = input.prepare ? await input.prepare() : input.file
  const result = await input.run(comicMontageBody({
    workspace: input.workspace,
    file,
    between: input.between,
    mode: input.mode,
    intentId: input.intentId,
  }))
  return input.load(input.workspace, result.montage?.file || file)
}
