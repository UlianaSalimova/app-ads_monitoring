import requests


def fetch_app_ads(domain: str) -> dict[str, str | None]:
    url = f"https://{domain}/app-ads.txt"

    try:
        response = requests.get(url, timeout=10, allow_redirects=True)

        if response.status_code == 200:
            return {
                "domain": domain,
                "url": response.url,
                "content": response.text,
                "error_details": None,
            }

        return {
            "domain": domain,
            "url": response.url,
            "content": None,
            "error_details": f"HTTP {response.status_code}",
        }

    except requests.exceptions.Timeout:
        return {
            "domain": domain,
            "url": url,
            "content": None,
            "error_details": "Timeout",
        }

    except requests.exceptions.RequestException:
        return {
            "domain": domain,
            "url": url,
            "content": None,
            "error_details": "RequestException",
        }