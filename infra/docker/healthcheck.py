"""HTTP probe for the API container.

Prod settings redirect plain HTTP to HTTPS. The probe presents
X-Forwarded-Proto so SECURE_SSL_REDIRECT does not turn a live check into 301.
"""

import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/health/live/"
    status_name = sys.argv[2] if len(sys.argv) > 2 else "alive"
    host = os.environ.get("HEALTHCHECK_HOST", "spy.way2points.com")
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        headers={"Host": host, "X-Forwarded-Proto": "https"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
            status = response.status
    except (urllib.error.URLError, TimeoutError, OSError):
        return 1
    token = f'"status":"{status_name}"'.encode()
    if status != 200 or token not in body:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
