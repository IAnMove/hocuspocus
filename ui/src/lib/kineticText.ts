// Public entry. Callers keep importing from here; the implementation lives in kineticText/.
export {
  KINETIC_PRESETS, TEXT_FONTS, TEXT_ENTERS, TEXT_EXITS, TEXT_LOOPS, TEXT_WEIGHTS, TEXT_ALIGNS, TEXT_BOX_KINDS,
  TEXT_FONT_STACK, KINETIC_TEXT_SCHEMA, parseKineticTexts, kineticTextFields, isLegacyKineticText,
  derivedTextMotion, kineticTextState, paintKineticTexts, ensureTextFonts, displayedKineticText, wrapKineticLines,
} from './kineticText/index'
export type { KineticText, TextFont, TextEnter, TextExit, TextLoop, TextAlign, TextBox, TextBoxKind, TextCounter, TextFill, TextMotion, TextStroke, TextShadow, TextWeight } from './kineticText/index'
