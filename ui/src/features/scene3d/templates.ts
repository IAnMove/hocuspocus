import { effectsTemplateDocument, EFFECTS_TEMPLATES } from './effectsTemplates'
import { cinematicDocument, CINEMATIC_TEMPLATES, CINEMATIC_CATEGORIES } from './cinematicTemplates'
import { speechTemplateDocument, SPEECH_TEMPLATES, SPEECH_CATEGORIES } from './speech/templates'
import { mediaTemplateDocument, MEDIA_TEMPLATES, MEDIA_CATEGORIES } from './mediaTemplates'
import { campaignTemplateDocument, CAMPAIGN_TEMPLATES, CAMPAIGN_CATEGORIES } from './campaignTemplates'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { actionTemplateDocument, ACTION_TEMPLATES, ACTION_CATEGORIES } from './actionTemplates'
import { createDefaultScene3DDocument } from './document.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DCamera, type Scene3DCameraFamily, type Scene3DDocument, type Scene3DSlot, type Scene3DSlotId, type Scene3DTemplateId } from './types.ts'

export { SCENE3D_TEMPLATE_IDS, type Scene3DTemplateId }

export type Scene3DTemplate = {
  id: Scene3DTemplateId
  camera: Scene3DCameraFamily
  duration: number
  slots: Scene3DSlotId[]
}

export type Scene3DTemplateCategory = 'cinema' | 'action' | 'product' | 'music' | 'space' | 'drive'
export const TEMPLATE_CATEGORIES: Record<Scene3DTemplateId, Scene3DTemplateCategory> = {
  ...CINEMATIC_CATEGORIES,
  ...SPEECH_CATEGORIES,
  ...MEDIA_CATEGORIES,
  ...CAMPAIGN_CATEGORIES,
  ...ACTION_CATEGORIES,
  'reflective-stage': 'cinema',
  'character-materialization': 'cinema',
  'blast-stage': 'cinema',
  'coder-room': 'cinema',
  'clone-chase': 'cinema',
  'siege-ring': 'cinema',
  'spell-duel': 'cinema',
  'victory-circle': 'music',
  'two-shot': 'cinema',
  'product-orbit': 'product',
  'hero-push': 'cinema',
  'over-shoulder': 'cinema',
  'tracking': 'cinema',
  'crane-reveal': 'cinema',
  'establishing': 'cinema',
  'run-loop': 'music',
  'neon-run': 'music',
  'block-street': 'music',
  'space-float': 'space',
  'walk-void': 'music',
  'dance-orbit': 'music',
  'dance-stage': 'music',
  'cafe-dance': 'music',
  'drive-chase': 'drive',
  'drive-hood': 'drive',
  'drive-wing': 'drive',
  'drive-orbit': 'drive',
  'drive-tunnel': 'drive',
  'drive-hero': 'drive',
  'portrait-arc': 'cinema',
  'duo-diagonal': 'cinema',
  'high-angle': 'cinema',
  'wide-tableau': 'cinema',
  'product-detail': 'product',
  'product-pair': 'product',
  'product-pedestal': 'product',
  'duet-stage': 'music',
  'cafe-duet': 'music',
  'stage-crane': 'music',
  'space-encounter': 'space',
  'space-survey': 'space',
  'drive-coast-reveal': 'drive',
  'drive-city-wide': 'drive',
  'drive-tunnel-wing': 'drive',
}

