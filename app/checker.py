from datetime import datetime

from app.fetcher import fetch_app_ads
from app.preprocessor import preprocess_ads_lines


STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
STATUS_NETWORK_ERROR = "NETWORK_ERROR"


def check_domain(domain: str, reference_set: set[str]) -> dict:
    fetch_result = fetch_app_ads(domain)

    if fetch_result["content"] is None:
        return {
            "domain": domain,
            "ads_status": STATUS_NETWORK_ERROR,
            "error_details": fetch_result["error_details"],
            "missing_lines": set(),
            "missing_count": 0,
            "match_rate": 0.0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    partner_set = preprocess_ads_lines(fetch_result["content"].splitlines())
    missing_lines = reference_set - partner_set

    ads_status = STATUS_OK if not missing_lines else STATUS_ERROR

    match_rate = (
        (len(reference_set) - len(missing_lines)) / len(reference_set) * 100
        if reference_set
        else 0.0
    )

    return {
        "domain": domain,
        "ads_status": ads_status,
        "error_details": None,
        "missing_lines": missing_lines,
        "missing_count": len(missing_lines),
        "match_rate": round(match_rate, 2),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }