"""Fetch public university directory pages into a resumable local cache."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from http.client import InvalidURL
import argparse
import base64
import json
import os
from pathlib import Path
from shutil import which
import ssl
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
USER_AGENT = "GeometryFacultyIndex/1.0 (public academic directory lookup)"


def load_sources():
    return json.loads((ROOT / "rosters.json").read_text(encoding="utf-8"))


def get_page(url, transport=None, data_type="html"):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Use HTTPS directory URLs.")
    media_type = {"html":"text/html", "json":"application/json"}[data_type]
    if transport == "system" and os.name == "nt":
        shell = which("pwsh") or which("powershell")
        if not shell:
            raise ValueError("The system HTTPS requester is unavailable.")
        response = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "fetch-public.ps1"), "-Url", url, "-MediaType", media_type],
            capture_output=True, text=True, encoding="utf-8", timeout=25,
        )
        if response.returncode:
            raise OSError(response.stderr.strip()[-500:] or "System HTTPS request failed.")
        received = json.loads(response.stdout)
        return received["url"], base64.b64decode(received["html"], validate=True)
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": media_type}), timeout=16) as response:
                if urlparse(response.geturl()).scheme != "https" or response.headers.get_content_type() != media_type:
                    raise ValueError(f"The directory did not return the expected public {media_type} content.")
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise ValueError("Directory response exceeds the download limit.")
                return response.geturl(), body
        except HTTPError as error:
            if attempt or error.code not in (429, 502, 503, 504):
                raise
            delay = error.headers.get("Retry-After", "2")
            time.sleep(min(int(delay), 15) if delay.isdigit() else 2)
        except URLError as error:
            if os.name == "nt" and isinstance(error.reason, ssl.SSLCertVerificationError):
                return get_page(url, "system", data_type)
            raise


def save_source(source, refresh=False):
    name = source["id"]
    data_type = source.get("data_type","html")
    meta_path = CACHE / f"{name}.json"
    if meta_path.exists() and not refresh:
        previous = json.loads(meta_path.read_text(encoding="utf-8"))
        if previous.get("url") == source["url"] and previous.get("data_type","html") == data_type and previous.get("sha256"):
            saved = CACHE / f"{name}.{previous['sha256']}.{data_type}"
            if saved.is_file() and sha256(saved.read_bytes()).hexdigest() == previous["sha256"]:
                return {"id": name, "status": "cached", "bytes": saved.stat().st_size}
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        final_url, body = get_page(source["url"], source.get("transport"), data_type)
        fingerprint = sha256(body).hexdigest()
        target = CACHE / f"{name}.{fingerprint}.{data_type}"
        if not target.exists():
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(target)
        result = {**source, "status": "fetched", "final_url": final_url, "sha256": fingerprint, "retrieved_at": timestamp, "bytes": len(body)}
    except (InvalidURL, OSError, ValueError, subprocess.TimeoutExpired) as error:
        result = {**source, "status": "source_error", "error": str(error), "retrieved_at": timestamp}
    temp = meta_path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(meta_path)
    return result


def fetch_sources(schools=(), refresh=False):
    CACHE.mkdir(exist_ok=True)
    sources = [source for source in load_sources() if not schools or source["school"] in schools]
    with ThreadPoolExecutor(max_workers=3) as workers:
        for result in workers.map(lambda source: save_source(source, refresh), sources):
            shown = {key: result[key] for key in ("id", "status", "bytes", "error") if key in result}
            print(json.dumps(shown, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", action="append", default=[], help="只查询指定学校 ID，可重复")
    parser.add_argument("--refresh", action="store_true", help="重新读取已缓存的目录")
    args = parser.parse_args()
    fetch_sources(args.school, args.refresh)
