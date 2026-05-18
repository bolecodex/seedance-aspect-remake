from seedance_aspect.planning import choose_target_ratio, plan_scene_segments, plan_segments


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


def test_auto_generation_duration_uses_seedance_auto_for_normal_segments():
    plans = plan_scene_segments(
        14.52,
        [],
        max_segment_seconds=15,
        generation_duration_mode="auto",
    )

    assert plans[0].generation_duration == -1


def test_scene_planning_prefers_cut_points_near_segment_limit():
    plans = plan_scene_segments(67.0, [1.5, 4.0, 14.5, 17.0, 27.5, 41.3, 52.8], max_segment_seconds=15)

    assert [round(plan.start, 1) for plan in plans[:4]] == [0.0, 14.5, 27.5, 41.3]
    assert all(plan.duration <= 15 for plan in plans)
    assert plans[1].continuity_from_previous is False
    assert plans[0].cut_reason == "scene"


def test_scene_planning_marks_internal_split_for_long_shot():
    plans = plan_scene_segments(34.0, [], max_segment_seconds=15)

    assert len(plans) == 3
    assert plans[1].continuity_from_previous is True
    assert plans[1].continuity_group == plans[0].continuity_group
