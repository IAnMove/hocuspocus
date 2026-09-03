import { useState, useCallback, useRef, useMemo } from 'react'
import { Upload, Loader2, Music, Zap, RotateCcw, X, ChevronRight, ChevronDown, ImageIcon, Play } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { DirectorClipImagePreview } from './DirectorClipImagePreview'
import { useObjectUrl } from '../../lib/useObjectUrl'
import { useUiTranslation } from '../../i18n'
import { SpokenLanguageOptions } from '../../i18n/SpokenLanguageOptions'

const AUDIO_ACCEPT = '.wav,.mp3,.flac,.ogg,.m4a'
const IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp,.bmp'

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

const sectionColors: Record<string, string> = {
  intro: 'bg-blue-500/20 text-chip-blue',
  verse: 'bg-green-500/20 text-chip-green',
  'pre-chorus': 'bg-pink-500/20 text-chip-pink',
  chorus: 'bg-purple-500/20 text-chip-purple',
  bridge: 'bg-yellow-500/20 text-chip-yellow',
  outro: 'bg-gray-500/20 text-chip-gray',
  instrumental: 'bg-cyan-500/20 text-chip-cyan',
}

const sectionBarColors: Record<string, string> = {
  intro: 'bg-blue-500',
  verse: 'bg-green-500',
  'pre-chorus': 'bg-pink-500',
  chorus: 'bg-purple-500',
  bridge: 'bg-yellow-500',
  outro: 'bg-gray-500',
  instrumental: 'bg-cyan-500',
}

