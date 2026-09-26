import { useState } from 'react'
import { templateComponentPrompt } from './componentContract'
import { getCandidateSceneTemplate } from './catalog'

export function TemplateComponentHelp({ templateId }: { templateId: string }) {
  const [message, setMessage] = useState('')
  const contract = templateComponentPrompt(templateId)
  const motion = getCandidateSceneTemplate(templateId).motionIntensity
  const copy = async () => {
    try { await navigator.clipboard.writeText(contract); setMessage('Contract copied. It does not run actions or generate assets.') }
    catch { setMessage('Could not copy. Open the contract and select it manually.') }
  }
  return <div className="rounded border border-border p-3 text-xs">
    {motion && <p className="mb-2 text-amber-100">{motion === 'high' ? 'Strong' : 'Moderate'} motion within the shot, not an edit transition. Review the spins and avoid chaining them densely if they cause motion sickness. The images' alpha and pose need a visual review.</p>}
    <button type="button" onClick={() => void copy()} className="rounded border border-cyan-400/40 px-3 py-1.5">Copy contract for the Wizard</button>
    <details className="mt-2"><summary>View components and requirements</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[10px]">{contract}</pre></details>
    {message && <p role="status" className="mt-2">{message}</p>}
  </div>
}
