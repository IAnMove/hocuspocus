import type { SceneLayer } from '../../types'
import type { CharacterKitRef } from '../../lib/characterVoice'
import { controlLabel } from '../../i18n/controlLabel'
import { CharacterKitLink } from './CharacterKitLink'
export function ModelCharacterLink({ layer, workspace, disabled, title, onChange }: {
  layer?: SceneLayer | null; workspace: string; disabled: boolean; title?: string; onChange: (id: string, ref?: CharacterKitRef) => void
}) {
  if (layer?.type !== 'model3d') return null
  const blocked = disabled || layer.locked
  const reason = !blocked ? undefined : disabled ? (title || controlLabel('disabled.actionInProgress')) : controlLabel('disabled.unlockLayer')
  return <CharacterKitLink workspace={workspace} requireSpeech3d value={layer.characterKitRef} disabled={blocked} title={reason}
    onChange={ref => onChange(layer.id, ref)} />
}
