from novelwiki.platform.web.factory import _log_completed_request


def test_successful_job_list_poll_is_replaced_by_job_snapshot_logging():
    assert _log_completed_request("GET", "/api/jobs", 200) is False
    assert _log_completed_request("GET", "/api/jobs/", 204) is False


def test_job_list_failures_and_other_requests_keep_http_logging():
    assert _log_completed_request("GET", "/api/jobs", 500) is True
    assert _log_completed_request("POST", "/api/jobs", 200) is True
    assert _log_completed_request("GET", "/api/jobs/8", 200) is True
    assert _log_completed_request("GET", "/api/activity", 200) is True
