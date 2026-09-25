import type { OutputFile, OutputMetadata } from '../../types'

export interface OutputSettingsSource { name: string; workspace: string }
interface RestoreState {
  activeWorkspace: string
  browsingUploads: boolean
  selectedOutput: number
  selectedOutputMeta: OutputMetadata | null
  filteredOutputs: () => OutputFile[]
  loadOutputMetadata: (name: string) => Promise<void>
  params?: object
  generationMode?: string
  imageStudioIntent?: string
}

let restoreEpoch = 0
const workspaceOf = (state: RestoreState) => state.browsingUploads ? '__uploads__' : state.activeWorkspace
const selectedName = (state: RestoreState) => state.filteredOutputs()[state.selectedOutput]?.name
const sameForm = (before: RestoreState, after: RestoreState) => before.params === after.params
  && before.generationMode === after.generationMode && before.imageStudioIntent === after.imageStudioIntent

/** An explicit card action owns its source; scroll selection never redirects it. */
export async function beginOutputSettingsRestore(
  get: () => RestoreState,
  fetchMetadata: (name: string, workspace: string) => Promise<OutputMetadata>,
  source?: OutputSettingsSource,
) {
  const initial = get(), workspace = workspaceOf(initial)
  if (source && source.workspace !== workspace) return null
  const epoch = ++restoreEpoch, name = source?.name ?? selectedName(initial)
  const isCurrent = () => epoch === restoreEpoch && workspaceOf(get()) === workspace
    && (source !== undefined || selectedName(get()) === name)
  let metadata = initial.selectedOutputMeta
  if (source) {
    metadata = await fetchMetadata(source.name, source.workspace)
  } else if (!metadata?.params && name) {
    await initial.loadOutputMetadata(name)
    metadata = get().selectedOutputMeta
  }
  if (!isCurrent() || !metadata?.params || !sameForm(initial, get())) return null
  return { name: name ?? '', metadata: structuredClone(metadata), isCurrent }
}
