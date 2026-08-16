"""SAM3 preprocessing wrapper."""

from .preprocessor import run_sam3_video

__all__ = ["build_sam3_image_model", "build_sam3_predictor", "run_sam3_video"]


def __getattr__(name: str):
    """Load the model builder only when one of its public factories is used.

    Importing ``preprocessing.sam3.preprocessor`` is common for orchestration
    and unit tests and must not eagerly import the complete SAM model graph.
    """
    if name in {"build_sam3_image_model", "build_sam3_predictor"}:
        from . import model_builder

        return getattr(model_builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
