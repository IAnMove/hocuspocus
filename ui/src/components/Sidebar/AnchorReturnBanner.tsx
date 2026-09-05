import { ArrowLeft, X, Check, SkipForward } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

/**
 * Persistent banner that drives Edit Anything/Recast/Repaint → Image Mode
 * round-trips for one boundary anchor or reference at a time.
 * Mounted at the top of the sidebar whenever `editReturnTarget` is set.
 *
 * Each round-trip is independent — start and end anchors are populated
 * by separate "Edit X in Image Mode" buttons in EditAnythingControls.
 *
 * Actions:
 *   - Apply: take the most recent Image-mode output and store it as the
 *     anchor identified by editReturnTarget.anchor, then return to Edit
 *     Anything mode.
 *   - Skip: return to Edit Anything without setting the anchor. The
 *     model will fall back to extracting the source frame at generation
 *     time (the morph-from-source default).
 *   - Cancel (×): same as Skip — return without applying.
 */
export function AnchorReturnBanner() {
  const { t } = useUiTranslation('studio')
  const target = useStore(s => s.editReturnTarget)
  const outputs = useStore(s => s.outputs)
  const apply = useStore(s => s.applyOutputAsAnchor)
  const skip = useStore(s => s.skipAnchorPhase)
  const cancel = useStore(s => s.cancelAnchorReturn)

  if (!target) return null

  const isRecast = target.anchor === 'recast'
  const isRepaint = target.anchor === 'repaint'
  const anchorLabel = target.anchor === 'start'
    ? t('anchor.start')
    : target.anchor === 'end'
      ? t('anchor.end')
      : isRepaint
        ? t('anchor.repaintFrame')
        : t('anchor.recastRef')

  // Latest image output (newest first, type === 'image')
  const latestImage = outputs.find(o => o.type === 'image')
  const hasLatestImage = !!latestImage

  return (
    <div className="px-3 py-2 bg-accent-blue/10 border-b border-accent-blue/30">
      <div className="flex items-center gap-2 mb-1.5">
        <ArrowLeft size={12} className="text-accent-blue shrink-0" />
        <span className="text-[10px] font-semibold text-accent-blue">
          {isRecast
            ? t('anchor.editingRecast')
            : isRepaint
              ? t('anchor.editingRepaint')
              : t('anchor.editingAnchor', { label: anchorLabel })}
        </span>
        <button
          onClick={cancel}
          title={isRecast
            ? t('anchor.cancelRecast')
            : isRepaint
              ? t('anchor.cancelRepaint')
              : t('anchor.cancelEdit')}
          className="ml-auto p-0.5 rounded hover:bg-accent-blue/20 text-accent-blue/80 hover:text-accent-blue"
        >
          <X size={11} />
        </button>
      </div>
      <p className="text-[9px] text-text-muted leading-snug mb-2">
        {isRecast
          ? t('anchor.bodyRecast')
          : isRepaint
            ? t('anchor.bodyRepaint')
            : t('anchor.bodyAnchor', { label: anchorLabel.toLowerCase() })}
      </p>
      <div className="flex gap-1.5">
        <button
          onClick={() => void apply()}
          disabled={!hasLatestImage}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded bg-accent-blue text-white hover:bg-accent-blue/90 disabled:opacity-40 disabled:cursor-not-allowed text-[10px] transition-colors"
        >
          <Check size={11} />
          {t('anchor.applyReturn')}
        </button>
        <button
          onClick={skip}
          title={isRecast
            ? t('anchor.skipRecast')
            : isRepaint
              ? t('anchor.skipRepaint')
              : t('anchor.skipAnchor', { label: anchorLabel })}
          className="flex items-center justify-center gap-1 px-2 py-1 rounded border border-border text-text-secondary hover:bg-bg-hover text-[10px] transition-colors"
        >
          <SkipForward size={11} />
          {isRecast || isRepaint ? t('anchor.returnUnchanged') : t('anchor.skip')}
        </button>
      </div>
      {!hasLatestImage && (
        <p className="text-[9px] text-text-muted mt-1.5 italic">
          {t('anchor.needImage')}
        </p>
      )}
    </div>
  )
}
