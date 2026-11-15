"""
Pydantic schemas for AresPath API v1.

Coordinate convention (confirmed):
  body                 = Mars
  latitude_type        = planetocentric
  longitude_direction  = positive_east
  longitude_domain     = -180_to_180
  angular_unit         = degrees

Display coordinate space (arespath_display_v1):
  X = East, metres
  Y = North, metres
  Region-specific projection definition and origin.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import VERSION, PROJECT_NAME
from app.scientific.dem.models import CoverageStatus


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthStatus(BaseModel):
    status: str = "OK"
    project: str = PROJECT_NAME
    version: str = VERSION
    body: str = "Mars"
    datum: str = "IAU:2015:49900"
    dem_available: bool = False
    dem_loaded: bool = False
    dem_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Shared planetary coordinate reference
# ---------------------------------------------------------------------------

class MarsCoordinateReference(BaseModel):
    """
    Canonical Mars coordinate reference used in every request and
    embedded in every metadata response.
    """
    body: Literal["Mars"] = "Mars"
    latitude_type: Literal["planetocentric"] = "planetocentric"
    longitude_direction: Literal["positive_east"] = "positive_east"
    longitude_domain: Literal["-180_to_180"] = "-180_to_180"
    angular_unit: Literal["degrees"] = "degrees"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoutingProfile(str, Enum):
    SAFE = "safe"
    FAST = "fast"
    SCIENCE = "science"
    DEMONSTRATION = "demonstration"


class RouteAlgorithm(str, Enum):
    ASTAR = "a_star"
    DIJKSTRA = "dijkstra"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Route request
# ---------------------------------------------------------------------------

class MarsPoint(BaseModel):
    """
    A Mars surface coordinate in the confirmed convention:
      planetocentric latitude, positive-east longitude, degrees, -180..180.
    """
    latitude: float = Field(..., ge=-90.0, le=90.0,
                            description="Planetocentric latitude in degrees [-90, 90]")
    longitude: float = Field(..., ge=-180.0, le=180.0,
                             description="Positive-east longitude in degrees [-180, 180]")

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def reject_boolean_coordinates(cls, v: object, info) -> object:
        if isinstance(v, bool):
            raise ValueError(f"{info.field_name} cannot be a boolean value, got {v!r}")
        return v


class RouteRequest(BaseModel):
    region_id: str = Field(...,
                           description="Identifier for the Mars surface region (e.g. 'jezero_crater')",
                           min_length=1)
    start: MarsPoint = Field(..., description="Start coordinate in confirmed Mars convention")
    destination: MarsPoint = Field(..., description="Destination coordinate in confirmed Mars convention")
    coordinate_reference: MarsCoordinateReference = Field(
        default_factory=MarsCoordinateReference,
        description="Must match the confirmed AresPath Mars convention"
    )
    routing_profile: RoutingProfile = Field(
        default=RoutingProfile.SAFE,
        description="Traversal optimisation profile"
    )

    @field_validator("coordinate_reference")
    @classmethod
    def validate_crs(cls, v: MarsCoordinateReference) -> MarsCoordinateReference:
        if v.body != "Mars":
            raise ValueError("coordinate_reference.body must be 'Mars'")
        if v.latitude_type != "planetocentric":
            raise ValueError("coordinate_reference.latitude_type must be 'planetocentric'")
        if v.longitude_direction != "positive_east":
            raise ValueError("coordinate_reference.longitude_direction must be 'positive_east'")
        if v.longitude_domain != "-180_to_180":
            raise ValueError("coordinate_reference.longitude_domain must be '-180_to_180'")
        return v


# ---------------------------------------------------------------------------
# Route response — geometry
# ---------------------------------------------------------------------------

class DisplayPoint(BaseModel):
    """
    A 2-D point in the arespath_display_v1 coordinate space.
      X = East  (metres from region origin)
      Y = North (metres from region origin)
    """
    x: float = Field(..., description="Easting from region display origin, metres")
    y: float = Field(..., description="Northing from region display origin, metres")


class RouteGeometry(BaseModel):
    coordinate_space: Literal[
    "arespath_display_v1",
    "jezero_dem_native_projected_crs",
] = "arespath_display_v1"
    points: List[DisplayPoint] = Field(...,
                                       description="Ordered waypoints in display-frame metres")


# ---------------------------------------------------------------------------
# Route response — terrain summary
# ---------------------------------------------------------------------------

class TerrainSummary(BaseModel):
    min_elevation_m: Optional[float] = Field(None, description="Minimum elevation along route (metres)")
    max_elevation_m: Optional[float] = Field(None, description="Maximum elevation along route (metres)")
    max_slope_deg: Optional[float] = Field(None, description="Maximum terrain slope along route (degrees); None if not evaluated")
    hazard_count: Optional[int] = Field(None, description="Number of identified hazard zones crossed; None if not evaluated")
    surface_types: List[str] = Field(default_factory=list,
                                     description="Surface material categories encountered")
    evaluation_status: str = Field(default="measured_elevation_only",
                                   description="Distinguishes measured, derived, and unevaluated metrics")


# ---------------------------------------------------------------------------
# Route response
# ---------------------------------------------------------------------------

class RouteResponse(BaseModel):
    status: Literal["success"] = "success"
    route_id: str = Field(..., description="Unique identifier for this computed route")
    region_id: str = Field(..., description="Region the route was computed within")
    algorithm: RouteAlgorithm = Field(..., description="Routing algorithm that produced the route")
    distance_m: float = Field(..., ge=0.0, description="Great-circle distance approximation in metres")
    route_geometry: RouteGeometry
    terrain_summary: TerrainSummary
    warnings: List[str] = Field(default_factory=list,
                                description="Non-fatal advisory messages about data quality")
    data_sources: List[str] = Field(default_factory=list,
                                    description="Dataset identifiers used to compute this route")


# ---------------------------------------------------------------------------
# Error response (PRD standard)
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorDetail
    request_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Region metadata
# ---------------------------------------------------------------------------

class DisplayProjectionDefinition(BaseModel):
    """
    Describes the map projection used for the arespath_display_v1 frame
    for a specific region.

    NOTE: Actual projection parameters (e.g. standard parallels, false
    easting/northing) are dataset-specific and must be populated from
    verified configuration files, not invented here.  Fields are typed
    Optional and default to None to make the absence explicit.
    """
    projection_name: Optional[str] = Field(None,
        description="PROJ/OGC projection name, e.g. 'Equirectangular', 'Stereographic'")
    proj4_string: Optional[str] = Field(None,
        description="PROJ4/PROJ6 string — populated from verified dataset config only")
    wkt2_string: Optional[str] = Field(None,
        description="OGC WKT2 string — populated from verified dataset config only")
    datum: str = "IAU:2015:49900"
    semi_major_axis_m: float = Field(3_396_190.0,
        description="Mars IAU2015 mean volumetric sphere radius (metres)")
    is_spherical: bool = True


class DisplayOrigin(BaseModel):
    """
    Region-specific origin of the arespath_display_v1 local display frame.

    NOTE: Actual numeric values depend on the verified terrain dataset for
    the region.  Populated from configuration; never invented.
    """
    description: str = Field(..., description="Human-readable description of origin choice")
    latitude_deg: Optional[float] = Field(None, description="Origin latitude (planetocentric degrees)")
    longitude_deg: Optional[float] = Field(None, description="Origin longitude (positive-east degrees)")
    source: Optional[str] = Field(None, description="Reference establishing this origin")


class TransformationParameters(BaseModel):
    """
    Documents the mathematical transformation from the source dataset CRS
    to the arespath_display_v1 local frame.

    Parameters are populated only from verified dataset documentation.
    """
    method: str = Field(...,
        description="Transformation method name, e.g. 'Equirectangular projection + local offset'")
    parameters: Optional[Dict[str, Any]] = Field(None,
        description="Numeric parameters — populated from verified config only, never invented")
    notes: Optional[str] = None


class DatasetProvenance(BaseModel):
    name: str
    agency: str
    instrument: Optional[str] = None
    mission: Optional[str] = None
    resolution_m_per_px: Optional[float] = None
    coverage: Optional[str] = None
    reference_url: Optional[str] = None
    is_synthetic: bool = Field(False,
        description="True when data is synthetic/placeholder, not real NASA observations")
    synthetic_description: Optional[str] = Field(None,
        description="If synthetic, describes what real data would replace it")


# ---------------------------------------------------------------------------
# Layer catalogue and metadata
# ---------------------------------------------------------------------------

class LayerType(str, Enum):
    """
    Categories of terrain / map layer.

    Values are machine-readable identifiers used in filtering and display.
    """
    DEM = "dem"                          # Digital Elevation Model
    ORTHOIMAGE = "orthoimage"            # Optical orthorectified image
    SLOPE = "slope"                      # Derived slope map
    HAZARD = "hazard"                    # Hazard / traversability map
    GEOLOGIC = "geologic"                # Geologic classification map
    CUSTOM = "custom"                    # Other / user-defined


class LayerCoordinateFrame(BaseModel):
    """
    Coordinate frame metadata attached to every layer.

    Mirrors the region-level metadata contract so the frontend can verify
    consistency between region and layer without a separate lookup.

    NOTE: Numeric parameters (proj4_string, origin coordinates) are null
    until a verified dataset is integrated.  Never invented.
    """
    coordinate_space: Literal["arespath_display_v1"] = "arespath_display_v1"
    source_crs: MarsCoordinateReference = Field(
        default_factory=MarsCoordinateReference,
        description="Source CRS of the underlying dataset"
    )
    x_axis: Literal["East, metres"] = "East, metres"
    y_axis: Literal["North, metres"] = "North, metres"
    projection_name: Optional[str] = Field(
        None,
        description="PROJ/OGC projection name — populated from verified dataset config only"
    )
    proj4_string: Optional[str] = Field(
        None,
        description="PROJ4/PROJ6 string — populated from verified dataset config only"
    )
    datum: str = "IAU:2015:49900"
    semi_major_axis_m: float = Field(
        3_396_190.0,
        description="Mars IAU2015 mean volumetric sphere radius (metres)"
    )
    origin_latitude_deg: Optional[float] = Field(
        None,
        description="Display-frame origin latitude (planetocentric degrees) — from verified config"
    )
    origin_longitude_deg: Optional[float] = Field(
        None,
        description="Display-frame origin longitude (positive-east degrees) — from verified config"
    )
    transformation_method: Optional[str] = Field(
        None,
        description="Transformation method from source CRS to display frame — from verified config"
    )
    transformation_parameters: Optional[Dict[str, Any]] = Field(
        None,
        description="Numeric transformation parameters — from verified config only, never invented"
    )


class LayerCatalogueEntry(BaseModel):
    """
    Summary record returned in the layer catalogue list.

    One entry per available layer.  When no verified layers exist the
    catalogue list is empty and the response carries an explicit notice.
    """
    layer_id: str = Field(..., description="Stable identifier for this layer")
    region_id: str = Field(..., description="Region this layer covers")
    layer_type: LayerType = Field(..., description="Category of terrain / map layer")
    display_name: str = Field(..., description="Human-readable layer name")
    description: Optional[str] = None
    is_verified: bool = Field(
        False,
        description=(
            "True only when this layer is derived from a verified NASA/ESA "
            "scientific dataset.  False for synthetic or placeholder layers."
        )
    )
    is_synthetic: bool = Field(
        False,
        description="True when data is synthetic/placeholder, not real observations"
    )
    available: bool = Field(
        True,
        description="True only when the underlying dataset file exists on disk."
    )
    resolution_m_per_px: Optional[float] = Field(
        None,
        description="Ground sample distance (metres/pixel) — from verified dataset only"
    )
    coverage: Optional[str] = Field(
        None,
        description="Textual description of geographic coverage"
    )
    data_source: Optional[str] = Field(
        None,
        description="Dataset identifier or PDS product ID — from verified dataset only"
    )
    reference_url: Optional[str] = Field(
        None,
        description="URL to the original dataset — from verified source only"
    )


class LayerMetadata(BaseModel):
    """
    Full metadata record for a single layer, returned by
    GET /api/v1/layers/{layer_id}/metadata.

    Satisfies the coordinate metadata consistency contract:
      - Projection definition
      - Region-specific origin
      - Transformation method and parameters
      - Source CRS metadata

    All numeric projection / transformation fields are null until a verified
    dataset is integrated.
    """
    layer_id: str
    region_id: str
    layer_type: LayerType
    display_name: str
    description: Optional[str] = None
    is_verified: bool = False
    is_synthetic: bool = False
    available: bool = True

    # Dataset provenance
    dataset_provenance: DatasetProvenance

    # Coordinate frame (must be consistent with region metadata)
    coordinate_frame: LayerCoordinateFrame

    # Availability notes
    availability_note: Optional[str] = Field(
        None,
        description="Human-readable note on data availability status"
    )


class LayerCatalogueResponse(BaseModel):
    """
    Response envelope for GET /api/v1/layers?region_id=...

    Always returns a valid structure.  When no verified layers exist,
    `layers` is an empty list and `verified_layers_available` is False
    with an explicit notice.
    """
    region_id: str
    verified_layers_available: bool = Field(
        False,
        description=(
            "True only when at least one layer with is_verified=True exists "
            "for this region.  False when only synthetic/placeholder layers "
            "or no layers are registered."
        )
    )
    total_count: int = Field(0, description="Total number of layers in this response")
    layers: List[LayerCatalogueEntry] = Field(
        default_factory=list,
        description="Layer summary records.  Empty when no verified layers are available."
    )
    notice: Optional[str] = Field(
        None,
        description=(
            "Informational notice about layer availability, "
            "present when verified_layers_available is False."
        )
    )


class RegionMetadata(BaseModel):
    """
    Full metadata block for a Mars surface region, satisfying the metadata
    contract defined in the AresPath PRD.
    """
    region_id: str
    display_name: str
    description: Optional[str] = None

    # Coordinate reference
    source_crs: MarsCoordinateReference = Field(
        default_factory=MarsCoordinateReference,
        description="Source coordinate reference system for all input coordinates"
    )

    # Display projection
    display_coordinate_space: Literal["arespath_display_v1"] = "arespath_display_v1"
    display_projection: DisplayProjectionDefinition
    display_origin: DisplayOrigin
    x_axis: Literal["East, metres"] = "East, metres"
    y_axis: Literal["North, metres"] = "North, metres"

    # Transformation
    transformation: TransformationParameters

    # Data provenance
    datasets: List[DatasetProvenance] = Field(default_factory=list)

    # Routing availability
    routing_available: bool = Field(False,
        description="True only when verified terrain data and routing service are operational")
    routing_unavailable_reason: Optional[str] = Field(None,
        description="Machine-readable reason code when routing_available is False")


# ---------------------------------------------------------------------------
# Elevation sampling
# ---------------------------------------------------------------------------

class ElevationSampleRequest(BaseModel):
    """
    Request body for POST /api/v1/elevation/sample.

    Coordinates must be in the confirmed AresPath Mars convention:
      planetocentric latitude, positive-east longitude, degrees, [-180, 180].
    """
    region_id: str = Field(
        ...,
        min_length=1,
        description="Identifier for the Mars surface region (e.g. 'jezero_crater')"
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Planetocentric latitude in degrees [-90.0, 90.0]"
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Positive-east longitude in degrees [-180.0, 180.0]"
    )
    coordinate_reference: MarsCoordinateReference = Field(
        default_factory=MarsCoordinateReference,
        description="Must match the confirmed AresPath Mars convention"
    )

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def reject_boolean_coordinates(cls, v: object, info) -> object:
        if isinstance(v, bool):
            raise ValueError(f"{info.field_name} cannot be a boolean value, got {v!r}")
        return v

    @field_validator("coordinate_reference")
    @classmethod
    def validate_crs(cls, v: MarsCoordinateReference) -> MarsCoordinateReference:
        if v.body != "Mars":
            raise ValueError("coordinate_reference.body must be 'Mars'")
        if v.latitude_type != "planetocentric":
            raise ValueError("coordinate_reference.latitude_type must be 'planetocentric'")
        if v.longitude_direction != "positive_east":
            raise ValueError("coordinate_reference.longitude_direction must be 'positive_east'")
        if v.longitude_domain != "-180_to_180":
            raise ValueError("coordinate_reference.longitude_domain must be '-180_to_180'")
        return v


class ElevationSampleResponse(BaseModel):
    """
    Response model for POST /api/v1/elevation/sample.

    Directly reflects the outcome of nearest-neighbor DEM elevation sampling
    and CoverageStatus classification. Internal coordinate pipeline details
    (projected coordinates, continuous pixel coordinates, raster indices)
    and bilinear interpolation stubs are strictly not exposed.
    """
    region_id: str = Field(
        ...,
        description="Region the query was evaluated against"
    )
    latitude: float = Field(
        ...,
        description="Query planetocentric latitude in degrees"
    )
    longitude: float = Field(
        ...,
        description="Query positive-east longitude in degrees"
    )
    status: CoverageStatus = Field(
        ...,
        description="Coverage classification: 'valid', 'out_of_bounds', 'nodata_collar', or 'elevation_unavailable'"
    )
    geometric_coverage: bool = Field(
        ...,
        description="True if coordinates lie inside half-open raster bounds [0, width) x [0, height)"
    )
    elevation_valid: bool = Field(
        ...,
        description="True if containing cell contains a finite, valid non-NoData value"
    )
    elevation_m: Optional[float] = Field(
        None,
        description="Nominal elevation value in metres as represented by the source DEM. The vertical datum is not explicitly identified in the source GeoTIFF metadata."
    )
    sampling_method: Literal["nearest_neighbor"] = Field(
        "nearest_neighbor",
        description="Sampling method used; nearest-neighbor (containing-cell) only in Milestone 2"
    )
    coordinate_reference: MarsCoordinateReference = Field(
        default_factory=MarsCoordinateReference,
        description="Planetary coordinate reference frame of input and evaluation"
    )
    message: Optional[str] = Field(
        None,
        description="Diagnostic details explaining why elevation is unavailable or invalid"
    )

    @model_validator(mode="after")
    def validate_elevation_and_status(self) -> ElevationSampleResponse:
        if self.elevation_valid:
            if self.elevation_m is None:
                raise ValueError("elevation_valid=True requires a non-null elevation_m")
            if not math.isfinite(self.elevation_m):
                raise ValueError("elevation_valid=True requires a finite elevation_m")
        else:
            if self.elevation_m is not None:
                raise ValueError("elevation_valid=False requires elevation_m=None")

        if self.status == CoverageStatus.VALID:
            if not self.geometric_coverage:
                raise ValueError("CoverageStatus.VALID requires geometric_coverage=True")
            if not self.elevation_valid:
                raise ValueError("CoverageStatus.VALID requires elevation_valid=True")
        elif self.status == CoverageStatus.OUT_OF_BOUNDS:
            if self.geometric_coverage:
                raise ValueError("CoverageStatus.OUT_OF_BOUNDS requires geometric_coverage=False")
            if self.elevation_valid:
                raise ValueError("CoverageStatus.OUT_OF_BOUNDS requires elevation_valid=False")
        elif self.status == CoverageStatus.NODATA_COLLAR:
            if not self.geometric_coverage:
                raise ValueError("CoverageStatus.NODATA_COLLAR requires geometric_coverage=True")
            if self.elevation_valid:
                raise ValueError("CoverageStatus.NODATA_COLLAR requires elevation_valid=False")
        elif self.status == CoverageStatus.ELEVATION_UNAVAILABLE:
            if not self.geometric_coverage:
                raise ValueError("CoverageStatus.ELEVATION_UNAVAILABLE requires geometric_coverage=True")
            if self.elevation_valid:
                raise ValueError("CoverageStatus.ELEVATION_UNAVAILABLE requires elevation_valid=False")

        return self
