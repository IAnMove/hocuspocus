import assert from 'node:assert/strict'
import test from 'node:test'
import { kineticTextState, parseKineticTexts, paintKineticTexts } from '../src/lib/kineticText.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'
import { sceneToRecipe } from '../src/lib/sceneToRecipe.ts'
import { parseSceneRecipe, compileSceneRecipe } from '../src/lib/sceneRecipe.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { remountScene3DTemplate } from '../src/features/scene3d/templates.ts'

const cue = parseKineticTexts([{id:'title', text:'¡Código 🧙!\nLínea 2', start:1, end:4, preset:'typewriter',font:'mono'}])[0]

test('text time sampling supports seeking and exclusive end times', () => {
  assert.equal(kineticTextState(cue, .9), null)
  assert.equal(kineticTextState(cue, 4), null)
  const early = kineticTextState(cue, 1.1)
  assert.ok(kineticTextState(cue, 3).letters > early.letters)
  assert.deepEqual(kineticTextState(cue, 1.1), early)
  for (const preset of ['impact','rise','wave']) assert.equal(kineticTextState({...cue,preset}, 2).opacity, 1)
})

test('untrusted text imports are bounded and literal text is preserved', () => {
  const texts = parseKineticTexts([null, 5, {...cue, x:Infinity, size:999}, cue, {...cue,id:'bad',end:0}, {...cue,id:'huge',text:'x'.repeat(241)}])
  assert.equal(texts.length, 1)
  assert.equal(texts[0].text, cue.text)
  assert.equal(texts[0].x, 50)
  assert.equal(texts[0].size, 25)
  assert.equal(parseKineticTexts(Array.from({length:60}, (_,i)=>({...cue,id:String(i)}))).length,48)
  assert.equal(parseKineticTexts([{...cue,font:'untrusted-font'}])[0].font,undefined)
})

test('the same text survives 2D file, recipe, compiled scene and 3D template round trips', () => {
  const scene = {version:1,width:1280,height:720,fps:30,duration:5,name:'text round trip',texts:[cue],layers:[{id:'bg',name:'BG',type:'image',source:'/image.png',visible:true,z:0,transform:{x:50,y:50,scale:1,opacity:1,rotation:0},animation:{start:{},end:{},duration:5,curve:'linear'}}]}
  const reopened = parseSceneFile(serializeSceneFile(scene))
  const recipe = parseSceneRecipe(JSON.parse(JSON.stringify(sceneToRecipe(reopened))))
  assert.deepEqual(compileSceneRecipe(recipe,{},url=>url).texts, [cue])
  const doc = createDefaultScene3DDocument(); doc.texts = [cue]
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(remountScene3DTemplate('coder-room',restored).texts,[cue])
  restored.texts[0].text = 'changed'
  assert.equal(doc.texts[0].text, cue.text)
})

test('all text presets paint visible glyphs and restore the canvas state', () => {
  let saves=0, restores=0; const glyphs=[]
  const ctx={save(){saves++},restore(){restores++},measureText(t){return {width:t.length*20}},translate(){},rotate(){},scale(){},strokeText(){},fillText(t){glyphs.push(t)}}
  for(const preset of ['impact','rise','typewriter','wave']) paintKineticTexts(ctx,1280,720,3,[{...cue,preset}])
  assert.equal(saves,4);assert.equal(restores,4)
  assert.ok(glyphs.includes('¡Código 🧙!'));assert.ok(glyphs.includes('🧙'))
  assert.match(ctx.font,/ui-monospace, monospace$/)
  paintKineticTexts(ctx,1280,720,3,[{...cue,font:undefined}])
  assert.match(ctx.font,/system-ui, sans-serif$/)
})
