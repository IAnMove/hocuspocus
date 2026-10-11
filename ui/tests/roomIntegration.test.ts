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
  const result=compile({template:'two-shot',cast:{subject_1:'/api/v1/file/person.png?workspace=test'}})
  assert.equal(createHash('sha256').update(result).digest('hex'),'e708c002b4058f13d0e74d3902826a14d291415b358d38b23d3f7bf1f9d243e1')
})
test('production room camera and prop metadata survive compilation',()=>{
  const mold=JSON.parse(readFileSync('../app/shared/set_molds/despacho.json','utf8'));mold.dimensions=mold.sizes.medium;mold.size='medium'
  const document=JSON.parse(compile({template:'two-shot',background:{room:{mold}},roomCamera:'ots_b',cast:{lamp:{source:'/lamp.png',add:true,scale:.25,imageLook:{grounded:true},setItem:{heightM:.5},billboard:true}}}))
  assert.deepEqual(document.camera.eye,mold.cameras.find((c:{id:string})=>c.id==='ots_b').position)
  assert.equal(document.slots.find((s:{id:string})=>s.id==='lamp').setItem.heightM,.5)
})
