import { useMemo, useState } from 'react'
import { Check, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Pill, SeriesField } from './components'
import { SeriesShotDurationControl } from './SeriesShotDurationControl'
import { greenButton, inputClass, secondaryButton, textareaClass } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesScene, SeriesShot } from './types'

const cloneEpisode = (episode: SeriesEpisode): SeriesEpisode => structuredClone(episode)

export function SeriesEpisodeProposalReview({
  workspace, currentEpisode, proposal, series, busy, onApply,
}: {
  workspace: string
  currentEpisode: SeriesEpisode
  proposal: SeriesEpisode
  series: SeriesProject
  busy: boolean
  onApply: (episode: SeriesEpisode) => Promise<void>
}) {
  const [draft, setDraft] = useState<SeriesEpisode>(() => cloneEpisode(proposal))
  const changed = useMemo(() => JSON.stringify(draft) !== JSON.stringify(proposal), [draft, proposal])
  const duration = draft.shots.reduce((sum, shot) => sum + shot.durationSeconds, 0)

  const updateScene = (index: number, updater: (scene: SeriesScene) => SeriesScene) => {
    setDraft(current => ({
      ...current,
      script: current.script.map((scene, sceneIndex) => sceneIndex === index ? updater(scene) : scene),
    }))
  }
  const updateShot = (index: number, updater: (shot: SeriesShot) => SeriesShot) => {
    setDraft(current => ({
      ...current,
      shots: current.shots.map((shot, shotIndex) => shotIndex === index ? updater(shot) : shot),
    }))
  }

  return <div className="mt-3 space-y-4 rounded-xl border border-green-500/30 bg-green-500/5 p-3">
    <div className="flex flex-wrap items-center gap-2">
      <div>
        <p className="text-sm font-semibold text-green-200">Generated proposal — review and edit</p>
        <p className="mt-0.5 text-[11px] text-text-muted">Every visible field below can be corrected before applying. Internal IDs remain protected.</p>
      </div>
      {changed && <Pill tone="amber">Manual edits pending</Pill>}
      <button className={`ml-auto ${secondaryButton}`} disabled={!changed || busy} onClick={() => setDraft(cloneEpisode(proposal))}>
        <RotateCcw size={13} />Reset edits
      </button>
    </div>

    <div className="grid gap-2 sm:grid-cols-3">
      <ProposalStat label="Outline" before={currentEpisode.outline.beats.length} after={draft.outline.beats.length} suffix="beats" />
      <ProposalStat label="Script" before={currentEpisode.script.length} after={draft.script.length} suffix="scenes" />
      <ProposalStat label="Shots" before={currentEpisode.shots.length} after={draft.shots.length} suffix={`shots · ${duration.toFixed(1)}s`} />
    </div>

    <ProposalSection title="Outline" description="Edit, remove or add story beats.">
      <div className="grid gap-2 md:grid-cols-2">
        {draft.outline.beats.map((beat, index) => <div key={index} className="rounded-lg border border-border bg-bg-primary p-2">
          <div className="mb-2 flex items-center gap-2"><Pill tone="violet">Beat {index + 1}</Pill><button className="ml-auto text-text-muted hover:text-red-300" aria-label={`Delete proposal beat ${index + 1}`} onClick={() => setDraft(current => ({ ...current, outline: { beats: current.outline.beats.filter((_, beatIndex) => beatIndex !== index) } }))}><Trash2 size={14} /></button></div>
          <textarea className={textareaClass} value={beat} onChange={event => setDraft(current => ({ ...current, outline: { beats: current.outline.beats.map((item, beatIndex) => beatIndex === index ? event.target.value : item) } }))} />
        </div>)}
      </div>
      <button className={`mt-2 ${secondaryButton}`} onClick={() => setDraft(current => ({ ...current, outline: { beats: [...current.outline.beats, ''] } }))}><Plus size={13} />Add beat</button>
    </ProposalSection>

    <ProposalSection title="Script" description={`${draft.script.length} scene cards · action, states and dialogue are editable.`}>
      <div className="space-y-3">
        {draft.script.map((scene, sceneIndex) => <div key={scene.id} className="rounded-xl border border-border bg-bg-primary p-3">
          <div className="mb-3 flex items-center gap-2"><Pill tone="blue">Scene {sceneIndex + 1}</Pill><span className="truncate text-[11px] text-text-muted">{series.locations.find(item => item.id === scene.locationId)?.name || 'No location'}</span></div>
          <div className="grid gap-2 lg:grid-cols-2">
            <SeriesField label="Purpose"><textarea className={textareaClass} value={scene.purpose} onChange={event => updateScene(sceneIndex, item => ({ ...item, purpose: event.target.value }))} /></SeriesField>
            <SeriesField label="Entry state"><textarea className={textareaClass} value={scene.entryState} onChange={event => updateScene(sceneIndex, item => ({ ...item, entryState: event.target.value }))} /></SeriesField>
            <SeriesField label="Location"><select className={inputClass} value={scene.locationId} onChange={event => updateScene(sceneIndex, item => ({ ...item, locationId: event.target.value }))}>{series.locations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></SeriesField>
            <SeriesField label="Time"><input className={inputClass} value={scene.time} onChange={event => updateScene(sceneIndex, item => ({ ...item, time: event.target.value }))} /></SeriesField>
            <SeriesField label="Exit state"><textarea className={textareaClass} value={scene.exitState} onChange={event => updateScene(sceneIndex, item => ({ ...item, exitState: event.target.value }))} /></SeriesField>
          </div>
          {scene.beats.length > 0 && <div className="mt-3 grid gap-2 md:grid-cols-2">{scene.beats.map((beat, beatIndex) => <label key={beat.id} className="rounded-lg border border-border bg-bg-secondary p-2 text-[10px] text-text-muted"><span className="mb-1 block uppercase tracking-wide">{beat.kind} {beatIndex + 1}</span><textarea className={textareaClass} value={beat.summary} onChange={event => updateScene(sceneIndex, item => ({ ...item, beats: item.beats.map((entry, index) => index === beatIndex ? { ...entry, summary: event.target.value } : entry) }))} /></label>)}</div>}
          {scene.dialogue.length > 0 && <div className="mt-3 space-y-2"><p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Dialogue</p>{scene.dialogue.map((line, lineIndex) => <div key={line.id} className="grid gap-2 rounded-lg border border-border bg-bg-secondary p-2 lg:grid-cols-[160px_1fr_140px_140px]">
            <select className={inputClass} value={line.characterId} onChange={event => updateScene(sceneIndex, item => ({ ...item, dialogue: item.dialogue.map((entry, index) => index === lineIndex ? { ...entry, characterId: event.target.value } : entry) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
            <textarea className={`${textareaClass} min-h-10`} value={line.text} onChange={event => updateScene(sceneIndex, item => ({ ...item, dialogue: item.dialogue.map((entry, index) => index === lineIndex ? { ...entry, text: event.target.value } : entry) }))} />
            <input className={inputClass} value={line.emotion} placeholder="Emotion" onChange={event => updateScene(sceneIndex, item => ({ ...item, dialogue: item.dialogue.map((entry, index) => index === lineIndex ? { ...entry, emotion: event.target.value } : entry) }))} />
            <input className={inputClass} value={line.delivery} placeholder="Delivery" onChange={event => updateScene(sceneIndex, item => ({ ...item, dialogue: item.dialogue.map((entry, index) => index === lineIndex ? { ...entry, delivery: event.target.value } : entry) }))} />
          </div>)}</div>}
        </div>)}
      </div>
    </ProposalSection>

    <ProposalSection title="Timed shots" description={`${draft.shots.length} readable shot cards in start-to-finish order.`}>
      <div className="grid gap-3 xl:grid-cols-2">
        {draft.shots.map((shot, shotIndex) => <div key={shot.id} className="rounded-xl border border-border bg-bg-primary p-3">
          <div className="mb-3 flex flex-wrap items-center gap-2"><Pill tone="violet">Shot {shotIndex + 1}</Pill><Pill tone="blue">{shot.durationSeconds}s</Pill><span className="truncate text-[10px] text-text-muted">Scene {draft.script.findIndex(scene => scene.id === shot.sceneId) + 1}</span></div>
          <div className="grid gap-2 sm:grid-cols-3">
            <SeriesField label="Scene"><select className={inputClass} value={shot.sceneId} onChange={event => updateShot(shotIndex, item => ({ ...item, sceneId: event.target.value, locationId: draft.script.find(scene => scene.id === event.target.value)?.locationId || item.locationId }))}>{draft.script.map((scene, index) => <option key={scene.id} value={scene.id}>Scene {index + 1} · {scene.purpose.slice(0, 40)}</option>)}</select></SeriesField>
            <SeriesShotDurationControl workspace={workspace} series={series} shot={shot} onChange={planned => updateShot(shotIndex, () => planned)} />
            <SeriesField label="Framing"><input className={inputClass} value={shot.framing} onChange={event => updateShot(shotIndex, item => ({ ...item, framing: event.target.value }))} /></SeriesField>
          </div>
          <div className="mt-2 grid gap-2 lg:grid-cols-2">
            <SeriesField label="Camera"><textarea className={textareaClass} value={shot.camera} onChange={event => updateShot(shotIndex, item => ({ ...item, camera: event.target.value }))} /></SeriesField>
            <SeriesField label="Action"><textarea className={textareaClass} value={shot.action} onChange={event => updateShot(shotIndex, item => ({ ...item, action: event.target.value }))} /></SeriesField>
            <SeriesField label="Generation prompt"><textarea className={textareaClass} value={shot.prompt} onChange={event => updateShot(shotIndex, item => ({ ...item, prompt: event.target.value }))} /></SeriesField>
            <SeriesField label="Negative prompt"><textarea className={textareaClass} value={shot.negativePrompt} onChange={event => updateShot(shotIndex, item => ({ ...item, negativePrompt: event.target.value }))} /></SeriesField>
            <SeriesField label="Audio direction"><textarea className={textareaClass} value={shot.audioDirection || ''} onChange={event => updateShot(shotIndex, item => ({ ...item, audioDirection: event.target.value }))} /></SeriesField>
          </div>
          <div className="mt-2"><p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">Visible characters</p><div className="flex flex-wrap gap-2">{series.characters.map(character => { const isSpeaker = shot.dialogueBeats.some(line => line.characterId === character.id); return <label key={character.id} title={isSpeaker ? 'A speaking character must remain visible' : undefined} className="flex items-center gap-1 rounded-md border border-border bg-bg-secondary px-2 py-1 text-[10px] text-text-secondary"><input type="checkbox" disabled={isSpeaker} checked={shot.visibleCharacterIds.includes(character.id) || isSpeaker} onChange={event => updateShot(shotIndex, item => ({ ...item, visibleCharacterIds: event.target.checked ? [...item.visibleCharacterIds, character.id] : item.visibleCharacterIds.filter(id => id !== character.id) }))} />{character.name}</label> })}</div></div>
          {shot.dialogueBeats.length > 0 && <div className="mt-3 space-y-2"><p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Dialogue in this shot</p>{shot.dialogueBeats.map((line, lineIndex) => <div key={line.id} className="grid gap-2 rounded-lg border border-border bg-bg-secondary p-2 md:grid-cols-[150px_1fr_120px]">
            <select className={inputClass} value={line.characterId} onChange={event => updateShot(shotIndex, item => ({ ...item, dialogueBeats: item.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, characterId: event.target.value } : entry), visibleCharacterIds: item.visibleCharacterIds.includes(event.target.value) ? item.visibleCharacterIds : [...item.visibleCharacterIds, event.target.value] }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
            <textarea className={`${textareaClass} min-h-10`} value={line.text} onChange={event => updateShot(shotIndex, item => ({ ...item, dialogueBeats: item.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, text: event.target.value } : entry) }))} />
            <input className={inputClass} value={line.emotion} placeholder="Emotion" onChange={event => updateShot(shotIndex, item => ({ ...item, dialogueBeats: item.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, emotion: event.target.value } : entry) }))} />
          </div>)}</div>}
        </div>)}
      </div>
    </ProposalSection>

    {(draft.continuityIssues?.length || draft.proposedCanonDelta.add.length || draft.proposedCanonDelta.change.length || draft.proposedCanonDelta.retire.length) ? <ProposalSection title="Continuity and canon" description="Warnings and proposed canon changes are shown as separate cards.">
      <div className="grid gap-2 md:grid-cols-2">
        {draft.continuityIssues?.map(issue => <div key={issue.id} className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200"><Pill tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.kind}</Pill><p className="mt-2">{issue.message}</p></div>)}
        {[...draft.proposedCanonDelta.add, ...draft.proposedCanonDelta.change].map((item, index) => <div key={item.id} className="rounded-lg border border-border bg-bg-primary p-3"><div className="mb-2 flex items-center gap-2"><Pill tone="violet">Canon change {index + 1}</Pill><select className={`${inputClass} ml-auto w-auto`} value={item.decision} onChange={event => setDraft(current => { const update = (entry: typeof item) => entry.id === item.id ? { ...entry, decision: event.target.value as typeof entry.decision } : entry; return { ...current, proposedCanonDelta: { ...current.proposedCanonDelta, add: current.proposedCanonDelta.add.map(update), change: current.proposedCanonDelta.change.map(update) } } })}><option value="pending">Pending</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option></select></div><textarea className={textareaClass} value={item.description} onChange={event => setDraft(current => { const update = (entry: typeof item) => entry.id === item.id ? { ...entry, description: event.target.value } : entry; return { ...current, proposedCanonDelta: { ...current.proposedCanonDelta, add: current.proposedCanonDelta.add.map(update), change: current.proposedCanonDelta.change.map(update) } } })} /></div>)}
      </div>
    </ProposalSection> : null}

    <details className="text-[10px] text-text-muted"><summary className="cursor-pointer">Technical JSON (optional, read-only)</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify({ outline: draft.outline, script: draft.script, shots: draft.shots, continuityIssues: draft.continuityIssues, proposedCanonDelta: draft.proposedCanonDelta }, null, 2)}</pre></details>
    <div className="sticky bottom-2 flex justify-end rounded-xl border border-green-500/20 bg-bg-secondary/95 p-2 shadow-xl backdrop-blur">
      <button className={greenButton} onClick={() => void onApply(draft)} disabled={busy}><Check size={13} />Apply reviewed{changed ? ' + edited' : ''} proposal</button>
    </div>
  </div>
}

function ProposalStat({ label, before, after, suffix }: { label: string; before: number; after: number; suffix: string }) {
  return <div className="rounded-xl border border-border bg-bg-primary p-3"><p className="text-[10px] uppercase tracking-wide text-text-muted">{label}</p><p className="mt-1 text-lg font-semibold text-text-primary">{before} <span className="text-text-muted">→</span> {after}</p><p className="text-[10px] text-text-secondary">{suffix}</p></div>
}

function ProposalSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-border bg-bg-secondary p-3"><div className="mb-3"><h4 className="text-xs font-semibold text-text-primary">{title}</h4><p className="mt-0.5 text-[10px] text-text-muted">{description}</p></div>{children}</section>
}
