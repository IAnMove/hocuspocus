"""Standard humanoid rig: Mixamo bone names, skin weights, and reusable clips.

The Hunyuan3D worker imports this package. The app process should not need
pygltflib; GLB writing stays behind ``gltf_export``.
"""

from services.humanoid_rig.errors import NotHumanoid

__all__ = ["NotHumanoid"]
