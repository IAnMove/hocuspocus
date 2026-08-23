MINIMAX H3 CONTEXT-IR RULES (apply to video_prompt):
- Structure the prompt with these exact fields: integrated_multimodal_description, overall_soundscape, and non_diegetic_music.
- Begin the multimodal timeline with [Shot 1]. Describe only visible action and camera.
- Assign every speaking person a stable ID such as (S1) or (S2). Keep the same ID across shots.
- Write literal speech only as <d>[English] Exact words.</d>, changing the language tag when requested. Put speaker identity and visible action outside the tag.
- Preserve supplied dialogue verbatim. When speech is requested without a script, create concise meaningful lines that fit the clip at no more than about two words per second.
- Preserve recognizable proper names, characters, performers, series, films, and franchises exactly as supplied. Never replace a trained identity such as "Dwight from The Office" with a generic descriptor.
- After the final line, continue with visible reactions or movement.
- With a keyframe, preserve its identities, wardrobe, composition, setting, objects, and lighting while describing the motion that follows.
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
