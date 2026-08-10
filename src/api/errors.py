"""Safe HTTP mapping for incident workflow domain errors."""

from fastapi import HTTPException


def incident_http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "INCIDENT_WORKFLOW_FAILED")
    input_errors = {
        "ANALYSIS_PROMPT_TOO_LONG",
        "VIDEO_INPUT_INVALID",
        "VIDEO_DURATION_EXCEEDED",
        "INCIDENT_INPUT_OUTSIDE_ROOT",
        "INCIDENT_INPUT_NOT_FOUND",
        "INCIDENT_INPUT_TOO_LARGE",
        "UPLOAD_FILE_TYPE_INVALID",
        "UPLOAD_FILE_TOO_LARGE",
        "UPLOAD_FILE_EMPTY",
    }
    status_code = {
        "INCIDENT_NOT_FOUND": 404,
        "INCIDENT_ALREADY_EXISTS": 409,
        "INVALID_REVIEW_TRANSITION": 409,
        "REANALYSIS_TARGET_INVALID": 409,
        "REPORT_ALREADY_STORED": 409,
        "INCIDENT_DELETE_ACTIVE": 409,
    }.get(code, 422 if code in input_errors else 500)
    safe_message = {
        "INCIDENT_NOT_FOUND": "incident does not exist",
        "INCIDENT_ALREADY_EXISTS": "incident ID already exists",
        "INVALID_REVIEW_TRANSITION": "incident is not awaiting review",
        "REANALYSIS_TARGET_INVALID": "re-analysis target claim does not exist",
        "REPORT_ALREADY_STORED": "terminal outcome is already stored",
        "INCIDENT_DELETE_ACTIVE": "running incident cannot be deleted",
    }.get(code, "incident input is invalid" if code in input_errors else "incident workflow failed")
    return HTTPException(status_code=status_code, detail={"code": code, "message": safe_message})
