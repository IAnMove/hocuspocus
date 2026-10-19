import type { MusicVideoChorusSet, MusicVideoTreatment } from '../../types'

/** The server's default coverage cycle (`COVERAGE_SEQUENCE` in
 *  app/services/director/music_video_coverage.py); a test in
 *  tests/test_director_v2_story_refs.py checks that both lists match. */
export const DEFAULT_COVERAGE_CYCLE: readonly string[] = [
  'hero wide performance',
  'direct-to-camera medium performance',
  'beauty close-up',
  'moving profile coverage',
  'low-angle performance',
  'detail insert',
]

export const CHORUS_SET_MODES: readonly MusicVideoChorusSet[] = ['first', 'rotate', 'free']

/** The cycle the planner will use: a missing field means the server's six lines. */
export function coverageCycle(treatment: Pick<MusicVideoTreatment, 'coverage'>): string[] {
  return treatment.coverage ? [...treatment.coverage] : [...DEFAULT_COVERAGE_CYCLE]
}

/** Lines typed in the editor; an empty box is an empty cycle (the planner chooses). */
export function parseCoverageLines(text: string): string[] {
  return text.split('\n').map(line => line.trim()).filter(Boolean).slice(0, 12)
}