const CAMERA_PROFILES: Partial<Record<Scene3DTemplateId, Partial<Scene3DCamera>>> = {
  'coder-room': { eye: [3, 2.2, 3.9], look: [0, 1, -.4], fov: 42 },
  'clone-chase': { orbitRadius: 8, fov: 52 },
  'siege-ring': { eye: [0.8, 3.5, 8], look: [0, 0.8, 0], fov: 46 },
  'spell-duel': { eye: [0, 1.6, 5.8], fov: 42 },
  'victory-circle': { orbitRadius: 6.7, orbitHeight: 1.4, orbitTurns: 0.22, fov: 46 },
  'two-shot': { eye: [0, 1.65, 5.6], fov: 44 },
  'product-orbit': { orbitRadius: 3.6, orbitHeight: 0.35, orbitTurns: 0.65, fov: 40 },
  'hero-push': { eye: [0.25, 1.15, 4.5], fov: 40 },
  'over-shoulder': { eye: [1.4, 1.7, 4.6], fov: 42 },
  'tracking': { orbitRadius: 5.2, fov: 40 },
  'crane-reveal': { eye: [1.2, 3.5, 5.6], fov: 45 },
  'establishing': { orbitRadius: 7.5, orbitHeight: 2.4, orbitTurns: 0.22, fov: 52 },
  'run-loop': { fov: 38 },
  'neon-run': { fov: 40 },
  'block-street': { fov: 42 },
  'space-float': { orbitRadius: 5.6, orbitHeight: 0.45, orbitTurns: 0.18, fov: 44 },
  'walk-void': { eye: [0.5, 1.4, 5.2], fov: 44 },
  'dance-orbit': { orbitRadius: 5.4, orbitHeight: 0.5, orbitTurns: 0.5, fov: 44 },
  'dance-stage': { orbitRadius: 6.2, orbitHeight: 0.8, orbitTurns: 0.22, fov: 48 },
  'cafe-dance': { fov: 42 },
  'drive-chase': { fov: 40 },
  'drive-hood': { fov: 55 },
  'drive-wing': { fov: 36 },
  'drive-orbit': { orbitRadius: 6.4, orbitHeight: 1.25, orbitTurns: 0.28, fov: 46 },
  'drive-tunnel': { fov: 55 },
  'drive-hero': { fov: 43 },
  'portrait-arc': { orbitRadius: 3.6, orbitHeight: 0.25, orbitTurns: 0.12, fov: 36 },
  'duo-diagonal': { eye: [1.7, 2.2, 6], fov: 44 },
  'high-angle': { eye: [1.4, 5.8, 5.8], look: [0, 0.5, 0], fov: 45 },
  'wide-tableau': { eye: [0, 2.5, 7.5], fov: 50 },
  'product-detail': { orbitRadius: 2.8, orbitHeight: 0.15, orbitTurns: 0.08, fov: 34 },
  'product-pair': { eye: [0, 1.5, 5.4], fov: 40 },
  'product-pedestal': { eye: [1.7, 2.5, 4.5], look: [0, 1.2, 0], fov: 40 },
  'duet-stage': { eye: [0, 1.8, 6.2], fov: 45 },
  'cafe-duet': { eye: [0, 1.7, 5.8], fov: 44 },
  'stage-crane': { eye: [0.7, 3.9, 6.2], fov: 48 },
  'space-encounter': { eye: [0, 2.7, 7], fov: 48 },
  'space-survey': { orbitRadius: 8, orbitHeight: 3, orbitTurns: 0.3, fov: 50 },
  'drive-coast-reveal': { eye: [2.8, 3.3, 6.5], look: [0, 0.7, -0.4], fov: 44 },
  'drive-city-wide': { look: [0, 0.7, -0.4], orbitRadius: 8.5, orbitHeight: 1.6, orbitTurns: 0.15, fov: 48 },
  'drive-tunnel-wing': { fov: 40 },
}

