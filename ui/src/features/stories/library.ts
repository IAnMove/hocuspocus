import type { StoryMusicCandidate, StoryProject } from './types'

export interface StoryLibraryData {
  version: 2
  /** Monotonic backend CAS revision; project revisions remain independent. */
  revision: number
  activeId: string
  projects: Record<string, StoryProject>
}

export interface StoryLibraryConflict {
  id: string
  title: string
  localUpdatedAt: string
  remoteUpdatedAt: string
  localProject: StoryProject
  remoteProject: StoryProject
}

export interface StoryLibraryMergeResult {
  library: StoryLibraryData
  conflicts: StoryLibraryConflict[]
  needsRemoteSync: boolean
}

function updatedAtValue(value: string): number {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY
}

function sameProject(left: StoryProject, right: StoryProject): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function sameLibrary(left: StoryLibraryData, right: StoryLibraryData): boolean {
  const leftIds = Object.keys(left.projects).sort()
  const rightIds = Object.keys(right.projects).sort()
  return left.activeId === right.activeId
    && JSON.stringify(leftIds) === JSON.stringify(rightIds)
    && leftIds.every(id => sameProject(left.projects[id], right.projects[id]))
}

function isPublishedSong(candidate: StoryMusicCandidate | undefined): boolean {
  return Boolean(candidate && candidate.status === 'ready' && String(candidate.source || '').trim())
}

function preferPublishedSong(
  preferred: StoryMusicCandidate,
  other: StoryMusicCandidate | undefined,
): StoryMusicCandidate {
  return other && isPublishedSong(other) && !isPublishedSong(preferred) ? other : preferred
}

function mergePublishedSongs(
  preferred: StoryMusicCandidate[] | undefined,
  other: StoryMusicCandidate[] | undefined,
): StoryMusicCandidate[] | undefined {
  if (!preferred || !other?.length) return preferred
  const otherById = new Map(other.map(item => [item.id, item]))
  let changed = false
  const next = preferred.map(candidate => {
    const merged = preferPublishedSong(candidate, otherById.get(candidate.id))
    if (merged !== candidate) changed = true
    return merged
  })
  return changed ? next : preferred
}

/** Keep a published song row when the other copy still has the empty reservation. */
function mergePublishedProjectMusic(winner: StoryProject, other: StoryProject): StoryProject {
  const winnerMusic = winner.music
  const otherMusic = other.music
  if (!winnerMusic || !otherMusic) return winner
  const otherCues = new Map((otherMusic.cues || []).map(cue => [cue.id, cue]))
  let changed = false
  const cues = (winnerMusic.cues || []).map(cue => {
    const candidates = mergePublishedSongs(cue.candidates, otherCues.get(cue.id)?.candidates)
    if (candidates && candidates !== cue.candidates) {
      changed = true
      return { ...cue, candidates }
    }
    return cue
  })
  const candidates = mergePublishedSongs(winnerMusic.candidates, otherMusic.candidates)
  if (candidates && candidates !== winnerMusic.candidates) changed = true
  if (!changed) return winner
  return {
    ...winner,
    music: {
      ...winnerMusic,
      cues,
      candidates: candidates || winnerMusic.candidates,
    },
  }
}

/** Merge browser and server Story libraries without allowing stale data to win. */
export function mergeStoryLibraries(
  local: StoryLibraryData,
  remote: StoryLibraryData,
): StoryLibraryMergeResult {
  const projects: Record<string, StoryProject> = {}
  const conflicts: StoryLibraryConflict[] = []
  const ids = new Set([...Object.keys(local.projects), ...Object.keys(remote.projects)])

  ids.forEach(id => {
    const localProject = local.projects[id]
    const remoteProject = remote.projects[id]
    if (!localProject) {
      projects[id] = remoteProject
      return
    }
    if (!remoteProject) {
      projects[id] = localProject
      return
    }
    if (sameProject(localProject, remoteProject)) {
      projects[id] = localProject
      return
    }

    const localMerged = mergePublishedProjectMusic(localProject, remoteProject)
    const remoteMerged = mergePublishedProjectMusic(remoteProject, localProject)
    if (sameProject(localMerged, remoteMerged)) {
      projects[id] = localMerged
      return
    }

    const localTime = updatedAtValue(localProject.updatedAt)
    const remoteTime = updatedAtValue(remoteProject.updatedAt)
    if (localTime > remoteTime) {
      projects[id] = localMerged
    } else if (remoteTime > localTime) {
      projects[id] = remoteMerged
    } else {
      // Keep the browser copy visible, but retain the conflict and block the
      // autosave path so the server copy cannot be silently overwritten.
      projects[id] = localMerged
      conflicts.push({
        id,
        title: localProject.title || remoteProject.title || id,
        localUpdatedAt: localProject.updatedAt,
        remoteUpdatedAt: remoteProject.updatedAt,
        localProject: localMerged,
        remoteProject: remoteMerged,
      })
    }
  })

  const activeId = local.projects[local.activeId]
    ? local.activeId
    : remote.projects[remote.activeId]
      ? remote.activeId
      : Object.keys(projects)[0] || ''
  const remoteRevision = Number.isInteger(remote.revision) && remote.revision >= 0
    ? remote.revision : 0
  const library: StoryLibraryData = { version: 2, revision: remoteRevision, activeId, projects }
  return {
    library,
    conflicts,
    needsRemoteSync: conflicts.length === 0 && !sameLibrary(library, remote),
  }
}

/**
 * Rebuild a single-project mutation CAS baseline after a 409.
 *
 * The retry PUT replaces the whole library. Taking `remote.projects` alone
 * drops local-only siblings and unsaved sibling edits. Keep the merge for
 * those stories, but mutate the server copy of `projectId` so a newer local
 * pending reservation cannot replace a song the worker already attached.
 */
export function rebaseStoryMutationBaseline(
  projectId: string,
  local: StoryLibraryData,
  remote: StoryLibraryData,
): StoryLibraryData {
  const merged = mergeStoryLibraries(local, remote)
  const source = remote.projects[projectId] || merged.library.projects[projectId]
  return {
    version: 2,
    revision: merged.library.revision,
    activeId: merged.library.activeId,
    projects: source
      ? { ...merged.library.projects, [projectId]: source }
      : merged.library.projects,
  }
}
