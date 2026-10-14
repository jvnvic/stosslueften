"""Air-replacement metrics from a tracer curve (no OpenFOAM needed)."""

import numpy as np
import pytest

from analysis.metrics import tracer_metrics


def test_perfectly_mixed_room_gives_its_time_constant():
    tau = 30.0
    t = np.arange(0, 600.1, 0.2)
    metrics = tracer_metrics(t, 1 - np.exp(-t / tau), 600)
    assert metrics["tau_s"] == pytest.approx(tau, rel=1e-3)
    assert metrics["t90_s"] == pytest.approx(tau * np.log(10), rel=1e-3)  # 90 % after tau * ln(10)
    assert metrics["fresh_frac_030s"] == pytest.approx(1 - np.exp(-1), abs=1e-6)
    assert sum(key.startswith("fresh_frac_") for key in metrics) == 20  # every 30 s up to 600 s


def test_t90_is_missing_when_never_reached():
    t = np.linspace(0, 600, 601)
    metrics = tracer_metrics(t, 0.5 * (1 - np.exp(-t / 50)), 600)  # only half the air is ever replaced
    assert np.isnan(metrics["t90_s"])
    assert np.isfinite(metrics["tau_s"])  # tau is always defined
