// Optional isolated runtime; system/examples/comfy/install.js:50–59.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [
    ...runtime.preflight('creation_models'),
    ...runtime.installEngines(['creation_models']),
    {method: 'script.return', params: {success: true}},
  ],
}
