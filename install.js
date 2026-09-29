// Install and Update share the same platform recipes and dependency checks.
const runtime = require("./runtime_install")
module.exports = {
  requires: {bundle: "ai"},
  run: [
    ...runtime.preflight(),
    // Public models work without login. This only lifts Hub rate limits, so the
    // core/remote studio (no local models) skips it.
    {when: "{{local.runtime.engines.wangp.supported}}", method: "hf.login", params: {wait: false}},
    ...runtime.call("runtime_setup.js", {update: false}),
    {method: "input", params: {
      title: "Installation completed",
      description: "Check the runtime report above, then click Start."
    }}
  ]
}
