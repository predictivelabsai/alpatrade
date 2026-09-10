import json
import math

from utils.agent_storage import _json_safe


def test_run_results_replace_nonfinite_numbers_before_json_storage():
    result = _json_safe({"score": float("nan"), "nested": [1.0, float("inf")]})
    assert result == {"score": None, "nested": [1.0, None]}
    assert math.isfinite(result["nested"][0])
    assert json.dumps(result, allow_nan=False)
