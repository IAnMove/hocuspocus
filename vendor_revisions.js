// DEPS-03: every external source checkout is pinned to an immutable commit.
// Keep this manifest as the single source of truth for install/update scripts.
// The revisions were resolved from the upstream GitHub commit histories on
// 2026-08-16; see docs/DEPS-03_VENDOR_REVISIONS.md for the evidence URLs.
module.exports = Object.freeze({
  hunyuan3d2: Object.freeze({
    url: "https://github.com/Tencent-Hunyuan/Hunyuan3D-2",
    path: "app/services/hunyuan3d/vendor/Hunyuan3D-2",
    revision: "f8db63096c8282cb27354314d896feba5ba6ff8a",
    marker: "app/services/hunyuan3d/env/.maestro_hunyuan3d_2_f8db63096c8282cb27354314d896feba5ba6ff8a.installed"
  }),
  hunyuan3d21: Object.freeze({
    url: "https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1",
    path: "app/services/hunyuan3d/vendor/Hunyuan3D-2.1",
    revision: "82920d643c0dc2f7bfd7255f45f62d386edfe60c",
    marker: "app/services/hunyuan3d/env/.maestro_hunyuan3d_21_82920d643c0dc2f7bfd7255f45f62d386edfe60c.installed"
  })
})
