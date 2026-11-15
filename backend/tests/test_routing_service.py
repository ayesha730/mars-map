import pytest

from app.scientific.dem.routing_service import (
    DEM_PATH,
    JezeroRoutingService,
    RoutingDataError,
)


@pytest.mark.skipif(
    not DEM_PATH.is_file(),
    reason="Real Jezero DEM is not available.",
)
def test_real_jezero_route_between_nearby_points():
    service = JezeroRoutingService()

    # Nearby test points inside the Jezero DEM coverage.
    result = service.compute_route(
        start_latitude=18.40,
        start_longitude=77.70,
        destination_latitude=18.401,
        destination_longitude=77.701,
    )

    assert len(result.path.cells) >= 1
    assert len(result.projected_points) == len(result.path.cells)
    assert result.path.distance_m >= 0
    assert result.window_shape[0] * result.window_shape[1] <= 1_500_000


def test_missing_dem_raises_clear_error(tmp_path):
    missing = tmp_path / "missing.tif"

    with pytest.raises(RoutingDataError):
        JezeroRoutingService(dem_path=missing)