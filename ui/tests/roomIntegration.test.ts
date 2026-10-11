import assert from 'node:assert/strict'
import { test } from 'node:test'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
function compile(scene3d: unknown) {
  const r=spawnSync(process.execPath,['--import','./node_modules/tsx/dist/loader.mjs','scripts/production-scene3d.mjs'],{input:JSON.stringify({scene3d,duration:5}),encoding:'utf8'})
  assert.equal(r.status,0,r.stderr)
  return r.stdout
}
test('legacy compiler output matches the pre-integration snapshot',()=>{
  // Since RENDER_RECIPE 3 the picture in the model's place is a grounded cutout as tall as the model (pictureStandIn.ts).
  const result=compile({template:'two-shot',cast:{subject_1:'/api/v1/file/person.png?workspace=test'}})
  assert.equal(createHash('sha256').update(result).digest('hex'),'16e5961b29a37b5f54335a1c4415371d276ae6db79615460eb763589c575bdf0')
})
test('production room camera and prop metadata survive compilation',()=>{
  const mold=JSON.parse(readFileSync('../app/shared/set_molds/despacho.json','utf8'));mold.dimensions=mold.sizes.medium;mold.size='medium'
  const document=JSON.parse(compile({template:'two-shot',background:{room:{mold}},roomCamera:'ots_b',cast:{lamp:{source:'/lamp.png',add:true,scale:.25,imageLook:{grounded:true},setItem:{heightM:.5},billboard:true}}}))
  assert.deepEqual(document.camera.eye,mold.cameras.find((c:{id:string})=>c.id==='ots_b').position)
  assert.equal(document.slots.find((s:{id:string})=>s.id==='lamp').setItem.heightM,.5)
})


test('inspector edits inherited props without freezing untouched set entries', async () => {
  const { visibleRoomItems, roomItemOverrides } = await import('../src/features/series/inspector/roomItems')
  const base = [{ objectId: 'lamp', scale: .2 }, { objectId: 'plant', scale: .8 }]
  const moved = { ...base[0], position: [1, .75, 0] }
  const overrides = roomItemOverrides(base, [moved])
  assert.deepEqual(overrides, { objects: [moved], removedSetObjects: ['plant'] })
  assert.deepEqual(visibleRoomItems(base, overrides.objects, overrides.removedSetObjects), [moved])
  assert.deepEqual(roomItemOverrides(base, base), { objects: [], removedSetObjects: [] })
})
