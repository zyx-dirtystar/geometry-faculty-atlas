"""Fetch public university directory pages into a resumable local cache."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import base64
import json
import os
from pathlib import Path
from shutil import which
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
USER_AGENT = "GeometryFacultyIndex/1.0 (public academic directory lookup)"


def load_sources():
    return json.loads((ROOT / "rosters.json").read_text(encoding="utf-8"))


def get_page(url, transport=None):
    if urlparse(url).scheme != "https":
        raise ValueError("Use HTTPS directory URLs.")
    if transport == "system" and os.name == "nt":
        shell = which("pwsh") or which("powershell")
        if not shell:
            raise ValueError("The system HTTPS requester is unavailable.")
        response = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "fetch-public.ps1"), "-Url", url],
            capture_output=True, text=True, encoding="utf-8", timeout=25,
        )
        if response.returncode:
            raise OSError(response.stderr.strip()[-500:] or "System HTTPS request failed.")
        received = json.loads(response.stdout)
        return received["url"], base64.b64decode(received["html"], validate=True)
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}), timeout=16) as response:
                if urlparse(response.geturl()).scheme != "https" or response.headers.get_content_type() != "text/html":
                    raise ValueError("The directory did not return an HTTPS HTML page.")
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise ValueError("Directory response exceeds the download limit.")
                return response.geturl(), body
        except HTTPError as error:
            if attempt or error.code not in (429, 502, 503, 504):
                raise
            delay = error.headers.get("Retry-After", "2")
            time.sleep(min(int(delay), 15) if delay.isdigit() else 2)


def save_source(source, refresh=False):
    name = source["id"]
    meta_path = CACHE / f"{name}.json"
    if meta_path.exists() and not refresh:
        previous = json.loads(meta_path.read_text(encoding="utf-8"))
        if previous.get("url") == source["url"] and previous.get("sha256"):
            saved = CACHE / f"{name}.{previous['sha256']}.html"
            if saved.is_file() and sha256(saved.read_bytes()).hexdigest() == previous["sha256"]:
                return {"id": name, "status": "cached", "bytes": saved.stat().st_size}
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        final_url, body = get_page(source["url"], source.get("transport"))
        fingerprint = sha256(body).hexdigest()
        target = CACHE / f"{name}.{fingerprint}.html"
        if not target.exists():
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(target)
        result = {**source, "status": "fetched", "final_url": final_url, "sha256": fingerprint, "retrieved_at": timestamp, "bytes": len(body)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
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
