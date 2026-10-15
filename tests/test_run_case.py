from cfd.run_case import method_for


def test_only_same_wall_cases_use_the_time_varying_method(make_config):
    assert method_for(make_config(layout="same_wall", w1=(1.4, "turn", 90), w2=(3.6, "tilt", 6))) == "B"
    assert method_for(make_config(layout="opposite_walls")) == "A"
    assert method_for(make_config(layout="adjacent_walls", w1=(2.5, "turn", 60), w2=(2.0, "tilt", 6))) == "A"
