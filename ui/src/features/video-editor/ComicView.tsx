import { useState, type DragEvent as ReactDragEvent } from 'react'
import { Copy, Trash2 } from 'lucide-react'
import type { EditorClip } from './editorClipNormalization'
import type { EditorSoundtrack } from './editorDraft'
import { effectiveDuration } from './editorTimeline'
import { ShotClipMenu } from './ShotBoard'
import { layoutComic, PAGE_H, PAGE_W, type ComicPanelBox } from './comicView'
import type { ClipExtra, ComicExtraPatch, ComicTextStyle } from './comicEdits'
import { useComicPanels } from './useComicPanels'
import { useUiTranslation } from '../../i18n'

const PAPER = '#F0E8D6'
const INK = '#141110'
const LETTER = '"Comic Sans MS", "Trebuchet MS", sans-serif'

interface Props {
  open: boolean
  workspace: string
  file?: string
  clips: EditorClip[]
  soundtrack: EditorSoundtrack | null
  extras: Record<string, ClipExtra | undefined>
  selectedId: string | null
  revision: number
  onSelect: (index: number) => void
  onMove: (insertionIndex: number, id: string) => void
  onDelete: (id: string) => void
  onDuplicate: (id: string) => void
  onExtra: (id: string, patch: ComicExtraPatch) => void
  onChanged: () => Promise<void>
  onError: (message: string | null) => void
}

/** A second view of the open montage. Every control edits that same montage. */
export function ComicView(props: Props) {
  if (!props.open || !props.file) return null
  return <ComicPages {...props} file={props.file} />
}

function ComicPages(props: Props & { file: string }) {
  const { t } = useUiTranslation('videoEditor')
  const [printed, setPrinted] = useState(true)
  const [armedId, setArmedId] = useState<string | null>(null)
  const { imageFor, observe } = useComicPanels(props)
  const pages = layoutComic(props.clips.map(clip => ({
    id: clip.id,
    duration: effectiveDuration(clip),
    width: clip.width,
    height: clip.height,
    focusX: clip.focusX,
    focusY: clip.focusY,
  })))
  return <div data-testid="comic-view" className="absolute inset-0 z-20 overflow-auto" style={{ background: '#2a241c' }}>
    <div className="sticky top-0 z-10 flex items-center gap-2 px-3 py-2 text-xs" style={{ background: '#2a241c' }}>
      <button type="button" data-testid="comic-printed" aria-pressed={printed} onClick={() => setPrinted(true)}
        className={`rounded border px-2 py-1 ${printed ? 'border-amber-200 text-amber-100' : 'border-white/20 text-white/70'}`}>{t('comic.printed')}</button>
      <button type="button" data-testid="comic-original" aria-pressed={!printed} onClick={() => setPrinted(false)}
        className={`rounded border px-2 py-1 ${!printed ? 'border-amber-200 text-amber-100' : 'border-white/20 text-white/70'}`}>{t('comic.original')}</button>
    </div>
    {!props.clips.length && <p className="px-4 text-sm text-amber-100/80">{t('comic.empty')}</p>}
    <div className="flex flex-col items-center gap-6 px-3 pb-8">
      {pages.map(page => <section key={page.index} data-testid="comic-page" data-page={page.index} className="w-full max-w-[440px]">
        <p className="mb-1 text-center text-[10px] text-amber-100/70">{t('comic.page', { n: page.index + 1 })}</p>
        <div className="relative shadow-xl" style={{ width: '100%', aspectRatio: `${PAGE_W} / ${PAGE_H}`, background: PAPER }}>
          {page.tiers.flatMap(tier => tier.panels).map(panel => {
            const index = props.clips.findIndex(clip => clip.id === panel.id)
            const clip = props.clips[index]
            if (!clip) return null
            return <ComicPanel key={panel.id} panel={panel} clip={clip} index={index} printed={printed}
              image={imageFor(panel.id)} extra={props.extras[panel.id]} selected={props.selectedId === panel.id}
              editing={armedId === panel.id} onArm={setArmedId}
              hasSong={Boolean(props.soundtrack)} observe={observe} {...props} />
          })}
        </div>
      </section>)}
    </div>
  </div>
}

