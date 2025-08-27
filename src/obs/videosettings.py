"""
OBS video settings.
"""

from dataclasses import dataclass


@dataclass
class OBSVideoSettings:
    """OBS video settings."""

    base_width: int
    base_height: int
    output_width: int
    output_height: int
    fps_numerator: float
    fps_denominator: float
