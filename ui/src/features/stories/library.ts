import type { StoryProject } from './types'

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

    const localTime = updatedAtValue(localProject.updatedAt)
    const remoteTime = updatedAtValue(remoteProject.updatedAt)
    if (localTime > remoteTime) {
      projects[id] = localProject
    } else if (remoteTime > localTime) {
      projects[id] = remoteProject
    } else {
      // Keep the browser copy visible, but retain the conflict and block the
      // autosave path so the server copy cannot be silently overwritten.
      projects[id] = localProject
      conflicts.push({
        id,
        title: localProject.title || remoteProject.title || id,
        localUpdatedAt: localProject.updatedAt,
        remoteUpdatedAt: remoteProject.updatedAt,
        localProject,
        remoteProject,
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