function ComicPanel(props: {
  panel: ComicPanelBox
  clip: EditorClip
  index: number
  printed: boolean
  image: { frame: string; print: string; at: number } | undefined
  extra: ClipExtra | undefined
  selected: boolean
  editing: boolean
  onArm: (id: string) => void
  hasSong: boolean
  observe: (id: string, element: Element | null) => void
} & Pick<Props, 'workspace' | 'file' | 'onSelect' | 'onMove' | 'onDelete' | 'onDuplicate' | 'onExtra' | 'onChanged' | 'onError'>) {
  const { t } = useUiTranslation('videoEditor')
  const box = {
    left: `${(props.panel.x / PAGE_W) * 100}%`,
    top: `${(props.panel.y / PAGE_H) * 100}%`,
    width: `${(props.panel.w / PAGE_W) * 100}%`,
    height: `${(props.panel.h / PAGE_H) * 100}%`,
  }
  const url = props.image ? (props.printed ? props.image.print : props.image.frame) : ''
  return <article data-testid="comic-panel" data-clip-id={props.clip.id} data-splash={props.panel.splash ? '1' : '0'}
    ref={element => props.observe(props.clip.id, element)} draggable
    onDragStart={event => startPanelDrag(event, props.clip.id)}
    onDragOver={event => event.preventDefault()}
    onDrop={event => dropPanel(event, props.index, props.onMove)}
    onClick={() => { props.onArm(props.clip.id); props.onSelect(props.index) }}
    className="absolute" style={{ ...box, outline: props.selected ? '2px solid #1d4e89' : undefined, outlineOffset: '1px' }}>
    <div className="absolute inset-0 overflow-hidden" style={{ border: `3px solid ${INK}`, background: '#e4dcc8' }}>
      {url ? <img src={url} alt="" draggable={false} className="h-full w-full" style={{ objectFit: 'cover', objectPosition: `${props.panel.focusX}% ${props.panel.focusY}%` }} />
        : <div className="flex h-full items-center justify-center text-[10px]" style={{ color: INK }}>{t('comic.loading')}</div>}
    </div>
    <ComicLettering clipId={props.clip.id} lyric={props.extra?.lyric} style={props.extra?.comic?.text ?? 'caption'}
      hasSong={props.hasSong} selected={props.editing} onCommit={lyric => props.onExtra(props.clip.id, { lyric })} />
    {props.editing && <ComicTools {...props} />}
  </article>
}

function startPanelDrag(event: ReactDragEvent, id: string) {
  if ((event.target as HTMLElement).closest('textarea, button, input, select, video')) {
    event.preventDefault()
    return
  }
  event.dataTransfer.setData('text/x-maestro-video-clip', id)
  event.dataTransfer.setData('text/plain', id)
  event.dataTransfer.effectAllowed = 'move'
}

function dropPanel(event: ReactDragEvent<HTMLElement>, index: number, onMove: (insertionIndex: number, id: string) => void) {
  event.preventDefault()
  event.stopPropagation()
  const movingId = event.dataTransfer.getData('text/x-maestro-video-clip') || event.dataTransfer.getData('text/plain')
  if (!movingId) return
  const rect = event.currentTarget.getBoundingClientRect()
  const after = event.clientX > rect.left + rect.width / 2
  onMove(index + (after ? 1 : 0), movingId)
}

function ComicLettering(props: {
  clipId: string
  lyric: string | undefined
  style: ComicTextStyle
  hasSong: boolean
  selected: boolean
  onCommit: (lyric: string) => void
}) {
  const { t } = useUiTranslation('videoEditor')
  const propLyric = props.lyric ?? ''
  const [source, setSource] = useState(propLyric)
  const [seenId, setSeenId] = useState(props.clipId)
  const [draft, setDraft] = useState(propLyric)
  if (props.clipId !== seenId || propLyric !== source) {
    setSeenId(props.clipId)
    setSource(propLyric)
    setDraft(propLyric)
  }
  if (props.style === 'none' && !props.selected) return null
  const shown = displayLine(props.lyric, props.style, props.hasSong)
  const caption = props.style !== 'bubble'
  const place = caption ? 'left-1 top-1 max-w-[86%]' : props.selected ? 'bottom-12 left-2 right-2' : 'bottom-2 left-2 right-2'
  return <div className={`absolute z-[1] ${place}`}
    onClick={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()}>
    {props.selected ? <textarea data-testid="comic-lyric" value={draft} rows={draft.trim() ? 3 : 1} maxLength={500}
      placeholder={t('comic.editText')} aria-label={t('comic.editText')}
      onChange={event => setDraft(event.target.value)}
      onBlur={() => { if (draft.trim() !== (props.lyric ?? '').trim()) props.onCommit(draft) }}
      className="w-full resize-none rounded px-1.5 py-1 text-[11px] leading-snug"
      style={{ fontFamily: LETTER, color: INK, background: caption ? '#fff2a8' : '#fff' }} />
      : shown ? <>
        <p className={`line-clamp-3 overflow-hidden px-1.5 py-1 text-[11px] leading-snug ${caption ? '' : 'rounded-2xl'}`}
          style={{ fontFamily: LETTER, color: INK, background: caption ? '#fff2a8' : '#fff' }}>{shown}</p>
        {!caption && <span className="absolute left-4 top-full border-x-8 border-x-transparent border-t-8 border-t-white" />}
      </> : null}
  </div>
}

