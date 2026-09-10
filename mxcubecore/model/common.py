from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
)


class CommonCollectionParamters(BaseModel):
    skip_existing_images: bool
    take_snapshots: int
    type: str
    label: str


class PathParameters(BaseModel):
    prefix: str
    subdir: str
    experiment_name: str | None = None

    class Config:
        extra = "ignore"


class LegacyParameters(BaseModel):
    take_dark_current: int
    inverse_beam: bool
    num_passes: int
    offset: float

    class Config:
        extra = "ignore"


class StandardCollectionParameters(BaseModel):
    num_images: int
    osc_start: float | None = None
    osc_range: float | None = None
    energy: float
    transmission: float
    resolution: float
    first_image: int
    kappa: float | None = None
    kappa_phi: float | None = None
    beam_size: str
    shutterless: bool
    selection: list = Field([])
    shape: str = ""
    create_point: bool = False

    class Config:
        extra = "ignore"


class BeamlineParameters(BaseModel):
    energy: float
    transmission: float
    resolution: float
    wavelength: float
    detector_distance: float
    beam_x: float
    beam_y: float
    beam_size_x: float
    beam_size_y: float
    beam_shape: str
    energy_bandwidth: float


class ISPYBCollectionParameters(BaseModel):
    flux_start: float
    flux_end: float
    start_time: datetime
    end_time: datetime
    chip_model: str
    mono_stripe: str
    number_of_rows: int | None = 0
    number_of_columns: int | None = 0