export const SCENE3D_TEMPLATES: readonly Scene3DTemplate[] = [
  { id: 'two-shot', camera: 'establishment', duration: 6, slots: ['subject_1', 'subject_2', 'background'] },
  { id: 'product-orbit', camera: 'product', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'hero-push', camera: 'establishment', duration: 5, slots: ['subject_1', 'background'] },
  { id: 'over-shoulder', camera: 'encounter', duration: 6, slots: ['subject_1', 'subject_2', 'background'] },
  { id: 'tracking', camera: 'follow', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'crane-reveal', camera: 'reveal', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'establishing', camera: 'orbit', duration: 8, slots: ['background', 'prop'] },
  { id: 'run-loop', camera: 'side', duration: 8, slots: ['subject_1', 'background'] },
  { id: 'neon-run', camera: 'side', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'block-street', camera: 'side', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'space-float', camera: 'musical', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'walk-void', camera: 'establishment', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'dance-orbit', camera: 'orbit', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'dance-stage', camera: 'musical', duration: 8, slots: ['subject_1', 'background'] },
  { id: 'cafe-dance', camera: 'front', duration: 8, slots: ['subject_1'] },
  { id: 'drive-chase', camera: 'chase', duration: 8, slots: ['background'] },
  { id: 'drive-hood', camera: 'hood', duration: 8, slots: ['background'] },
  { id: 'drive-wing', camera: 'wing', duration: 8, slots: ['background'] },
  { id: 'drive-orbit', camera: 'musical', duration: 8, slots: ['background'] },
  { id: 'drive-tunnel', camera: 'hood', duration: 8, slots: ['background'] },
  { id: 'drive-hero', camera: 'chase', duration: 8, slots: ['subject_1', 'background'] },
  { id: 'portrait-arc', camera: 'orbit', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'duo-diagonal', camera: 'encounter', duration: 8, slots: ['subject_1', 'subject_2', 'prop', 'background'] },
  { id: 'high-angle', camera: 'reveal', duration: 7, slots: ['subject_1', 'prop', 'background'] },
  { id: 'wide-tableau', camera: 'establishment', duration: 9, slots: ['subject_1', 'subject_2', 'prop', 'background'] },
  { id: 'product-detail', camera: 'product', duration: 6, slots: ['subject_1', 'background'] },
  { id: 'product-pair', camera: 'encounter', duration: 8, slots: ['subject_1', 'subject_2', 'background'] },
  { id: 'product-pedestal', camera: 'reveal', duration: 7, slots: ['subject_1', 'prop', 'background'] },
  { id: 'duet-stage', camera: 'encounter', duration: 8, slots: ['subject_1', 'subject_2', 'background'] },
  { id: 'cafe-duet', camera: 'encounter', duration: 8, slots: ['subject_1', 'subject_2'] },
  { id: 'stage-crane', camera: 'reveal', duration: 8, slots: ['subject_1', 'prop', 'background'] },
  { id: 'space-encounter', camera: 'encounter', duration: 9, slots: ['subject_1', 'subject_2', 'background'] },
  { id: 'space-survey', camera: 'orbit', duration: 10, slots: ['subject_1', 'prop', 'background'] },
  { id: 'drive-coast-reveal', camera: 'reveal', duration: 9, slots: ['background'] },
  { id: 'drive-city-wide', camera: 'musical', duration: 10, slots: ['background'] },
  { id: 'drive-tunnel-wing', camera: 'wing', duration: 8, slots: ['background'] },
  { id: 'siege-ring', camera: 'reveal', duration: 8, slots: ['subject_1', 'subject_2', 'prop'] },
  { id: 'spell-duel', camera: 'encounter', duration: 6, slots: ['subject_1', 'subject_2'] },
  { id: 'victory-circle', camera: 'orbit', duration: 8, slots: ['subject_1', 'subject_2', 'prop'] },
  { id: 'coder-room', camera: 'establishment', duration: 7, slots: ['subject_1', 'background'] },
  { id: 'clone-chase', camera: 'follow', duration: 7, slots: ['subject_1', 'subject_2', 'prop', 'background'] },
  ...CINEMATIC_TEMPLATES,
  ...SPEECH_TEMPLATES,
  ...MEDIA_TEMPLATES,
  ...EFFECTS_TEMPLATES,
  ...CAMPAIGN_TEMPLATES,
  ...ACTION_TEMPLATES,
]

