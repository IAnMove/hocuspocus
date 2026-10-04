import { checkGeometry, geometrySampleTimes, type GeometryReport, type GeometrySample } from './geometryChecks.ts'
import type { Scene3DDocument } from './types.ts'

/** Sample a stage at the geometry times. Undefined when a frame cannot be measured. */
export function collectGeometry(
  sampleAt: (seconds: number, document: Scene3DDocument) => GeometrySample | undefined,
  document: Scene3DDocument,
): GeometryReport | undefined {
  const samples: GeometrySample[] = []
  for (const time of geometrySampleTimes(document.duration)) {
    const sample = sampleAt(time, document)
    if (!sample) return undefined
    samples.push(sample)
  }
  return checkGeometry(samples)
}
