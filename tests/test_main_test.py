from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

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


def test_claim_status_rows_include_verification_reason_and_hide_raw_evidence() -> None:
    rows = main_test._claim_status_rows(
        [
            {
                "claim_id": "claim-1",
                "text": "Xe ego va chạm bụi cây",
                "timestamp_s": 18.25,
                "evidence": [{"evidence_id": "frame-1", "timestamp_s": 18.25}],
                "verification_status": "supported",
            }
        ],
        {
            "results": [
                {
                    "claim_id": "claim-1",
                    "status": "supported",
                    "reason": "Tốc độ giảm về gần 0 km/h đúng thời điểm claim.",
                    "evidence_ids": ["log-row:18.25"],
                }
            ]
        },
    )

    assert rows == [
        {
            "ID": "claim-1",
            "Thời điểm": "18.25s",
            "Nhận định": "Xe ego va chạm bụi cây",
            "Trạng thái": "Được log hỗ trợ",
            "Lý do": "Tốc độ giảm về gần 0 km/h đúng thời điểm claim.",
        }
    ]


def test_claim_status_rows_leave_reason_empty_when_verification_is_unavailable() -> None:
    rows = main_test._claim_status_rows(
        [{"claim_id": "claim-1", "text": "Claim", "timestamp_s": 1.0}]
    )

    assert rows[0]["Lý do"] == ""


def test_claim_status_rows_uses_verification_result_as_status_source() -> None:
    rows = main_test._claim_status_rows(
        [{"claim_id": "claim-1", "text": "Xe ego dừng lại.", "timestamp_s": 2}],
        {
            "results": [
                {
                    "claim_id": "claim-1",
                    "status": "contradicted",
                    "reason": "Tốc độ vẫn tăng.",
                }
            ]
        },
    )

    assert rows[0]["Trạng thái"] == "Mâu thuẫn với log"


def test_unified_report_uses_embedded_verification_and_deduplicates_warnings() -> None:
    report = {
        "alignment": {"verification": {"results": [{"claim_id": "claim-1"}]}},
        "evidence_and_warnings": {"warnings": ["Log không đầy đủ.", "Cảnh báo video."]},
    }
    snapshot = {"warnings": ["Log không đầy đủ."]}

    assert main_test._report_verification(snapshot, report) == report["alignment"]["verification"]
    assert main_test._report_warnings(snapshot, report) == ["Log không đầy đủ.", "Cảnh báo video."]


def test_unified_report_formats_timeline_as_readable_rows() -> None:
    rows = main_test._timeline_rows(
        {
            "events": [
                {
                    "timestamp_s": 7.5,
                    "description": "Xe ego bắt đầu giảm tốc.",
                    "evidence_ids": ["frame-1", "log-row:7.5"],
                }
            ]
        }
    )

    assert rows == [
        {
            "Thời điểm": "7.5s",
            "Diễn biến": "Xe ego bắt đầu giảm tốc.",
            "Bằng chứng": "frame-1, log-row:7.5",
        }
    ]


def test_accident_type_uses_readable_vietnamese_label() -> None:
    assert main_test._accident_type_label("roadside_collision") == "Va chạm môi trường ven đường / rời đường"
    assert main_test._accident_type_label("no_incident") == "Không có tai nạn của ego"


def test_reanalyze_review_fields_require_target_claims() -> None:
    with pytest.raises(ValueError, match="ít nhất một claim"):
        main_test._reanalyze_review_fields("Kiểm tra lại claim", [])


def test_reanalyze_review_fields_normalize_valid_input() -> None:
    assert main_test._reanalyze_review_fields(
        "  Kiểm tra lại claim  ",
        ["claim-1", "claim-1", " claim-2 "],
    ) == {
        "feedback": "Kiểm tra lại claim",
        "target_claim_ids": ["claim-1", "claim-2"],
    }


def test_review_request_is_submitted_once_while_future_is_running() -> None:
    running = Future()
    streamlit = SimpleNamespace(
        session_state={},
        info=Mock(),
        warning=Mock(),
    )
    executor = SimpleNamespace(submit=Mock(return_value=running))
    payload = {"action": "reanalyze", "feedback": "Review", "target_claim_ids": ["claim-1"]}
    with patch("main_test.st", streamlit), patch("main_test._REQUEST_EXECUTOR", executor):
        first = main_test._start_review_async(
            "POST",
            "http://localhost:8000",
            "/api/v1/incidents/INC-1/review",
            payload,
        )
        second = main_test._start_review_async(
            "POST",
            "http://localhost:8000",
            "/api/v1/incidents/INC-1/review",
            payload,
        )

    assert first is True
    assert second is False
    executor.submit.assert_called_once_with(
        main_test.api_request,
        "POST",
        "http://localhost:8000",
        "/api/v1/incidents/INC-1/review",
        payload,
    )
    streamlit.warning.assert_called_once()


def test_review_request_in_progress_ends_when_future_completes() -> None:
    completed = Future()
    completed.set_result({"status": "awaiting_review"})
    streamlit = SimpleNamespace(session_state={"review_future": completed})

    with patch("main_test.st", streamlit):
        assert main_test._review_request_in_progress() is False