const LAYOUTS: Partial<Record<Scene3DTemplateId, Partial<Record<Scene3DSlotId, Pick<Scene3DSlot, 'position' | 'rotationY' | 'scale'>>>>> = {
  'coder-room': {
    subject_1: { position: [0, 0, .55], rotationY: Math.PI, scale: 1.05 },
    background: { position: [0, .7, -4.8], rotationY: 0, scale: 6 },
  },
  'clone-chase': {
    subject_1: { position: [-3, 0, 1], rotationY: Math.PI / 2, scale: 1.05 },
    subject_2: { position: [-6, 0, -.3], rotationY: Math.PI / 2, scale: 1 },
    prop: { position: [-7.5, 0, -1.5], rotationY: Math.PI / 2, scale: 1 },
    background: { position: [0, 1, -6], rotationY: 0, scale: 13 },
  },
  'siege-ring': {
    subject_1: { position: [0, 0, 0.7], rotationY: 0, scale: 1.1 },
    subject_2: { position: [-2.2, 0, -1], rotationY: 0.8, scale: 1 },
    prop: { position: [2.2, 0, -1], rotationY: -0.8, scale: 1 },
  },
  'spell-duel': {
    subject_1: { position: [-1, 0, 0.4], rotationY: 1.1, scale: 1.1 },
    subject_2: { position: [1.1, 0, -0.2], rotationY: -1.1, scale: 1 },
  },
  'victory-circle': {
    subject_1: { position: [0, 0, 0.7], rotationY: 0, scale: 1.1 },
    subject_2: { position: [-1.8, 0, -0.5], rotationY: 0.25, scale: 1 },
    prop: { position: [1.8, 0, -0.5], rotationY: -0.25, scale: 1 },
  },
  'portrait-arc': {
    subject_1: { position: [0, 0, 0], rotationY: 0.2, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'duo-diagonal': {
    subject_1: { position: [-1, 0, 0.6], rotationY: 0.7, scale: 1 },
    subject_2: { position: [0.9, 0, -0.6], rotationY: -2.3, scale: 1 },
    prop: { position: [0, 0, -0.2], rotationY: 0, scale: 0.35 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'high-angle': {
    subject_1: { position: [-0.6, 0, 0], rotationY: 0.3, scale: 1 },
    prop: { position: [1.4, 0, -1], rotationY: -0.4, scale: 0.8 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 9 },
  },
  'wide-tableau': {
    subject_1: { position: [-1.5, 0, -0.4], rotationY: 0.3, scale: 1 },
    subject_2: { position: [1.5, 0, -0.9], rotationY: -0.3, scale: 1 },
    prop: { position: [0, 0, 1], rotationY: 0, scale: 0.55 },
    background: { position: [0, 0, -7], rotationY: 0, scale: 10 },
  },
  'product-detail': {
    subject_1: { position: [0, 0, 0], rotationY: 0.5, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'product-pair': {
    subject_1: { position: [-0.85, 0, 0], rotationY: 0.15, scale: 0.8 },
    subject_2: { position: [0.85, 0, 0], rotationY: -0.15, scale: 0.8 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'product-pedestal': {
    subject_1: { position: [0, 0.6, 0], rotationY: 0.2, scale: 0.7 },
    prop: { position: [0, 0, 0], rotationY: 0, scale: 0.35 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'duet-stage': {
    subject_1: { position: [-1, 0, 0], rotationY: 0.1, scale: 1 },
    subject_2: { position: [1, 0, 0], rotationY: -0.1, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'cafe-duet': {
    subject_1: { position: [-0.8, 0, 0.45], rotationY: 0.1, scale: 0.95 },
    subject_2: { position: [0.8, 0, 0.45], rotationY: -0.1, scale: 0.95 },
  },
  'stage-crane': {
    subject_1: { position: [0, 0, 0], rotationY: 0.15, scale: 1 },
    prop: { position: [1.5, 0, -0.5], rotationY: -0.3, scale: 0.65 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'space-encounter': {
    subject_1: { position: [-1.2, 0.8, 0], rotationY: 1, scale: 0.8 },
    subject_2: { position: [1.2, 1.1, -1], rotationY: -1, scale: 0.7 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'space-survey': {
    subject_1: { position: [0, 0.5, 0], rotationY: 0.4, scale: 0.8 },
    prop: { position: [2, 0.2, -1], rotationY: 0, scale: 1.1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-coast-reveal': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-city-wide': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-tunnel-wing': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },

  'two-shot': {
    subject_1: { position: [-0.95, 0, 0], rotationY: 0.4, scale: 1 },
    subject_2: { position: [0.95, 0, 0], rotationY: -0.4, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'product-orbit': {
    subject_1: { position: [0, 0, 0], rotationY: 0, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'hero-push': {
    subject_1: { position: [0, 0, 0], rotationY: 0.15, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'over-shoulder': {
    subject_1: { position: [0.35, 0, 0.55], rotationY: -0.7, scale: 1 },
    subject_2: { position: [-0.55, 0, -0.35], rotationY: 2.5, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'tracking': {
    subject_1: { position: [0, 0, 0], rotationY: 1.57, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  'crane-reveal': {
    subject_1: { position: [0, 0, 0], rotationY: 0.2, scale: 1 },
    background: { position: [0, 0, -6], rotationY: 0, scale: 8 },
  },
  establishing: {
    background: { position: [0, 0, -6], rotationY: 0, scale: 10 },
    prop: { position: [1.6, 0, -1.2], rotationY: -0.4, scale: 0.8 },
  },
  'run-loop': {
    subject_1: { position: [0, 0, 0], rotationY: 1.57, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'neon-run': {
    subject_1: { position: [0, 0, 0], rotationY: 1.57, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'block-street': {
    subject_1: { position: [0, 0, 0], rotationY: 1.57, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'space-float': {
    subject_1: { position: [0, 0.7, 0], rotationY: 0.35, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'walk-void': {
    subject_1: { position: [0, 0, 0], rotationY: 0.25, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'dance-orbit': {
    subject_1: { position: [0, 0, 0], rotationY: 0, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'dance-stage': {
    subject_1: { position: [0, 0, 0], rotationY: 0.2, scale: 1 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'cafe-dance': {
    subject_1: { position: [0, 0, 0.35], rotationY: 0, scale: 1 },
  },
  'drive-chase': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-hood': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-wing': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-orbit': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-tunnel': {
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
  'drive-hero': {
    subject_1: { position: [0.38, 0.52, 0.15], rotationY: 3.14, scale: 0.58 },
    background: { position: [0, 0, 0], rotationY: 0, scale: 1 },
  },
}

function emptySlot(id: Scene3DSlotId): Scene3DSlot {
  return {
    id,
    slot: id,
    position: [0, 0, 0],
    rotationY: 0,
    scale: 1,
    sourceUrl: '',
    media: id === 'background' ? 'image' : 'model3d',
    clip: null,
  }
}

export function applyScene3DTemplate(id: Scene3DTemplateId): Scene3DDocument {
  const action = actionTemplateDocument(id)
  if (action) return action
  const campaign = campaignTemplateDocument(id)
  if (campaign) return campaign
  const effects = effectsTemplateDocument(id)
  if (effects) return effects
  const speech = speechTemplateDocument(id)
  if (speech) return speech
  const media = mediaTemplateDocument(id)
  if (media) return media
  const cinematic = cinematicDocument(id)
  if (cinematic) return cinematic
  const template = SCENE3D_TEMPLATES.find(item => item.id === id) ?? SCENE3D_TEMPLATES[0]
  const layout = LAYOUTS[template.id] ?? {}
  const document = createDefaultScene3DDocument()
  document.templateId = template.id
  document.duration = template.duration
  document.camera = {
    ...document.camera,
    family: template.camera,
    look: template.camera === 'chase' || template.camera === 'wing' || template.camera === 'hood' || template.id === 'drive-orbit'
      ? [0, 0.7, -0.4]
      : document.camera.look,
    orbitRadius: template.id === 'drive-orbit' ? 6.4 : document.camera.orbitRadius,
    orbitHeight: template.id === 'drive-orbit' ? 1.25 : document.camera.orbitHeight,
    ...(template.camera === 'side' ? { fov: 38 } : {}),
    ...(template.camera === 'front' ? { fov: 42 } : {}),
    ...(template.camera === 'chase' ? { fov: 40 } : {}),
    ...(template.camera === 'hood' ? { fov: 55 } : {}),
    ...(template.camera === 'wing' ? { fov: 36 } : {}),
    ...CAMERA_PROFILES[template.id],
  }
  document.slots = template.slots.map(slotId => {
    const slot = emptySlot(slotId)
    const pose = layout[slotId]
    const next = pose ? { ...slot, ...pose } : slot
    const cylinder = CYLINDER_BY_TEMPLATE[template.id]
    if (cylinder && slotId === 'background') {
      return {
        ...next,
        media: 'image',
        sourceUrl: cylinder.plate ?? next.sourceUrl,
        loop: { cylinder: true, speed: cylinder.speed },
      }
    }
    return next
  })
  const category = TEMPLATE_CATEGORIES[template.id]
  const cool = category === 'space' || category === 'music'
  document.light = { kind: 'directional', direction: [-0.65, -1, -0.4], intensity: cool ? 1.4 : 1.3, color: cool ? '#dceaff' : '#fff0d9' }
  document.dressing = DRESSING_BY_TEMPLATE[template.id]
  if (template.id === 'clone-chase') document.slots.forEach(slot => {
    if (slot.media !== 'image') slot.motion = { to: [slot.position[0] + 14, slot.position[1], slot.position[2]], faceTravel: true }
  })
  return document
}

const CYLINDER_BY_TEMPLATE: Partial<Record<Scene3DTemplateId, { speed: number; plate?: string }>> = {
  'duet-stage': { speed: 0.025 },
  'stage-crane': { speed: 0.02 },
  'space-encounter': { speed: 0.025 },
  'space-survey': { speed: 0.02 },
  'drive-coast-reveal': { speed: 0.13, plate: '/scene3d/drive-coast.jpg' },
  'drive-city-wide': { speed: 0.12, plate: '/scene3d/drive-city.jpg' },
  'drive-tunnel-wing': { speed: 0.2, plate: '/scene3d/drive-tunnel.jpg' },

  'run-loop': { speed: -0.18 },
  'neon-run': { speed: -0.26 },
  'block-street': { speed: -0.16 },
  'space-float': { speed: 0.05 },
  'walk-void': { speed: 0.08 },
  'dance-orbit': { speed: 0.04 },
  'dance-stage': { speed: 0.03 },
  'drive-chase': { speed: 0.2, plate: '/scene3d/drive-city.jpg' },
  'drive-hood': { speed: 0.24, plate: '/scene3d/drive-city.jpg' },
  'drive-wing': { speed: 0.16, plate: '/scene3d/drive-coast.jpg' },
  'drive-orbit': { speed: 0.12, plate: '/scene3d/drive-city.jpg' },
  'drive-tunnel': { speed: 0.22, plate: '/scene3d/drive-tunnel.jpg' },
  'drive-hero': { speed: 0.18, plate: '/scene3d/drive-city.jpg' },
}

const DRESSING_BY_TEMPLATE: Partial<Record<Scene3DTemplateId, Scene3DDocument['dressing']>> = {
  'coder-room': 'workshop',
  'clone-chase': 'chase-street',
  'siege-ring': 'citadel',
  'spell-duel': 'citadel',
  'victory-circle': 'citadel',
  'wide-tableau': 'street',
  'duet-stage': 'street',
  'cafe-duet': 'cafe',
  'stage-crane': 'street',
  'space-encounter': 'space',
  'space-survey': 'space',
  'drive-coast-reveal': 'drive-coast',
  'drive-city-wide': 'drive-city',
  'drive-tunnel-wing': 'drive-tunnel',

  'run-loop': 'treadmill',
  'neon-run': 'treadmill',
  'block-street': 'treadmill',
  'space-float': 'space',
  'dance-stage': 'street',
  'cafe-dance': 'cafe',
  'drive-chase': 'drive-city',
  'drive-hood': 'drive-city',
  'drive-wing': 'drive-coast',
  'drive-orbit': 'drive-city',
  'drive-tunnel': 'drive-tunnel',
  'drive-hero': 'drive-city',
}

export function patchScene3DSlot(
  document: Scene3DDocument,
  slotId: string,
  patch: Partial<Pick<Scene3DSlot, 'position' | 'rotationY' | 'scale' | 'sourceUrl' | 'sourceRef' | 'media' | 'clip' | 'clipPlayback' | 'motion' | 'loop' | 'surface' | 'performance' | 'grounded' | 'textureRepeat' | 'speech' | 'screen' | 'character' | 'appearance'>>,
): Scene3DDocument {
  return {
    ...document,
    slots: document.slots.map(slot => slot.id === slotId ? { ...slot, ...patch } : slot),
  }
}

export function slotHasKeepableAsset(slot: Scene3DSlot) {
  return Boolean(slot.sourceUrl || slot.screen?.sourceUrl)
}

function takePreviousSlot(
  previous: readonly Scene3DSlot[],
  used: Set<string>,
  predicate: (item: Scene3DSlot) => boolean,
): Scene3DSlot | undefined {
  const found = previous.find(item => !used.has(item.id) && predicate(item))
  if (found) used.add(found.id)
  return found
}

/** One previous slot per destination. Same id wins, then unused same role+media. */
export function takeKeptSlot(
  slot: Scene3DSlot,
  previous: readonly Scene3DSlot[],
  used: Set<string>,
): Scene3DSlot | undefined {
  return takePreviousSlot(previous, used, item => item.id === slot.id && item.media === slot.media && slotHasKeepableAsset(item))
    ?? takePreviousSlot(previous, used, item => item.slot === slot.slot && item.media === slot.media && slotHasKeepableAsset(item))
}

export function applyKeptSlotAssets(slot: Scene3DSlot, old: Scene3DSlot | undefined): Scene3DSlot {
  if (!old) return slot
  const keptScreenUrl = slot.screen?.sourceUrl || old.screen?.sourceUrl || ''
  const screen = slot.screen
    ? {
        ...slot.screen,
        sourceUrl: keptScreenUrl,
        sourceRef: slot.screen.sourceRef || old.screen?.sourceRef,
        media: slot.screen.sourceUrl ? slot.screen.media : (old.screen?.media || slot.screen.media),
      }
    : (old.speech?.facePack && old.screen ? structuredClone(old.screen) : slot.screen)
  if (slot.sourceUrl) return { ...slot, screen }
  return {
    ...slot,
    character: old.character,
    sourceUrl: old.sourceUrl,
    sourceRef: old.sourceRef,
    clip: old.clip,
    clipPlayback: old.clipPlayback,
    speech: old.speech ? structuredClone(old.speech) : undefined,
    screen,
  }
}

/** Carry durable identity and clip choice, but use the new shot's placement. */
export function remountScene3DTemplate(id: Scene3DTemplateId, previous: Scene3DDocument, keepAssets = true): Scene3DDocument {
  const next = applyScene3DTemplate(id)
  next.playbackSpeed = previous.playbackSpeed
  next.clipNumber = previous.clipNumber
  next.production = previous.production ? structuredClone(previous.production) : undefined
  next.soundtrack = previous.soundtrack ? structuredClone(previous.soundtrack) : undefined
  if (previous.production) next.duration = previous.duration
  next.texts = previous.texts ? structuredClone(previous.texts) : undefined
  next.width = previous.width
  next.height = previous.height
  next.fps = previous.fps
  next.camera = adaptAuthoredCameraToFrame(next.camera, next.width, next.height)
  if (!keepAssets) return next
  const used = new Set<string>()
  next.slots = next.slots.map(slot => applyKeptSlotAssets(slot, takeKeptSlot(slot, previous.slots, used)))
  return next
}
