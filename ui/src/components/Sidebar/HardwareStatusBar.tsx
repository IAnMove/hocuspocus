import { useEffect, useRef, useState } from 'react'
import { ChevronUp, ChevronDown, Cpu, MemoryStick, Power, Zap } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { fetchSystemStats, releaseModels } from '../../api/client'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'

// Color a "fullness" bar (VRAM / RAM) by how close to full it is —
// green well below, amber as it tightens, red near the ceiling. This is
// the at-a-glance OOM-risk read that matters most in this app.
function fullnessColor(pct: number): string {
  if (pct >= 90) return 'bg-red-500'
  if (pct >= 75) return 'bg-indicator-warning'
  return 'bg-emerald-500'
}

// Same thresholds, applied to TEXT (used by the collapsed chips, which
// have no bars). Low load stays neutral so only pressure stands out.
function fullnessText(pct: number): string {
  if (pct >= 90) return 'text-chip-red'
  if (pct >= 75) return 'text-indicator-warning'
  return 'text-text-secondary'
}

function Gauge({
  label,
  percent,
  value,
  fill,
  title,
}: {
  label: string
  percent: number
  value: string
  fill: string
  title?: string
}) {
  const w = Math.max(0, Math.min(100, percent))
  return (
    <div className="flex items-center gap-2" title={title}>
      <span className="w-10 shrink-0 text-[10px] text-text-muted uppercase tracking-wide">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-bg-tertiary overflow-hidden">
        <div
          className={`h-full rounded-full ${fill} transition-[width] duration-500`}
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="w-[92px] shrink-0 text-right text-[10px] text-text-secondary tabular-nums">{value}</span>
    </div>
  )
}

const COLLAPSE_KEY = 'hwbar_collapsed'

/**
 * Live hardware status indicators docked at the bottom of the sidebar.
 * Two views, toggled by the chevron and remembered in localStorage:
 *   - Expanded: labeled mini-gauges (GPU util + VRAM, CPU, RAM) plus the
 *     resident model and loaded LLM.
 *   - Collapsed: a single one-line row of tiny status chips (~the height
 *     of the model line), for users who want the readout but not the bulk.
 * Polls GET /api/v1/system-stats every ~2s while mounted (both views);
 * one request at a time, next tick only after the previous settles.
 * Pauses when the tab is hidden.
 */
