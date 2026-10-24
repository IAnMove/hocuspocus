import { useEffect, useState } from 'react'
import { fetchCharacterKitLibrary, rigFlatCharacter, type FlatRigResult } from '../../api/characters'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import { layerFaceStyle } from '../../lib/flatRigMouth'

type Props = {
  kit: CharacterKit
  workspace: string
  disabled?: boolean
  /** Other Face Rig work is running: this button waits. */
  busy?: boolean
  onRigged?: (result: FlatRigResult) => void | Promise<void>
  onBusyChange?: (busy: boolean) => void
}

const message = (cause: unknown, fallback: string) => cause instanceof Error ? cause.message : fallback

/** Re-rig every pose with `style.faceSource: "layers"`. The server runs See-through; this only asks. */
export function SeeThroughLayersButton({ kit, workspace, disabled = false, busy = false, onRigged, onBusyChange }: Props) {
  const { t } = useUiTranslation('characters')
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const locked = disabled || busy || saving || !onRigged

  useEffect(() => { onBusyChange?.(saving) }, [saving, onBusyChange])
  useEffect(() => () => onBusyChange?.(false), [onBusyChange])

  const place = async () => {
    if (locked) return
    setSaving(true); setFailure(null); setNote(null)
    try {
      const library = await fetchCharacterKitLibrary(workspace)
      const stored = library.kits[kit.id]
      if (!stored || JSON.stringify(stored) !== JSON.stringify(kit)) throw new Error(t('faceRig.seeThrough.missing'))
      const rig = [...kit.provenance].reverse().find(entry => entry.method === 'flat-rig')
      const style = (rig?.style && typeof rig.style === 'object' ? rig.style : undefined) as Record<string, number | boolean | string> | undefined
      const result = await rigFlatCharacter({
        workspace, kitId: kit.id, baseRevision: library.revision, style: layerFaceStyle(style),
      })
      setNote(t('faceRig.seeThrough.done'))
      await onRigged?.(result)
    } catch (cause) {
      setFailure(message(cause, t('faceRig.seeThrough.failed')))
    } finally { setSaving(false) }
  }

  return <div className="space-y-1 rounded border border-cyan-300/30 bg-black/15 p-2">
    <p className="text-xs leading-relaxed text-text-secondary">{t('faceRig.seeThrough.hint')}</p>
    <button type="button" disabled={locked} onClick={() => void place()}
      className="min-h-9 w-full rounded border border-cyan-300/50 bg-cyan-400/10 px-2 py-1 text-xs text-cyan-100 disabled:opacity-40">
      {t(saving ? 'faceRig.seeThrough.busy' : 'faceRig.seeThrough.button')}</button>
    {note && <p className="text-xs text-emerald-100">{note}</p>}
    {failure && <p className="text-xs text-red-200">{failure}</p>}
  </div>
}
