// Loaded after git pull too, so Update executes the new revision's recipes.
const runtime = require('./runtime_install')
const components = require('./install_components')
module.exports = {
  requires: {bundle: 'ai'},
  run: [
    // Repair React before lengthy native installs, including on an unchanged Git revision.
    ...runtime.call('ui_build.js'),
    ...runtime.preflight(),
    {when: "{{!exists('app/postprocessing/seedvc/__init__.py')}}", method: 'shell.run', params: {
      message: runtime.guarded('git clone --depth 1 --branch v1.0.0 https://github.com/Blizaine/maestro-seedvc app/postprocessing/seedvc'),
    }},
    ...runtime.installEngines(['core', 'wangp']),
    ...runtime.call('speech_install.js'),
    // Optional components (install_catalog.json): Install adds the ones ticked in its dialog,
    // Update refreshes only those whose environment already exists.
    ...components.setupSteps(),
    {method: 'log', params: {
      raw: '{{"HocusPocus runtime recipes checked.\\r\\n" + local.runtime.summary.join("\\r\\n")}}',
    }},
    {method: 'script.return', params: {success: true}},
  ],
}
