"""Inspect canonical image/video references for typed generation.video.

SFX keeps ``resources("video")``. This adapter is a distinct ``studio_video``
path so image/video references of Wan Text2Video never reuse the MMAudio
guide resolver. Portable identities stay on the receipt; resolved paths stay
in the detached worker map.
"""

from __future__ import annotations

from copy import deepcopy
import math
import subprocess

from PIL import Image

from services.studio_image_resources import IMAGE_FIELDS, StudioImageResources, file_identity
from services.video_editor import probe_media


VIDEO_FIELDS = ("video_guide", "video_mask", "video_source")


class StudioVideoResources(StudioImageResources):
    """Resolve image and optional video references for generation.video."""

    media_kind = "image"

    def _resolve(self, value, kind):
        previous = self.media_kind
        self.media_kind = kind
        try:
            return self._media(value)
        finally:
            self.media_kind = previous

    def _image_identity(self, path, url, workspace, role, index):
        identity = file_identity(path)
        with Image.open(path) as picture:
            picture.verify()
        return {
            "role": role,
            "index": index,
            "url": url,
            "workspace": workspace,
            **identity,
        }

    def _video_identity(self, path, url, workspace, role, index):
        identity = file_identity(path)
        try:
            information = probe_media(path)
        except subprocess.TimeoutExpired as error:
            raise ValueError("A selected video reference could not be inspected in time") from error
        except (OSError, TypeError, ValueError) as error:
            raise ValueError("A selected video reference is not a readable video") from error
        duration = information.get("duration")
        width = information.get("width")
        height = information.get("height")
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(float(duration)) or float(duration) <= 0):
            raise ValueError("A selected video reference has no finite positive duration")
        if type(width) is not int or width <= 0 or type(height) is not int or height <= 0:
            raise ValueError("A selected video reference has invalid dimensions")
        return {
            "role": role,
            "index": index,
            "url": url,
            "workspace": workspace,
            "duration_seconds": float(duration),
            "width": width,
            "height": height,
            "fps": information.get("fps"),
            **identity,
        }

    def _prepare_field(self, working, resources, field, kind, identity):
        raw = working.get(field)
        if raw in (None, "", []):
            return
        values = raw if isinstance(raw, list) else [raw]
        paths = []
        for index, value in enumerate(values):
            if value in (None, ""):
                paths.append("" if isinstance(raw, list) else None)
                continue
            if not isinstance(value, str):
                raise ValueError(f"input.params.{field} must be a canonical {kind} reference")
            path, workspace = self._resolve(value, kind)
            resources.append(identity(path, value, workspace, field, index))
            paths.append(path)
        working[field] = paths if isinstance(raw, list) else paths[0]

    def prepare_media(self, params):
        working = deepcopy(params)
        resources = []
        for field in IMAGE_FIELDS:
            self._prepare_field(working, resources, field, "image", self._image_identity)
        for field in VIDEO_FIELDS:
            self._prepare_field(working, resources, field, "video", self._video_identity)
        return working, resources
