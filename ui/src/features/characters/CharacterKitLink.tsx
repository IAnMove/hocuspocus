import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { listCharacterKitsFrom, type CharacterKit } from '../../lib/characterKit'
import type { CharacterKitRef } from '../../lib/characterVoice'
import { useCharacterKitLibrary } from './useCharacterKitLibrary'

/** Stores an id, not a display-name match or a duplicate character definition. */
export function CharacterKitLink({
  value, onChange, workspace: scope, disabled, requireSpeech3d = false, kits: kitsOverride, error: errorOverride,
}: {
  value?: CharacterKitRef
  onChange: (ref: CharacterKitRef | undefined) => void
  workspace?: string
  disabled?: boolean
  /** Video 3D talkers need a GLB. Story/Series cast lists 2D cutouts too. */
  requireSpeech3d?: boolean
  kits?: CharacterKit[]
  error?: string
}) {
  const active = useStore(s => s.activeWorkspace)
  const workspace = scope ?? active
  const { t } = useUiTranslation('scene3dEditor')
  const fetched = useCharacterKitLibrary(workspace, requireSpeech3d, !kitsOverride)
  const kits = kitsOverride ? listCharacterKitsFrom(kitsOverride, { requireSpeech3d }) : fetched.kits
  const error = kitsOverride ? errorOverride : fetched.error
  const selected = value?.workspace === workspace ? value.id : ''
  return (
    <label className="block space-y-1 text-xs">
      {t('speech.savedCharacter')}
      <select
        data-testid="character-kit-link"
        disabled={disabled}
        className="min-h-10 w-full rounded border border-border bg-bg-primary px-2"
        value={selected}
        onChange={event => onChange(event.target.value ? { id: event.target.value, workspace } : undefined)}
      >
        <option value="">{t('speech.noLinkedCharacter')}</option>
        {selected && !kits.some(kit => kit.id === selected) && (
          <option value={selected}>{selected} · {t('speech.missingCharacter')}</option>
        )}
        {kits.map(kit => (
          <option key={kit.id} value={kit.id}>
            {kit.name} · {kit.speech3d ? t('speech.kitKind3d') : t('speech.kitKind2d')}
          </option>
        ))}
      </select>
      {value && value.workspace !== workspace && <span>{t('speech.otherWorkspace', { workspace: value.workspace })}</span>}
      {error && <span role="status">{error}</span>}
    </label>
  )
}
