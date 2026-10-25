"""HTTP client for go-sensor-data-collector."""

import json
import urllib.error
import urllib.parse
import urllib.request


class API:
    def __init__(self, base_url, token="", timeout=5):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("API_URL must be an HTTP(S) base URL without credentials, query or fragment")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def send(self, readings):
        results = {}
        for sensor, payload in readings.items():
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            request = urllib.request.Request(
                f"{self.base_url}/sensor/{sensor}",
                data=json.dumps(payload, allow_nan=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.status != 201:
                        raise RuntimeError(f"Unexpected HTTP status {response.status}")
                results[sensor] = "ok"
            except urllib.error.HTTPError as error:
                results[sensor] = f"HTTP {error.code}"
                error.close()
            except (OSError, ValueError, RuntimeError):
                # Do not log credentials, URLs or response bodies.
                results[sensor] = "connection error"
        return results
