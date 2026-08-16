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

for (const [name, source] of [
  ["hunyuan3d2", install],
  ["hunyuan3d21", install],
  ["sam3", samInstall],
  ["unirig", rigInstall]
]) {
  check(source.includes(`vendors.${name}`), `${name}: install script does not use manifest`)
  check(source.includes(`${name}.revision`), `${name}: install does not reference revision`)
  check(source.includes(`${name}.marker`), `${name}: marker is not written by install`)
  check(source.includes("fetch --depth 1 origin"), `${name}: install lacks explicit fetch`)
  check(source.includes("checkout --detach"), `${name}: install lacks detached checkout`)
}

check(update.includes("hunyuan3d2.revision") && update.includes("hunyuan3d21.revision"), "update: Hunyuan revisions missing")
check(update.includes("sam3.marker") && update.includes("unirig.marker"), "update: optional vendor markers missing")
check(install.includes(".maestro_hunyuan3d_v1.installed"), "install: operational Hunyuan marker missing")
check(update.includes(".maestro_hunyuan3d_v1.installed"), "update: operational Hunyuan marker missing")
check(rigInstall.includes(".maestro_rigging_v1.installed"), "UniRig: operational service marker missing")
check(update.includes('uri: "sam_install.js"'), "update: SAM refresh is not wired")
check(update.includes('uri: "rigging_install.js"'), "update: UniRig refresh is not wired")
check(update.includes("git checkout --detach"), "update: detached checkout missing")
check(!/path:[^\n]*vendor[^\n]*[\s\S]{0,180}?git pull/.test(update), "update: vendor update still uses git pull")
check(start.includes('"event": "/(http:\\/\\/[0-9.:]+)/"'), "start: URL capture block changed")
check(start.includes('url: "{{input.event[1]}}"'), "start: captured URL is not input.event[1]")

console.log(`DEPS-03 offline contract smoke: ${checks.length} checks passed`)
