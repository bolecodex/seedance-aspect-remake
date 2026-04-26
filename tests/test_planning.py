from seedance_aspect.planning import choose_target_ratio, plan_segments


def test_auto_opposite_target_ratio():
    assert choose_target_ratio(1920, 1080, "auto-opposite") == "9:16"
    assert choose_target_ratio(1080, 1920, "auto-opposite") == "16:9"
    assert choose_target_ratio(1080, 1920, "9:16") == "9:16"


def test_long_video_has_no_short_tail():
    plans = plan_segments(31.0, max_segment_seconds=15)
    assert len(plans) == 3
    assert all(2.0 <= plan.reference_duration <= 15.0 for plan in plans)
    assert all(4 <= plan.generation_duration <= 15 for plan in plans)
    assert round(sum(plan.duration for plan in plans), 3) == 31.0


def test_short_video_is_padded_for_reference_and_generation():
    plans = plan_segments(1.5, max_segment_seconds=15)
    assert len(plans) == 1
    assert plans[0].duration == 1.5
    assert plans[0].reference_duration == 2.0
    assert plans[0].generation_duration == 4

