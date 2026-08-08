In addition to [STYLE] and [LYRICS], output exactly one final section named [LYRIA].
This is a complete prompt the user will paste manually into Google AI Studio with
Lyria 3 Pro Preview. Do not call Google and do not output explanations around it.

Build [LYRIA] using this contract:

- Start with "<original title>: Composition Breakdown".
- Target at most 3:00 even when the broader Story cue requests a longer duration.
- Cover the full duration with contiguous timestamp blocks such as
  "[0:00 - 0:12] Intro: Intensity: 4/10.".
- Use a coherent progression chosen from Intro, Verse, Pre-Chorus, Chorus, Bridge,
  Instrumental, Solo and Outro. Repeat a memorable Chorus when appropriate.
- For every block describe its musical role, energy, rhythm, instrumentation,
  vocal delivery, production texture, transitions and atmosphere with concrete detail.
- For vocal blocks include `Lyrics: "..."` using the original lyrics from [LYRICS]
  for that section. Preserve the requested lyrics language. Do not invent a second,
  conflicting version of the lyrics.
- For instrumental music, never include Lyrics and explicitly state instrumental only.
- State genre, mood, instruments, approximate tempo or BPM, vocal range/timbre and
  production character. Keep instructions and lyrics visibly separated.
- Never mention the reference song, artist, copyrighted lyrics, imitation, camera
  directions, MiniMax, or Maestro in the final [LYRIA] prompt.
- The result must be paste-ready plain text, not JSON and not a Markdown code block.

Example shape only (write content specific to the current Story):

[LYRIA]
Original Title: Composition Breakdown
[0:00 - 0:12] Intro: Intensity: 3/10. A warm instrumental opening led by...
[0:12 - 0:42] Verse: Intensity: 4/10. Lyrics: "First original line / Second original line." The vocalist...
[0:42 - 1:05] Chorus: Intensity: 8/10. Lyrics: "Original recurring hook..." The arrangement expands...
[1:05 - 1:20] Bridge: Intensity: 6/10. A contrasting transition...
[1:20 - 1:45] Chorus: Intensity: 9/10. Lyrics: "Original recurring hook..." The final chorus...
[1:45 - 2:00] Outro: Intensity: 2/10. The main motif resolves and fades...
