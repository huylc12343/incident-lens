"""Standalone Streamlit client for exercising the incident HTTP API."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import uuid4

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
        if isinstance(detail, dict):
            message = detail.get("message", "Yêu cầu API thất bại.")
            if detail.get("code"):
                message = f"{detail['code']}: {message}"
        elif isinstance(detail, list):
            errors: list[str] = []
            for error in detail:
                if not isinstance(error, dict):
                    continue
                location = ".".join(str(item) for item in error.get("loc", []) if item != "body")
                reason = error.get("msg", "giá trị không hợp lệ")
                errors.append(f"{location or 'request'}: {reason}")
            message = "Lỗi validation (HTTP 422): " + "; ".join(errors) if errors else str(detail)
        else:
            message = str(detail)
        raise RuntimeError(message)
    if not isinstance(data, dict):
        raise RuntimeError("FastAPI trả về dữ liệu không hợp lệ.")
    return data


def main() -> None:
    st.set_page_config(page_title="Báo cáo sự cố giao thông", layout="wide")
    st.title("Phân tích sự cố giao thông")
    base_url = st.sidebar.text_input("FastAPI base URL", "http://localhost:8000")
    if st.session_state.get("history_base_url") != base_url:
        st.session_state.history_base_url = base_url
        _refresh_incident_history(base_url, show_success=False)
    _render_incident_sidebar(base_url)

    incident_id = st.session_state.get("draft_incident_id")
    if not isinstance(incident_id, str):
        incident_id = _new_incident_id()
        st.session_state.draft_incident_id = incident_id

    with st.form("start-incident"):
        st.caption(f"Incident ID tự động: `{incident_id}`")
        video_file = st.file_uploader("Video", type=["mp4", "mov", "avi", "mkv", "webm"])
        log_file = st.file_uploader("Log CSV (tùy chọn)", type=["csv"])
        analysis_prompt = st.text_area("Analysis prompt", "Phân tích sự cố giao thông trong video.")
        submitted = st.form_submit_button("Bắt đầu phân tích")
    if submitted:
        if video_file is None:
            st.error("Bạn phải chọn một file video.")
        else:
            st.session_state.pop("incident_error", None)
            _upload_and_start_async(base_url, incident_id, analysis_prompt, video_file, log_file)

    incident_error = st.session_state.get("incident_error")
    if isinstance(incident_error, str) and incident_error:
        st.error(incident_error)

    active_id = st.session_state.get("incident_id", "")
    if st.button("Làm mới trạng thái") and active_id:
        _run_and_store("GET", base_url, f"/api/v1/incidents/{active_id}")

    _render_live_incident(base_url, active_id)


def _render_incident_sidebar(base_url: str) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Cuộc trò chuyện")
    if st.sidebar.button("＋ Cuộc trò chuyện mới", use_container_width=True):
        st.session_state.pop("snapshot", None)
        st.session_state.pop("incident_id", None)
        st.session_state.draft_incident_id = _new_incident_id()
        st.session_state.pop("pending_delete_incident_id", None)
    if st.sidebar.button("↻ Làm mới lịch sử", use_container_width=True):
        _refresh_incident_history(base_url)

    incident_ids = st.session_state.get("incident_history", [])
    if not incident_ids:
        st.sidebar.caption("Chưa có Incident nào trong SQLite.")
    for incident_id in incident_ids:
        columns = st.sidebar.columns([5, 1])
        if columns[0].button(
            incident_id,
            key=f"open-incident-{incident_id}",
            use_container_width=True,
        ):
            _open_incident(base_url, incident_id)
        if columns[1].button("🗑", key=f"delete-incident-{incident_id}"):
            st.session_state.pending_delete_incident_id = incident_id

    pending = st.session_state.get("pending_delete_incident_id")
    if isinstance(pending, str):
        st.sidebar.warning(f"Xóa lịch sử `{pending}`?")
        confirm, cancel = st.sidebar.columns(2)
        if confirm.button("Xóa", key="confirm-delete-incident", use_container_width=True):
            _delete_incident(base_url, pending)
        if cancel.button("Hủy", key="cancel-delete-incident", use_container_width=True):
            st.session_state.pop("pending_delete_incident_id", None)


def _refresh_incident_history(base_url: str, *, show_success: bool = True) -> None:
    try:
        payload = api_request("GET", base_url, "/api/v1/incidents")
        incident_ids = payload.get("incident_ids")
        if not isinstance(incident_ids, list) or not all(isinstance(item, str) for item in incident_ids):
            raise RuntimeError("API lịch sử Incident trả về dữ liệu không hợp lệ.")
        st.session_state.incident_history = incident_ids
        if show_success:
            st.sidebar.success(f"Đã tải {len(incident_ids)} cuộc trò chuyện.")
    except RuntimeError as exc:
        st.sidebar.error(str(exc))


def _open_incident(base_url: str, incident_id: str) -> None:
    try:
        st.session_state.snapshot = api_request("GET", base_url, f"/api/v1/incidents/{incident_id}")
        st.session_state.incident_id = incident_id
    except RuntimeError as exc:
        st.sidebar.error(str(exc))


def _delete_incident(base_url: str, incident_id: str) -> None:
    try:
        api_request("DELETE", base_url, f"/api/v1/incidents/{incident_id}")
        st.session_state.incident_history = [
            item for item in st.session_state.get("incident_history", []) if item != incident_id
        ]
        if st.session_state.get("incident_id") == incident_id:
            st.session_state.pop("snapshot", None)
            st.session_state.pop("incident_id", None)
            st.session_state.draft_incident_id = _new_incident_id()
        st.session_state.pop("pending_delete_incident_id", None)
        st.sidebar.success("Đã xóa cuộc trò chuyện.")
    except RuntimeError as exc:
        st.sidebar.error(str(exc))


def _new_incident_id() -> str:
    return f"INC-{uuid4().hex[:12].upper()}"


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
        _remember_incident(incident_id)
        st.session_state.draft_incident_id = _new_incident_id()
        st.success("Upload và tạo incident thành công.")
    except (KeyError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "API upload trả về dữ liệu không hợp lệ."
        st.session_state.incident_error = message
        st.error(message)


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
        st.session_state.pending_incident_id = incident_id
        st.session_state.incident_future = _REQUEST_EXECUTOR.submit(
            api_request, "POST", base_url, "/api/v1/incidents", payload
        )
        st.info("Upload thành công. Đang tạo incident và kiểm tra dữ liệu đầu vào…")
    except (KeyError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "API upload trả về dữ liệu không hợp lệ."
        st.session_state.incident_error = message
        st.error(message)


def _remember_incident(incident_id: str) -> None:
    getter = getattr(st.session_state, "get", None)
    incident_ids = getter("incident_history", []) if callable(getter) else getattr(st.session_state, "incident_history", [])
    st.session_state.incident_history = [incident_id, *(item for item in incident_ids if item != incident_id)]


@st.fragment(run_every=1)
def _render_live_incident(base_url: str, incident_id: str) -> None:
    incident_error = st.session_state.get("incident_error")
    if isinstance(incident_error, str) and incident_error:
        st.error(incident_error)

    future = st.session_state.get("incident_future")
    if isinstance(future, Future):
        if future.done():
            try:
                st.session_state.snapshot = future.result()
                created_id = st.session_state.snapshot.get("incident_id")
                if isinstance(created_id, str) and created_id:
                    st.session_state.incident_id = created_id
                    _remember_incident(created_id)
                    st.session_state.draft_incident_id = _new_incident_id()
                st.success("Tạo incident thành công. Workflow đang chạy.")
            except RuntimeError as exc:
                message = f"Không thể tạo incident: {exc}"
                st.session_state.incident_error = message
                st.error(message)
            finally:
                del st.session_state.incident_future
                st.session_state.pop("pending_incident_id", None)
        elif incident_id:
            try:
                st.session_state.snapshot = api_request(
                    "GET", base_url, f"/api/v1/incidents/{incident_id}", timeout_s=10
                )
            except RuntimeError:
                st.info("Workflow is starting…")

    review_future = st.session_state.get("review_future")
    if isinstance(review_future, Future):
        action = st.session_state.get("review_action", "review")
        if review_future.done():
            try:
                st.session_state.snapshot = review_future.result()
                st.success(f"{_review_action_label(action)} đã hoàn tất.")
            except RuntimeError as exc:
                st.error(str(exc))
            finally:
                st.session_state.pop("review_future", None)
                st.session_state.pop("review_action", None)
        else:
            st.info(f"⏳ Đang {_review_action_label(action).lower()}. Vui lòng không gửi lại yêu cầu.")

    snapshot = st.session_state.get("snapshot")
    if not isinstance(snapshot, dict):
        return
    _render_snapshot(snapshot)
    if snapshot.get("status") == "awaiting_review" and not _review_request_in_progress():
        _render_review_form(base_url, snapshot)


def _render_snapshot(snapshot: dict[str, Any]) -> None:
    report = snapshot.get("draft_report") or snapshot.get("final_report")
    report = report if isinstance(report, dict) else {}
    verification = _report_verification(snapshot, report)
    if snapshot.get("error_message"):
        st.error(f"{snapshot.get('error_code')}: {snapshot.get('error_message')}")

    _render_unified_report(snapshot, report, verification)

    with st.expander("Chi tiết kỹ thuật và mức sử dụng model"):
        _render_model_activity(snapshot.get("model_activities", []))


def _render_unified_report(
    snapshot: dict[str, Any],
    report: dict[str, Any],
    verification: dict[str, Any] | None,
) -> None:
    with st.container(border=True):
        st.header("Báo cáo sự cố")
        general = report.get("general_information")
        general = general if isinstance(general, dict) else {}
        columns = st.columns(4)
        columns[0].metric("Incident ID", snapshot.get("incident_id") or general.get("incident_id") or "—")
        columns[1].metric("Trạng thái", _status_label(snapshot.get("status")))
        columns[2].metric("Review", _review_status_label(report.get("review_status")))
        has_log = general.get("has_log", snapshot.get("has_log"))
        columns[3].metric("Dữ liệu log", "Có" if has_log is True else "Không" if has_log is False else "—")

        st.markdown("### 1. Tóm tắt video (VLM)")
        st.write(snapshot.get("video_summary") or report.get("summary") or "VLM chưa trả về tóm tắt video.")

        _render_incident_media(snapshot.get("artifact_uris"))

        st.markdown("### 2. Khoảng thời gian sự cố")
        _render_incident_window(
            report.get("incident_window"),
            representative_timestamp_s=report.get("representative_timestamp_s"),
        )

        st.markdown("### 3. Diễn biến theo thời gian")
        timeline = report.get("timeline")
        _render_section_narrative(timeline)
        _render_timeline(timeline)

        st.markdown("### 4. Đối chiếu từng nhận định (claim)")
        _render_claim_details(snapshot.get("claims"), verification)

        st.markdown("### 5. Nhận định tổng quát (LLM)")
        accident_type = report.get("type_of_accident")
        st.markdown(
            f"**Loại tai nạn:** {_accident_type_label(accident_type)} "
            f"(`{accident_type}`)" if accident_type else "**Loại tai nạn:** Chưa phân loại"
        )
        observations = report.get("video_observations")
        if isinstance(observations, dict) and observations.get("narrative"):
            st.write(observations["narrative"])
        else:
            st.caption("Report LLM chưa trả về nhận định tổng quát.")

        st.markdown("### 6. Nguyên nhân giả thuyết")
        st.write(report.get("hypothesized_causes") or "Chưa có kết luận về nguyên nhân.")

        warnings = _report_warnings(snapshot, report)
        if warnings:
            st.markdown("#### Cảnh báo cần lưu ý")
            for warning in warnings:
                st.warning(warning)


def _render_incident_media(artifacts: Any) -> None:
    if not isinstance(artifacts, dict):
        return
    has_media = any(artifacts.get(key) for key in ("normalized_video", "incident_clip", "representative_frame"))
    chart_keys = sorted(key for key in artifacts if key.startswith("chart_") and artifacts.get(key))
    if not has_media and not chart_keys:
        return
    st.markdown("#### Video và hình ảnh đại diện")
    columns = st.columns(2)
    video_uri = artifacts.get("incident_clip") or artifacts.get("normalized_video")
    if video_uri:
        columns[0].video(video_uri)
    if artifacts.get("representative_frame"):
        columns[1].image(artifacts["representative_frame"], caption="Khung hình đại diện")
    if chart_keys:
        st.markdown("#### Biểu đồ telemetry")
        chart_columns = st.columns(2)
        for index, key in enumerate(chart_keys):
            chart_columns[index % 2].image(artifacts[key])


def _render_timeline(value: Any) -> None:
    events = value.get("events") if isinstance(value, dict) else None
    if not isinstance(events, list) or not events:
        st.caption("Chưa có mốc timeline.")
        return
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue
        with st.container(border=True):
            st.markdown(f"**Mốc {index} · {_seconds(event.get('timestamp_s'))}**")
            st.write(event.get("description") or "Không có mô tả.")
            evidence_ids = event.get("evidence_ids")
            if isinstance(evidence_ids, list) and evidence_ids:
                st.caption(f"Bằng chứng: {', '.join(str(item) for item in evidence_ids)}")


def _render_claim_details(claims: Any, verification: Any) -> None:
    if not isinstance(claims, list) or not claims:
        st.caption("Chưa có nhận định để xác thực.")
        return

    verification_by_id = {
        item.get("claim_id"): item
        for item in (verification.get("results", []) if isinstance(verification, dict) else [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
    }
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        verified = verification_by_id.get(claim_id, {})
        status = verified.get("status", claim.get("verification_status", "unverified"))
        with st.container(border=True):
            st.markdown(f"#### Claim {index} · `{claim_id or '—'}`")
            metadata = st.columns(2)
            metadata[0].markdown(f"**Thời điểm:** {_seconds(claim.get('timestamp_s'))}")
            metadata[1].markdown(f"**Trạng thái:** {_verification_status_label(status)}")

            st.markdown("**Nhận định**")
            st.write(claim.get("text") or "Không có nội dung claim.")

            st.markdown("**Lý do xác thực**")
            st.write(verified.get("reason") or "Chưa có kết quả xác thực từ log.")

            evidence_ids = verified.get("evidence_ids")
            if isinstance(evidence_ids, list) and evidence_ids:
                st.caption(f"Evidence verification: {', '.join(str(item) for item in evidence_ids)}")


def _render_incident_window(value: Any, *, representative_timestamp_s: Any = None) -> None:
    if not isinstance(value, dict):
        st.caption("Chưa xác định khoảng thời gian sự cố.")
        return
    columns = st.columns(4)
    columns[0].metric("Bắt đầu", _seconds(value.get("t_start")))
    columns[1].metric("Sự kiện chính", _seconds(value.get("t0")))
    columns[2].metric("Kết thúc", _seconds(value.get("t_end")))
    columns[3].metric("Khung hình đại diện", _seconds(representative_timestamp_s))


def _render_section_narrative(value: Any) -> None:
    if isinstance(value, dict):
        narrative = value.get("narrative")
        if narrative:
            st.write(narrative)
    elif value:
        st.write(value)


def _timeline_rows(value: Any) -> list[dict[str, Any]]:
    events = value.get("events") if isinstance(value, dict) else None
    if not isinstance(events, list):
        return []
    return [
        {
            "Thời điểm": _seconds(event.get("timestamp_s")),
            "Diễn biến": event.get("description"),
            "Bằng chứng": ", ".join(event.get("evidence_ids", [])),
        }
        for event in events
        if isinstance(event, dict)
    ]


def _observation_rows(value: Any) -> list[dict[str, Any]]:
    observations = value.get("observations") if isinstance(value, dict) else None
    if not isinstance(observations, list):
        return []
    return [
        {
            "Thời điểm": _seconds(item.get("timestamp_s")),
            "Quan sát": item.get("text"),
            "Bằng chứng": ", ".join(item.get("evidence_ids", [])),
        }
        for item in observations
        if isinstance(item, dict)
    ]


def _render_log_summary(value: Any) -> None:
    summary = value.get("summary") if isinstance(value, dict) else None
    if not isinstance(summary, dict):
        return
    if summary.get("summary"):
        st.text(summary["summary"])
    metrics = summary.get("metrics")
    if isinstance(metrics, dict) and metrics:
        st.dataframe(
            [{"Chỉ số": key, "Giá trị": metric} for key, metric in metrics.items()],
            use_container_width=True,
            hide_index=True,
        )


def _evidence_rows(value: Any) -> list[dict[str, Any]]:
    evidence = value.get("evidence") if isinstance(value, dict) else None
    if not isinstance(evidence, list):
        return []
    return [
        {"Evidence ID": item.get("evidence_id"), "Thời điểm": _seconds(item.get("timestamp_s"))}
        for item in evidence
        if isinstance(item, dict)
    ]


def _report_verification(snapshot: dict[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
    verification = snapshot.get("verification")
    if isinstance(verification, dict):
        return verification
    alignment = report.get("alignment")
    if isinstance(alignment, dict) and isinstance(alignment.get("verification"), dict):
        return alignment["verification"]
    return None


def _report_warnings(snapshot: dict[str, Any], report: dict[str, Any]) -> list[str]:
    warnings = snapshot.get("warnings")
    combined = [item for item in warnings if isinstance(item, str)] if isinstance(warnings, list) else []
    evidence = report.get("evidence_and_warnings")
    report_warnings = evidence.get("warnings") if isinstance(evidence, dict) else None
    if isinstance(report_warnings, list):
        combined.extend(item for item in report_warnings if isinstance(item, str))
    return list(dict.fromkeys(combined))


def _seconds(value: Any) -> str:
    return f"{value:g}s" if isinstance(value, (int, float)) else "—"


def _status_label(value: Any) -> str:
    return {
        "queued": "Đang chờ",
        "running": "Đang phân tích",
        "awaiting_review": "Chờ review",
        "approved": "Đã duyệt",
        "not_incident": "Không phải sự cố",
        "failed": "Thất bại",
        "cancelled": "Đã hủy",
    }.get(value, str(value or "—"))


def _review_status_label(value: Any) -> str:
    return {
        "pending": "Chờ review",
        "approved": "Đã duyệt",
        "edited": "Đã chỉnh sửa",
        "not_incident": "Không phải sự cố",
    }.get(value, str(value or "—"))


def _verification_status_label(value: Any) -> str:
    return {
        "supported": "Được log hỗ trợ",
        "contradicted": "Mâu thuẫn với log",
        "unverified": "Chưa xác thực",
    }.get(value, str(value or "—"))


def _accident_type_label(value: Any) -> str:
    return {
        "vehicle_collision": "Va chạm với phương tiện khác",
        "crossing_collision": "Va chạm xe cắt ngang",
        "pedestrian_collision": "Va chạm người đi bộ",
        "environment_collision": "Va chạm môi trường / rời khỏi phần đường",
        "no_incident": "Không có tai nạn của ego",
        "other_unknown": "Có tai nạn nhưng chưa xác định được loại",
    }.get(value, "Chưa phân loại")


def _claim_status_rows(claims: Any, verification: Any = None) -> list[dict[str, Any]]:
    if not isinstance(claims, list):
        return []

    reasons_by_claim_id: dict[str, str] = {}
    statuses_by_claim_id: dict[str, str] = {}
    if isinstance(verification, dict) and isinstance(verification.get("results"), list):
        for result in verification["results"]:
            if not isinstance(result, dict):
                continue
            claim_id = result.get("claim_id")
            reason = result.get("reason")
            if isinstance(claim_id, str) and isinstance(reason, str):
                reasons_by_claim_id[claim_id] = reason
            status = result.get("status")
            if isinstance(claim_id, str) and isinstance(status, str):
                statuses_by_claim_id[claim_id] = status

    return [
        {
            "ID": claim.get("claim_id"),
            "Thời điểm": _seconds(claim.get("timestamp_s")),
            "Nhận định": claim.get("text"),
            "Trạng thái": _verification_status_label(
                statuses_by_claim_id.get(claim.get("claim_id"), claim.get("verification_status", "unverified"))
            ),
            "Lý do": reasons_by_claim_id.get(claim.get("claim_id"), ""),
        }
        for claim in claims
        if isinstance(claim, dict)
    ]


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
        targets = st.multiselect("Target claim IDs", claim_ids, default=claim_ids)
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
        try:
            payload.update(_reanalyze_review_fields(feedback, targets))
        except ValueError as exc:
            st.error(str(exc))
            return
    elif action == "edit":
        payload["edits"] = edits
    _start_review_async(
        "POST",
        base_url,
        f"/api/v1/incidents/{snapshot['incident_id']}/review",
        payload,
    )


def _start_review_async(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any],
) -> bool:
    if _review_request_in_progress():
        st.warning("Yêu cầu review đang được xử lý. Vui lòng không nhấn lại.")
        return False
    action = str(payload.get("action") or "review")
    st.session_state["review_action"] = action
    st.session_state["review_future"] = _REQUEST_EXECUTOR.submit(
        api_request,
        method,
        base_url,
        path,
        payload,
    )
    st.info(f"⏳ Đã gửi yêu cầu {_review_action_label(action).lower()}. Hệ thống đang xử lý…")
    return True


def _review_request_in_progress() -> bool:
    future = st.session_state.get("review_future")
    return isinstance(future, Future) and not future.done()


def _review_action_label(action: str) -> str:
    return {
        "reanalyze": "Reanalyze claims",
        "approve": "Approve incident",
        "edit": "Cập nhật report",
        "not_incident": "Đánh dấu not incident",
    }.get(action, "Review incident")


def _reanalyze_review_fields(feedback: str, target_claim_ids: list[str]) -> dict[str, Any]:
    normalized_feedback = feedback.strip()
    normalized_targets = list(dict.fromkeys(claim_id.strip() for claim_id in target_claim_ids if claim_id.strip()))
    if not normalized_feedback:
        raise ValueError("Feedback là bắt buộc khi reanalyze.")
    if not normalized_targets:
        raise ValueError("Hãy chọn ít nhất một claim để reanalyze.")
    return {"feedback": normalized_feedback, "target_claim_ids": normalized_targets}


def _narrative(report: dict[str, Any], field: str) -> str:
    section = report.get(field, {})
    return section.get("narrative", "") if isinstance(section, dict) else ""


if __name__ == "__main__":
    main()
