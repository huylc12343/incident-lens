from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import main_test


def test_streamlit_client_imports_and_calls_http_api() -> None:
    response = Mock(is_error=False)
    response.json.return_value = {"incident_id": "INC-UI", "status": "awaiting_review"}
    with patch("main_test.httpx.request", return_value=response) as request:
        payload = main_test.api_request("GET", "http://localhost:8000/", "/api/v1/incidents/INC-UI")

    assert payload["status"] == "awaiting_review"
    request.assert_called_once()


def test_streamlit_uploads_files_before_creating_incident() -> None:
    video = SimpleNamespace(name="camera.mp4", type="video/mp4", getvalue=lambda: b"video")
    log = SimpleNamespace(name="vehicle.csv", type="text/csv", getvalue=lambda: b"timestamp_s\n0\n")
    streamlit = SimpleNamespace(session_state=SimpleNamespace(), success=Mock(), error=Mock())
    with (
        patch("main_test.st", streamlit),
        patch(
            "main_test.api_request",
            side_effect=[
                {"video_uri": "/uploads/camera.mp4", "log_uri": "/uploads/vehicle.csv"},
                {"incident_id": "INC-UPLOAD", "status": "awaiting_review"},
            ],
        ) as request,
    ):
        main_test._upload_and_start("http://localhost:8000", "INC-UPLOAD", "Analyze", video, log)

    assert request.call_args_list == [
        call(
            "POST",
            "http://localhost:8000",
            "/api/v1/incidents/uploads",
            files={
                "video": ("camera.mp4", b"video", "video/mp4"),
                "log": ("vehicle.csv", b"timestamp_s\n0\n", "text/csv"),
            },
        ),
        call(
            "POST",
            "http://localhost:8000",
            "/api/v1/incidents",
            {
                "incident_id": "INC-UPLOAD",
                "video_uri": "/uploads/camera.mp4",
                "analysis_prompt": "Analyze",
                "log_uri": "/uploads/vehicle.csv",
            },
        ),
    ]
    assert streamlit.session_state.incident_id == "INC-UPLOAD"


def test_streamlit_reports_timeout_cause() -> None:
    with patch("main_test.httpx.request", side_effect=main_test.httpx.ReadTimeout("slow")):
        try:
            main_test.api_request("POST", "http://localhost:8000", "/api/v1/incidents", timeout_s=5)
        except RuntimeError as exc:
            assert "5 giây" in str(exc)
        else:
            raise AssertionError("timeout must be mapped to a useful error")


def test_streamlit_reports_non_json_backend_response() -> None:
    response = Mock(status_code=500)
    response.json.side_effect = ValueError("not json")
    with patch("main_test.httpx.request", return_value=response):
        try:
            main_test.api_request("POST", "http://localhost:8000", "/api/v1/incidents")
        except RuntimeError as exc:
            assert "HTTP 500" in str(exc)
        else:
            raise AssertionError("non-JSON responses must be explained")


def test_report_renderer_does_not_parse_plain_text_as_json() -> None:
    streamlit = SimpleNamespace(json=Mock(), write=Mock(), caption=Mock())
    with patch("main_test.st", streamlit):
        main_test._render_report_value("Video bắt đầu trên cầu.")

    streamlit.write.assert_called_once_with("Video bắt đầu trên cầu.")
    streamlit.json.assert_not_called()


def test_generated_incident_ids_are_unique() -> None:
    first = main_test._new_incident_id()
    second = main_test._new_incident_id()

    assert first.startswith("INC-")
    assert second.startswith("INC-")
    assert first != second
