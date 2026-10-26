import { useState } from 'react'
import { fetchCharacterKitLibrary } from '../../api/characters'
import { BASE } from '../../api/http'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'

const EYES = ['dot', 'oval', 'halflid', 'wide'] as const
const BROWS = ['thick', 'thin', 'none'] as const
const NOSES = ['none', 'dot', 'line', 'bulb'] as const
const MOUSTACHES = ['none', 'walrus', 'pencil', 'handlebar'] as const
const GLASSES = ['none', 'round', 'square'] as const
const MOUTHS = ['paper', 'ink'] as const

type Traits = {
  eyes: typeof EYES[number]
  brows: typeof BROWS[number]
  nose: typeof NOSES[number]
  moustache: typeof MOUSTACHES[number]
  glasses: typeof GLASSES[number]
  freckles: boolean
  stubble: boolean
  ink: string
  line: number
  mouth: typeof MOUTHS[number]
}

/** The same POST as `characters.face.make`: a parametric face, saved as a Character Kit. */
export function BlobFaceMaker({
  workspace, library, disabled, onLibrary, onSelect,
}: {
  workspace: string
  library: CharacterKitLibrary
  disabled?: boolean
  onLibrary?: (library: CharacterKitLibrary) => void
  onSelect: (kit: CharacterKit) => void
}) {
  const { t } = useUiTranslation('characters')
  const [traits, setTraits] = useState<Traits>({ eyes: 'oval', brows: 'thin', nose: 'dot', moustache: 'none', glasses: 'none', freckles: false, stubble: false, ink: '#221614', line: 8, mouth: 'paper' })
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function set<Key extends keyof Traits>(key: Key, value: Traits[Key]) {
    setTraits(current => ({ ...current, [key]: value }))
  }

  async function make() {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${BASE}/api/v1/character-kits/face`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace, traits, ...(name.trim() ? { name: name.trim() } : {}), baseRevision: library.revision }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        const detail = body.detail
        throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : t('library.blobFace.failed'))
      }
      const next = await fetchCharacterKitLibrary(workspace)
      onLibrary?.(next)
      const kit = next.kits[body.kit_id as string]
      if (kit) onSelect(kit)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const field = 'mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[8px]'
  return (
    <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1" data-testid="blob-face-maker">
      <summary className="cursor-pointer text-[9px] text-text-muted">{t('library.blobFace.summary')}</summary>
      <input value={name} onChange={event => setName(event.target.value)} placeholder={t('library.namePlaceholder')} className={`${field} mt-1`} />
      <div className="mt-1 grid grid-cols-2 gap-1">
        <label className="text-[8px] text-text-muted">{t('library.blobFace.eyes')}<select aria-label={t('library.blobFace.eyes')} value={traits.eyes} onChange={event => set('eyes', event.target.value as Traits['eyes'])} className={field}>{EYES.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-[8px] text-text-muted">{t('library.blobFace.brows')}<select aria-label={t('library.blobFace.brows')} value={traits.brows} onChange={event => set('brows', event.target.value as Traits['brows'])} className={field}>{BROWS.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-[8px] text-text-muted">{t('library.blobFace.nose')}<select aria-label={t('library.blobFace.nose')} value={traits.nose} onChange={event => set('nose', event.target.value as Traits['nose'])} className={field}>{NOSES.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-[8px] text-text-muted">{t('library.blobFace.moustache')}<select aria-label={t('library.blobFace.moustache')} value={traits.moustache} onChange={event => set('moustache', event.target.value as Traits['moustache'])} className={field}>{MOUSTACHES.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-[8px] text-text-muted">{t('library.blobFace.glasses')}<select aria-label={t('library.blobFace.glasses')} value={traits.glasses} onChange={event => set('glasses', event.target.value as Traits['glasses'])} className={field}>{GLASSES.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-[8px] text-text-muted">{t('library.blobFace.mouth')}<select aria-label={t('library.blobFace.mouth')} value={traits.mouth} onChange={event => set('mouth', event.target.value as Traits['mouth'])} className={field}>{MOUTHS.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
      </div>
      <label className="mt-1 block text-[8px] text-text-muted">{t('library.blobFace.ink')}
        <input aria-label={t('library.blobFace.ink')} value={traits.ink} onChange={event => set('ink', event.target.value)} className={field} />
      </label>
      <label className="mt-1 flex items-center gap-1 text-[8px] text-text-muted"><input type="checkbox" checked={traits.freckles} onChange={event => set('freckles', event.target.checked)} />{t('library.blobFace.freckles')}</label>
      <label className="mt-1 flex items-center gap-1 text-[8px] text-text-muted"><input type="checkbox" checked={traits.stubble} onChange={event => set('stubble', event.target.checked)} />{t('library.blobFace.stubble')}</label>
      <button type="button" disabled={disabled || busy} onClick={() => void make()} className="mt-1 w-full rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1 text-[9px] text-emerald-100 disabled:opacity-40">{busy ? t('library.blobFace.working') : t('library.blobFace.make')}</button>
      {error && <p className="mt-1 text-[8px] text-red-300">{error}</p>}
    </details>
  )
}
