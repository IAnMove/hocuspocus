// Install and Update share the same platform recipes and dependency checks.
const runtime = require("./runtime_install")
const components = require("./install_components")
module.exports = {
  requires: {bundle: "ai"},
  run: [
    // A first install is unfinished until the last step. Not written once app/env exists, so a failed
    // "add extras" run on a working install can never hide it (pinokio.js reads this marker).
    {when: "{{!exists('app/env')}}", method: "fs.write", params: {
      path: "app/.install.incomplete",
      text: "The first install did not finish. Run Install again.",
    }},
    ...runtime.preflight(),
    // The core/remote studio has no optional engines, so it is not asked.
    ...components.chooseSteps(),
    // The core/remote studio downloads no local models, so it skips the Hub login.
    ...runtime.hfLogin("{{local.runtime.engines.wangp.supported}}"),
    ...runtime.call("runtime_setup.js", {update: false, extras: "{{local.extras || ''}}"}),
    // runtime.call stops the script when the setup did not succeed, so this runs only after a full install.
    {when: "{{exists('app/.install.incomplete')}}", method: "fs.rm", params: {path: "app/.install.incomplete"}},
    {method: "input", params: {
      title: "Installation completed",
      description: "The studio is installed. {{(local.runtime.unavailable || []).join(' ')}} {{local.runtime.engines.wangp.supported ? 'Add or remove extras any time in Settings > Installation. ' : ''}}Click Start."
    }}
  ]
}
