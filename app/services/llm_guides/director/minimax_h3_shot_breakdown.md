VIDEO PROMPT (video_prompt) — for MiniMax H3:

MiniMax H3 generates picture and stereo sound together, but Maestro currently
sends picture plus exact dialogue tags only. A Director shot may be text-only
(FL2VA) or use soft image/audio references (Ref2VA); neither path guarantees a
fixed start frame. Every video prompt therefore stands on its own.

SELF-CONTAINED SHOT RULES:
- Describe the finished target shot, not instructions to copy, animate, replace,
  or edit a reference.
- Include the setting, composition, every visible subject, identity/appearance,
  wardrobe, action, camera behavior, lighting, and any exact dialogue tags.
- Follow the model-aware CHARACTER NAMING block in the surrounding Director
  instructions. In prompt-only/direct-reference mode, preserve every recognizable
  proper identity and its series, film, franchise, or performer exactly as
  supplied and pair reference labels with useful visible traits. When generated
  shot images are enabled, follow the supplied name-to-description conversion
  instead so the image and video prompts stay aligned.
- Do not invent names, dialogue, franchises, or scene details absent from the
  screenplay or concept.
- References are guidance. Do not emit guessed <Picture N>, <Video N>, or
  <Audio N> tags; Maestro maps the per-shot references after planning.

CONTINUITY WITHOUT A FIXED START IMAGE:
- Treat wardrobe and blocking as explicit shot state. For every visible person,
  repeat the complete head-to-toe clothing and exact first-frame position:
  screen-left/center/right, depth, pose, facing direction, and nearby props.
- State the same opening composition in video_prompt; names alone do not carry
  appearance, clothing, or position into a new text-only generation.
- Give each uninterrupted place/time one continuity_group. Before an ordinary
  same-scene cut, visibly move each person into the next shot's opening position.
- Use continuity_strategy=extend_previous only for a literal same-composition
  continuation that should inherit the preceding generated final frame. Use
  continuity_strategy=continuous for normal cuts within the same scene.

CONTEXT-IR FORMAT:
- Structure video_prompt with exactly these labeled sections:
  integrated_multimodal_description, overall_soundscape, non_diegetic_music.
- Begin integrated_multimodal_description with [Shot 1] and narrate only
  visible action and camera.
- Give each speaking person a stable ID such as (S1) or (S2).
- Literal speech uses <d>[English] Exact words.</d> (change the language tag
  when requested). Speaker identity and visible action are outside the tag.
- Every structured dialogue_beats entry must also appear exactly once in
  video_prompt. Never leave the actual spoken words only in the JSON field.
- When no dialogue is requested, omit <d> tags and continue with visible
  action only.
- After the last spoken line, continue with visible reactions or motion.

AUDIO POLICY (temporary, highest priority):
MiniMax H3 treats any written audio note as something to perform, including
negative conditions and silence. Until native audio is reliable, the prompt
must contain zero sound description.
- The only allowed audio content is exact spoken dialogue, written solely as
  <d>[Language] exact words</d> when someone actually speaks.
- If there is no dialogue, omit <d> tags entirely and keep describing picture.
- A mute shot of a known talking character still makes H3 invent speech unless
  the picture fills the duration with physical action and closed lips. Closed
  lips are visible acting, not an audio note. Do not assign speaker IDs unless
  that person has a <d> line. Do not write stills, freeze-frames, or leftover
  quiet time.
- Do not describe sound in any form: not ambience, room tone, foley, practical
  effects, music, voices, vocal performance, or the audible result of a visible
  action.
- Do not describe silence or the absence of sound. Do not write negative audio
  conditions of any kind. Do not mention leftover duration as quiet time.
- overall_soundscape must be exactly N/A.
- non_diegetic_music must be exactly N/A.
- These two labels are required schema, not permission to invent audio.

TIMING:
- Keep actions and dialogue realistic for the requested duration. Spoken text
  should generally stay at or below about two words per second.
- H3 renders bounded native shots. Do not put LTX sliding-window commands,
  references to a previous shot, or IC-LoRA ``Shot N (Camera, Xs)`` trigger
  syntax inside video_prompt. Use the required structured continuity fields
  only for Director's planning and handoff logic.
- For supplied driving audio, describe the visible performance, lip movement,
  rhythm, and action that synchronize to it; do not transcribe, describe, or
  replace its audible content.

Do not include negative prompts, model names, LoRA names, technical settings,
reference-index guesses, or explanatory prose in video_prompt.
