"""Maintain the local roster queue and build the website's research directory."""

from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
from threading import Lock
import time
import unicodedata
from urllib.parse import urlparse

from lxml import etree, html

from roster_parsers import ADJACENT, PARSERS, Entry, matched_fields, parse_structured_directory, profile_fields, split_role
from snapshot import CACHE, ROOT, load_sources, save_source

PROJECT = ROOT.parent
OUTPUT = PROJECT / "dist"
STATE = ROOT / "progress.sqlite3"
CHECKPOINT = ROOT / "checkpoint.json"
CHECKPOINT_TABLES = {
    "sources": ("id", "school", "url", "label", "status", "count", "checked_at", "note"),
    "sightings": ("source", "person_key", "school", "record"),
    "profiles": ("url", "cache_id", "status", "record", "checked_at"),
}
SHANGHAI = timezone(timedelta(hours=8))
PROFILE_HOSTS = {
    "stanford": {"mathematics.stanford.edu"},
    "princeton": {"www.math.princeton.edu", "math.princeton.edu"},
    "stony-brook": {"www.math.stonybrook.edu", "math.stonybrook.edu"},
    "bonn": {"www.math.uni-bonn.de", "www.mathematics.uni-bonn.de"},
    "pku": {"bicmr.pku.edu.cn", "math.pku.edu.cn", "math-en.pku.edu.cn"},
    "rutgers": {"sites.math.rutgers.edu", "math.rutgers.edu", "www.math.rutgers.edu"},
    "mit": {"math.mit.edu", "www.mit.edu"},
    "oxford": {"www.maths.ox.ac.uk", "people.maths.ox.ac.uk"},
    "nyu": {"math.nyu.edu", "cims.nyu.edu", "www.cims.nyu.edu"},
    "eth": {"math.ethz.ch", "people.math.ethz.ch", "people.ethz.ch", "www.mis.mpg.de"},
    "epfl": {"people.epfl.ch", "www.epfl.ch", "cag.epfl.ch", "sma.epfl.ch", "egg.epfl.ch"},
    "ucla": {"ww3.math.ucla.edu", "www.math.ucla.edu", "math.ucla.edu"},
    "berkeley": {"math.berkeley.edu", "www.math.berkeley.edu"},
    "yale": {"math.yale.edu", "users.math.yale.edu", "www.math.yale.edu"},
    "kyoto": {"www.math.kyoto-u.ac.jp", "www.kurims.kyoto-u.ac.jp", "kdb.iimc.kyoto-u.ac.jp"},
    "warwick": {"warwick.ac.uk", "www.warwick.ac.uk", "homepages.warwick.ac.uk"},
    "duke": {"math.duke.edu", "scholars.duke.edu", "www.math.duke.edu", "services.math.duke.edu"},
    "uchicago": {"mathematics.uchicago.edu", "math.uchicago.edu"},
    "imperial": {"profiles.imperial.ac.uk", "www.imperial.ac.uk"},
    "brown": {"mathematics.brown.edu", "www.math.brown.edu"},
    "tokyo": {"www.ms.u-tokyo.ac.jp", "www.ipmu.jp", "member.ipmu.jp"},
    "washington": {"math.washington.edu", "sites.math.washington.edu", "www.math.washington.edu"},
    "hebrew-jerusalem": {"mathematics.huji.ac.il", "math.huji.ac.il", "www.math.huji.ac.il"},
    "harvard": {"www.math.harvard.edu", "people.math.harvard.edu"},
    "barcelona": {"www.ub.edu", "www.maia.ub.edu", "sira.ub.edu", "webgrec.ub.edu"},
    "cambridge": {"www.dpmms.cam.ac.uk", "www.maths.cam.ac.uk", "dow.cam.ac.uk", "www.joh.cam.ac.uk"},
    "fudan": {"faculty.fudan.edu.cn", "math.fudan.edu.cn", "scms.fudan.edu.cn"},
    "johns-hopkins": {"mathematics.jhu.edu", "math.jhu.edu", "www.math.jhu.edu"},
    "minnesota": {"cse.umn.edu", "www.math.umn.edu", "math.umn.edu"},
    "shanghai-university": {"math.shu.edu.cn", "scicol.shu.edu.cn"},
    "turin": {"www.dipmatematica.unito.it", "www.mathphd.unito.it", "www.matematica.unito.it"},
    "ut-austin": {"math.utexas.edu", "web.ma.utexas.edu"},
    "edinburgh": {"webhomes.maths.ed.ac.uk", "www.maths.ed.ac.uk", "www.research.ed.ac.uk"},
    "tsinghua": {"math.tsinghua.edu.cn", "www.math.tsinghua.edu.cn", "ymsc.tsinghua.edu.cn"},
}
UNITS = {"stanford":"数学系", "princeton":"数学系", "stony-brook":"数学系", "bonn":"Bonn Mathematics", "pku":"北京国际数学研究中心"}


def json_text(value):
    return json.dumps(value, ensure_ascii=False)


def now_date():
    return datetime.now(SHANGHAI).date().isoformat()


def name_key(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name).casefold() if c.isalnum())


def name_slug(name):
    latin = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub("[^a-z0-9]+", "-", latin).strip("-")
    return slug if slug and slug[0].isalpha() else "person-" + sha256(name.encode()).hexdigest()[:12]


def node_path():
    node = shutil.which("node")
    bundled = Path(os.environ.get("USERPROFILE", ".")) / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if bundled.is_file() and not node:
        node = str(bundled)
    if not node:
        raise SystemExit("需要 Node.js 读取现有网站学校池与样本。")
    return node


