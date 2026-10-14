"""The monitor reads OpenFOAM postProcessing files that mix text and number columns."""

import numpy as np

from analysis.monitor import _table


def test_table_reads_names_and_numbers(tmp_path):
    path = tmp_path / "solverInfo.dat"
    path.write_text(
        "# Solver information\n"
        "# Time  U_solver  Ux_initial  p_initial\n"
        "1  smoothSolver  1.0e+00  5.0e-01\n"
        "2  smoothSolver  3.0e-01  1.0e-01\n"
    )
    header, data = _table(path)
    assert header == ["Time", "U_solver", "Ux_initial", "p_initial"]
    assert data.shape == (2, 4)
    assert np.isnan(data[0, 1])  # the solver name is text
    assert data[1, 2] == 0.3


def test_missing_file_gives_empty_table(tmp_path):
    header, data = _table(tmp_path / "missing.dat")
    assert header == [] and data.size == 0
