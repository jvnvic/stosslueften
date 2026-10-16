import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from cfd.config import load_config
from geometry.windows import place_windows
from sweeps import generate, queues

REPO = Path(__file__).parents[1]


def _spec(tmp_path, n_cases=12, seed=7, **changes):
    spec = yaml.safe_load((REPO / "configs" / "sweep" / "train-v1" / "spec.yaml").read_text())
    spec.update(run_id="t", n_cases=n_cases, seed=seed, base_config=str(REPO / "configs" / "default.yaml"), **changes)
    path = tmp_path / "t" / "spec.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec))
    return path


def test_same_spec_gives_the_same_case_files(tmp_path):
    first = [p.read_text() for p in generate.generate(_spec(tmp_path), plot=False)]
    second = [p.read_text() for p in generate.generate(_spec(tmp_path), plot=False)]
    assert first == second and len(first) == 12


def test_cases_are_valid_balanced_interleaved_and_in_range(tmp_path):
    paths = generate.generate(_spec(tmp_path, n_cases=30), plot=False)
    cfgs = [load_config(p) for p in paths]
    for cfg in cfgs:
        place_windows(cfg)  # no overlaps, no colliding sashes
        assert 1 <= cfg.wind_speed_ms <= 5
        for w in (cfg.window1, cfg.window2):
            assert (15 <= w.angle_deg <= 90) if w.mode == "turn" else (w.angle_deg == 6 and w.hinge == "left")
    assert [c.layout for c in cfgs[:3]] == list(generate.LAYOUTS)  # every block of three has each layout
    assert sum(c.layout == "same_wall" for c in cfgs) == 10
    assert [c.case_id for c in cfgs[:2]] == ["t_001", "t_002"]


def test_latin_hypercube_fills_every_wind_band_evenly(tmp_path):
    # 30 cases per layout: every 0.4 m/s band of the 1-5 m/s range gets exactly 3 cases per layout
    cfgs = [load_config(p) for p in generate.generate(_spec(tmp_path, n_cases=90), plot=False)]
    for layout in generate.LAYOUTS:
        wind = np.array([c.wind_speed_ms for c in cfgs if c.layout == layout])
        counts, _ = np.histogram(wind, bins=10, range=(1, 5))
        assert counts.tolist() == [3] * 10


def test_manifest_records_methods_and_redraws(tmp_path):
    spec = _spec(tmp_path, n_cases=30)
    generate.generate(spec, plot=False)
    manifest = json.loads((spec.parent / "manifest.json").read_text())
    assert manifest["cases_per_method"] == {"B": 10, "A": 20}
    assert set(manifest["position_redraws"]) == set(generate.LAYOUTS)


def test_queue_split_puts_long_cases_first_and_balances_the_work():
    cases = [(Path(f"c{i}.yaml"), "same_wall" if i < 3 else "opposite_walls") for i in range(9)]
    q1, q2 = queues.split(cases, 2)
    work = [sum(queues.METHOD_B_COST if int(p.stem[1:]) < 3 else 1 for p in q) for q in (q1, q2)]
    assert abs(work[0] - work[1]) <= queues.METHOD_B_COST
    assert all(int(q[0].stem[1:]) < 3 for q in (q1, q2))  # each queue starts with a same-wall case


@pytest.mark.parametrize("summary, layout, done", [
    ({"tau_s": 30.0}, "opposite_walls", True),
    ({"tau_s": 200.0}, "same_wall", False),             # method B still missing
    ({"tau_s": 200.0, "transient": {}}, "same_wall", True),
])
def test_done_needs_the_final_method(tmp_path, monkeypatch, summary, layout, done):
    monkeypatch.setattr(queues, "CASES", tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "summary.json").write_text(json.dumps(summary))
    assert queues.is_done("x", layout) is done
