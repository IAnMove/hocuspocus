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
  }),
  sam3: Object.freeze({
    url: "https://github.com/facebookresearch/sam3",
    path: "app/services/sam/sam3",
    revision: "8f0b7f4d4e7eda2ed606ebde6702c93359ad01da",
    marker: "app/services/sam/env/.maestro_sam3_8f0b7f4d4e7eda2ed606ebde6702c93359ad01da.installed"
  }),
  unirig: Object.freeze({
    url: "https://github.com/VAST-AI-Research/UniRig",
    path: "app/services/rigging/vendor/UniRig",
    revision: "6793c6640ff01c8fb389f3993434124bb43d2933",
    marker: "app/services/rigging/env/.maestro_unirig_6793c6640ff01c8fb389f3993434124bb43d2933.installed"
  })
})
