"""Monitor helpers: incremental file reading, window placement, queue estimate."""

import time

import numpy as np

from analysis.monitor import TailTable, cpu_grid, queue_remaining_s, right_half_geometry


def test_tail_table_reads_only_new_complete_lines(tmp_path):
    path = tmp_path / "solverInfo.dat"
    path.write_text("# Time  U_solver  Ux_initial\n1  smoothSolver  1.0\n2  smoothSolver  0.5\n3  smooth")
    table = TailTable(path)
    header, data = table.update()
    assert header == ["Time", "U_solver", "Ux_initial"]
    assert data.shape == (2, 3) and np.isnan(data[0, 1]) and data[1, 2] == 0.5  # line 3 is not complete yet

    with path.open("a") as f:
        f.write("Solver  0.25\n4  smoothSolver  0.1\n")
    _, data = table.update()
    np.testing.assert_array_equal(data[:, 0], [1, 2, 3, 4])
    np.testing.assert_array_equal(data[:, 2], [1.0, 0.5, 0.25, 0.1])


def test_missing_file_gives_empty_table(tmp_path):
    header, data = TailTable(tmp_path / "missing.dat").update()
    assert header == [] and data.size == 0


def test_window_goes_to_the_right_half():
    assert right_half_geometry(1920, 1080) == "960x1010+960+0"
    assert right_half_geometry(3840, 1080) == "960x1010+2880+0"  # two monitors side by side: the right one


def test_queue_estimate_uses_the_average_duration():
    now = time.time()
    state = {"entries": [
        {"status": "done", "seconds": 100, "started": now - 300},
        {"status": "done", "seconds": 200, "started": now - 200},
        {"status": "running", "seconds": None, "started": now - 50},
        {"status": "pending", "seconds": None, "started": None},
    ]}
    assert abs(queue_remaining_s(state) - (150 + 100)) < 1  # one pending + the rest of the running one


def test_cpu_grid_fills_rows_evenly():
    assert cpu_grid(8, 9.0) == (2, 4)    # half a 16:9 screen
    assert cpu_grid(8, 18.0) == (1, 8)   # full width
    assert cpu_grid(32, 9.0) == (8, 4)   # many cores: longer columns
