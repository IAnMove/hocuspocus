# Tijeral — how to make the cut-paper chapter in HocusPocus

The example is a **Story Lab** chapter. Each beat opens **Video 2D** (Scene Animator)
so you can edit the shot. The assembled episode is **not** an MP4 baked outside Hocus.

## Path (do this in the app)

1. **Story Lab** → **Load Tijeral cut-paper example**.
   Lore (world, cast, relationships, structure) is already filled.
   Nilo, Berta, Kito, Rami, Paca and Lino are also inserted into the
   Character Kit library of the current workspace (skipped if that id already
   exists). Story characters link those kits (`characterKitRef`).
2. Open **Structure**. Each beat has **Open in Video 2D**.
   - Plano 1 plaza → establishing shot
   - Plano 2 cola fría → Nilo / Berta dialogue
   - Plano 3 sticker → Kito slides in
3. In **Video 2D** you can move layers, swap mouths, attach speech, export MP4.
   Each speaking puppet is **one transparent body** plus four small paper visemes
   (`closed` `small` `wide` `round`) parented to that body. Do not stack opaque
   full-face copies. Talking must not change the brows.
4. Optional: a later beat can use **Video 3D** (`sceneLink.editor = video3d`) if a shot needs depth. This gag stays 2D.
5. Voices: each library character has a local Qwen3 CustomVoice preset.
   Example WAVs exist in **Spanish** (`vo-*-nilo-1.wav`) and **English**
   (`vo-*-nilo-1-en.wav`). Import `shots/` or `shots/en/`. Mouth visemes use
   Hocus audio analysis (`aligned-audio`) then **Export MP4** from Video 2.5D.
   Do not clone actors. The planner treats spoken vowels in Spanish and English
   (`you`/`see`/`hielo`); consonants are not silence.
6. MiniMax Image uses the linked kit still (`identityReference` or body) as
   `subject_reference`. Bundled `/examples/` stills are uploaded first.

## What you author vs what the kit ships

| You (in Hocus) | Kit (bundled) |
|---|---|
| Edit lore in Story Lab | Bible + filled Story project |
| Open/edit each beat in Video 2D | Three `.maestro-scene.json` shots |
| Generate more puppets in Character Kit (style Recorte de papel) | Nilo, Berta, Kito stills |
| Record or Qwen-TTS the lines | Example WAVs to save time |
| Export MP4 from Video 2D | — |

## Face = front card

Square/rectangle glued on the paper head. Not a round portrait in a circle.
Not `tv-head-humanoid.glb`.

## Files

- `ui/src/features/cutPaper/characterKits.ts` — library characters + Qwen presets
- `ui/src/features/cutPaper/storyProject.ts` — Story Lab chapter
- `ui/src/features/cutPaper/pilot.ts` — Video 2D compilers
- `ui/public/examples/cut-paper/shots/` — one scene per beat
