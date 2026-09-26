import { useState } from 'react'
import { APPROVED_REFERENCE_JSON } from './approvedReferences'

const REFERENCE_BASE = 'https://github.com/IAnMove/hocuspocus/releases/download/procedural-style-reference-v1'

export function TemplateReferencePanel({ templateId, disabled, onOpen }: {
  templateId: string; disabled: boolean; onOpen: (file: File) => void
}) {
  const [show, setShow] = useState(false)
  const [failed, setFailed] = useState(false)
  if (!Object.hasOwn(APPROVED_REFERENCE_JSON, templateId)) return <p role="status" className="rounded border border-amber-300/30 p-3 text-xs text-amber-100">New choreography: visual reference awaiting review. You can create it with your assets and edit it; no approved original is published.</p>
  return <div className="rounded border border-border p-3 text-xs">
    <button type="button" onClick={() => setShow(value => !value)} className="rounded border border-cyan-400/40 px-3 py-1.5">{show ? 'Hide reference' : 'Watch reference video (GitHub)'}</button>
    {show && !failed && <video aria-label="Original reference video" controls playsInline preload="metadata" src={`${REFERENCE_BASE}/${templateId}.mp4`} onError={() => setFailed(true)} className="mt-2 max-h-64 w-full rounded bg-black" />}
    {failed && <p role="status" className="mt-2">Reference unavailable. You can continue with your assets; the video is not replaced with a fake preview.</p>}
    <p className="mt-2 text-text-muted">Chorus original v1: SVG/GLB composition, 4 seconds, no audio. It does not represent how your images look or later compiler changes.</p>
    <a href={`${REFERENCE_BASE}/${templateId}.json`} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-cyan-200 underline">Download original configuration ↗</a>
    <p className="mt-1 text-text-muted">To open the original, download its JSON and select it here after confirming the replacement at the end. We verify SHA-256; this needs localhost or HTTPS. The button below creates a new scene with your assets.</p>
    <label className="mt-2 block">Open verified original JSON<input aria-label="Open verified original JSON" type="file" accept="application/json,.json" disabled={disabled} onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) onOpen(file) }} className="mt-1 block w-full disabled:opacity-40" /></label>
  </div>
}
