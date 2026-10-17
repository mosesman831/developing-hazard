"""Frame timestamps are clip time at the sample rate."""

from dh.frames import frame_times


def test_frame_times_start_at_zero():
    assert frame_times(3, 5) == [0.0, 0.2, 0.4]
    assert frame_times(1, 5) == [0.0]
