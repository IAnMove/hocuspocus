import type { defineCapability } from './capabilityRegistry'
import type { AgentAnimeMakeAction } from './agentActions'

const GENDERS = ['girl', 'boy', 'man']
const BODIES = ['slim', 'average', 'tall']
const HAIR = ['none', 'short', 'bangs', 'bob', 'long', 'twin_tails', 'spiky', 'ponytail', 'bun']
const OUTFITS = ['school', 'casual', 'sport']
const FACE_SOURCES = ['program', 'qwen']
const FACE_STYLES = ['anime', 'cute']
const FACE_SHAPES = ['soft', 'sharp']
const HEX = /^#[0-9a-fA-F]{6}$/

function text(value: unknown, max: number): string {
  return typeof value === 'string' ? value.trim().slice(0, max) : ''
}

function choice(value: unknown, allowed: string[]): string | undefined {
  return typeof value === 'string' && allowed.includes(value) ? value : undefined
}

function hex(value: unknown): string | undefined {
  return typeof value === 'string' && HEX.test(value) ? value.toUpperCase() : undefined
}

export function registerAnimeCharacterCapability(register: typeof defineCapability) {
  register<AgentAnimeMakeAction>({
    name: 'anime_make',
    title: 'Make an anime 3D character',
    description: 'One anime 3D character from traits, as model3d.anime.make: a lofted PS2-style body rigged on CPU in the same call plus its anime_head face kit (eleven expressions, nine visemes, a blink) that world3d.scene.face projects onto the head. The rigged GLB opens in the 3D gallery; the kit in Characters.',
    useWhen: 'The user asks for an anime 3D character, an anime girl or boy in 3D, or a character for a Video 3D scene in anime style.',
    parameters: ['name', 'gender', 'body', 'height', 'skin', 'eye_color', 'hair_style', 'hair_color', 'outfit', 'face_style', 'face_shape', 'face_source', 'face_image'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'anime_make' },
        name: { type: 'string', maxLength: 64 },
        gender: { enum: GENDERS },
        body: { enum: BODIES },
        height: { type: 'number', minimum: 1.2, maximum: 2.2 },
        skin: { type: 'string', description: '#rrggbb' },
        eye_color: { type: 'string', description: '#rrggbb' },
        hair_style: { enum: HAIR },
        hair_color: { type: 'string', description: '#rrggbb' },
        outfit: { enum: OUTFITS },
        face_style: { enum: FACE_STYLES, description: 'anime (almond eyes) or cute (round mascot eyes)' },
        face_shape: { enum: FACE_SHAPES },
        face_source: { enum: FACE_SOURCES, description: 'program draws the face; qwen uses a keyed bald face picture (face_image) with the expressions as overlays' },
        face_image: { type: 'string', maxLength: 300, description: 'a keyed bald face picture of this workspace (image.remove_background output)' },
      },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Building the anime character…',
    resolve(raw) {
      const height = typeof raw.height === 'number' ? raw.height : Number(raw.height)
      return {
        type: 'anime_make',
        name: text(raw.name, 64) || 'Anime',
        ...(choice(raw.gender, GENDERS) ? { gender: choice(raw.gender, GENDERS) } : {}),
        ...(choice(raw.body, BODIES) ? { body: choice(raw.body, BODIES) } : {}),
        ...(Number.isFinite(height) && height >= 1.2 && height <= 2.2 ? { height } : {}),
        ...(hex(raw.skin) ? { skin: hex(raw.skin) } : {}),
        ...(hex(raw.eye_color) ? { eyeColor: hex(raw.eye_color) } : {}),
        ...(choice(raw.hair_style, HAIR) ? { hairStyle: choice(raw.hair_style, HAIR) } : {}),
        ...(hex(raw.hair_color) ? { hairColor: hex(raw.hair_color) } : {}),
        ...(choice(raw.outfit, OUTFITS) ? { outfit: choice(raw.outfit, OUTFITS) } : {}),
        ...(choice(raw.face_style, FACE_STYLES) ? { faceStyle: choice(raw.face_style, FACE_STYLES) } : {}),
        ...(choice(raw.face_shape, FACE_SHAPES) ? { faceShape: choice(raw.face_shape, FACE_SHAPES) } : {}),
        ...(choice(raw.face_source, FACE_SOURCES) ? { faceSource: choice(raw.face_source, FACE_SOURCES) } : {}),
        ...(text(raw.face_image, 300) ? { faceImage: text(raw.face_image, 300) } : {}),
      }
    },
    validate(action) { return !action.name.trim() ? ['name is required'] : action.faceSource === 'qwen' && !action.faceImage ? ['face_image is required with face_source qwen'] : [] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.animeCharacter.make(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'output', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: '3d', anchors: ['anime'], replay: 'atomic' },
  })
}
