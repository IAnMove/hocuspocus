#!/usr/bin/env node
// Offline DEPS-03 contract smoke. It inspects launcher source only; no
// network, package manager, or vendor checkout is required.
const fs = require("node:fs")
const path = require("node:path")

const root = path.resolve(__dirname, "..")
const read = (name) => fs.readFileSync(path.join(root, name), "utf8")
const vendors = require(path.join(root, "vendor_revisions.js"))
const install = read("install.js")
const update = read("update.js")
const samInstall = read("sam_install.js")
const rigInstall = read("rigging_install.js")
const hunyuanInstall = read("hunyuan3d_install.js")
const start = read("start.js")

const checks = []
function check(ok, message) {
  checks.push({ ok, message })
  if (!ok) throw new Error(message)
}

for (const [name, vendor] of Object.entries(vendors)) {
  check(/^[0-9a-f]{40}$/.test(vendor.revision), `${name}: revision is not a full SHA-1`)
  check(vendor.marker.includes(vendor.revision), `${name}: marker omits revision`)
  check(vendor.path.startsWith("app/"), `${name}: checkout path must be relative under app/`)
}

const runtime = require(path.join(root, "runtime_install.js"))
const setup = require(path.join(root, "runtime_setup.js"))
const plans = runtime.installEngines(Object.keys(runtime.catalog.engines))
for (const [name, vendor] of Object.entries(vendors)) {
  const steps = runtime.vendorSteps(name)
  const source = JSON.stringify(steps)
  check(source.includes(`fetch --depth 1 origin ${vendor.revision}`), `${name}: explicit revision fetch missing`)
  check(source.includes(`checkout --detach ${vendor.revision}`), `${name}: detached checkout missing`)
  check(!source.includes('git pull'), `${name}: vendor must not follow branch HEAD`)
  check(plans.some(s => s.method === 'fs.write' && s.params.path === vendor.marker), `${name}: verified marker missing`)
}
for (const source of [install, update]) {
  check(source.includes('runtime_setup.js'), 'Install/Update must share setup')
}
for (const [engine, source] of [['hunyuan3d', hunyuanInstall], ['sam', samInstall], ['rigging', rigInstall]]) {
  check(source.includes(`installEngines(['${engine}'])`), `${engine}: installer bypasses profile builder`)
  check(setup.run.some(s => s.method === 'script.start' && s.params.uri === `${engine}_install.js`), `${engine}: optional update missing`)
}
check(start.includes('"event": "/(http:\\/\\/[0-9.:]+)/"'), "start: URL capture block changed")
check(start.includes('url: "{{input.event[1]}}"'), "start: captured URL is not input.event[1]")

console.log(`DEPS-03 offline contract smoke: ${checks.length} checks passed`)