def seed_catalog():
    reader = (
        'const fs=require("node:fs"),vm=require("node:vm");'
        'const box={window:{}};vm.createContext(box);'
        'for(const path of ["dist/schools.js","dist/faculty.js"])'
        'vm.runInContext(fs.readFileSync(path,"utf8"),box);'
        'const s=box.window;console.log(JSON.stringify({schools:s.geometrySchools,'
        'people:s.geometryFaculty,ranking:s.geometryRanking}));'
    )
    result = subprocess.run([node_path(),"-e",reader], cwd=PROJECT, check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def connect():
    db = sqlite3.connect(STATE)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS schools (id TEXT PRIMARY KEY, record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, school TEXT NOT NULL, url TEXT NOT NULL,
            label TEXT NOT NULL, status TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT, note TEXT
        );
        CREATE TABLE IF NOT EXISTS sightings (
            source TEXT NOT NULL, person_key TEXT NOT NULL, school TEXT NOT NULL,
            record TEXT NOT NULL, PRIMARY KEY (source, person_key)
        );
        CREATE TABLE IF NOT EXISTS profiles (
            url TEXT PRIMARY KEY, cache_id TEXT NOT NULL, status TEXT NOT NULL,
            record TEXT, checked_at TEXT
        );
    """)
    if CHECKPOINT.is_file() and all(
        db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is None for table in CHECKPOINT_TABLES
    ):
        checkpoint = read_checkpoint()
        with db:
            for table, columns in CHECKPOINT_TABLES.items():
                placeholders = ",".join("?" for _ in columns)
                rows = [
                    tuple(json_text(row[key]) if key == "record" and row[key] is not None else row[key] for key in columns)
                    for row in checkpoint[table]
                ]
                db.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", rows)
    return db


def read_checkpoint():
    if not CHECKPOINT.is_file():
        return {"schemaVersion":1, "sources":[], "sightings":[], "profiles":[], "metrics":{}}
    payload = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("无法读取此版本的采集断点文件。")
    return payload


def read_snapshot(source_id):
    location = CACHE / f"{source_id}.json"
    if not location.exists():
        return None, None
    meta = json.loads(location.read_text(encoding="utf-8"))
    if not meta.get("sha256"):
        return meta, None
    data_type = meta.get("data_type","html")
    snapshot = CACHE / f"{source_id}.{meta['sha256']}.{data_type}"
    if not snapshot.exists():
        return meta, None
    content = snapshot.read_bytes()
    if sha256(content).hexdigest() != meta["sha256"]:
        return meta, None
    if data_type == "json":
        try:
            return meta, json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return meta, None
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        declared = re.search(rb"charset\s*=\s*[\"']?\s*([\w.-]+)", content[:8192], re.I)
        encoding = declared[1].decode("ascii") if declared else "windows-1252"
        try:
            content = content.decode(encoding, errors="replace").encode("utf-8")
        except LookupError:
            content = content.decode("windows-1252", errors="replace").encode("utf-8")
    try:
        document = html.fromstring(content, parser=html.HTMLParser(encoding="utf-8"))
    except etree.ParserError:
        return meta, None
    title = " ".join(document.xpath("string(/html/head/title)").split()).casefold()
    if title in {"request rejected", "access denied", "just a moment...", "attention required! | cloudflare"}:
        return {**meta, "error":"Access denied by the source website."}, None
    return meta, document


def seen_date(meta):
    timestamp = meta.get("retrieved_at") if meta else None
    return datetime.fromisoformat(timestamp).astimezone(SHANGHAI).date().isoformat() if timestamp else None


def ingest_rosters(db, seed):
    configured_sources = load_sources()
    configured_ids = {source["id"] for source in configured_sources}
    with db:
        db.executemany("INSERT OR REPLACE INTO schools VALUES (?,?)", [(s["id"], json_text(s)) for s in seed["schools"]])
        retired = [(row["id"],) for row in db.execute("SELECT id FROM sources") if row["id"] not in configured_ids]
        db.executemany("DELETE FROM sightings WHERE source=?", retired)
        db.executemany("DELETE FROM sources WHERE id=?", retired)
    transcript_path = ROOT / "official-roster-transcripts.json"
    transcripts = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.is_file() else {}
    for source in configured_sources:
        meta, document = read_snapshot(source["id"])
        transcript = transcripts.get(source["id"])
        if source["kind"] == "campus":
            with db:
                db.execute("DELETE FROM sightings WHERE source=?", (source["id"],))
                db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?)", (
                    source["id"], source["school"], source["url"], source["name"], "reference", 0, seen_date(meta),
                    "全校名录保留作任职补证。研究人员范围由数学研究所及有关研究组确认。",
                ))
            continue
        if not transcript and meta is None and db.execute("SELECT 1 FROM sources WHERE id=? AND url=?", (source["id"], source["url"])).fetchone():
            continue
        rows = []
        if document is not None:
            if "layout" in source:
                rows = parse_structured_directory(document, meta["final_url"], source["layout"])
            else:
                rows = PARSERS[source["parser"]](document, meta["final_url"])
        if meta is None:
            status, note = "pending", "尚未取得网页。"
        elif document is None:
            error = (meta.get("error") or "").casefold()
            status = "source_error"
            if re.search(r"\b(?:401|403|forbidden|access denied)\b", error):
                note = "机构网站限制了目录请求。"
            elif "ssl:" in error or "certificate" in error:
                note = "HTTPS 连接或证书校验失败。"
            elif "timed out" in error or "timeout" in error:
                note = "网页请求超时。"
            elif "html" in error:
                note = "来源返回的内容需要另行读取。"
            else:
                note = "网页暂未读取成功。"
        elif not rows:
            status, note = "needs_adapter", "已保存网页，目录为动态列表或结构尚未对账。"
        else:
            status, note = "parsed", ""
        checked_at = seen_date(meta)
        if not rows and transcript and transcript["url"] == source["url"] and transcript["entries"]:
            rows = [Entry(**row) for row in transcript["entries"]]
            checked_at = transcript["checkedAt"]
            status, note = "parsed", transcript["scope"]
        # Preserve the last successful records if a later fetch fails.
        with db:
            if status == "parsed":
                db.execute("DELETE FROM sightings WHERE source=?", (source["id"],))
                for row in rows:
                    data = {**asdict(row), "source_kind":source["kind"], "source_url":source.get("evidence_url",source["url"]), "checked_at":checked_at}
                    if source.get("unit"):
                        data["unit"] = source["unit"]
                    db.execute("INSERT OR REPLACE INTO sightings VALUES (?,?,?,?)",
                               (source["id"], name_key(row.name), source["school"], json_text(data)))
            count = db.execute("SELECT COUNT(*) FROM sightings WHERE source=?", (source["id"],)).fetchone()[0]
            db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?)",
                       (source["id"],source["school"],source["url"],source["name"],status,count,checked_at,note))


def add_profile_data(db):
    for row in db.execute("SELECT url, cache_id FROM profiles").fetchall():
        meta, document = read_snapshot(row["cache_id"])
        if meta is None:
            continue
        if document is None:
            with db:
                db.execute("UPDATE profiles SET status='source_error', checked_at=? WHERE url=?", (seen_date(meta), row["url"]))
            continue
        details = profile_fields(document, meta["final_url"])
        details["checked_at"] = seen_date(meta)
        with db:
            db.execute("UPDATE profiles SET status='parsed', record=?, checked_at=? WHERE url=?",
                       (json_text(details),seen_date(meta),row["url"]))


def population(db):
    result = {}
    regions = {row["id"]:json.loads(row["record"])["region"] for row in db.execute("SELECT id,record FROM schools")}
    source_order = {source["id"]:index for index, source in enumerate(load_sources())}
    sightings = db.execute("SELECT school,person_key,source,record FROM sightings").fetchall()
    for sighting in sorted(sightings, key=lambda row: (
        row["school"], row["person_key"], source_order.get(row["source"],len(source_order)), row["source"],
    )):
        row = json.loads(sighting["record"])
        school = sighting["school"]
        group = result.setdefault((school,sighting["person_key"]), {"school":school, "name":row["name"],"evidence":[]})
        group["evidence"].append(row)
    profiles = {item["url"]:json.loads(item["record"]) for item in db.execute("SELECT url,record FROM profiles WHERE record IS NOT NULL")}
    review_path = ROOT / "verified-profiles.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else []
    reviewed = {(row["school"],name_key(row["name"])):row for row in reviews}
    for row in reviews:
        result.setdefault((row["school"],name_key(row["name"])), {"school":row["school"],"name":row["name"],"evidence":[]})
    for group in result.values():
        evidence = group["evidence"]
        active = next((row for row in evidence if row["source_kind"] in ("department","center") and row["title"]), None)
        review = reviewed.get((group["school"],name_key(group["name"])), {})
        group["profile"] = review.get("affiliation") or next((row["profile"] for row in evidence if row["profile"]), "")
        directory_profile = profiles.get(group["profile"], {})
        official_title = directory_profile.get("official_title", "") if group["school"] == "uab" else ""
        group["title"] = review.get("title") or (active["title"] if active else official_title)
        group["unit"] = review.get("unit") or (active.get("unit") if active else None)
        group["role"] = review.get("role") or split_role(group["title"], regions.get(group["school"]))
        group["affiliation_url"] = review.get("affiliation") or (active["profile"] or active["source_url"] if active else group["profile"] if official_title else "")
        group["homepage"] = review.get("homepage") or next((row["homepage"] for row in evidence if row["homepage"]), "")
        sources = [
            {"text":row["research"], "url":row["source_url"]} for row in evidence
            if row["research"] and not review.get("replace_research")
        ]
        if review.get("research"):
            sources.append({"text":review["research"],"url":review["research_source"]})
        cv = review.get("cv") or ""
        publications = review.get("publications") or ""
        counts = list(review.get("publicationCounts", []))
        is_relevant_role = group["role"] in ("faculty","unverified")
        official = profiles.get(group["profile"], {}) if is_relevant_role else {}
        if not group["homepage"] and official.get("homepage"):
            group["homepage"] = official["homepage"]
        for url in dict.fromkeys([group["profile"], group["homepage"]]) if is_relevant_role else ():
            profile = profiles.get(url, {})
            if profile.get("research") and not review.get("replace_research"):
                sources.append({"text":profile["research"],"url":url})
            if not group["homepage"] and profile.get("homepage"):
                group["homepage"] = profile["homepage"]
            cv = cv or profile.get("cv") or ""
            publications = publications or profile.get("publications") or ""
            for count in profile.get("publication_counts", []):
                checked = profile.get("checked_at")
                if not checked or any(item["scope"] == count["scope"] and item["url"] == count["url"]
                                      and item["checkedAt"] == checked for item in counts):
                    continue
                counts.append({**count, "checkedAt":checked})
        group["cv"] = cv
        group["cv_type"] = review.get("cvType") or ("公开 CV（简版）" if cv and re.search(r"(?:mini|short|brief)[-_]?[_-]?(?:cv|vita)|cv[-_](?:mini|short|brief)", cv, re.I) else None)
        group["cv_status"] = review.get("cvStatus")
        group["publications"] = publications
        group["publication_counts"] = counts
        group["topic_sources"] = sources
        text = " / ".join(item["text"] for item in sources)
        fields = matched_fields(text)
        group["fields"] = fields
        if review.get("decision") == "adjacent":
            decision = "adjacent"
        elif group["role"] in ("emeritus","associated","other"):
            decision = group["role"]
        elif not text or (ADJACENT.search(text) and not fields):
            decision = "topic_review"
        elif not fields:
            decision = "other_topic"
        elif group["role"] != "faculty":
            decision = "role_review"
        else:
            decision = "candidate"
        group["decision"] = decision
        group["decision_note"] = review.get("reason", "")
        group["opportunities"] = review.get("opportunities", [])
        group["papers"] = review.get("papers", [])
        group["aliases"] = review.get("aliases", [])
        dates = [row.get("checked_at") or "" for row in evidence]
        group["checked_at"] = max(dates + [review.get("checkedAt","")]) or None
    homepage_owners = defaultdict(set)
    for group in result.values():
        if group["decision"] == "candidate" and group["homepage"]:
            homepage_owners[group["homepage"].rstrip("/")].add(name_key(group["name"]))
    shared_homepages = {url for url, owners in homepage_owners.items() if len(owners) > 1}
    for group in result.values():
        if group["homepage"].rstrip("/") in shared_homepages:
            group["homepage"] = ""
            group["homepage_status"] = "现有链接由不同学者共用，未核实到独立个人主页。"
    return sorted(result.values(), key=lambda group: (group["school"],group["name"]))


def allowed_profile(school, url):
    result = urlparse(url)
    return (
        result.scheme == "https" and not result.username and not result.password
        and result.hostname in PROFILE_HOSTS.get(school, set()) and result.path not in ("", "/")
        and not result.path.lower().endswith(".pdf")
    )


def fetch_profiles(db, schools, refresh=False, max_profiles=0):
    queue = {}
    current = {row["url"]:row for row in db.execute("SELECT url,status,checked_at FROM profiles")}
    today = now_date()
    for source in load_sources():
        if source["parser"] != "pending":
            PROFILE_HOSTS.setdefault(source["school"], set()).add(urlparse(source["url"]).hostname)
    reviews = json.loads((ROOT / "verified-profiles.json").read_text(encoding="utf-8"))
    for review in reviews:
        for key in ("affiliation", "homepage"):
            target = review.get(key)
            if target and urlparse(target).scheme == "https":
                PROFILE_HOSTS.setdefault(review["school"], set()).add(urlparse(target).hostname)
    people = sorted(population(db), key=lambda row: (row["decision"] != "candidate", row["school"], row["name"]))
    for person in people:
        school = person["school"]
        if (schools and school not in schools) or person["role"] in ("emeritus","associated","other"):
            continue
        topical = " ".join(item["text"] for item in person["topic_sources"])
        if person["decision"] == "adjacent" or (person["decision"] == "other_topic" and not ADJACENT.search(topical)):
            continue
        for target in (person["profile"], person["homepage"]):
            if not target or not allowed_profile(school, target):
                continue
            previous = current.get(target)
            if previous and not refresh and (previous["status"] == "parsed" or previous["checked_at"] == today):
                continue
            cache_id = "profile-" + sha256(target.encode()).hexdigest()[:16]
            queue[target] = {"id":cache_id, "school":school, "name":person["name"], "url":target, "kind":"profile",
                             "transport":"system" if school == "bonn" else None}
    by_host = defaultdict(deque)
    for job in queue.values():
        by_host[urlparse(job["url"]).hostname].append(job)
    jobs = []
    while by_host:
        for host in list(by_host):
            jobs.append(by_host[host].popleft())
            if not by_host[host]:
                del by_host[host]
    if max_profiles:
        jobs = jobs[:max_profiles]
    print(json_text({"profile_queue":len(queue),"this_run":len(jobs)}),flush=True)
    CACHE.mkdir(exist_ok=True)
    with db:
        db.executemany("INSERT OR IGNORE INTO profiles(url,cache_id,status) VALUES (?,?,'queued')", [(job["url"],job["id"]) for job in jobs])

    locks = {urlparse(job["url"]).hostname:Lock() for job in jobs}

    def fetch(job):
        with locks[urlparse(job["url"]).hostname]:
            time.sleep(0.35)
            return job, save_source(job, refresh)

    with ThreadPoolExecutor(max_workers=8) as workers:
        for job, saved in workers.map(fetch, jobs):
            print(json_text({"school":job["school"],"name":job["name"],"status":saved["status"]}),flush=True)
    add_profile_data(db)


def keep_tags(sources):
    tags = []
    for source in sources:
        for part in re.split(r"\s*[;；/]+\s*|\.\s+",source["text"]):
            cleaned = part.strip(" .")
            if cleaned and len(cleaned) < 64 and cleaned.casefold() not in {t.casefold() for t in tags}:
                tags.append(cleaned)
            if len(tags) >= 8:
                return tags
    return tags


def metrics_evidence():
    anchors_path = ROOT / "metric-anchors.json"
    findings_path = ROOT / "metric-findings.json"
    reviewed_path = ROOT / "metric-review.json"
    anchors = json.loads(anchors_path.read_text(encoding="utf-8")) if anchors_path.exists() else []
    findings = read_checkpoint()["metrics"]
    if findings_path.exists():
        findings.update(json.loads(findings_path.read_text(encoding="utf-8")))
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8")) if reviewed_path.exists() else {}
    return {row["id"]:row for row in anchors}, findings, reviewed.get("accepted",{}), reviewed.get("notes",{})


def make_patch(seed, data, source_rows, scope_notes, school_reviews):
    original = {(a["schoolId"], name_key(p["name"])):p for p in seed["people"] for a in p["affiliations"]}
    original_names = {name for _, name in original}
    cross_school = Counter(name_key(p["name"]) for p in data if p["decision"] == "candidate")
    used_ids = {p["id"] for p in seed["people"]}
    anchors, findings, reviewed, review_notes = metrics_evidence()
    additions = []
    supplements = {}
    for person in data:
        if person["decision"] != "candidate":
            continue
        school = person["school"]
        key = name_key(person["name"])
        seeded = original.get((school,key))
        if seeded is not None:
            updated = supplements.setdefault(seeded["id"], dict(seeded))
            for target, value in (("homepage",person["homepage"]), ("cvUrl",person["cv"]),
                                  ("publicationsUrl",person["publications"])):
                if value and not updated.get(target):
                    updated[target] = value
            if person.get("homepage_status") and not updated.get("homepage"):
                updated["homepageStatus"] = person["homepage_status"]
            if updated.get("cvUrl") == person["cv"] and person["cv_type"]:
                updated["cvType"] = person["cv_type"]
            if person.get("cv_status") and not updated.get("cvUrl"):
                updated["cvStatus"] = person["cv_status"]
            if person["publication_counts"]:
                counts = {(m["scope"], m["url"], m["checkedAt"]): m for m in updated.get("publicationCounts", [])}
                counts.update({(m["scope"], m["url"], m["checkedAt"]): m for m in person["publication_counts"]})
                updated["publicationCounts"] = list(counts.values())
            if person["opportunities"]:
                opportunities = {item["url"]: item for item in updated.get("opportunities", [])}
                opportunities.update({item["url"]: item for item in person["opportunities"]})
                updated["opportunities"] = list(opportunities.values())
            if person["papers"]:
                papers = {paper["url"]: paper for paper in updated.get("papers", []) + person["papers"]}
                updated["papers"] = list(papers.values())
            if person["aliases"]:
                updated["aliases"] = list(dict.fromkeys(updated.get("aliases", []) + person["aliases"]))
            finding = findings.get(seeded["id"], {})
            if finding.get("author_id") and finding["author_id"] == reviewed.get(seeded["id"]) and finding.get("snapshot"):
                snapshot = finding["snapshot"]
                metrics = {(m["source"],m["authorId"],m["checkedAt"]):m for m in updated.get("metrics", [])}
                metrics[(snapshot["source"],snapshot["authorId"],snapshot["checkedAt"])] = snapshot
                updated["metrics"] = list(metrics.values())
                papers = {p["url"]:p for p in finding.get("papers", [])}
                papers.update({p["url"]:p for p in updated.get("papers", [])})
                updated["papers"] = list(papers.values())
            if updated != seeded:
                updated["checkedAt"] = max(updated.get("checkedAt") or "", person["checked_at"] or "")
            continue
        if key in original_names or cross_school[key] > 1:
            person["decision"] = "affiliation_review"
            continue
        slug = name_slug(person["name"])
        if slug in used_ids:
            slug = f"{slug}-{school}"
        used_ids.add(slug)
        anchor = anchors.get(slug,{})
        finding = findings.get(slug,{})
        known = finding.get("status") == "review_ready" and finding.get("author_id") and finding["author_id"] == reviewed.get(slug)
        reason = (("已用机构公开 ORCID、作者姓名与数学论文抽样核对 OpenAlex 作者档案。" if anchor.get("orcid") else
                   "已用论文 DOI、机构与数学论文抽样核对 OpenAlex 作者档案。") if known else
                  review_notes.get(slug) or finding.get("reason") or "已从公开师资目录匹配任职与研究方向。作者 ID、文章计数和引用仍待核对。")
        cv = anchor.get("cv") or person["cv"]
        publications = person["publications"]
        sources = list(person["topic_sources"])
        if anchor.get("source"):
            sources.append({"text":"个人研究或论文来源","url":anchor["source"]})
        additions.append({
            "id":slug, "name":person["name"], "aliases":person["aliases"], "affiliations":[{
                "schoolId":school, "department":person["unit"] or UNITS.get(school,"数学系"),"title":person["title"],
                "url":person["affiliation_url"],"type":"primary","checkedAt":person["checked_at"],
            }],
            "fields":person["fields"],"tags":keep_tags(person["topic_sources"]),
            "homepage":anchor.get("homepage") or person["homepage"] or None,
            "homepageStatus":person.get("homepage_status"), "cvUrl":cv or None,
            "cvType":person["cv_type"] if cv == person["cv"] else None,
            "cvStatus":(person.get("cv_status") or "独立 CV 待核对。") if not cv else None,
            "publicationsUrl":publications or None,
            "publicationCounts":person["publication_counts"],
            "opportunities":person["opportunities"],
            "identityNote":reason, "metrics":[finding["snapshot"]] if known else [],
            "identityUrl":(finding.get("candidate_url") or finding.get("snapshot",{}).get("url"))
                if slug in review_notes or finding.get("status") == "identity_review" else None,
            "papers":list({p["url"]: p for p in finding.get("papers", []) + person["papers"]}.values()),
            "directoryEvidence":sources,
            "checkedAt":person["checked_at"], "recordStatus":"directory",
        })
    school_patches = []
    listed = {}
    roster_audit = {row["id"]:row for row in load_sources() if "audited_count" in row}
    for person in [supplements.get(person["id"], person) for person in seed["people"]] + additions:
        for affiliation in person["affiliations"]:
            listed.setdefault(affiliation["schoolId"], []).append(person)
    for school in seed["schools"]:
        school_id = school["id"]
        sources = [item for item in source_rows if item["school"] == school_id]
        if not sources:
            continue
        successful = [item for item in sources if item["status"] == "parsed"]
        parsed = len(successful)
        refs = [[source["label"],source["url"]] for source in sources]
        pending = sum(person["school"] == school_id and person["decision"] in ("topic_review","role_review","affiliation_review") for person in data)
        people = listed.get(school_id, [])
        covers = [
            f"个人主页 {sum(bool(p.get('homepage')) for p in people)}",
            f"CV {sum(bool(p.get('cvUrl')) for p in people)}",
            f"指标 {sum(bool(p.get('metrics')) for p in people)}",
        ]
        note = f"已解析 {parsed}/{len(sources)} 个登记来源，{pending} 条任职或方向待核。"
        checked_lists = [
            row["label"] for row in successful
            if roster_audit.get(row["id"], {}).get("audited_count") == row["count"]
            and roster_audit[row["id"]]["audit_date"] == row["checked_at"]
        ]
        if checked_lists:
            note += f" 已逐条核对 {'、'.join(checked_lists)}。"
        if people:
            note += f" 已收录 {len(people)} 位学者，" + "、".join(covers) + "。"
        if not parsed:
            note += " 官方目录内容待提取。"
        if school_id in scope_notes:
            note += " " + scope_notes[school_id]
        state = "sample" if people or parsed else "limited"
        review = school_reviews.get(school_id, {})
        reviewed_sources = set(review.get("sources", []))
        available_sources = {row["id"] for row in successful}
        if review.get("complete") and reviewed_sources and reviewed_sources <= available_sources and not pending:
            state = "verified"
        latest_check = max((item["checked_at"] or "" for item in successful), default="") or school.get("checkedAt")
        school_patches.append({"id":school_id, "coverage":state, "coverageNote":note,
                               "rosterLinks":refs,"checkedAt":latest_check})
    changed_seeds = [p for p in seed["people"] if p["id"] in supplements and supplements[p["id"]] != p]
    return {"schemaVersion":1, "ranking":seed["ranking"], "schools":school_patches,
            "people":[supplements[p["id"]] for p in changed_seeds] + additions}


def atomic_write(path, value):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(value, encoding="utf-8")
    pending.replace(path)


def export_checkpoint(db, profile_urls):
    checkpoint = {"schemaVersion":1}
    for table, columns in CHECKPOINT_TABLES.items():
        rows = []
        for item in db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY 1,2"):
            row = dict(item)
            if table == "profiles" and (row["url"] not in profile_urls or row["status"] == "queued"):
                continue
            if row.get("record") is not None:
                row["record"] = json.loads(row["record"])
            rows.append(row)
        checkpoint[table] = rows

    _, findings, approved, notes = metrics_evidence()
    checkpoint["metrics"] = {}
    for key, result in sorted(findings.items()):
        evidence = {field:result[field] for field in ("status", "reason", "author_id", "papers", "checkedAt") if field in result}
        if result.get("author_id") and result["author_id"] == approved.get(key) and result.get("snapshot"):
            evidence["snapshot"] = result["snapshot"]
        elif key in notes or result.get("status") == "identity_review":
            candidate_url = result.get("candidate_url") or result.get("snapshot",{}).get("url")
            if candidate_url:
                evidence["candidate_url"] = candidate_url
        checkpoint["metrics"][key] = evidence
    atomic_write(CHECKPOINT,json.dumps(checkpoint,ensure_ascii=False,indent=2)+"\n")


def export(db, seed):
    candidates = population(db)
    sources = list(db.execute("SELECT * FROM sources ORDER BY school,id"))
    cohort_path = ROOT / "cohort-review.json"
    cohorts = json.loads(cohort_path.read_text(encoding="utf-8")) if cohort_path.is_file() else {}
    scope_notes = cohorts.get("scopeNotes", {})
    patch = make_patch(seed,candidates,sources,scope_notes,cohorts.get("schoolReviews", {}))
    public_by_id = {p["id"]:p for p in seed["people"] + patch["people"]}
    public_people = list(public_by_id.values())
    profile_urls = {
        url for person in candidates if person["role"] in ("faculty", "unverified")
        for url in (person["profile"], person["homepage"]) if url
    }
    # UAB directory entries depend on the personal page for their appointment category.
    profile_urls.update(person["profile"] for person in candidates if person["school"] == "uab" and person["profile"])
    export_checkpoint(db, profile_urls)
    atomic_write(OUTPUT / "collection.js", "window.geometryCollection = " + json_text(patch).replace("</", "<\\/") + ";\n")
    atomic_write(ROOT / "catalog-batch.json", json.dumps(patch,ensure_ascii=False,indent=2) + "\n")
    decisions = Counter(p["decision"] for p in candidates)
    with (ROOT / "review-queue.csv.tmp").open("w",encoding="utf-8-sig",newline="") as handle:
        rows = csv.writer(handle)
        rows.writerow(["学校 ID","姓名","职位","目录判定","方向","公开任职","主页","CV","论文数","累计引用","指标来源","指标日期",
                       "研究依据","判定备注","本次名录或职务来源","核对日期"])
        by_affiliation = {
            (a["schoolId"],name_key(p["name"])):p
            for p in public_people for a in p["affiliations"]
        }
        for p in candidates:
            public = by_affiliation.get((p["school"], name_key(p["name"])), {})
            metric = next(iter(public.get("metrics") or []), {})
            decision = p["decision"]
            pending = "待核" if decision in ("candidate","topic_review","role_review","affiliation_review") else ""
            appointment_source = p["affiliation_url"] or p["profile"] or next(
                (evidence["source_url"] for evidence in p["evidence"]), ""
            )
            decision_note = p["decision_note"] or {
                "topic_review": "公开方向资料不足，或目录只披露相邻领域。",
                "role_review": "已有相关方向依据，公开名录仍缺可确认的现任科研职位。",
                "affiliation_review": "不同学校的姓名相同，现任或联合任职关系仍待核。",
                "emeritus": "公开职称显示为荣休或退休。",
                "associated": "公开职称显示为访问、兼职、附属或荣誉任职。",
                "other": "公开职称显示为博士后、教学岗、学生或其他非主名单职位。",
                "other_topic": "已提取的方向说明中未确认三个收录方向。",
            }.get(decision, "")
            rows.writerow([p["school"],p["name"],p["title"],p["decision"]," / ".join(p["fields"]),p["affiliation_url"],
                           public.get("homepage") or p["homepage"] or pending,public.get("cvUrl") or p["cv"] or pending,
                           metric.get("articles", pending),metric.get("citations", pending),metric.get("url", ""),metric.get("checkedAt", ""),
                           " | ".join(f"{x['text']} [{x['url']}]" for x in p["topic_sources"]), decision_note,
                           appointment_source, p["checked_at"] or ""])
    (ROOT / "review-queue.csv.tmp").replace(ROOT / "review-queue.csv")
    page_attempts = {row["url"]:row for row in db.execute("SELECT url, status, checked_at FROM profiles WHERE status != 'queued'")}
    _, findings, _, _ = metrics_evidence()
    with (ROOT / "field-review.csv.tmp").open("w", encoding="utf-8-sig", newline="") as handle:
        rows = csv.writer(handle)
        rows.writerow(["学者 ID", "姓名", "学校 ID", "任职来源", "主页", "CV", "CV 类型", "发表列表",
                       "机构或作者统计", "OpenAlex 文章", "OpenAlex 引用", "OpenAlex 来源", "指标日期",
                       "已查个人页面", "作者复核日期", "代表作链接", "待核原因"])
        for p in public_people:
            appointments = p["affiliations"]
            trusted = [m for m in p.get("metrics", []) if m.get("source") == "OpenAlex"]
            metric = max(trusted, key=lambda m: m["checkedAt"], default={})
            finding = findings.get(p["id"], {})
            urls = dict.fromkeys([*(a["url"] for a in appointments), p.get("homepage"), p.get("publicationsUrl")])
            attempts = [page_attempts[url] for url in urls if url in page_attempts]
            checked_pages = " | ".join(
                f"{row['checked_at'] or ''} {row['status']} {row['url']}" for row in attempts
            )
            notes = []
            access_failed = any(row["status"] == "source_error" for row in attempts)
            page_read = any(row["status"] == "parsed" for row in attempts)
            if page_read and access_failed:
                link_reason = "可读页面未发现该链接，其他已查入口访问失败"
            elif page_read:
                link_reason = "已查的公开页面未发现该链接"
            elif access_failed:
                link_reason = "已查询的公开入口访问失败"
            else:
                link_reason = "尚无可复核的个人页访问记录"
            for key, label in (("homepage", "个人主页"), ("cvUrl", "CV"), ("publicationsUrl", "发表列表")):
                if not p.get(key):
                    reason = p.get("homepageStatus") if key == "homepage" else p.get("cvStatus") if key == "cvUrl" else None
                    if reason == "独立 CV 待核对。":
                        reason = None
                    notes.append(f"{label}待核，{reason.rstrip('。') if reason else link_reason}")
            counts = p.get("publicationCounts") or []
            if not counts:
                notes.append("未登记作者或机构明确披露的计数及口径")
            if metric.get("articles") is None or metric.get("citations") is None:
                notes.append(finding.get("reason") or p.get("identityNote") or "OpenAlex 作者匹配或指标待复核")
            if not p.get("papers"):
                notes.append("代表作待逐篇核验")
            rows.writerow([p["id"], p["name"], " / ".join(a["schoolId"] for a in appointments),
                           " / ".join(a["url"] for a in appointments), p.get("homepage") or "待核",
                           p.get("cvUrl") or "待核", p.get("cvType") or "", p.get("publicationsUrl") or "待核",
                           " / ".join(f"{c['value']}{'+' if c.get('lowerBound') else ''} · {c['scope']} · {c['checkedAt']} · {c['url']}" for c in counts) or "待核",
                           metric.get("articles", "待核"), metric.get("citations", "待核"),
                           metric.get("url") or finding.get("candidate_url", ""),
                           metric.get("checkedAt", ""), checked_pages, finding.get("checkedAt", ""),
                           " / ".join(paper["url"] for paper in p.get("papers", [])), "；".join(notes)])
    (ROOT / "field-review.csv.tmp").replace(ROOT / "field-review.csv")
    scope_size = len(seed["schools"])
    checked = len({row["school"] for row in sources if row["status"] == "parsed"})
    profile_count = sum(row["url"] in profile_urls for row in db.execute("SELECT url FROM profiles WHERE status='parsed'"))
    metrics = sum(any(m.get("source") == "OpenAlex" for m in p.get("metrics", [])) for p in public_people)
    cv_count = sum(bool(p.get("cvUrl")) for p in public_people)
    homepage_count = sum(bool(p.get("homepage")) for p in public_people)
    publications = sum(bool(p.get("publicationsUrl")) for p in public_people)
    official_counts = sum(bool(p.get("publicationCounts")) for p in public_people)
    representative_papers = sum(bool(p.get("papers")) for p in public_people)
    qs_count = sum("qs" in school["ranks"] for school in seed["schools"])
    gras_count = sum("gras" in school["ranks"] for school in seed["schools"])
    represented = len({a["schoolId"] for p in public_people for a in p["affiliations"]})
    completed_schools = sum(s["coverage"] == "verified" for s in patch["schools"])
    school_states = {s["id"]: s["coverage"] for s in patch["schools"]}
    with (ROOT / "school-review.csv.tmp").open("w", encoding="utf-8-sig", newline="") as handle:
        rows = csv.writer(handle)
        rows.writerow(["学校 ID", "学校", "QS 2026", "软科 2026", "校级名册状态", "已入库", "任职或方向待核",
                       "已登记名册及访问结果", "名册范围及未解事项"])
        for s in seed["schools"]:
            school_id = s["id"]
            registered = [row for row in sources if row["school"] == school_id]
            source_checks = " | ".join(
                f"{row['checked_at'] or '无读取记录'} · {row['label']} · {row['status']} · {row['count']} 条 · {row['url']}"
                + (f" · {row['note']}" if row["note"] else "") for row in registered
            )
            pending_count = sum(
                p["school"] == school_id and p["decision"] in ("topic_review", "role_review", "affiliation_review")
                for p in candidates
            )
            recorded = sum(any(a["schoolId"] == school_id for a in p["affiliations"]) for p in public_people)
            state = school_states.get(school_id, "limited")
            note = scope_notes.get(school_id, "")
            if state != "verified":
                if not any(row["status"] == "parsed" for row in registered):
                    note += " 登记名录仍缺可提取的人员记录。"
                if pending_count:
                    note += f" {pending_count} 条任职或方向需逐人对账。"
                note += " 校内分组和联合研究单位的覆盖范围尚未证明完整。"
            rows.writerow([school_id, s["nameZh"], s["ranks"].get("qs", ""), s["ranks"].get("gras", ""),
                           state, recorded, pending_count, source_checks, note.strip()])
    (ROOT / "school-review.csv.tmp").replace(ROOT / "school-review.csv")
    lines = [
        "# 几何学者库进度",
        "",
        f"更新日期 {now_date()}。QS 2026 数学 {qs_count} 所，软科 GRAS 2026 数学 {gras_count} 所，两榜合并去重 {scope_size} 所。已登记来源 {len({row['school'] for row in sources})} 所，至少有一个已解析来源 {checked} 所。",
        f"目录去重后共 {len(candidates)} 条学者与学校记录，来源外的任职或研究交叉需要继续复核。",
        f"网页收录 {len(public_people)} 位，覆盖 {represented} 所。有个人主页 {homepage_count} 位、公开 CV {cv_count} 位、发表列表 {publications} 位、代表作 {representative_papers} 位、机构或作者计数 {official_counts} 位、OpenAlex 指标 {metrics} 位。",
        f"已解析 {profile_count} 个个人页面。校级全名单对账完成 {completed_schools} 所。",
        "",
    ]
    profile_run = cohorts.get("latestProfileRun")
    if profile_run:
        lines.extend([
            "## 最近一轮个人页补查",
            "",
            f"{profile_run['checkedAt']} 对 {profile_run['schools']} 所学校登记的个人页入口执行 {profile_run['attempted']} 次公开访问，"
            f"其中 {profile_run['fetched']} 次返回内容、{profile_run['failed']} 次请求失败。"
            "后续以个人页内容和官方任职为准核对方向与个人字段。",
            "",
        ])
    if cohorts:
        parsed_schools = {row["school"] for row in sources if row["status"] == "parsed"}
        review_groups = cohorts["cohorts"]
        lines.extend(["## 原待查批次", ""])
        for key, description in (("needs_adapter", "原已找到官网、待提取名册"), ("source_error", "原官网暂无法读取")):
            ids = set(review_groups[key])
            pending_schools = [s["nameZh"] for s in seed["schools"] if s["id"] in ids - parsed_schools]
            lines.append(f"- {description}的 {len(ids)} 所中，已有可提取名册 {len(ids & parsed_schools)} 所。")
            if pending_schools:
                lines.append(f"  名册待核 {len(pending_schools)} 所，包括{'、'.join(pending_schools)}。")
        lines.extend(["", "出现在可提取名册中的学校仍需核实院系范围和未公开的人员字段。", ""])
        followup = set(review_groups.get("missing_at_16e3dbb", []))
        if followup:
            remaining = [s["nameZh"] for s in seed["schools"] if s["id"] in followup - parsed_schools]
            lines.extend(["## 本轮优先复核学校", "",
                          f"- 续跑时缺名册的 {len(followup)} 所中，已有可提取名册 {len(followup & parsed_schools)} 所。"])
            if remaining:
                lines.append(f"- 仍缺名册 {len(remaining)} 所，包括{'、'.join(remaining)}。")
            lines.append("")
    lines.extend([
        "| 学校 | QS 2026 | 软科 2026 | 状态 | 官方来源 | 网页学者 | 主页 / CV / 指标 | 待核任职或方向 |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ])
    for school in seed["schools"]:
        sl = [row for row in sources if row["school"] == school["id"]]
        pl = [p for p in candidates if p["school"] == school["id"]]
        listed = [person for person in public_people if any(a["schoolId"] == school["id"] for a in person["affiliations"])]
        label = "校级已对账" if school_states.get(school["id"]) == "verified" else (
            "工作名单" if listed or any(row["status"] == "parsed" for row in sl) else "来源待复核" if sl else "待发现来源"
        )
        links = " · ".join(f"[{r['label']}]({r['url']})" for r in sl)
        coverage = " / ".join(str(sum(bool(p.get(field)) for p in listed)) for field in ("homepage","cvUrl","metrics"))
        pending = sum(p["decision"] in ("topic_review","role_review","affiliation_review") for p in pl)
        ranks = school["ranks"]
        lines.append(f"| {school['nameZh']} | {ranks.get('qs', '—')} | {ranks.get('gras', '—')} | {label} | {links} | {len(listed)} | {coverage} | {pending} |")
    if scope_notes:
        lines.extend(["", "## 名册覆盖与待核原因", ""])
        for school in seed["schools"]:
            if note := scope_notes.get(school["id"]):
                lines.append(f"- {school['nameZh']}。{note}")
    lines += ["", "## 来源待处理", ""]
    for row in sources:
        if row["status"] not in ("parsed", "reference"):
            school = next(s for s in seed["schools"] if s["id"] == row["school"])
            lines.append(f"- {school['nameZh']} · {row['label']}。{row['note']} [{row['label']}]({row['url']})")
    lines += ["", "见 [逐校名录复核表](school-review.csv)、[人物与任职队列](review-queue.csv) 和 [已收录学者字段待核表](field-review.csv)。"]
    atomic_write(ROOT / "PROGRESS.md","\n".join(lines)+"\n")
    print(json_text({"schools":scope_size,"parsedSchools":checked,"rosterRows":len(candidates),"decisions":dict(decisions),
                     "profilePages":profile_count,"newProfiles":len(public_people)-len(seed["people"]),"totalProfiles":len(public_people),
                     "homepageLinks":homepage_count,"cvLinks":cv_count,"publicationLinks":publications,
                     "officialCounts":official_counts,"representativePapers":representative_papers,
                     "metrics":metrics,"completedSchools":completed_schools}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles",action="store_true",help="读取现有官方目录指向的个人页面")
    parser.add_argument("--school",action="append",default=[],help="限制 --profiles 的学校 ID，可重复")
    parser.add_argument("--max-profiles",type=int,default=0,help="限制本轮读取页数。0 表示处理当前待查队列")
    parser.add_argument("--refresh-profiles",action="store_true",help="重读已缓存的个人页面")
    args = parser.parse_args()
    seed = seed_catalog()
    with connect() as db:
        ingest_rosters(db,seed)
        if args.profiles:
            fetch_profiles(db,set(args.school),args.refresh_profiles,args.max_profiles)
        else:
            add_profile_data(db)
        export(db,seed)


if __name__ == "__main__":
    main()
