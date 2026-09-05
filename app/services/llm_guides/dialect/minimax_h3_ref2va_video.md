MINIMAX H3 REF2VA CONTEXT-IR RULES (apply to video_prompt):
- Describe the finished target shot, not an instruction to copy, replace, or animate a reference.
- Maestro maps the exact per-shot ordered media manifest after planning. Do not guess reference numbers; the deterministic final compiler binds the actual <Picture N>, <Video N>, and <Audio N> labels.
- The final model prompt uses exactly these ordered fields: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music.
- subject_definitions identifies each <Subject N>, stable speaking ID (S1), and the reference media that defines identity, scene, motion, or voice.
- Begin summary with the applicable official task types in square brackets, such as [reference generation + audio reference] or [reference generation + audio reuse]. Do not repeat literal dialogue in summary.
- In retention_analysis, visual subjects/pictures/videos use only fully_preserved, partially_preserved, attribute_transfer, or weak_reference. Audio uses only fully_copy, partially_copy, reference, or weak_reference.
- When a picture supplies only a reusable person, object, environment, or style, cite it inside that <Subject N> definition instead of pretending it is a concrete keyframe. Identity images never contribute their source background, framing, composition, or pose unless explicitly mapped as composition references.
- Begin detailed_description with [Shot 1]. Describe only visible action and camera.
- Assign every speaking person a stable ID such as (S1) or (S2). Keep the same ID throughout the Director project.
- Write literal speech only as <d>[English] Exact words.</d>, changing the language tag when requested. Put speaker identity and visible action outside the tag.
- Preserve supplied dialogue verbatim. When speech is requested without a script, create concise meaningful lines that fit the clip at no more than about two words per second.
- Preserve recognizable proper names, characters, performers, series, films, and franchises exactly as supplied.
- When no dialogue is requested, omit <d> tags. Never invent speech to fill time.
- When driving audio is supplied, describe only visible performance and action; do not describe, transcribe, or replace its audible content.
- No negative prompts, technical parameters, model names, LoRA filenames, or explanatory prose.

AUDIO POLICY (temporary, highest priority):
MiniMax H3 treats any written audio note as something to perform, including negative conditions and silence. Until native audio is reliable, the prompt must contain zero sound description.
- The only allowed audio content is exact spoken dialogue, written solely as <d>[Language] exact words</d> when someone actually speaks.
- If there is no dialogue, omit <d> tags entirely and keep describing picture.
- A mute shot of a known talking character still makes H3 invent speech unless the picture fills the duration with physical action and closed lips. Closed lips are visible acting, not an audio note. Do not assign speaker IDs unless that person has a <d> line. Do not write stills, freeze-frames, or leftover quiet time.
- Do not describe sound in any form: not ambience, room tone, foley, practical effects, music, voices, vocal performance, or the audible result of a visible action.
- Do not describe silence or the absence of sound. Do not write negative audio conditions of any kind. Do not mention leftover duration as quiet time.
- overall_soundscape must be exactly N/A.
- non_diegetic_music must be exactly N/A.
- These two labels are required schema, not permission to invent audio.
