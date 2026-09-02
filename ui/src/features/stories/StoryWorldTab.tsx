import type { ComponentType, RefObject } from 'react'
import { ImagePlus, Loader2, Plus, Upload } from 'lucide-react'
import { button, panel, Field, SectionHeader } from './storyLabChrome'
import { storyId } from './model'
import type { StoryGenerationScope, StoryLocation, StoryProject } from './types'

type WorldUploadTarget = { kind: 'world' | 'character' | 'location'; id?: string }

export function StoryWorldTab({
  project,
  patch,
  update,
  busy,
  instruction,
  setInstruction,
  generate,
  approve,
  isApproved,
  imageBusy,
  referenceBatchBusy,
  generateVisual,
  setUploadTarget,
  uploadRef,
  removeReference,
  ReferenceGallery,
  LocationEditor,
}: {
  project: StoryProject
  patch: (patch: Partial<StoryProject>) => void
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  instruction: string
  setInstruction: (value: string) => void
  generate: (scope: StoryGenerationScope) => void
  approve: (key: keyof StoryProject['approvals']) => void
  isApproved: (key: keyof StoryProject['approvals']) => boolean
  imageBusy: string
  referenceBatchBusy: boolean
  generateVisual: (target: { kind: 'world' | 'character' | 'location'; id?: string }, prompt: string) => void
  setUploadTarget: (target: WorldUploadTarget) => void
  uploadRef: RefObject<HTMLInputElement | null>
  removeReference: (target: 'world' | 'character' | 'location', targetId: string | undefined, assetId: string) => void
  ReferenceGallery: ComponentType<{
    ids: string[]
    assets: StoryProject['assets']
    onRemove: (id: string) => void
  }>
  LocationEditor: ComponentType<{
    location: StoryLocation
    index: number
    total: number
    project: StoryProject
    update: (updater: (project: StoryProject) => StoryProject) => void
    imageBusy: string
    generateVisual: (target: { kind: 'location'; id: string }, prompt: string) => void
    upload: () => void
    removeReference: (id: string) => void
  }>
}) {
  return (
    <>
      <div id="story-review-world" className="scroll-mt-4">
        <SectionHeader title="World bible" description="Rules, places and a visual language that every production can reuse." scope="world" busy={busy} approved={isApproved('world')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('world')} />
      </div>
      <div className={`${panel} grid md:grid-cols-2 gap-3`}>
        <div className="md:col-span-2"><Field label="World summary" value={project.world.summary} onChange={summary => patch({ world: { ...project.world, summary } })} rows={5} /></div>
        {(['period', 'geography', 'society', 'technology'] as const).map(key => (
          <Field key={key} label={key[0].toUpperCase() + key.slice(1)} value={project.world[key]} onChange={value => patch({ world: { ...project.world, [key]: value } })} rows={2} />
        ))}
        <div className="md:col-span-2"><Field label="Rules — one per line" value={project.world.rules.join('\n')} onChange={value => patch({ world: { ...project.world, rules: value.split('\n').filter(Boolean) } })} rows={4} /></div>
        <div className="md:col-span-2"><Field label="World-specific visual language (lighting, palette, motifs)" value={project.world.visualLanguage} onChange={visualLanguage => patch({ world: { ...project.world, visualLanguage } })} rows={3} /></div>
        <Field label="World concept content prompt" value={project.world.visualPrompt} onChange={visualPrompt => patch({ world: { ...project.world, visualPrompt } })} rows={4} />
        <Field label="Negative visual prompt" value={project.world.negativePrompt} onChange={negativePrompt => patch({ world: { ...project.world, negativePrompt } })} rows={4} />
        <div className="md:col-span-2 flex gap-2">
          <button className={button} disabled={Boolean(imageBusy) || referenceBatchBusy || !project.world.visualPrompt.trim()} onClick={() => generateVisual({ kind: 'world' }, project.world.visualPrompt)}>
            {imageBusy === 'world:world' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {project.world.referenceAssetIds.length ? 'Generate another world concept' : 'Generate world concept'}
          </button>
          <button className={button} onClick={() => { setUploadTarget({ kind: 'world' }); uploadRef.current?.click() }}><Upload size={13} /> Add reference</button>
        </div>
        <div className="md:col-span-2"><ReferenceGallery ids={project.world.referenceAssetIds} assets={project.assets} onRemove={id => removeReference('world', undefined, id)} /></div>
      </div>
      <div className="mt-4 space-y-3">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-semibold text-text-primary">Locations</h3>
          <button className={button} onClick={() => update(current => {
            current.world.locations.push({ id: storyId('location'), name: 'New location', purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [] })
            return current
          })}><Plus size={13} /> Location</button>
        </div>
        {project.world.locations.map((location, index) => (
          <LocationEditor key={location.id} location={location} index={index} total={project.world.locations.length} project={project} update={update} imageBusy={imageBusy} generateVisual={generateVisual} upload={() => { setUploadTarget({ kind: 'location', id: location.id }); uploadRef.current?.click() }} removeReference={id => removeReference('location', location.id, id)} />
        ))}
      </div>
    </>
  )
}
