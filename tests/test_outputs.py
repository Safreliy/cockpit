import json
from pathlib import Path

import run


def test_run_generates_all_mvp_artifacts():
    run.main()
    expected = [
        "timeseries.csv",
        "episode.json",
        "validation.json",
        "timeseries_payments_p95.png",
        "timeseries_storage_latency.png",
        "timeseries_short_query_wait.png",
        "timeseries_reporting_concurrency.png",
        "cockpit_mock.html",
    ]
    for name in expected:
        path = Path("output") / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name
    assert json.loads(Path("output/validation.json").read_text(encoding="utf-8"))["passed"] is True
    html = Path("output/cockpit_mock.html").read_text(encoding="utf-8")
    assert "Telemetry Explorer" in html
    assert "const telemetry =" in html
    assert "id=\"chart\"" in html
    assert Path("web_cockpit/index.html").exists()
    web_data = Path("web_cockpit/data.js").read_text(encoding="utf-8")
    assert "window.COCKPIT_DATA" in web_data
    assert "heavy_reporting_on_primary" in web_data
    assert "runtimeStream" in web_data
    assert "hypotheses" in web_data
    assert "client_db_packet_loss" in web_data
    assert "cpu_saturation_on_primary" in web_data
    web_html = Path("web_cockpit/index.html").read_text(encoding="utf-8")
    web_js = Path("web_cockpit/app.js").read_text(encoding="utf-8")
    assert "id=\"causalChain\"" in web_html
    assert "Investigation path" in web_html
    assert "Only incidents detected by the current stream time" in web_html
    assert "data-tab=\"hypotheses\"" in web_html
    assert "anomaly-line" in web_js
    assert "data-incident-id" in web_js
    assert "data-hypothesis-cause" in web_js
    assert "chainForHypothesis" in web_js
    assert "No detections yet" in web_js
    assert "visibleIncidents().slice()" in web_js
    assert "renderCausalChain" in web_js
    assert Path("web_cockpit/live.html").exists()
    live_js = Path("web_cockpit/live_app.js").read_text(encoding="utf-8")
    assert "new EventSource(API_BASE + \"/events\")" in live_js
    assert "http://127.0.0.1:8088" in live_js
    assert "/api/load/start" in live_js
    assert "Start load" in Path("web_cockpit/live.html").read_text(encoding="utf-8")
    assert Path("tools/cockpit_backend.py").exists()
