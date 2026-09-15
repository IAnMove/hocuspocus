import { useRef, useState } from 'react'
import type { ApiOutput } from '../../api/outputs'
import { useUiTranslation } from '../../i18n'
import { parseScene3DDocument } from './document.ts'
import type { Scene3DDocumentRef } from './documentHistory.ts'
import { applyFrameFormat, scene3dFrameFormat, type Scene3DFrameFormat } from './frameFormat.ts'
import { reviewClipNumber } from './performance.ts'
import { Scene3DLibraryControls } from './Scene3DLibraryControls'
import type { Scene3DDocument } from './types.ts'
import { isWorld3DTemplateRaw } from './userTemplates.ts'

export function Scene3DDocumentControls({ document, disabled, workspace, preview, identity, onChange, onLoad, onSaved }: {
  document: Scene3DDocument
  disabled: boolean
  workspace: string
  preview: () => string | undefined
  identity?: Scene3DDocumentRef
  onChange: (document: Scene3DDocument) => void
  onLoad: (document: Scene3DDocument, source?: Scene3DDocumentRef) => void
  onSaved?: (output: ApiOutput, document: Scene3DDocument, identity: Scene3DDocumentRef) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const save = () => {
    const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = `clip-${String(document.clipNumber ?? 0).padStart(2, '0')}-${document.templateId}.world3d.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <div className="flex flex-wrap items-center gap-3 text-xs text-text-secondary">
    <Scene3DLibraryControls document={document} workspace={workspace} disabled={disabled} preview={preview} identity={identity} onLoad={onLoad} onSaved={onSaved} />
    <label>{t('clipNumber')}
      <input type="number" min="1" step="1" aria-label={t('clipNumber')} disabled={disabled}
        className="ml-2 min-h-10 w-20 rounded-lg border border-border bg-bg-primary px-2"
        value={document.clipNumber ?? ''} onChange={event => onChange({ ...document, clipNumber: reviewClipNumber(event.target.valueAsNumber) })} />
    </label>
    <label>{t('duration')}
      <input type="number" min="0.1" max="600" step="0.1" aria-label={t('duration')} disabled={disabled}
        className="ml-2 min-h-10 w-20 rounded-lg border border-border bg-bg-primary px-2" value={document.duration}
        onChange={event => {
          const duration = event.target.valueAsNumber
          if (Number.isFinite(duration) && duration >= 0.1 && duration <= 600) onChange({ ...document, duration })
        }} />
    </label>
    <label>{t('frameFormat')}
      <select data-testid="world3d-frame-format" aria-label={t('frameFormat')} disabled={disabled}
        className="ml-2 min-h-10 rounded-lg border border-border bg-bg-primary px-2"
        value={scene3dFrameFormat(document.width, document.height)}
        onChange={event => onChange(applyFrameFormat(document, event.target.value as Scene3DFrameFormat))}>
        <option value="landscape">{t('frameFormatLandscape')}</option>
        <option value="portrait">{t('frameFormatPortrait')}</option>
      </select>
    </label>
    <label>{t('frameRate')}
      <select data-testid="world3d-fps" aria-label={t('frameRate')} disabled={disabled}
        className="ml-2 min-h-10 rounded-lg border border-border bg-bg-primary px-2"
        value={document.fps}
        onChange={event => onChange({ ...document, fps: Number(event.target.value) as 24 | 30 | 60 })}>
        <option value={24}>24</option>
        <option value={30}>30</option>
        <option value={60}>60</option>
      </select>
    </label>
    <button type="button" disabled={disabled} onClick={save} className="min-h-10 rounded-lg border border-border px-3">{t('saveDocument')}</button>
    <button type="button" disabled={disabled} onClick={() => input.current?.click()} className="min-h-10 rounded-lg border border-border px-3">{t('loadDocument')}</button>
    <input ref={input} type="file" accept=".json,application/json" data-testid="world3d-load-shot" aria-label={t('loadDocument')} disabled={disabled} className="hidden"
      onChange={async event => {
        const file = event.target.files?.[0]
        event.target.value = ''
        if (!file) return
        try {
          if (file.size > 8 * 1024 * 1024) throw new Error('size')
          const raw = JSON.parse(await file.text())
          if (isWorld3DTemplateRaw(raw)) throw new Error('template')
          const next = parseScene3DDocument(raw)
          if (!next) throw new Error('document')
          onLoad(next); setError('')
        } catch (cause) { setError(cause instanceof Error && cause.message === 'template' ? t('userTemplates.openAsShot') : t('invalidDocument')) }
      }} />
    {error && <p role="alert">{error}</p>}
  </div>
}