function displayLine(lyric: string | undefined, style: ComicTextStyle, hasSong: boolean): string {
  const text = (lyric ?? '').trim()
  if (!text || style === 'none') return ''
  return style === 'caption' && hasSong ? `♪ ${text}` : text
}

function ComicTools(props: {
  clip: EditorClip
  extra: ClipExtra | undefined
  workspace: string
  file?: string
  onDelete: (id: string) => void
  onDuplicate: (id: string) => void
  onExtra: (id: string, patch: ComicExtraPatch) => void
  onChanged: () => Promise<void>
  onError: (message: string | null) => void
}) {
  const { t } = useUiTranslation('videoEditor')
  const [takes, setTakes] = useState(false)
  const [picking, setPicking] = useState(false)
  const style = props.extra?.comic?.text ?? 'caption'
  const stop = (event: { stopPropagation: () => void }) => event.stopPropagation()
  return <div className="absolute inset-x-0 bottom-0 z-[2] space-y-1 bg-black/55 p-1" onClick={stop} onMouseDown={stop}>
    <div className="flex flex-wrap items-center gap-1">
      <select data-testid="comic-style" value={style} aria-label={t('comic.textStyle')}
        onChange={event => props.onExtra(props.clip.id, { comic: { text: event.target.value as ComicTextStyle } })}
        className="rounded bg-white px-1 py-0.5 text-[10px] text-black">
        <option value="caption">{t('comic.caption')}</option>
        <option value="bubble">{t('comic.bubble')}</option>
        <option value="none">{t('comic.none')}</option>
      </select>
      <button type="button" className="rounded bg-white/90 px-1 py-0.5 text-[10px] text-black" onClick={() => setTakes(open => !open)}>{t('comic.changeTake')}</button>
      <button type="button" data-testid="comic-pick" className="rounded bg-white/90 px-1 py-0.5 text-[10px] text-black" onClick={() => setPicking(open => !open)}>{t('comic.pickFrame')}</button>
      <button type="button" data-testid="comic-duplicate" className="rounded bg-white/90 p-0.5 text-black" onClick={() => props.onDuplicate(props.clip.id)} aria-label={t('comic.duplicate')}><Copy size={11} /></button>
      <button type="button" data-testid="comic-delete" className="rounded bg-white/90 p-0.5 text-black" onClick={() => props.onDelete(props.clip.id)} aria-label={t('comic.delete')}><Trash2 size={11} /></button>
    </div>
    {takes && props.file && <div className="max-h-28 overflow-auto rounded bg-white p-1 text-black">
      <ShotClipMenu workspace={props.workspace} file={props.file} clipId={props.clip.id} onChanged={props.onChanged} onError={props.onError} />
    </div>}
    {picking && <FramePicker clip={props.clip} value={props.extra?.comic?.frame} onCommit={frame => props.onExtra(props.clip.id, { comic: { frame } })} />}
  </div>
}

function FramePicker(props: { clip: EditorClip; value: number | undefined; onCommit: (frame: number) => void }) {
  const { t } = useUiTranslation('videoEditor')
  const duration = Math.max(0.04, effectiveDuration(props.clip))
  const [at, setAt] = useState(props.value ?? Math.min(duration / 2, duration))
  return <label className="block text-[10px] text-white" onClick={event => event.stopPropagation()}>
    {t('comic.frameAt', { time: at.toFixed(2) })}
    <input data-testid="comic-frame" type="range" min={0} max={duration} step={0.05} value={Math.min(at, duration)}
      onChange={event => setAt(Number(event.target.value))}
      onPointerUp={event => props.onCommit(Number(event.currentTarget.value))}
      onKeyUp={event => props.onCommit(Number(event.currentTarget.value))}
      onBlur={event => props.onCommit(Number(event.currentTarget.value))}
      className="w-full" />
    <video src={props.clip.previewUrl} muted playsInline preload="metadata" className="mt-1 h-16 w-full object-cover"
      ref={element => { if (element && element.readyState >= 1) element.currentTime = props.clip.trimStart + at }}
      onLoadedMetadata={event => { event.currentTarget.currentTime = props.clip.trimStart + at }} />
  </label>
}
