import { getCandidateSceneTemplate } from './catalog'
import { compileCandidateScene, type TemplateBindings } from './compile'
import { demoArtwork } from './demoArtwork'
import { demoShip } from './demoShips'

export function candidateDemoBindings(id: string, variant: 'coral' | 'teal' = 'coral'): TemplateBindings {
  const template = getCandidateSceneTemplate(id)
  const art = demoArtwork(variant)
  if (template.group === 'music-motion') {
    const sources = { subject_1: art.subject, subject_2: art.partner, background: art.stage, prop_1: art.prop }
    return Object.fromEntries(template.slots.filter(slot => slot.required).map(slot => [slot.id, sources[slot.id as keyof typeof sources]]))
  }
  const space = template.family === 'space'
  const bindings: TemplateBindings = {
    subject_1: space ? demoShip(variant) : id === 'music-product' || id === 'cinema-detail' ? art.prop : art.subject,
    background: space ? art.space : template.family === 'music' ? art.stage : art.background,
  }
  if (template.slots.some(slot => slot.id === 'subject_2' && slot.required)) bindings.subject_2 = art.partner
  if (template.slots.some(slot => slot.id === 'prop_1' && slot.required)) {
    bindings.prop_1 = space ? id === 'space-orbit' ? art.planet : demoShip(variant === 'coral' ? 'teal' : 'coral') : art.prop
  }
  if (!space) bindings.foreground = art.foreground
  return bindings
}
export function candidateDemoScene(id: string, variant: 'coral' | 'teal' = 'coral') {
  return compileCandidateScene(id, candidateDemoBindings(id, variant))
}
