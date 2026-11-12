/** Where the last flat rig placed this pose's eyes and mouth. Absent until a rig writes them. */

export const FACE_PLACEMENT_SOURCES = ['whites', 'landmarks', 'hint'] as const

export type FacePlacementSource = (typeof FACE_PLACEMENT_SOURCES)[number]

type PlacementGroup = {
  eyesSource?: FacePlacementSource | string
  mouthSource?: FacePlacementSource | string
  brows?: [[number, number, number, number], [number, number, number, number]]
}

function isSource(value: unknown): value is FacePlacementSource {
  return FACE_PLACEMENT_SOURCES.includes(value as FacePlacementSource)
}

/** Both sources, or nothing. A pose that predates the field stays unlabeled. */
export function faceRigPlacementSources(
  kit: { anchors?: Record<string, PlacementGroup | undefined> },
  poseId: string,
): { eyes: FacePlacementSource; mouth: FacePlacementSource } | null {
  const group = kit.anchors?.[poseId.trim() || 'base']
  if (!isSource(group?.eyesSource) || !isSource(group?.mouthSource)) return null
  return { eyes: group.eyesSource, mouth: group.mouthSource }
}

/** The placement record a mouth edit must keep. Invalid values are dropped. */
export function keptFacePlacement(group: PlacementGroup | undefined): {
  eyesSource?: FacePlacementSource
  mouthSource?: FacePlacementSource
  brows?: [[number, number, number, number], [number, number, number, number]]
} {
  if (!group) return {}
  const kept: ReturnType<typeof keptFacePlacement> = {}
  if (isSource(group.eyesSource)) kept.eyesSource = group.eyesSource
  if (isSource(group.mouthSource)) kept.mouthSource = group.mouthSource
  if (twoBoxes(group.brows)) kept.brows = group.brows
  return kept
}

function twoBoxes(value: unknown): value is [[number, number, number, number], [number, number, number, number]] {
  return Array.isArray(value) && value.length === 2
    && value.every(box => Array.isArray(box) && box.length === 4 && box.every(item => typeof item === 'number'))
}
