import { ArrowLeft, ArrowRight, Box, Copy, Plus, Square, Trash2, TriangleAlert } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { videoJsTimeline } from './document.ts'
import type { VideoJsDocument, VideoJsSceneError, VideoJsSceneKind } from './types.ts'

interface SceneListProps {
  document: VideoJsDocument
  selectedId: string | null
  errors: VideoJsSceneError[]
  locked: boolean
  onSelect: (sceneId: string) => void
  onAdd: (kind: VideoJsSceneKind) => void
  onMove: (sceneId: string, offset: -1 | 1) => void
  onDuplicate: (sceneId: string) => void
  onDelete: (sceneId: string) => void
}

const iconButton = 'flex h-8 w-8 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:opacity-30'

export function VideoJsSceneList(props: SceneListProps) {
  const { t } = useUiTranslation('videojs')
  const { document, selectedId, errors, locked } = props
  const failing = new Set(errors.map(error => error.sceneId))
  const timeline = videoJsTimeline(document)
  return (
    <section className="flex flex-col gap-2" aria-label={t('scenes.title')}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-text-primary">{t('scenes.title')}</h2>
        <span className="text-xs text-text-muted">{t('scenes.count', { count: document.scenes.length })}</span>
        <div className="ml-auto flex gap-2">
          <button type="button" disabled={locked} onClick={() => props.onAdd('2d')} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border px-3 text-xs text-text-primary hover:bg-bg-hover disabled:opacity-40">
            <Plus size={14} /><Square size={13} />{t('scenes.add2d')}
          </button>
          <button type="button" disabled={locked} onClick={() => props.onAdd('3d')} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border px-3 text-xs text-text-primary hover:bg-bg-hover disabled:opacity-40">
            <Plus size={14} /><Box size={13} />{t('scenes.add3d')}
          </button>
        </div>
      </div>
      <ol className="flex gap-2 overflow-x-auto pb-1">
        {timeline.map(({ scene, index }) => {
          const selected = scene.id === selectedId
          return (
            <li key={scene.id} className={`flex w-52 shrink-0 flex-col rounded-lg border ${selected ? 'border-accent-blue bg-accent-blue/10' : 'border-border bg-bg-secondary'}`}>
              <button type="button" onClick={() => props.onSelect(scene.id)} aria-pressed={selected} className="flex flex-col items-start gap-1 px-3 pt-2 text-left">
                <span className="flex w-full items-center gap-2 text-xs text-text-muted">
                  <span className="rounded bg-bg-tertiary px-1.5 py-0.5 font-mono uppercase">{scene.kind}</span>
                  <span>{index + 1}</span>
                  <span className="ml-auto tabular-nums">{scene.duration.toFixed(1)} s</span>
                </span>
                <span className="flex w-full items-center gap-1 truncate text-sm font-medium text-text-primary">
                  {failing.has(scene.id) && <TriangleAlert size={14} className="shrink-0 text-red-400" aria-label={t('scenes.hasError')} />}
                  <span className="truncate">{scene.title}</span>
                </span>
              </button>
              <div className="flex items-center gap-0.5 px-1 pb-1">
                <button type="button" className={iconButton} disabled={locked || index === 0} onClick={() => props.onMove(scene.id, -1)} aria-label={t('scenes.moveLeft')} title={t('scenes.moveLeft')}><ArrowLeft size={14} /></button>
                <button type="button" className={iconButton} disabled={locked || index === document.scenes.length - 1} onClick={() => props.onMove(scene.id, 1)} aria-label={t('scenes.moveRight')} title={t('scenes.moveRight')}><ArrowRight size={14} /></button>
                <button type="button" className={iconButton} disabled={locked} onClick={() => props.onDuplicate(scene.id)} aria-label={t('scenes.duplicate')} title={t('scenes.duplicate')}><Copy size={14} /></button>
                <button type="button" className={`${iconButton} ml-auto hover:text-red-400`} disabled={locked || document.scenes.length <= 1} onClick={() => props.onDelete(scene.id)} aria-label={t('scenes.delete')} title={t('scenes.delete')}><Trash2 size={14} /></button>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
