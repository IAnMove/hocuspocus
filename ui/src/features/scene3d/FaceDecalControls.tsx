import { useState } from 'react'
import { fetchCharacterKitLibrary } from '../../api/characters'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import { artFromKit, type Scene3DFaceDecal } from './faceDecal'
import type { Scene3DSlot } from './types'

/** Kit and expression for the 2D face on the selected model. Placement stays whatever the scene already stored. */
export function FaceDecalControls({
  slot, workspace, disabled, onChange,
}: {
  slot: Scene3DSlot
  workspace: string
  disabled?: boolean
  onChange: (faceDecal: Scene3DFaceDecal) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [kits, setKits] = useState<CharacterKit[] | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const decal = slot.faceDecal
  const poses = Object.keys(decal?.art?.poses || {})

  async function load() {
    if (kits) return
    try {
      const library = await fetchCharacterKitLibrary(workspace)
      setKits(Object.values(library.kits))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    }
  }

  function choose(kitId: string, pose: string) {
    const kit = kits?.find(item => item.id === kitId)
    if (!kit) return
    const art = artFromKit(kit)
    if (!art) { setError(t('faceDecal.mouths')); return }
    const poseName = art.poses[pose] ? pose : (art.poses.neutral ? 'neutral' : Object.keys(art.poses)[0])
    onChange({
      kitId: kit.id, pose: poseName, bone: decal?.bone || 'Head',
      ...(decal?.center ? { center: decal.center } : {}),
      ...(decal?.radii ? { radii: decal.radii } : {}),
      ...(decal?.size ? { size: decal.size } : {}),
      ...(decal?.expressions ? { expressions: decal.expressions } : {}),
      art: { ...art, ...(decal?.art?.cues ? { cues: decal.art.cues } : {}), ...(decal?.art?.blinks ? { blinks: decal.art.blinks } : {}) },
    })
    setError('')
    setNote(decal?.center ? '' : t('faceDecal.place'))
  }

  return (
    <details data-testid="scene3d-face-decal" className="mt-2 rounded border border-border px-2 py-1" onToggle={event => { if ((event.currentTarget as HTMLDetailsElement).open) void load() }}>
      <summary className="cursor-pointer text-[11px] text-text-primary">{t('faceDecal.title')}</summary>
      <label className="mt-1 block text-[8px] text-text-muted">{t('faceDecal.kit')}
        <select aria-label={t('faceDecal.kit')} value={decal?.kitId || ''} disabled={disabled || !kits} onChange={event => choose(event.target.value, decal?.pose || 'neutral')} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[10px]">
          <option value="">{kits ? t('faceDecal.empty') : '…'}</option>
          {(kits || []).map(kit => <option key={kit.id} value={kit.id}>{kit.name}</option>)}
        </select>
      </label>
      <label className="mt-1 block text-[8px] text-text-muted">{t('faceDecal.expression')}
        <select aria-label={t('faceDecal.expression')} value={decal?.pose || ''} disabled={disabled || poses.length === 0} onChange={event => { if (decal?.kitId) choose(decal.kitId, event.target.value) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[10px]">
          {poses.map(pose => <option key={pose} value={pose}>{pose}</option>)}
        </select>
      </label>
      {note && <p className="mt-1 text-[8px] text-text-muted">{note}</p>}
      {error && <p className="mt-1 text-[8px] text-red-300">{error}</p>}
    </details>
  )
}
