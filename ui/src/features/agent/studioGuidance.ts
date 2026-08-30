import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import type { AgentAttachStudioReferencesAction } from './agentActions'

const normalized = (value: string): string => value.trim().toLocaleLowerCase()

async function imageOutputFiles(names: string[]): Promise<File[]> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const { outputs } = await api.fetchOutputs(0, 0, { workspace, mediaType: 'image' })
  const byName = new Map(outputs.map(output => [normalized(output.name), output]))
  const files: File[] = []
  for (const requestedName of names) {
    const output = byName.get(normalized(requestedName))
    if (!output) {
      throw new Error(`No existe la imagen “${requestedName}” en el workspace activo; no he inventado ni sustituido la referencia.`)
    }
    const response = await fetch(api.getFileUrl(output.name, workspace))
    if (!response.ok) throw new Error(`No pude leer la imagen “${output.name}” para usarla como referencia.`)
    const blob = await response.blob()
    files.push(new File([blob], output.name, { type: blob.type || 'image/png' }))
  }
  return files
}

function clearImageReferences(): void {
  const state = useStore.getState()
  for (let index = state.imageRefs.length - 1; index >= 0; index -= 1) {
    useStore.getState().removeImageRef(index)
  }
}

export async function attachStudioReferences(
  action: AgentAttachStudioReferencesAction,
): Promise<string> {
  let state = useStore.getState()
  if (state.generationMode !== 'image' && state.generationMode !== 'video') {
    throw new Error('Las referencias visuales sólo pueden adjuntarse a Studio → Image o Studio → Video.')
  }
  const selectedModel = state.models.find(model => model.model_type === state.params.model_type)
  if (!selectedModel) throw new Error('Studio no tiene un modelo de imagen/vídeo válido seleccionado.')
  const files = await imageOutputFiles(action.outputNames)

  if (action.role === 'start_frame') {
    if (state.generationMode !== 'video' || !selectedModel.is_i2v) {
      throw new Error(`${selectedModel.name} no admite una imagen inicial en el modo actual.`)
    }
    if (action.replaceExisting) state.setStartImage(null)
    state.setStartImage(files[0])
    return `He adjuntado “${files[0].name}” como start frame de Studio → Video.`
  }

  const config = state.modelOptions?.image_ref_choices
  const choices = config?.choices?.map(([, value]) => value) || []
  const desiredType = action.role === 'style' ? 'KI' : 'I'
  const supportsDesiredType = desiredType === 'KI'
    ? choices.some(value => value.includes('K'))
    : choices.some(value => value === 'I')
  if (!config || !supportsDesiredType) {
    throw new Error(`${selectedModel.name} no admite referencias de ${action.role === 'style' ? 'estilo/escenario' : 'sujeto'} en este formulario.`)
  }
  const configuredLimit = state.modelOptions?.max_image_refs
  const existingCount = action.replaceExisting ? 0 : state.imageRefs.length
  if (configuredLimit != null && existingCount + files.length > configuredLimit) {
    throw new Error(`${selectedModel.name} admite como máximo ${configuredLimit} referencias; se solicitaron ${existingCount + files.length}.`)
  }
  if (action.replaceExisting) clearImageReferences()
  files.forEach(file => useStore.getState().addImageRef(file))
  state = useStore.getState()
  state.setImageRefType(desiredType)
  state.setRemoveBackgroundRefs(action.removeBackground)
  if (state.modelOptions?.architecture === 'minimax_h3') {
    state.setParam('h3_reference_mode', 'references')
  }
  return `He adjuntado ${files.length} referencia${files.length === 1 ? '' : 's'} de ${action.role === 'style' ? 'estilo/escenario' : 'sujeto'} a Studio usando nombres reales del workspace.`
}
