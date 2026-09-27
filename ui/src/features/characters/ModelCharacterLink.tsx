import type { SceneLayer } from '../../types'
import type { CharacterKitRef } from '../../lib/characterVoice'
import { CharacterKitLink } from './CharacterKitLink'
export function ModelCharacterLink({ layer, workspace, disabled, onChange }: {
  layer?: SceneLayer | null; workspace: string; disabled: boolean; onChange: (id: string, ref?: CharacterKitRef) => void
}) {
  if (layer?.type !== 'model3d') return null
  return <CharacterKitLink workspace={workspace} requireSpeech3d value={layer.characterKitRef} disabled={disabled || layer.locked}
    onChange={ref => onChange(layer.id, ref)} />
}
