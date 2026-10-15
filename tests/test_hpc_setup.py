import json
import math

import yaml

from hpc.setup import compare_reference, measure_throughput


def test_within_uses_a_relative_tolerance_and_accepts_both_not_reached():
    assert compare_reference.within(100.9, 100.0, 0.01)
    assert not compare_reference.within(101.1, 100.0, 0.01)
    assert not compare_reference.within(None, 100.0, 0.01)
    assert compare_reference.within(math.nan, math.nan, 0.01)
    assert not compare_reference.within(math.nan, 100.0, 0.01)


def test_method_b_is_compared_with_the_transient_result():
    check = {"method": "B", "n_cells": 1000, "t90_s": 400.0, "tau_s": 200.0, "tolerance": 0.05}
    summary = {"n_cells": 1000, "t90_s": 600.0, "tau_s": 250.0, "transient": {"t90_s": 410.0, "tau_s": 195.0}}
    rows = compare_reference.compare(check, summary, cell_tolerance=0.001)
    assert [ok for *_, ok in rows] == [True, True, True]


def test_reference_file_lists_complete_checks():
    reference = json.loads(compare_reference.REFERENCE.read_text())
    for check in reference["checks"]:
        assert {"case", "config", "method", "procs", "n_cells", "t90_s", "tau_s", "tolerance"} <= check.keys()


def test_throughput_configs_get_their_own_case_ids(tmp_path, monkeypatch):
    repo = compare_reference.REFERENCE.parents[2]
    monkeypatch.setattr(measure_throughput, "DEMO", repo / "configs" / "demo" / "demo_1.yaml")
    monkeypatch.setattr(measure_throughput, "WORK", tmp_path)
    paths = measure_throughput.make_configs(3)
    ids = [yaml.safe_load(p.read_text())["case_id"] for p in paths]
    assert ids == ["throughput_3_0", "throughput_3_1", "throughput_3_2"]
