export function buildCharacterOrbitPrompt(): string {
  return [
    'subject_definitions: <Subject 1> is the character whose face, hair and art style come from <Picture 1> and stay fully visible throughout the video.',
    '<Subject 2> is the outfit worn by <Subject 1>, referenced from <Picture 2>: its colors, cut, material and details are taken from the picture as-is. The face visible in <Picture 2> is ignored and replaced by <Subject 1>\'s face. The background, setting, floor, lighting and all other content in <Picture 2> are ignored.',
    '',
    'summary: [reference generation] A frozen full-body character on a seamless grey backdrop while the camera completes one 360-degree orbit.',
    '',
    'retention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved - keep the face, hair and art style from <Picture 1> unchanged.',
    '<Subject 2> (appears in [Shot 1]): fully_preserved - keep the outfit colors, cut, material and details from <Picture 2> as-is, with <Subject 1>\'s face substituted.',
    '<Picture 1> ([Shot 1] identity): fully_preserved - identity and appearance reference only; do not copy its background, framing or pose.',
    '<Picture 2> ([Shot 1] wardrobe): fully_preserved - wardrobe reference only; ignore its face, background, floor and lighting.',
    '',
    'detailed_description: [Shot 1] Solid light-grey seamless backdrop, one flat uniform tone edge to edge, with no gradient, no vignette, no texture and no floor line. Nothing else is in frame. The subject casts no shadow onto the backdrop and no contact shadow on the ground. Soft form shading on the subject itself is fine. Near-orthographic full-body view of the character standing completely still in a relaxed A-pose: arms hanging slightly away from the body, feet shoulder-width apart, head level, eyes open and looking forward. The face is exactly the face from <Picture 1>. The pose, framing and size in frame never change. Only the camera moves: one smooth fixed-speed 360-degree clockwise orbit starting square on the front, passing the right profile, the back, the left profile, and returning to the front. Hair, fabric and accessories stay locked. No wind, no breathing, no sway.',
    '',
    'overall_soundscape: Silence. No music, no room tone, no voices.',
    '',
    'non_diegetic_music: N/A',
  ].join('\n')
}

export const CHARACTER_ORBIT_VIEWS = [
  { id: 'front', label: 'Frente', fraction: 0.02 },
  { id: 'right', label: 'Mirando derecha', fraction: 0.25 },
  { id: 'back', label: 'Espalda', fraction: 0.5 },
  { id: 'left', label: 'Mirando izquierda', fraction: 0.75 },
] as const