export function HardwareStatusBar() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const stats = useStore(s => s.systemStats)
  const loadSystemStats = useStore(s => s.loadSystemStats)
  const llmStatus = useStore(s => s.llmStatus)
  const [tabVisible, setTabVisible] = useState(
    () => typeof document === 'undefined' || !document.hidden,
  )

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const toggle = () => setCollapsed(c => {
    const next = !c
    try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0') } catch { /* ignore */ }
    return next
  })

  // Manual model unload (issue #12). Models stay resident between
  // generations by design (instant retry with the same model); this is
  // the explicit opt-out for users who want their VRAM/RAM back now.
  // Two-step: the Power button arms an inline "are you sure" confirm.
  const [confirmUnload, setConfirmUnload] = useState(false)
  const [unloading, setUnloading] = useState(false)
  const [unloadNote, setUnloadNote] = useState<string | null>(null)
  const noteTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(noteTimer.current), [])

  const doUnload = async () => {
    setConfirmUnload(false)
    setUnloading(true)
    try {
      const r = await releaseModels()
      setUnloadNote(r.released.length ? t('hardware.unloaded') : t('hardware.nothing'))
      loadSystemStats()
    } catch (e) {
      setUnloadNote(e instanceof Error ? e.message : t('hardware.unloadFailed'))
    } finally {
      setUnloading(false)
      window.clearTimeout(noteTimer.current)
      noteTimer.current = window.setTimeout(() => setUnloadNote(null), 5000)
    }
  }

  useEffect(() => {
    const onVis = () => setTabVisible(!document.hidden)
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  useSerializedPoll({
    enabled: tabVisible,
    intervalMs: 2000,
    poll: async (signal) => fetchSystemStats(signal),
    onValue: (next) => { useStore.setState({ systemStats: next }) },
  })

  const gpu = stats?.gpu
  const ram = stats?.ram
  const cpu = stats?.cpu
  const model = stats?.model
  // Only treat a model as "current" when it is actually resident in VRAM.
  // On a fresh restart `transformer_type` is seeded from the config's
  // last_model_type (the model from the previous session), so without
  // this gate the bar would show a stale name that isn't loaded.
  const modelLoaded = !!model?.loaded

  const fmtGb = (used?: number, total?: number) =>
    used == null || total == null ? '—' : `${used.toFixed(1)} / ${total.toFixed(0)} GB`
  const fmtG = (v?: number) => (v == null ? '—' : `${v.toFixed(1)}G`)

  // ---- Collapsed: one row of tiny status chips ----------------------
  if (collapsed) {
    return (
      <button
        onClick={toggle}
        title={t('hardware.show')}
        className="w-full flex items-center gap-2.5 px-3 py-1.5 border-t border-border bg-bg-secondary hover:bg-bg-hover transition-colors text-[10px] shrink-0"
      >
        {gpu?.available && (
          <span
            className="flex items-center gap-1 shrink-0 text-text-secondary"
            title={t('hardware.gpuTitle', {
              percent: gpu.percent.toFixed(0),
              compute: gpu.compute_percent != null ? t('hardware.compute', { percent: gpu.compute_percent.toFixed(0) }) : '',
              vram: fmtGb(gpu.vram_used_gb, gpu.vram_total_gb),
            })}
          >
            <Zap size={11} className="text-text-muted" />
            <span className="tabular-nums">{gpu.percent.toFixed(0)}%</span>
            <span className={`tabular-nums ${fullnessText(gpu.vram_percent)}`}>{fmtG(gpu.vram_used_gb)}</span>
          </span>
        )}
        <span className="flex items-center gap-1 shrink-0 text-text-secondary" title={t('hardware.cpuTitle', { percent: (cpu?.percent ?? 0).toFixed(0) })}>
          <Cpu size={11} className="text-text-muted" />
          <span className="tabular-nums">{(cpu?.percent ?? 0).toFixed(0)}%</span>
        </span>
        <span className="flex items-center gap-1 shrink-0 text-text-secondary" title={t('hardware.ramTitle', { vram: fmtGb(ram?.used_gb, ram?.total_gb) })}>
          <MemoryStick size={11} className="text-text-muted" />
          <span className={`tabular-nums ${fullnessText(ram?.percent ?? 0)}`}>{fmtG(ram?.used_gb)}</span>
        </span>
        <span
          className="flex items-center gap-1 min-w-0 ml-auto"
          title={modelLoaded ? t('hardware.modelLoaded', { name: model?.name || t('hardware.unknownModel') }) : t('hardware.noModelLoaded')}
        >
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${modelLoaded ? 'bg-emerald-500' : 'bg-text-muted/40'}`} />
          <span className="truncate text-text-muted">{modelLoaded ? (model?.name || '—') : t('hardware.noModel')}</span>
        </span>
        <ChevronUp size={13} className="shrink-0 text-text-muted" />
      </button>
    )
  }

  // ---- Expanded: full gauges ----------------------------------------
  return (
    <div className="px-3 py-2 border-t border-border bg-bg-secondary shrink-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[9px] uppercase tracking-wider text-text-muted">{t('hardware.system')}</span>
        <button
          onClick={toggle}
          title={t('hardware.collapse')}
          className="p-0.5 rounded hover:bg-bg-hover text-text-muted hover:text-text-secondary transition-colors"
        >
          <ChevronDown size={13} />
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {gpu?.available ? (
          <>
            <Gauge label={t('hardware.gpu')} percent={gpu.percent} value={`${gpu.percent.toFixed(0)}%`} fill="bg-accent-blue"
              title={gpu.compute_percent != null ? t('hardware.engineTitle', { percent: gpu.compute_percent.toFixed(0) }) : undefined} />
            <Gauge
              label={t('hardware.vram')}
              percent={gpu.vram_percent}
              value={fmtGb(gpu.vram_used_gb, gpu.vram_total_gb)}
              fill={fullnessColor(gpu.vram_percent)}
            />
          </>
        ) : (
          <div className="text-[10px] text-text-muted">{t('hardware.noGpu')}</div>
        )}
        <Gauge label={t('hardware.cpu')} percent={cpu?.percent ?? 0} value={`${(cpu?.percent ?? 0).toFixed(0)}%`} fill="bg-accent-blue" />
        <Gauge label={t('hardware.ram')} percent={ram?.percent ?? 0} value={fmtGb(ram?.used_gb, ram?.total_gb)} fill={fullnessColor(ram?.percent ?? 0)} />
      </div>

      {/* Currently-loaded model(s) */}
      <div className="mt-1.5 pt-1.5 border-t border-border/50 flex flex-col gap-0.5">
        <div
          className="flex items-center gap-1.5 min-w-0"
          title={modelLoaded ? t('hardware.resident', { name: model?.name || t('hardware.unknownModel') }) : t('hardware.noGenerationModel')}
        >
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${modelLoaded ? 'bg-emerald-500' : 'bg-text-muted/40'}`} />
          <span className="text-[11px] text-text-secondary truncate">
            {modelLoaded ? (model?.name || t('hardware.unknownModel')) : t('hardware.noModelLoaded')}
          </span>
          {(modelLoaded || llmStatus?.loaded) && !confirmUnload && !unloading && (
            <button
              onClick={() => setConfirmUnload(true)}
              title={t('hardware.unloadTitle')}
              className="ml-auto p-0.5 rounded shrink-0 text-text-muted hover:text-text-secondary hover:bg-bg-hover transition-colors"
            >
              <Power size={11} />
            </button>
          )}
        </div>
        {llmStatus?.loaded && llmStatus.model_id && (
          <div className="flex items-center gap-1.5 min-w-0" title={t('hardware.llmTitle')}>
            <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-accent-blue" />
            <span className="text-[10px] text-text-muted truncate">{t('hardware.llmLine', { id: llmStatus.model_id })}</span>
          </div>
        )}
        {confirmUnload && (
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="text-text-secondary">{t('hardware.confirm')}</span>
            <button
              onClick={doUnload}
              className="px-1.5 py-0.5 rounded bg-red-500/15 text-chip-red hover:bg-red-500/25 transition-colors"
            >
              {t('hardware.unload')}
            </button>
            <button
              onClick={() => setConfirmUnload(false)}
              className="px-1.5 py-0.5 rounded text-text-muted hover:bg-bg-hover transition-colors"
            >
              {tCommon('actions.cancel')}
            </button>
          </div>
        )}
        {unloading && <div className="text-[10px] text-text-muted">{t('hardware.unloading')}</div>}
        {unloadNote && !unloading && <div className="text-[10px] text-text-muted">{unloadNote}</div>}
      </div>
    </div>
  )
}
