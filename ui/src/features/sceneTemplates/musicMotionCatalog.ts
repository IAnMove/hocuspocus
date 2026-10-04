/**
 * Candidate-only musical motion definitions.
 *
 * The rows live in app/shared/scene_templates.json (group music-motion).
 * Choreography stays in the motion builders. Adding an id to the JSON does
 * not generate an asset or approve a preview.
 */

export type MusicMotionIntensity = 'moderate' | 'high'

export { MUSIC_MOTION_TEMPLATES } from './catalog'
