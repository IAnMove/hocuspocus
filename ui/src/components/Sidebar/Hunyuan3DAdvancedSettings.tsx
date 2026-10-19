import { useState } from 'react'
import { ChevronDown, Layers3 } from 'lucide-react'
import type { Hunyuan3DCapabilities, Hunyuan3DModel } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'

type Props = {
  external3d: boolean
  textureMode: string
  setTextureMode: (value: string) => void
  outputFormat: string
  setOutputFormat: (value: string) => void
  operation: string
  capabilities: Hunyuan3DCapabilities | null
  selectedModel: Hunyuan3DModel | undefined
  steps: number
  setSteps: (value: number) => void
  guidance: number
  setGuidance: (value: number) => void
  octree: number
  setOctree: (value: number) => void
  chunks: number
  setChunks: (value: number) => void
  seed: number
  setSeed: (value: number) => void
  mcAlgo: string
  setMcAlgo: (value: string) => void
  textureResolution: number
  setTextureResolution: (value: number) => void
  reduceFace: boolean
  setReduceFace: (value: boolean) => void
  targetFaces: number
  setTargetFaces: (value: number) => void
  cpuOffload: boolean
  setCpuOffload: (value: boolean) => void
  flashvdm: boolean
  setFlashvdm: (value: boolean) => void
  removeBackground: boolean
  setRemoveBackground: (value: boolean) => void
  compile: boolean
  setCompile: (value: boolean) => void
}

// Hunyuan-only controls remain visible but inert for other engines.
export function Hunyuan3DAdvancedSettings({
  external3d, textureMode, setTextureMode, outputFormat, setOutputFormat, operation, capabilities, selectedModel, steps, setSteps, guidance, setGuidance, octree, setOctree, chunks, setChunks, seed, setSeed, mcAlgo, setMcAlgo, textureResolution, setTextureResolution, reduceFace, setReduceFace, targetFaces, setTargetFaces, cpuOffload, setCpuOffload, flashvdm, setFlashvdm, removeBackground, setRemoveBackground, compile, setCompile,
}: Props) {
  const { t } = useUiTranslation('scene3d')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  return <>
          <button onClick={() => setAdvancedOpen(value => !value)} className="flex items-center justify-between w-full rounded-lg bg-bg-tertiary border border-border px-3 py-2 text-[11px] text-text-secondary hover:text-text-primary">
            <span className="flex items-center gap-1.5"><Layers3 size={12} /> {t('hunyuan.advanced')}</span>
            <ChevronDown size={13} className={`transition-transform ${advancedOpen ? 'rotate-180' : ''}`} />
          </button>

          {advancedOpen && (
            <fieldset disabled={external3d} className="rounded-lg border border-border bg-bg-tertiary p-3 space-y-3 disabled:opacity-40">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[10px] text-text-muted">{t('hunyuan.texture')}
                  <select value={textureMode} onChange={event => setTextureMode(event.target.value)} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary">
                    {(capabilities?.texture_modes || []).filter(mode => mode.id !== 'pbr' || selectedModel?.engine === 'v21').map(mode => <option key={mode.id} value={mode.id}>{mode.label}</option>)}
                  </select>
                </label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.output')}
                  <select value={outputFormat} disabled={operation === 'retexture'} onChange={event => setOutputFormat(event.target.value)} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary disabled:opacity-60">
                    {(capabilities?.output_formats || ['glb']).map(format => <option key={format} value={format} disabled={textureMode === 'pbr' && format !== 'glb'}>{format.toUpperCase()}{textureMode === 'pbr' && format !== 'glb' ? t('hunyuan.pbrRequiresGlb') : ''}</option>)}
                  </select>
                </label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.steps')}<input type="number" min={1} max={100} value={steps} onChange={event => setSteps(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary" /></label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.guidance')}<input type="number" min={0} max={30} step={0.1} value={guidance} onChange={event => setGuidance(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary" /></label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.octree')}
                  <select value={octree} onChange={event => setOctree(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary">{[64, 128, 256, 384, 512].map(value => <option key={value} value={value}>{value}</option>)}</select>
                </label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.chunks')}<input type="number" min={1000} max={40000} step={1000} value={chunks} onChange={event => setChunks(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary" /></label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.seed')}<input type="number" min={-1} value={seed} title={t('hunyuan.seedRandom')} onChange={event => setSeed(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary" /></label>
                <label className="text-[10px] text-text-muted">{t('hunyuan.surface')}<select value={mcAlgo} onChange={event => setMcAlgo(event.target.value)} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary"><option value="dmc">{t('hunyuan.dmc')}</option><option value="mc">{t('hunyuan.marchingCubes')}</option></select></label>
                {textureMode !== 'none' && <label className="text-[10px] text-text-muted">{t('hunyuan.textureResolution')}<select value={textureResolution} onChange={event => setTextureResolution(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary"><option value={512}>512</option><option value={768}>768</option><option value={1024}>1024</option></select></label>}
                {reduceFace && <label className="text-[10px] text-text-muted">{t('hunyuan.targetFaces')}<input type="number" min={100} max={1000000} step={1000} value={targetFaces} onChange={event => setTargetFaces(Number(event.target.value))} className="mt-1 w-full bg-bg-primary border border-border rounded px-2 py-1.5 text-[11px] text-text-primary" /></label>}
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[10px] text-text-secondary">
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={cpuOffload} onChange={event => setCpuOffload(event.target.checked)} /> {t('hunyuan.cpuOffload')}</label>
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={flashvdm} onChange={event => setFlashvdm(event.target.checked)} /> {t('hunyuan.flashvdm')}</label>
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={removeBackground} onChange={event => setRemoveBackground(event.target.checked)} /> {t('hunyuan.removeBackground')}</label>
                <label className="flex items-center gap-1.5" title={t('hunyuan.compileTitle')}><input type="checkbox" checked={compile} onChange={event => setCompile(event.target.checked)} /> {t('hunyuan.torchCompile')}</label>
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={reduceFace} onChange={event => setReduceFace(event.target.checked)} /> {t('hunyuan.simplifyMesh')}</label>
              </div>
              <p className="text-[9px] text-text-muted">{t('hunyuan.advancedHelp')}</p>
            </fieldset>
          )}
  </>
}
