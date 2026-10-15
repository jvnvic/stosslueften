import numpy as np
import pytest

from cfd.run_case import copy_field, method_for, window_flows


def test_only_same_wall_cases_use_the_time_varying_method(make_config):
    assert method_for(make_config(layout="same_wall", w1=(1.4, "turn", 90), w2=(3.6, "tilt", 6))) == "B"
    assert method_for(make_config(layout="opposite_walls")) == "A"
    assert method_for(make_config(layout="adjacent_walls", w1=(2.5, "turn", 60), w2=(2.0, "tilt", 6))) == "A"


def _series(folder, rows):
    folder.mkdir(parents=True)
    (folder / "surfaceFieldValue.dat").write_text("# Time value\n" + "".join(f"{t} {v}\n" for t, v in rows))


def test_window_flows_give_net_flow_inflow_and_balance(make_config, tmp_path):
    cfg = make_config("opposite_walls")  # window1 south (sign +1), window2 north (sign -1)
    post = tmp_path / "postProcessing"
    # 0.5 m^3/s in through window 1, out through window 2 (positive along +y there);
    # window 1 also exchanges 0.1 m^3/s in both directions; values before t = 10 are ignored
    _series(post / "window1Net" / "0", [(5, 9.0), (10, 0.5), (20, 0.5)])
    _series(post / "window1Abs" / "0", [(5, 9.0), (10, 0.7), (20, 0.7)])
    _series(post / "window2Net" / "0", [(5, 9.0), (10, 0.5), (20, 0.5)])
    _series(post / "window2Abs" / "0", [(5, 9.0), (10, 0.5), (20, 0.5)])
    flows = window_flows(cfg, post, start=10)
    assert flows["net"] == {"window1": 1800.0, "window2": -1800.0}
    assert flows["inflow"] == {"window1": pytest.approx(2160.0), "window2": 0.0}
    assert flows["airflow_m3h"] == pytest.approx(2160.0) and flows["balance_m3h"] == 0.0


def test_copy_field_renames_the_field_in_the_header(tmp_path):
    source = tmp_path / "phiMean"
    source.write_bytes(b"FoamFile\n{\n    class       surfaceScalarField;\n    object      phiMean;\n}\n" + bytes(range(256)))
    copy_field(source, tmp_path / "phi", "phi")
    data = (tmp_path / "phi").read_bytes()
    assert b"object      phi;" in data and b"phiMean" not in data and data.endswith(bytes(range(256)))
