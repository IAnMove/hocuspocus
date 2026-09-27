/** Shared 24 / 30 / 60 contract for Video 2D compositor and Video 3D export. */
export type SceneFps = 24 | 30 | 60

export function canonicalSceneFps(value: unknown): SceneFps {
  return value === 24 || value === 60 ? value : 30
}