function SectionBadge({ label }: { label: string }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${sectionColors[label] || 'bg-bg-hover text-text-muted'}`}>
      {label}
    </span>
  )
}

function EnergyDot({ energy }: { energy: number }) {
  const { t } = useUiTranslation('director')
  const color = energy > 0.6 ? 'bg-chip-red' : energy < 0.3 ? 'bg-chip-blue' : 'bg-chip-yellow'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} title={t('panel.energy', { percent: (energy * 100).toFixed(0) })} />
}

function imageStatusLabel(
  status: string | undefined,
  t: (key: 'panel.imageStatus.generating' | 'panel.imageStatus.polling' | 'panel.imageStatus.downloading' | 'panel.imageStatus.processing') => string,
): string {
  if (status === 'generating') return t('panel.imageStatus.generating')
  if (status === 'polling') return t('panel.imageStatus.polling')
  if (status === 'downloading') return t('panel.imageStatus.downloading')
  return t('panel.imageStatus.processing')
}

export function DirectorPanel() {
  const { t } = useUiTranslation('director')
  const { t: tCommon } = useUiTranslation('common')
  const step = useStore(s => s.directorStep)
  const loading = useStore(s => s.directorLoading)
  // See DirectorChat.tsx for full rationale — sub-status set by the
  // polling loop in director*UploadAndAnalyze.
  const loadingMessage = useStore(s => s.directorLoadingMessage)
  const error = useStore(s => s.directorError)
  const analysis = useStore(s => s.directorAnalysis)
  const plannedClips = useStore(s => s.directorPlannedClips)
  const energyBias = useStore(s => s.directorEnergyBias)
  const clipPlans = useStore(s => s.directorClipPlans)
  const sceneDescription = useStore(s => s.directorSceneDescription)
  const spokenLanguage = useStore(s => s.directorSpokenLanguage)
  const setSpokenLanguage = useStore(s => s.setDirectorSpokenLanguage)
  const audioFile = useStore(s => s.directorAudioFile)
  const referenceImage = useStore(s => s.directorReferenceImage)
  const clipImages = useStore(s => s.directorClipImages)
  const imageGenProgress = useStore(s => s.directorImageGenProgress)
  const uploadAndAnalyze = useStore(s => s.directorUploadAndAnalyze)
  const setEnergyBias = useStore(s => s.directorSetEnergyBias)
  const confirmStructure = useStore(s => s.directorConfirmStructure)
  const setSceneDescription = useStore(s => s.directorSetSceneDescription)
  const setReferenceImage = useStore(s => s.directorSetReferenceImage)
  const planPrompts = useStore(s => s.directorPlanPrompts)
  const planVideoPrompts = useStore(s => s.directorPlanVideoPrompts)
  const generateStartImages = useStore(s => s.directorGenerateStartImages)
  const applyToClips = useStore(s => s.directorApplyToClips)
  const directorGenerate = useStore(s => s.directorGenerate)
  const editClipPlan = useStore(s => s.directorEditClipPlan)
  const reset = useStore(s => s.directorReset)
  const speakers = useStore(s => s.directorSpeakers)
  const speakerMappings = useStore(s => s.directorSpeakerMappings)
  const setSpeakerMapping = useStore(s => s.directorSetSpeakerMapping)
  const insertSpeakerMention = useStore(s => s.directorInsertSpeakerMention)
  const autoMode = useStore(s => s.directorAutoMode)
  const setAutoMode = useStore(s => s.setDirectorAutoMode)

  const refImagePreview = useObjectUrl(referenceImage)

  // Sample lyrics per speaker for identification
  const speakerSamples = useMemo(() => {
    const samples: Record<string, string[]> = {}
    if (analysis?.lyrics) {
      for (const seg of analysis.lyrics) {
        if (seg.speaker && !samples[seg.speaker]) {
          samples[seg.speaker] = []
        }
        if (seg.speaker && samples[seg.speaker].length < 2) {
          samples[seg.speaker].push(seg.text)
        }
      }
    }
    return samples
  }, [analysis])

  const [dragOver, setDragOver] = useState(false)
  const [localBias, setLocalBias] = useState<number | null>(null)
  const [showAnalysisDetails, setShowAnalysisDetails] = useState(false)
  const sliderRef = useRef<number | null>(null)

  const handleFile = useCallback((file: File) => {
    if (!file.type.startsWith('audio/') && !AUDIO_ACCEPT.split(',').some(ext => file.name.toLowerCase().endsWith(ext))) {
      return
    }
    uploadAndAnalyze(file)
  }, [uploadAndAnalyze])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  // Compute total duration from planned clips
  const totalClipDuration = useMemo(
    () => plannedClips.length > 0 ? plannedClips[plannedClips.length - 1].end : 0,
    [plannedClips]
  )

  // Beat count distribution summary
  const beatDistribution = useMemo(() => {
    const counts: Record<number, number> = {}
    for (const c of plannedClips) {
      counts[c.beat_count] = (counts[c.beat_count] || 0) + 1
    }
    return Object.entries(counts)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([beats, count]) => t('panel.beatDistribution', { count: Number(count), beats }))
      .join(', ')
  }, [plannedClips, t])

  return (
    <div className="bg-bg-tertiary/50 border border-accent-blue/30 rounded-lg p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Music size={14} className="text-accent-blue" />
          <span className="text-xs font-medium text-text-primary">{t('panel.title')}</span>
          {analysis && (
            <span className="text-[10px] text-text-muted">
              {t('panel.bpm', { bpm: analysis.bpm.toFixed(0) })}
            </span>
          )}
        </div>
        {step !== 'upload' && (
          <button
            onClick={reset}
            className="text-[10px] text-text-muted hover:text-text-primary flex items-center gap-0.5 transition-colors"
            title={t('panel.startOverTitle')}
          >
            <RotateCcw size={10} /> {t('panel.startOver')}
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="text-[11px] text-red-400 bg-red-500/10 rounded px-2 py-1.5">
          {error}
        </div>
      )}

      {/* Step 1: Upload */}
      {(step === 'upload' || step === 'analyze') && (
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
            dragOver ? 'border-accent-blue bg-accent-blue/10' : 'border-border hover:border-border-light'
          }`}
        >
          {loading ? (
            <div className="flex flex-col items-center gap-2 py-2">
              <Loader2 size={20} className="animate-spin text-accent-blue" />
              <span className="text-[11px] text-text-muted text-center px-2">
                {loadingMessage || t('panel.analyzing')}
              </span>
            </div>
          ) : audioFile ? (
            <div className="flex flex-col items-center gap-1">
              <Music size={16} className="text-text-muted" />
              <span className="text-xs text-text-secondary truncate max-w-full">{audioFile.name}</span>
            </div>
          ) : (
            <label className="cursor-pointer flex flex-col items-center gap-1.5">
              <Upload size={18} className="text-text-muted" />
              <span className="text-xs text-text-muted">{t('panel.dropSong')}</span>
              <span className="text-[10px] text-text-muted">{t('panel.audioFormats')}</span>
              <input
                type="file"
                accept={AUDIO_ACCEPT}
                className="hidden"
                onChange={e => {
                  const file = e.target.files?.[0]
                  if (file) handleFile(file)
                }}
              />
            </label>
          )}
        </div>
      )}

      {/* Analysis summary (shown as context once past upload) */}
      {analysis && step !== 'upload' && step !== 'analyze' && (
        <div className="space-y-1">
          <button
            onClick={() => setShowAnalysisDetails(v => !v)}
            className="flex items-center gap-3 text-[11px] text-text-muted w-full hover:text-text-secondary transition-colors"
          >
            <ChevronDown size={10} className={`transition-transform ${showAnalysisDetails ? '' : '-rotate-90'}`} />
            <span>{formatTime(analysis.duration)}</span>
            <span>{t('panel.bpm', { bpm: analysis.bpm.toFixed(0) })}</span>
            <span>{t('panel.sectionsCount', { count: analysis.sections.length })}</span>
            {analysis.lyrics && <span>{t('panel.lyricSegments', { count: analysis.lyrics.length })}</span>}
          </button>

          {showAnalysisDetails && (
            <div className="bg-bg-tertiary rounded-lg p-2 space-y-2 max-h-[250px] overflow-y-auto text-[10px]">
              {/* Sections */}
              <div>
                <div className="text-text-muted uppercase tracking-wider mb-1 font-medium">{t('panel.sections')}</div>
                <div className="space-y-0.5">
                  {analysis.sections.map((sec, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-text-muted w-16 shrink-0">
                        {formatTime(sec.start)}-{formatTime(sec.end)}
                      </span>
                      <SectionBadge label={sec.label} />
                      <EnergyDot energy={sec.energy} />
                      <span className="text-text-muted">{(sec.energy * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Lyrics — grouped by song structure if available */}
              {analysis.lyrics && analysis.lyrics.length > 0 && (
                <div>
                  <div className="text-text-muted uppercase tracking-wider mb-1 font-medium">
                    {t('panel.lyrics')} {analysis.song_structure?.length ? t('panel.lyricsLlm') : t('panel.lyricsWhisper')}
                  </div>
                  <div className="space-y-0.5">
                    {analysis.song_structure && analysis.song_structure.length > 0 ? (
                      // Show lyrics grouped under LLM-identified section headers
                      analysis.song_structure.map((section, si) => {
                        const nextStart = si < analysis.song_structure!.length - 1
                          ? analysis.song_structure![si + 1].start
                          : Infinity
                        const sectionLyrics = analysis.lyrics!.filter(
                          seg => seg.start >= section.start && seg.start < nextStart
                        )
                        return (
                          <div key={si} className="mb-1.5">
                            <div className="flex items-center gap-1.5 mb-0.5">
                              <SectionBadge label={section.label} />
                              <span className="text-text-muted">{formatTime(section.start)}</span>
                              <span className="text-text-secondary font-medium">[{section.display_label}]</span>
                            </div>
                            {sectionLyrics.map((seg, li) => (
                              <div key={li} className="flex gap-2 pl-2">
                                <span className="text-text-muted w-14 shrink-0 text-right">
                                  {formatTime(seg.start)}
                                </span>
                                <span className="text-text-secondary">
                                  {seg.speaker && (
                                    <span className="text-accent-blue text-[9px] mr-1">[{seg.speaker}]</span>
                                  )}
                                  {seg.text}
                                </span>
                              </div>
                            ))}
                            {sectionLyrics.length === 0 && (
                              <div className="pl-2 text-text-muted italic">{t('panel.instrumental')}</div>
                            )}
                          </div>
                        )
                      })
                    ) : (
                      // Fallback: flat transcript
                      analysis.lyrics.map((seg, i) => (
                        <div key={i} className="flex gap-2">
                          <span className="text-text-muted w-16 shrink-0">
                            {formatTime(seg.start)}-{formatTime(seg.end)}
                          </span>
                          <span className="text-text-secondary">
                            {seg.speaker && (
                              <span className="text-accent-blue text-[9px] mr-1">[{seg.speaker}]</span>
                            )}
                            {seg.text}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Clip Structure (beat-aligned) */}
      {step === 'structure' && (
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('panel.cutSpeed')}</label>
              <span className="text-xs text-text-secondary">
                {(localBias ?? energyBias) > 0 ? '+' : ''}{localBias ?? energyBias}
              </span>
            </div>
            <input
              type="range"
              min={-2}
              max={2}
              step={1}
              value={localBias ?? energyBias}
              onChange={e => {
                const v = Number(e.target.value)
                setLocalBias(v)
                sliderRef.current = v
              }}
              onMouseUp={() => {
                if (sliderRef.current !== null && sliderRef.current !== energyBias) {
                  setEnergyBias(sliderRef.current)
                }
                setLocalBias(null)
                sliderRef.current = null
              }}
              onTouchEnd={() => {
                if (sliderRef.current !== null && sliderRef.current !== energyBias) {
                  setEnergyBias(sliderRef.current)
                }
                setLocalBias(null)
                sliderRef.current = null
              }}
              className="w-full"
            />
            <div className="flex items-center justify-between mt-1 text-[10px] text-text-muted">
              <span>{t('panel.slowerCuts')}</span>
              <span>{t('panel.fasterCuts')}</span>
            </div>
          </div>

          {/* Clip structure visualization */}
          <div className="bg-bg-tertiary rounded-lg p-2 space-y-2">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-text-secondary font-medium">{t('panel.clipsCount', { count: plannedClips.length })}</span>
              <span className="text-text-muted">{t('panel.totalTime', { time: formatTime(totalClipDuration) })}</span>
            </div>

            {loading ? (
              <div className="flex items-center gap-1.5 text-[10px] text-text-muted py-1">
                <Loader2 size={10} className="animate-spin" /> {t('panel.recalculating')}
              </div>
            ) : (
              <>
                {/* Proportional bar chart */}
                <div className="flex gap-px h-8 rounded overflow-hidden">
                  {plannedClips.map((clip, i) => {
                    const widthPct = Math.max((clip.beat_count / plannedClips.reduce((s, c) => s + c.beat_count, 0)) * 100, 1.5)
                    const barColor = sectionBarColors[clip.section_label] || 'bg-gray-500'
                    return (
                      <div
                        key={i}
                        className={`${barColor} opacity-70 hover:opacity-100 transition-opacity relative group cursor-default`}
                        style={{ width: `${widthPct}%` }}
                        title={t('panel.clipTooltip', { n: i + 1, section: clip.section_label, beats: clip.beat_count, seconds: (clip.end - clip.start).toFixed(1) })}
                      >
                        {/* Tooltip on hover */}
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 pointer-events-none">
                          <div className="bg-bg-primary border border-border rounded px-1.5 py-1 text-[9px] text-text-secondary whitespace-nowrap shadow-lg">
                            {t('panel.clipTooltip', { n: i + 1, section: clip.section_label, beats: clip.beat_count, seconds: (clip.end - clip.start).toFixed(1) })}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Beat distribution and section legend */}
                <div className="text-[9px] text-text-muted space-y-1">
                  <div>{beatDistribution}</div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                    {Object.entries(sectionBarColors).map(([label, color]) => {
                      const count = plannedClips.filter(c => c.section_label === label).length
                      if (count === 0) return null
                      return (
                        <div key={label} className="flex items-center gap-1">
                          <span className={`w-2 h-2 rounded-sm ${color}`} />
                          <span>{t('panel.sectionCount', { label, count })}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          <button
            onClick={confirmStructure}
            disabled={loading || plannedClips.length === 0}
            className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
          >
            <ChevronRight size={12} /> {t('panel.continue')}
          </button>
        </div>
      )}

      {/* Step 3: Scene description + Reference image */}
      {step === 'style' && (
        <div className="space-y-2">
          <label className="block">
            <span className="text-[11px] text-text-muted uppercase tracking-wider">{t('spoken.label')}</span>
            <select className="mt-1 w-full rounded-lg border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary" value={spokenLanguage} onChange={event => setSpokenLanguage(event.target.value)}>
              <SpokenLanguageOptions />
            </select>
          </label>
          {/* Auto-mode checkbox */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoMode}
              onChange={e => setAutoMode(e.target.checked)}
              className="accent-red-500"
            />
            <span className="text-[11px] text-red-400 font-medium">{t('panel.autoMode')}</span>
          </label>
          {autoMode && (
            <p className="text-[10px] text-red-400/70 -mt-1">
              {t('panel.autoModeHint')}
            </p>
          )}

          {/* Reference image upload */}
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider block mb-1">{t('panel.referencePhoto')}</label>
            {referenceImage && refImagePreview ? (
              <div className="relative inline-block">
                <img
                  src={refImagePreview}
                  alt={t('panel.referenceAlt')}
                  className="w-20 h-20 object-cover rounded-lg border border-border"
                />
                <button
                  onClick={() => setReferenceImage(null)}
                  className="absolute -top-1 -right-1 bg-bg-secondary rounded-full p-0.5 border border-border hover:bg-bg-hover"
                >
                  <X size={10} />
                </button>
              </div>
            ) : (
              <label className="cursor-pointer flex items-center gap-2 border border-dashed border-border rounded-lg px-3 py-2 hover:border-border-light transition-colors">
                <ImageIcon size={14} className="text-text-muted" />
                <span className="text-xs text-text-muted">{t('panel.uploadReference')}</span>
                <input
                  type="file"
                  accept={IMAGE_ACCEPT}
                  className="hidden"
                  onChange={e => {
                    const file = e.target.files?.[0]
                    if (file) setReferenceImage(file)
                  }}
                />
              </label>
            )}
            <span className="text-[10px] text-text-muted mt-0.5 block">
              {t('panel.referenceHint')}
            </span>
          </div>

          {/* Speaker Mapping — shown when diarization found 2+ speakers */}
          {speakers.length >= 1 && (
            <div>
              <label className="text-[11px] text-text-muted uppercase tracking-wider block mb-1">{t('panel.speakersDetected')}</label>
              <div className="space-y-2">
                {speakerMappings.map((mapping) => (
                  <div key={mapping.speakerId} className="bg-bg-tertiary rounded-lg p-2 space-y-1">
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => insertSpeakerMention(mapping.speakerId)}
                        className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 shrink-0 transition-colors"
                        title={t('panel.insertSpeaker', { id: mapping.speakerId })}
                      >
                        {mapping.speakerId}
                      </button>
                      <input
                        type="text"
                        value={mapping.name}
                        onChange={e => setSpeakerMapping(mapping.speakerId, e.target.value, mapping.role)}
                        placeholder={t('panel.speakerPlaceholder')}
                        className="flex-1 bg-bg-secondary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
                      />
                      <select
                        value={mapping.role}
                        onChange={e => setSpeakerMapping(mapping.speakerId, mapping.name, e.target.value as typeof mapping.role)}
                        className="bg-bg-secondary border border-border rounded px-1.5 py-1 text-[10px] text-text-secondary focus:outline-none focus:border-accent-blue transition-colors"
                      >
                        <option value="">{t('panel.role')}</option>
                        <option value="rapping">{t('panel.rapping')}</option>
                        <option value="singing">{t('panel.singing')}</option>
                        <option value="speaking">{t('panel.speaking')}</option>
                      </select>
                    </div>
                    {/* Sample lyrics for identification */}
                    {speakerSamples[mapping.speakerId] && (
                      <div className="text-[9px] text-text-muted pl-1 italic">
                        {speakerSamples[mapping.speakerId].map((line, li) => (
                          <div key={li} className="truncate">&ldquo;{line}&rdquo;</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">
                {t('panel.speakersHint')}
              </span>
            </div>
          )}

          <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('panel.sceneCharacters')}</label>
          <textarea
            value={sceneDescription}
            onChange={e => setSceneDescription(e.target.value)}
            placeholder={speakers.length >= 2
              ? t('panel.scenePlaceholderMulti')
              : t('panel.scenePlaceholder')
            }
            rows={3}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none focus:border-accent-blue transition-colors"
          />
          <button
            onClick={planPrompts}
            disabled={!sceneDescription.trim() || loading}
            className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> {t('panel.planningShots')}</>
            ) : (
              <><Zap size={12} /> {t('panel.planShots')}</>
            )}
          </button>
        </div>
      )}

      {/* Step 4: Review image prompts (phase 1) */}
      {step === 'review' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('panel.startImagePrompts')}</label>
            <button
              onClick={planPrompts}
              disabled={loading}
              className="text-[10px] text-accent-blue hover:text-accent-blue-hover flex items-center gap-0.5"
            >
              <RotateCcw size={10} /> {t('panel.regenerate')}
            </button>
          </div>

          <div className="space-y-2 max-h-[350px] overflow-y-auto pr-1">
            {clipPlans.map((plan, i) => {
              const clip = plannedClips[i]
              return (
                <div key={i} className="bg-bg-tertiary rounded-lg p-2 space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                    <span className="font-medium text-text-secondary">{t('panel.clipN', { n: i + 1 })}</span>
                    {clip && (
                      <>
                        <span>{formatTime(clip.start)}-{formatTime(clip.end)}</span>
                        <span>{t('panel.beatsShort', { count: clip.beat_count })}</span>
                        <SectionBadge label={clip.section_label} />
                        <EnergyDot energy={clip.energy} />
                        {clip.dominant_speaker && (
                          <span className="text-accent-blue">
                            {speakerMappings.find(m => m.speakerId === clip.dominant_speaker)?.name || clip.dominant_speaker}
                          </span>
                        )}
                      </>
                    )}
                  </div>
                  <textarea
                    value={plan.image_prompt}
                    onChange={e => editClipPlan(i, 'image_prompt', e.target.value)}
                    rows={2}
                    className="w-full bg-bg-secondary border border-border rounded px-2 py-1.5 text-xs text-text-primary resize-none focus:outline-none focus:border-accent-blue transition-colors"
                  />
                </div>
              )
            })}
          </div>

          {referenceImage ? (
            <button
              onClick={generateStartImages}
              className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors flex items-center justify-center gap-1.5"
            >
              <ImageIcon size={12} /> {t('panel.generateStartImages')}
            </button>
          ) : (
            <button
              onClick={() => { planVideoPrompts() }}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors flex items-center justify-center gap-1.5"
            >
              <ChevronRight size={12} /> {t('panel.planVideoShots')}
            </button>
          )}
        </div>
      )}

      {/* Step 5: Generate per-clip start images */}
      {step === 'generate_images' && (
        <div className="space-y-3">
          <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('panel.generatingStartImages')}</label>

          {/* Progress */}
          {imageGenProgress && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-secondary">
                  {imageGenProgress.status === 'done'
                    ? t('panel.allImagesReady')
                    : t('panel.clipOf', { current: imageGenProgress.current + 1, total: imageGenProgress.total })}
                </span>
                <span className="text-text-muted">
                  {imageGenProgress.currentClipLabel}
                  {imageGenProgress.status !== 'done' && ` — ${imageStatusLabel(imageGenProgress.status, t)}`}
                </span>
              </div>
              <div className="w-full bg-bg-tertiary rounded-full h-1.5">
                <div
                  className="bg-accent-blue h-1.5 rounded-full transition-all"
                  style={{
                    width: `${imageGenProgress.status === 'done'
                      ? 100
                      : ((imageGenProgress.current + (imageGenProgress.status === 'polling' ? 0.5 : 0)) / imageGenProgress.total) * 100
                    }%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Loading spinner while generating */}
          {loading && (
            <div className="flex items-center justify-center gap-2 py-2">
              <Loader2 size={16} className="animate-spin text-accent-blue" />
              <span className="text-[11px] text-text-muted">
                {imageStatusLabel(imageGenProgress?.status, t)}
              </span>
            </div>
          )}

          {/* Clip image thumbnails (3-column grid) */}
          {clipImages.length > 0 && (
            <div className="grid grid-cols-3 gap-1.5 max-h-[300px] overflow-y-auto">
              {clipImages.map((img, i) => (
                <div key={i} className="relative">
                  <DirectorClipImagePreview
                    image={img}
                    alt={t('panel.clipN', { n: img.clipIndex + 1 })}
                    className="w-full aspect-square object-cover rounded-lg border border-border"
                  />
                  <span className="absolute bottom-0.5 left-0.5 text-[8px] bg-black/60 text-white px-1 py-0.5 rounded">
                    {img.clipIndex + 1}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Error recovery: let user retry video planning */}
          {!loading && imageGenProgress?.status === 'error' && (
            <button
              onClick={() => { planVideoPrompts() }}
              className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors flex items-center justify-center gap-1.5"
            >
              <RotateCcw size={12} /> {t('panel.retryVideoPlanning')}
            </button>
          )}
        </div>
      )}

      {/* Step 6: Review video prompts (phase 2) */}
      {step === 'review_video' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('panel.videoPrompts')}</label>
            <button
              onClick={planVideoPrompts}
              disabled={loading}
              className="text-[10px] text-accent-blue hover:text-accent-blue-hover flex items-center gap-0.5"
            >
              <RotateCcw size={10} /> {t('panel.regenerate')}
            </button>
          </div>

          {/* Generated images preview */}
          {clipImages.length > 0 && (
            <div className="grid grid-cols-5 gap-1 mb-1">
              {clipImages.map((img, i) => (
                <div key={i} className="relative">
                  <DirectorClipImagePreview
                    image={img}
                    alt={t('panel.clipN', { n: img.clipIndex + 1 })}
                    className="w-full aspect-square object-cover rounded border border-border"
                  />
                  <span className="absolute bottom-0 left-0 text-[7px] bg-black/60 text-white px-0.5 rounded-br">
                    {img.clipIndex + 1}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
            {clipPlans.map((plan, i) => {
              const clip = plannedClips[i]
              return (
                <div key={i} className="bg-bg-tertiary rounded-lg p-2 space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                    <span className="font-medium text-text-secondary">{t('panel.clipN', { n: i + 1 })}</span>
                    {clip && (
                      <>
                        <span>{formatTime(clip.start)}-{formatTime(clip.end)}</span>
                        <SectionBadge label={clip.section_label} />
                        {clip.dominant_speaker && (
                          <span className="text-accent-blue">
                            {speakerMappings.find(m => m.speakerId === clip.dominant_speaker)?.name || clip.dominant_speaker}
                          </span>
                        )}
                      </>
                    )}
                  </div>
                  <textarea
                    value={plan.video_prompt}
                    onChange={e => editClipPlan(i, 'video_prompt', e.target.value)}
                    rows={2}
                    className="w-full bg-bg-secondary border border-border rounded px-2 py-1.5 text-xs text-text-primary resize-none focus:outline-none focus:border-accent-blue transition-colors"
                  />
                </div>
              )
            })}
          </div>

          <div className="space-y-2">
            <button
              onClick={directorGenerate}
              className="w-full py-2.5 rounded-lg bg-accent-green hover:bg-accent-green-hover text-white text-sm font-semibold transition-colors flex items-center justify-center gap-1.5"
            >
              <Play size={14} fill="white" /> {tCommon('actions.generate')}
            </button>
            <button
              onClick={applyToClips}
              className="w-full py-2 rounded-lg border border-border text-text-secondary text-xs font-medium hover:bg-bg-hover hover:text-text-primary transition-colors flex items-center justify-center gap-1.5"
            >
              <ChevronRight size={12} /> {t('panel.editInStudio')}
            </button>
          </div>
        </div>
      )}

      {/* Loading overlay for plan steps */}
      {step === 'plan' && loading && (
        <div className="flex flex-col items-center gap-2 py-4">
          <Loader2 size={20} className="animate-spin text-accent-blue" />
          <span className="text-[11px] text-text-muted">{t('panel.writingImagePrompts')}</span>
        </div>
      )}
      {step === 'plan_video' && loading && (
        <div className="flex flex-col items-center gap-2 py-4">
          <Loader2 size={20} className="animate-spin text-accent-blue" />
          <span className="text-[11px] text-text-muted">{t('panel.writingVideoPrompts')}</span>
        </div>
      )}
    </div>
  )
}
