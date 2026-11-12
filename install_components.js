// Pinokio view of app/runtime/install_catalog.json: the one list of optional
// components. Install (choice dialog), Install/Update (runtime_setup.js) and the
// Advanced menu are all generated from it; add a component there, not here.
// The web UI and the server read the same file (app/services/install_catalog.py).
const runtime = require('./runtime_install')
const data = require('./app/runtime/install_catalog.json')

const components = data.components.map(component => ({
  ...component,
  env: runtime.catalog.engines[component.engine].env,
}))

// Choices travel between scripts as a comma-separated string, e.g. "sam,rigging".
const wanted = id => `(',' + (args.extras || '') + ',').includes(',${id},')`

const gib = value => `${value} GB`

// Install asks once what to add. Checkboxes cannot start ticked in Pinokio, so
// "unticked" means "not now", which is why the base install is never listed.
// The list is computed when the dialog opens: only extras this computer can run and
// that are not installed yet are offered, and with none left there is nothing to ask.
const offered = engine => `local.runtime.engines[${engine}].supported && !local.runtime.engines[${engine}].installed`

function chooseSteps() {
  const engines = JSON.stringify([...new Set(components.map(component => component.engine))])
  const gate = {when: `{{local.runtime.engines.wangp.supported && ${engines}.some(engine => ${offered('engine')})}}`}
  const fields = components.map(component => ({
    type: 'checkbox', key: component.id, engine: component.engine,
    title: `${component.title} (about ${gib(component.estimatedGiB)})`,
    description: component.summary,
  }))
  return [
    {...gate, method: 'input', params: {
      title: 'Choose what to install',
      confirm: 'Install',
      description: `<b>The studio and local generation (${gib(data.base.estimatedGiB)}) are always installed.</b> ` +
        'Tick the extras you want now. You can add or remove each one later in the app (Settings > Installation) or from the Advanced menu here. ' +
        'Free disk space: {{local.runtime.diskFreeGiB}} GB. {{(local.runtime.unavailable || []).join(" ")}}',
      form: `{{${JSON.stringify(fields)}.filter(field => ${offered('field.engine')})}}`,
    }},
    {...gate, method: 'local.set', params: {
      extras: '{{Object.keys(input || {}).filter(key => input[key]).join(",")}}',
    }},
  ]
}

// Install or refresh each optional component inside runtime_setup.js: a fresh
// Install adds the ones the user ticked, Update only refreshes those already present.
function setupSteps() {
  return components.flatMap(component => runtime.call(component.script).map(step => ({
    ...step,
    when: `{{local.runtime.engines.${component.engine}.supported && ((args.update && exists('${component.env}')) || ${wanted(component.id)})` +
      `${step.when ? ' && (' + step.when.slice(2, -2) + ')' : ''}}}`,
  })))
}

// Advanced menu entries. `gate: "always"` stays visible on every computer; the
// rest need a platform the engine supports (see filterUnsupported in pinokio.js).
function menuItems(info, gate) {
  return components.filter(component => component.menu.gate === gate).map(component => ({
    icon: component.menu.icon,
    text: `${info.exists(component.env) ? 'Update' : 'Install'} ${component.title}`,
    href: component.script,
  }))
}

// href -> engine for the entries that hide on unsupported hardware.
const gatedEngines = Object.fromEntries(
  components.filter(component => component.menu.gate !== 'always').map(component => [component.script, component.engine]))

module.exports = {data, components, chooseSteps, setupSteps, menuItems, gatedEngines}
