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

    def __eq__(self, other: "OBSVideoSettings") -> bool:
        return (
            self.base_width == other.base_width
            and self.base_height == other.base_height
            and self.output_width == other.output_width
            and self.output_height == other.output_height
            and self.fps_numerator == other.fps_numerator
            and self.fps_denominator == other.fps_denominator
        )
