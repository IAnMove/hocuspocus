"""SAM status and segment preview.

The handlers are the launch functions, moved verbatim. They call the inpaint
service, which already loads SAM. The full server keeps these names.
"""

import os
import traceback

from fastapi import HTTPException, Request


async def sam_status_endpoint():
    """Check if the SAM segmentation service is available."""
    from services.inpaint_service import check_sam_status
    return check_sam_status()


async def segment_preview_endpoint(request: Request):
    """Preview mask segmentation on a video frame.

    Body: {
        video_path: str, text: str,
        start_time?: float, end_time?: float, frame_index?: int
    }
    """
    body = await request.json()
    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    text = body.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    # Resolve path
    if not os.path.isabs(video_path):
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        candidate = os.path.join(uploads_dir, os.path.basename(video_path))
        if os.path.isfile(candidate):
            video_path = candidate

    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {video_path}")

    try:
        import asyncio
        from services.inpaint_service import segment_image_preview, segment_video, ensure_sam_running

        sam_target = text

        sam_ready = await asyncio.to_thread(ensure_sam_running)
        if not sam_ready:
            raise HTTPException(status_code=503, detail="SAM service not available. Check installation.")

        full_video = body.get("full_video", False)
        if full_video:
            result = await asyncio.to_thread(
                segment_video,
                video_path=video_path,
                text=sam_target,
                start_time=float(body.get("start_time", 0)),
                end_time=float(body.get("end_time", -1)),
                mask_padding=int(body.get("mask_padding", 20)),
            )
        else:
            result = await asyncio.to_thread(
                segment_image_preview,
                video_path=video_path,
                text=sam_target,
                frame_index=body.get("frame_index", -1),
                start_time=float(body.get("start_time", 0)),
                end_time=float(body.get("end_time", -1)),
            )
        result["target"] = sam_target

        # Invert mask if requested (select everything EXCEPT the target)
        invert = body.get("invert_mask", False)
        if invert:
            # Invert the preview image: swap green overlay
            if result.get("mask_preview"):
                import base64, io
                from PIL import Image as _PILImg
                import numpy as _np
                preview_bytes = base64.b64decode(result["mask_preview"])
                img = _PILImg.open(io.BytesIO(preview_bytes)).convert("RGB")
                arr = _np.array(img)
                # Detect green overlay pixels (G channel dominant)
                green_mask = (arr[:, :, 1] > arr[:, :, 0] + 30) & (arr[:, :, 1] > arr[:, :, 2] + 30)
                # Create inverted overlay
                original = arr.copy()
                # Remove green from currently-green pixels
                arr[green_mask] = (arr[green_mask] * 2).clip(0, 255).astype(_np.uint8)  # approximate original
                # Add green to currently non-green pixels
                arr[~green_mask] = (arr[~green_mask] * 0.5 + _np.array([0, 255, 0]) * 0.5).astype(_np.uint8)
                buf = io.BytesIO()
                _PILImg.fromarray(arr).save(buf, format="PNG")
                result["mask_preview"] = base64.b64encode(buf.getvalue()).decode()

            # Invert the saved mask file
            if result.get("masks_path") and os.path.isfile(result["masks_path"]):
                import numpy as _np
                mask = _np.load(result["masks_path"])
                _np.save(result["masks_path"], ~mask)

            result["target"] = f"NOT {sam_target}"

        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
