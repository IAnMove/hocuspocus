import type { Hunyuan3DModel } from '../api/model3d'

type Inputs = {
  model?: Hunyuan3DModel
  provider: string
  operation: 'generate' | 'retexture'
  runtimeInstalled?: boolean
  hasSource: boolean
  hasFront: boolean
  hasPrompt: boolean
  textureMode: string
}

function hasRequiredInput(input: Inputs, external: boolean, multiview: boolean) {
  if (external || multiview) return input.hasFront
  const reference = input.hasFront || input.hasPrompt
  if (input.operation === 'retexture') return input.hasSource && reference && input.textureMode !== 'none'
  return reference
}

/** UI availability mirrors the server contract; never infer support from a label. */
export function model3dInputState(input: Inputs) {
  const external3d = input.provider === 'local' && (input.model?.engine === 'trellis2' || input.model?.engine === 'pixal3d')
  const remote3d = input.provider === 'meshy' || input.provider === 'hi3d'
  const isMultiview = input.operation === 'generate' && !!input.model?.multiview
  const installed = remote3d || (external3d
    ? !!input.model?.runtime?.installed && input.model.runtime.compatible !== false && input.model.runtime.weights_downloaded !== false
    : !!input.runtimeInstalled)
  const hasInput = hasRequiredInput(input, external3d, isMultiview)
  return { external3d, remote3d, isMultiview, installed, hasInput, canRun: hasInput && installed }
}
