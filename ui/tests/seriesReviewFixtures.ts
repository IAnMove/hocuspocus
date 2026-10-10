import type { SeriesEpisode, SeriesProject, SeriesRenderAttempt, SeriesShot } from '../src/features/series/types'

export function take(id: string, extra: Partial<SeriesRenderAttempt> = {}): SeriesRenderAttempt {
  return { id, status: 'completed', prompt: '', negativePrompt: '', model: 'animation_2d', referenceManifest: {} as never, seed: null, settings: {},
    startTimeSeconds: 0, endTimeSeconds: 2, createdAt: '2026-10-06T10:00:00Z', elapsedMs: 0, outputAssetIds: [`asset-${id}`], retryCount: 0, ...extra }
}

export function shot(id: string, order: number, extra: Partial<SeriesShot> = {}): SeriesShot {
  return {
    id, sceneId: 'scene-1', order, durationSeconds: 2.5, framing: 'medium', camera: 'static', action: '', dialogueBeats: [],
    visibleCharacterIds: ['ines'], speakingCharacterIds: [], wardrobeByCharacterId: {}, propIds: [], emotionalStateByCharacterId: {},
    renderStrategy: 'auto', productionMethod: 'animation_2d',
    referencePolicy: { mode: 'automatic', manualIncludeAssetIds: [], manualExcludeAssetIds: [] }, prompt: '', negativePrompt: '', attempts: [],
    ...extra,
  }
}

export function episode(shots: SeriesShot[], review?: SeriesEpisode['review']): SeriesEpisode {
  return {
    id: 'ep1', seasonId: 'season-1', number: 1, title: 'La confesión', premise: '', logline: '', targetDurationSeconds: 60, status: 'shot_plan',
    canonRevisionAtCreation: 1, canonSnapshot: { revision: 1 }, outline: { beats: [] },
    script: [
      { id: 'scene-1', order: 1, locationId: 'nave', time: 'noche', participatingCharacterIds: [], purpose: 'La confesión', entryState: '', exitState: '', beats: [], dialogue: [] },
      { id: 'scene-2', order: 2, locationId: 'puerto', time: '', participatingCharacterIds: [], purpose: '', entryState: '', exitState: '', beats: [], dialogue: [] },
    ],
    shots, proposedCanonDelta: { baseRevision: 1, sourceEpisodeId: 'ep1', add: [], change: [], retire: [] }, productionIds: [],
    createdAt: '2026-10-06T09:00:00Z', updatedAt: '2026-10-06T09:00:00Z', ...(review ? { review } : {}),
  }
}

export function series(ep: SeriesEpisode): SeriesProject {
  const assets: SeriesProject['assets'] = {}
  for (const item of ep.shots) for (const attempt of item.attempts) for (const assetId of attempt.outputAssetIds) {
    assets[assetId] = { id: assetId, workspaceId: 'plus-ultra', kind: 'video', uri: `assets/mp-es/${assetId}.mp4`, ownerType: 'attempt', ownerId: attempt.id,
      isDerivedThumbnail: false, metadata: { sceneFilename: `mp-es-ep1-${item.id}.scene.json`, productionMethod: 'animation_2d' } }
  }
  return {
    version: 1, id: 'mp-es', revision: 7, title: 'Más allá del Plan', logline: '', premise: '', format: 'episodic', defaultEpisodeDurationSeconds: 75,
    language: 'Español', spokenLanguage: 'Español de España', languageIntent: {} as never, protagonistConsistency: false, protagonistCharacterId: '',
    genre: '', tone: '', audience: '', visualStyle: '', characterVisualStyle: '', cameraLanguage: '', allowClipText: false, sourceMode: 'original',
    masterUniversePrompt: '', rightsNote: '', bestEffortLipSyncAcknowledged: true,
    importSource: { kind: 'original', sourceWorkspaceId: null, sourceStoryId: null, importedAt: '', historicalProductionIds: [], migrationNotes: '' },
    canon: { worldSummary: '', immutableRules: [], currentFacts: [], forbiddenChanges: [], themes: [], longArcs: [], timeline: [], revision: 1, approval: 'approved' },
    characters: [
      { id: 'ines', name: 'Capitana Inés Valdés', aliases: [], role: '', personality: '', desire: '', need: '', flaw: '', longArc: '', voiceAndDialogue: '', appearance: '',
        identityLock: '', wardrobeVariants: [], referenceAssetIds: [], currentState: {}, approval: 'approved', voiceProfile: { characterKitRef: { workspace: 'plus-ultra', id: 'mp-ines' } } },
      { id: 'rayo', name: 'Teniente Rayo Salas', aliases: [], role: '', personality: '', desire: '', need: '', flaw: '', longArc: '', voiceAndDialogue: '', appearance: '',
        identityLock: '', wardrobeVariants: [], referenceAssetIds: [], currentState: {}, approval: 'approved' },
    ],
    relationships: [], locations: [{ id: 'nave', name: 'La nave', purpose: '', description: '', referenceAssetIds: [], variants: [], currentState: {}, approval: 'approved' }],
    props: [], seasons: [{ id: 'season-1', number: 1, title: '', premise: '', arc: '', episodeOrder: [ep.id], createdAt: '', updatedAt: '' }],
    episodesById: { [ep.id]: ep }, assets,
    provider: { useGlobalProfile: false, writingProvider: 'maestro' as never, writingModel: '', imageProvider: '', imageModel: '', videoModel: '', videoSettings: {} },
    createdAt: '', updatedAt: '2026-10-06T09:00:00Z',
  }
}

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
