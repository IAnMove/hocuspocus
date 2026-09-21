# HOWUSEIT — Tijeral cut-paper example

Operator guide for the bundled **limited-animation** chapter. This is original
HocusPocus construction-paper work, not a clone of another show and not a
MiniMax H3 clip.

UI: **Story Lab** library → **Load Tijeral cut-paper example**
(`data-testid="load-tijeral-example"`). Code: `ui/src/features/cutPaper/`.
Public assets: `ui/public/examples/cut-paper/`. In-app tutorial section:
Help → Cut-paper.

Related: bundled [HOWTO](../../ui/public/examples/cut-paper/HOWTO.md) and
[BIBLIA](../../ui/public/examples/cut-paper/BIBLIA.md),
[Character Kits](../character-kits/HOWUSEIT.md),
[2D speech quality](../character-kits/SPEECH_QUALITY.md).

---

## 1. What this system is

A Story Lab project plus Character Kits that open **Video 2D** scenes. Beats
are not baked MP4s.

| Piece | Identity | Job |
|---|---|---|
| Story | `story-tijeral-cut-paper` | 78 s chapter *Tijeral · la fuente* |
| Town | Tijeral, Sierra Cartulina | Highland paper village; winter is paper snow |
| Speaking kits | `tijeral-nilo`, `tijeral-berta`, `tijeral-kito` | Body PNG + four paper mouths + Qwen CustomVoice |
| Silent kits | `tijeral-rami`, `tijeral-paca`, `tijeral-lino` | Look notes and voice presets only |
| Shots | `shots/01-plaza`, `02-talk`, `03-sticker` | Video 2D JSON the beats link to |

Use this when you need a **known, editable paper puppet** to learn Story Lab →
Video 2D → mouths. Use Series **Generate all** when you want the same pipeline
on *your* cast. Use H3 when you want a performed face.

---

## 2. Hard limits

1. **Not a top-level tab.** The loader lives on the Story Lab library chrome.
2. **Idempotent kits.** `seedTijeralCharacterKits` inserts missing ids only. A
   kit the user already saved is never overwritten.
3. **Idempotent story.** A second click keeps the existing
   `story-tijeral-cut-paper` project and only fills missing `characterKitRef`
   values. It does not reset premise, beats, or approvals.
4. **Four mouths, not nine.** Bundled visemes are `closed`, `small`, `wide`,
   `round` (`CUT_PAPER_VISEMES`). That is enough for the compiled 2D scenes.
   Series phonetic regeneration of a *new* speaking shot still wants the nine
   approved slots — complete the kit in Character Creator before that batch.
5. **Qwen CustomVoice, not clones.** Presets are `dylan` / `serena` / `sohee` /
   `ryan` / `vivian` / `eric` with original acting notes. Do not replace them
   with celebrity references. Custom recorded voices (`qwen3_tts_base`) are a
   different kit field; see [Character Kits](../character-kits/HOWUSEIT.md).
6. **No private GLB body.** The compiler rejects a Tijeral scene that smuggles
   a mesh walker (`assertCutPaperKitHasNoPrivateGlb`).
7. **Duration is authored.** The pilot is 78 seconds. Importing a sliced shot
   must not keep a t=78 keyframe or Scene Animator will stretch the clip.

---

## 3. Operator workflow

1. Open **Story Lab**. Click **Load Tijeral cut-paper example**.
2. Confirm the story title *Tijeral · la fuente* and the three kid cards
   (Nilo Carda, Berta Miga, Kito Veleta). Adults exist as bible rows.
3. Wait for kit seeding. Failures are logged; the story still opens. Reload
   the library if a speaking kit is missing its body PNG.
4. Open **Structure**. Each beat has **Open in Video 2D**
   (`01-plaza`, `02-talk`, `03-sticker`). English copies live under
   `shots/en/`.
5. Play in Scene Animator. Mouths are opacity holds compiled from the script
   (`CUT_PAPER_PILOT_SCRIPT` ES, `_EN` English). Voices are bundled WAVs
   under `/examples/cut-paper/voices/`.
6. Edit layers, save a copy to the output folder, export MP4, or import the
   take into Series. Saving writes a *new* scene file; the bundled example
   stays in `ui/public`.

Spanish is the authored spoken language (`Español de España`). The Help
language switch does not rewrite this story.

---

## 4. Cast and voice contract

| Id | Name | Voice id | Speaks in the 78 s pilot |
|---|---|---|---|
| `nilo` | Nilo Carda | `dylan` | Yes |
| `berta` | Berta Miga | `serena` | Yes |
| `kito` | Kito Veleta | `sohee` | Yes |
| `rami` | Rami Tambo | `ryan` | No |
| `paca` | Doña Paca | `vivian` | No |
| `lino` | Lino Horna | `eric` | No |

Look notes persist on the kit (silhouette, hat, costume). Story acting notes
are not the TTS engine.

Visual rules encoded in the bible (do not “fix” them):

- Square frontal face cards, not round portraits-in-a-circle.
- Mouths change without changing brows.
- No orange parka, no pom-pom beanie, no TV-head walker.
- Mustard / navy / olive / teal-cream; mustard is not orange.

---

## 5. Data the loader writes

```text
StoryProject id=story-tijeral-cut-paper
  beats[].sceneLink → /examples/cut-paper/shots/{locale?}/…maestro-scene.json
  characters[].characterKitRef → { id: tijeral-<id>, workspace }

CharacterKit id=tijeral-<id>
  lookNotes, voice { provider: local, model: qwen3_tts_customvoice, voiceId }
  speaking only: identityReference (canonical JPG), base (body PNG),
  mouth { closed, small, wide, round } → /examples/cut-paper/mouths/paper-*.png
  provenance.method = tijeral-cut-paper
```

`workspace` on the kit ref is the physical output folder (`default` unless
the loader was called with another folder). It is not a Workspace collection
ID.

---

## 6. Pitfalls

- Asking the Wizard to “open the Tijeral tab.” There is no such tab.
- Expecting a second Load click to reset the chapter. It will not.
- Feeding the bundled four mouths into Series **Generate all** and treating
  a preflight error as a broken example. Complete the nine slots first.
- Replacing paper bodies with Hunyuan GLBs “for quality.” The kit compiler
  rejects that mix.
- Treating the Help screenshot of Story Lab as the Tijeral loader. The
  button is on the library chrome, not a dedicated studio.

---

## 7. Files to read next

| Path | Why |
|---|---|
| `ui/src/features/cutPaper/bible.ts` | Cast, town, four visemes |
| `ui/src/features/cutPaper/storyProject.ts` | Story payload and beat links |
| `ui/src/features/cutPaper/characterKits.ts` | Kit seed, Qwen presets, no-overwrite |
| `ui/src/features/cutPaper/pilot.ts` | 78 s compile and shot slices |
| `ui/src/features/cutPaper/puppet.ts` | Layer graph and GLB guard |
| `ui/tests/cutPaper.test.ts` | Identity and voice contract |
| `ui/src/i18n/locales/en/help.json` | In-app tutorial copy |
