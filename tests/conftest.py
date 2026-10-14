from pathlib import Path

import pytest
import yaml

from cfd.config import config_from_dict

DEFAULT_CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"


@pytest.fixture
def default_dict() -> dict:
    """The default case as a plain dict, ready to be modified by a test."""
    with DEFAULT_CONFIG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def make_config(default_dict):
    """Build a CaseConfig from the default with a different layout and windows.

    Windows are given as (x_m, mode, angle_deg).
    """

    def make(layout="opposite_walls", w1=(2.5, "turn", 90), w2=(2.5, "turn", 90)):
        data = dict(default_dict, layout=layout)
        for name, (x, mode, angle) in (("window1", w1), ("window2", w2)):
            data[name] = {"x_m": x, "mode": mode, "angle_deg": angle}
        return config_from_dict(data)

    return make
