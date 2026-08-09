"""Standalone Streamlit client for exercising the incident HTTP API."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import httpx
import streamlit as st

_REQUEST_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="incident-ui")


def api_request(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout_s: float = 900,
) -> dict[str, Any]:
    try:
        request_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(timeout_s, connect=10)}
        if files is not None:
            request_kwargs["files"] = files
        else:
            request_kwargs["json"] = payload
        response = httpx.request(method, f"{base_url.rstrip('/')}{path}", **request_kwargs)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"FastAPI chưa xử lý xong sau {timeout_s:.0f} giây. Hãy xem log Uvicorn hoặc tăng timeout client."
        ) from exc
    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Không kết nối được FastAPI. Kiểm tra backend đang chạy và base URL, ví dụ http://localhost:8000."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Lỗi HTTP khi gọi FastAPI: {type(exc).__name__}.") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"FastAPI trả response không phải JSON (HTTP {response.status_code}). Hãy xem log Uvicorn để biết lỗi backend."
        ) from exc
    if response.is_error:
        detail = data.get("detail", {}) if isinstance(data, dict) else {}
        message = detail.get("message", "Yêu cầu API thất bại.") if isinstance(detail, dict) else str(detail)
        raise RuntimeError(message)
    if not isinstance(data, dict):
        raise RuntimeError("FastAPI trả về dữ liệu không hợp lệ.")
    return data


def main() -> None:
    st.set_page_config(page_title="Incident Agent Test Client", layout="wide")
    st.title("Incident Agent — End-to-end test client")
    base_url = st.sidebar.text_input("FastAPI base URL", "http://localhost:8000")

    with st.form("start-incident"):
        incident_id = st.text_input("Incident ID", value=st.session_state.get("incident_id", "INC-DEMO-001"))
        video_file = st.file_uploader("Video", type=["mp4", "mov", "avi", "mkv", "webm"])
        log_file = st.file_uploader("Log CSV (tùy chọn)", type=["csv"])
        analysis_prompt = st.text_area("Analysis prompt", "Phân tích sự cố giao thông trong video.")
        submitted = st.form_submit_button("Start incident")
    if submitted:
        if video_file is None:
            st.error("Bạn phải chọn một file video.")
        else:
            _upload_and_start_async(base_url, incident_id, analysis_prompt, video_file, log_file)

    active_id = st.session_state.get("incident_id", incident_id)
    if st.button("Refresh status") and active_id:
        _run_and_store("GET", base_url, f"/api/v1/incidents/{active_id}")

    st.sidebar.divider()
    st.sidebar.subheader("SQLite")
    if st.sidebar.button("Refresh SQLite data"):
        _refresh_sqlite_reports(base_url)
    _render_sqlite_reports()

    _render_live_incident(base_url, active_id)


def _run_and_store(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        st.session_state.snapshot = api_request(method, base_url, path, payload)
        st.success("API request thành công.")
    except RuntimeError as exc:
        st.error(str(exc))


def _upload_and_start(
    base_url: str,
    incident_id: str,
    analysis_prompt: str,
    video_file: Any,
    log_file: Any | None,
) -> None:
    files = {
        "video": (video_file.name, video_file.getvalue(), video_file.type or "application/octet-stream"),
    }
    if log_file is not None:
        files["log"] = (log_file.name, log_file.getvalue(), log_file.type or "text/csv")
    try:
        uploaded = api_request("POST", base_url, "/api/v1/incidents/uploads", files=files)
        payload = {
            "incident_id": incident_id,
            "video_uri": uploaded["video_uri"],
            "analysis_prompt": analysis_prompt,
        }
        if uploaded.get("log_uri"):
            payload["log_uri"] = uploaded["log_uri"]
        st.session_state.snapshot = api_request("POST", base_url, "/api/v1/incidents", payload)
        st.session_state.incident_id = incident_id
        st.success("Upload và tạo incident thành công.")
    except (KeyError, RuntimeError) as exc:
        st.error(str(exc) if isinstance(exc, RuntimeError) else "API upload trả về dữ liệu không hợp lệ.")


def _upload_and_start_async(
    base_url: str,
    incident_id: str,
    analysis_prompt: str,
    video_file: Any,
    log_file: Any | None,
) -> None:
    files = {"video": (video_file.name, video_file.getvalue(), video_file.type or "application/octet-stream")}
    if log_file is not None:
        files["log"] = (log_file.name, log_file.getvalue(), log_file.type or "text/csv")
    try:
        uploaded = api_request("POST", base_url, "/api/v1/incidents/uploads", files=files)
        payload = {
            "incident_id": incident_id,
            "video_uri": uploaded["video_uri"],
            "analysis_prompt": analysis_prompt,
        }
        if uploaded.get("log_uri"):
            payload["log_uri"] = uploaded["log_uri"]
        st.session_state.incident_id = incident_id
        st.session_state.incident_future = _REQUEST_EXECUTOR.submit(
            api_request, "POST", base_url, "/api/v1/incidents", payload
        )
        st.success("Upload thành công. Workflow đang chạy và giao diện sẽ cập nhật theo thời gian thực.")
    except (KeyError, RuntimeError) as exc:
        st.error(str(exc) if isinstance(exc, RuntimeError) else "API upload trả về dữ liệu không hợp lệ.")


@st.fragment(run_every=1)
def _render_live_incident(base_url: str, incident_id: str) -> None:
    future = st.session_state.get("incident_future")
    if isinstance(future, Future):
        if future.done():
            try:
                st.session_state.snapshot = future.result()
            except RuntimeError as exc:
                st.error(str(exc))
            finally:
                del st.session_state.incident_future
        elif incident_id:
            try:
                st.session_state.snapshot = api_request(
                    "GET", base_url, f"/api/v1/incidents/{incident_id}", timeout_s=10
                )
            except RuntimeError:
                st.info("Workflow is starting…")

    snapshot = st.session_state.get("snapshot")
    if not isinstance(snapshot, dict):
        return
    _render_snapshot(snapshot)
    if snapshot.get("status") == "awaiting_review":
        _render_review_form(base_url, snapshot)


def _render_snapshot(snapshot: dict[str, Any]) -> None:
    st.subheader(f"{snapshot.get('incident_id')} — {snapshot.get('status')}")
    _render_model_activity(snapshot.get("model_activities", []))
    if snapshot.get("video_summary"):
        st.subheader("Video summary")
        st.info(snapshot["video_summary"])
    artifacts = snapshot.get("artifact_uris", {})
    if isinstance(artifacts, dict):
        columns = st.columns(2)
        for key in ("normalized_video", "incident_clip"):
            if artifacts.get(key):
                columns[0].caption(key)
                columns[0].video(artifacts[key])
        if artifacts.get("representative_frame"):
            columns[1].caption("representative_frame")
            columns[1].image(artifacts["representative_frame"])
        chart_keys = sorted(key for key in artifacts if key.startswith("chart_"))
        for index, key in enumerate(chart_keys):
            columns[index % 2].caption(key)
            columns[index % 2].image(artifacts[key])

    report = snapshot.get("draft_report") or snapshot.get("final_report")
    if isinstance(report, dict):
        st.subheader("Báo cáo 10 mục")
        labels = [
            ("1. Thông tin chung", "general_information"),
            ("2. Khoảng thời gian sự cố", "incident_window"),
            ("3. Tóm tắt sự cố", "summary"),
            ("4. Timeline", "timeline"),
            ("5. Quan sát từ video", "video_observations"),
            ("6. Kết quả log", "log_findings"),
            ("7. Đối chiếu video và log", "alignment"),
            ("8. Nguyên nhân giả thuyết", "hypothesized_causes"),
            ("9. Bằng chứng và cảnh báo", "evidence_and_warnings"),
            ("10. Trạng thái review", "review_status"),
        ]
        for label, key in labels:
            with st.expander(label, expanded=key in {"summary", "evidence_and_warnings"}):
                _render_report_value(report.get(key))

    st.subheader("Evidence claims")
    st.dataframe(snapshot.get("claims", []), use_container_width=True)
    for warning in snapshot.get("warnings", []):
        st.warning(warning)
    if snapshot.get("error_message"):
        st.error(f"{snapshot.get('error_code')}: {snapshot.get('error_message')}")


def _refresh_sqlite_reports(base_url: str) -> None:
    try:
        payload = api_request("GET", base_url, "/api/v1/incidents/reports")
        reports = payload.get("reports")
        if not isinstance(reports, list):
            raise RuntimeError("API SQLite trả về dữ liệu không hợp lệ.")
        st.session_state.sqlite_reports = reports
        st.success(f"Đã tải {len(reports)} record từ SQLite.")
    except RuntimeError as exc:
        st.error(str(exc))


def _render_sqlite_reports() -> None:
    st.subheader("Dữ liệu SQLite — incident_reports")
    reports = st.session_state.get("sqlite_reports", [])
    if not reports:
        st.info("Chọn 'Refresh SQLite data' để tải các báo cáo terminal đã lưu.")
        return

    rows = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        rows.append(
            {
                "incident_id": report.get("incident_id"),
                "status": report.get("status"),
                "has_log": report.get("has_log"),
                "reviewer": report.get("reviewer"),
                "decision": report.get("decision"),
                "stored_at": report.get("stored_at"),
                "evidence_count": len(report.get("evidence_ids", [])),
                "claims_count": len(report.get("claims", [])),
                "warnings_count": len(report.get("warnings", [])),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    for report in reports:
        if not isinstance(report, dict):
            continue
        incident_id = report.get("incident_id", "unknown")
        status = report.get("status", "unknown")
        with st.expander(f"{incident_id} — {status}"):
            st.json(report)


def _render_model_activity(activities: Any) -> None:
    st.subheader("Model activity")
    if not isinstance(activities, list) or not activities:
        st.info("No model usage data. Incidents created before usage tracking will not have historical token data.")
        return

    running = [item for item in activities if isinstance(item, dict) and item.get("status") == "running"]
    if running:
        current = running[-1]
        st.info(
            f"{current.get('provider')} / {current.get('model')} đang thực hiện "
            f"{current.get('description', current.get('operation'))}"
        )

    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    rows = []
    for item in activities:
        if not isinstance(item, dict):
            continue
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
        rows.append(
            {
                "status": item.get("status"),
                "step": item.get("step"),
                "operation": item.get("operation"),
                "provider": item.get("provider"),
                "model": item.get("model"),
                "doing": item.get("description"),
                "started_at": item.get("started_at"),
                "completed_at": item.get("completed_at"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cached_tokens": usage.get("cached_tokens"),
                "reasoning_tokens": usage.get("reasoning_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "duration_ms": item.get("duration_ms"),
                "error_code": item.get("error_code"),
                "request_metadata": item.get("metadata"),
            }
        )

    columns = st.columns(5)
    columns[0].metric("Input tokens", f"{totals['input_tokens']:,}")
    columns[1].metric("Output tokens", f"{totals['output_tokens']:,}")
    columns[2].metric("Cached tokens", f"{totals['cached_tokens']:,}")
    columns[3].metric("Reasoning tokens", f"{totals['reasoning_tokens']:,}")
    columns[4].metric("Total tokens", f"{totals['total_tokens']:,}")
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_report_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        st.json(value)
    elif value is None:
        st.caption("No data")
    else:
        st.write(str(value))


def _render_review_form(base_url: str, snapshot: dict[str, Any]) -> None:
    report = snapshot.get("draft_report") or {}
    claims = snapshot.get("claims", [])
    claim_ids = [claim["claim_id"] for claim in claims if isinstance(claim, dict) and claim.get("claim_id")]
    with st.form("review-incident"):
        action = st.selectbox("Review action", ["approve", "edit", "reanalyze", "not_incident"])
        reviewer = st.text_input("Reviewer", "reviewer@example.com")
        reason = st.text_area("Reason (bắt buộc cho not_incident)")
        feedback = st.text_area("Feedback (bắt buộc cho reanalyze)")
        targets = st.multiselect("Target claim IDs", claim_ids)
        edits = {
            "summary": st.text_area("Edit summary", report.get("summary", "")),
            "timeline": st.text_area("Edit timeline", _narrative(report, "timeline")),
            "video_observations": st.text_area("Edit video observations", _narrative(report, "video_observations")),
            "log_findings": st.text_area("Edit log findings", _narrative(report, "log_findings")),
            "alignment": st.text_area("Edit alignment", _narrative(report, "alignment")),
            "hypothesized_causes": st.text_area("Edit hypothesized causes", report.get("hypothesized_causes", "")),
        }
        submitted = st.form_submit_button("Submit review")
    if not submitted:
        return
    payload: dict[str, Any] = {"action": action, "reviewer": reviewer}
    if action == "not_incident":
        payload["reason"] = reason
    elif action == "reanalyze":
        payload.update({"feedback": feedback, "target_claim_ids": targets})
    elif action == "edit":
        payload["edits"] = edits
    _run_and_store(
        "POST",
        base_url,
        f"/api/v1/incidents/{snapshot['incident_id']}/review",
        payload,
    )


def _narrative(report: dict[str, Any], field: str) -> str:
    section = report.get(field, {})
    return section.get("narrative", "") if isinstance(section, dict) else ""


if __name__ == "__main__":
    main()
