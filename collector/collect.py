"""Maintain the local roster queue and build the website's research directory."""

from collections import Counter
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
import time
import unicodedata
from urllib.parse import urlparse

from lxml import etree, html

from roster_parsers import ADJACENT, PARSERS, Entry, matched_fields, profile_fields, split_role
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
        return meta, html.fromstring(content, parser=html.HTMLParser(encoding="utf-8"))
    except etree.ParserError:
        return meta, None


def seen_date(meta):
    timestamp = meta.get("retrieved_at") if meta else None
    return datetime.fromisoformat(timestamp).astimezone(SHANGHAI).date().isoformat() if timestamp else None


def ingest_rosters(db, seed):
    with db:
        db.executemany("INSERT OR REPLACE INTO schools VALUES (?,?)", [(s["id"], json_text(s)) for s in seed["schools"]])
    transcript_path = ROOT / "official-roster-transcripts.json"
    transcripts = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.is_file() else {}
    for source in load_sources():
        meta, document = read_snapshot(source["id"])
        transcript = transcripts.get(source["id"])
        if not transcript and meta is None and db.execute("SELECT 1 FROM sources WHERE id=? AND url=?", (source["id"], source["url"])).fetchone():
            continue
        rows = []
        if document is not None:
            rows = PARSERS[source["parser"]](document, meta["final_url"])
        if meta is None:
            status, note = "pending", "尚未取得网页。"
        elif document is None:
            error = (meta.get("error") or "").casefold()
            status = "source_error"
            if re.search(r"\b(?:401|403|forbidden)\b", error):
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
        group["title"] = review.get("title") or (active["title"] if active else "")
        group["unit"] = review.get("unit") or (active.get("unit") if active else None)
        group["role"] = split_role(group["title"])
        group["affiliation_url"] = review.get("affiliation") or (active["profile"] or active["source_url"] if active else "")
        group["profile"] = review.get("affiliation") or next((row["profile"] for row in evidence if row["profile"]), "")
        group["homepage"] = review.get("homepage") or next((row["homepage"] for row in evidence if row["homepage"]), "")
        sources = [
            {"text":row["research"], "url":row["source_url"]} for row in evidence
            if row["research"] and not review.get("replace_research")
        ]
        if review.get("research"):
            sources.append({"text":review["research"],"url":review["research_source"]})
        cv = review.get("cv") or ""
        publications = review.get("publications") or ""
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
        group["cv"] = cv
        group["publications"] = publications
        group["topic_sources"] = sources
        text = " / ".join(item["text"] for item in sources)
        fields = matched_fields(text)
        group["fields"] = fields
        if group["role"] in ("emeritus","associated","other"):
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
        dates = [row.get("checked_at") or "" for row in evidence]
        group["checked_at"] = max(dates + [review.get("checkedAt","")]) or None
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
    current = {row["url"]:row["status"] for row in db.execute("SELECT url,status FROM profiles")}
    for source in load_sources():
        if source["parser"] != "pending":
            PROFILE_HOSTS.setdefault(source["school"], set()).add(urlparse(source["url"]).hostname)
    people = sorted(population(db), key=lambda row: (row["decision"] != "candidate", row["school"], row["name"]))
    for person in people:
        school = person["school"]
        if (schools and school not in schools) or person["role"] in ("emeritus","associated","other"):
            continue
        topical = " ".join(item["text"] for item in person["topic_sources"])
        if person["role"] == "unverified" and not topical:
            continue
        if school == "stanford" and not re.search(r"geometry|analysis|algebra",topical,re.I):
            continue
        if school in ("stony-brook","bonn","pku","rutgers") and person["decision"] != "candidate":
            continue
        if person["decision"] == "other_topic" and person["title"] != "Academic Faculty":
            continue
        for target in (person["profile"], person["homepage"]):
            if not target or not allowed_profile(school, target) or (not refresh and current.get(target) == "parsed"):
                continue
            cache_id = "profile-" + sha256(target.encode()).hexdigest()[:16]
            queue[target] = {"id":cache_id, "school":school, "name":person["name"], "url":target, "kind":"profile",
                             "transport":"system" if school == "bonn" else None}
    jobs = list(queue.values())
    if max_profiles:
        jobs = jobs[:max_profiles]
    print(json_text({"profile_queue":len(queue),"this_run":len(jobs)}),flush=True)
    CACHE.mkdir(exist_ok=True)
    with db:
        db.executemany("INSERT OR IGNORE INTO profiles(url,cache_id,status) VALUES (?,?,'queued')", [(job["url"],job["id"]) for job in jobs])

    def fetch(job):
        time.sleep(0.35)
        return job, save_source(job, refresh)

    with ThreadPoolExecutor(max_workers=2) as workers:
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


def make_patch(seed, data, source_rows):
    original = {(a["schoolId"], name_key(p["name"])):p for p in seed["people"] for a in p["affiliations"]}
    original_names = {name for _, name in original}
    cross_school = Counter(name_key(p["name"]) for p in data if p["decision"] == "candidate")
    used_ids = {p["id"] for p in seed["people"]}
    anchors, findings, reviewed, review_notes = metrics_evidence()
    additions = []
    for person in data:
        if person["decision"] != "candidate":
            continue
        school = person["school"]
        key = name_key(person["name"])
        seeded = original.get((school,key))
        if seeded is not None:
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
            "id":slug, "name":person["name"], "affiliations":[{
                "schoolId":school, "department":person["unit"] or UNITS.get(school,"数学系"),"title":person["title"],
                "url":person["affiliation_url"],"type":"primary","checkedAt":person["checked_at"],
            }],
            "fields":person["fields"],"tags":keep_tags(person["topic_sources"]),
            "homepage":anchor.get("homepage") or person["homepage"] or None, "cvUrl":cv or None,
            "cvStatus":"独立 CV 待核对。" if not cv else None,
            "publicationsUrl":publications or None,
            "identityNote":reason, "metrics":[finding["snapshot"]] if known else [],
            "identityUrl":(finding.get("candidate_url") or finding.get("snapshot",{}).get("url")) if slug in review_notes else None,
            "papers":finding.get("papers",[]), "directoryEvidence":sources,
            "checkedAt":person["checked_at"], "recordStatus":"directory",
        })
    school_patches = []
    listed = {}
    roster_audit = {row["id"]:row for row in load_sources() if "audited_count" in row}
    for person in seed["people"] + additions:
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
        state = "sample" if people or parsed else "limited"
        latest_check = max((item["checked_at"] or "" for item in successful), default="") or school.get("checkedAt")
        school_patches.append({"id":school_id, "coverage":state, "coverageNote":note,
                               "rosterLinks":refs,"checkedAt":latest_check})
    return {"schemaVersion":1, "ranking":seed["ranking"], "schools":school_patches, "people":additions}


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
        evidence = {field:result[field] for field in ("status", "reason", "author_id", "papers") if field in result}
        if result.get("author_id") and result["author_id"] == approved.get(key) and result.get("snapshot"):
            evidence["snapshot"] = result["snapshot"]
        elif key in notes:
            candidate_url = result.get("candidate_url") or result.get("snapshot",{}).get("url")
            if candidate_url:
                evidence["candidate_url"] = candidate_url
        checkpoint["metrics"][key] = evidence
    atomic_write(CHECKPOINT,json.dumps(checkpoint,ensure_ascii=False,indent=2)+"\n")


def export(db, seed):
    candidates = population(db)
    sources = list(db.execute("SELECT * FROM sources ORDER BY school,id"))
    patch = make_patch(seed,candidates,sources)
    profile_urls = {
        url for person in candidates if person["role"] in ("faculty", "unverified")
        for url in (person["profile"], person["homepage"]) if url
    }
    export_checkpoint(db, profile_urls)
    atomic_write(OUTPUT / "collection.js", "window.geometryCollection = " + json_text(patch).replace("</", "<\\/") + ";\n")
    atomic_write(ROOT / "catalog-batch.json", json.dumps(patch,ensure_ascii=False,indent=2) + "\n")
    decisions = Counter(p["decision"] for p in candidates)
    with (ROOT / "review-queue.csv.tmp").open("w",encoding="utf-8-sig",newline="") as handle:
        rows = csv.writer(handle)
        rows.writerow(["学校 ID","姓名","职位","目录判定","方向","公开任职","主页","CV","论文数","累计引用","指标来源","指标日期","研究依据"])
        by_affiliation = {
            (a["schoolId"],name_key(p["name"])):p
            for p in seed["people"] + patch["people"] for a in p["affiliations"]
        }
        for p in candidates:
            public = by_affiliation.get((p["school"], name_key(p["name"])), {})
            metric = next(iter(public.get("metrics") or []), {})
            pending = "待核" if p["decision"] in ("candidate","topic_review","role_review","affiliation_review") else ""
            rows.writerow([p["school"],p["name"],p["title"],p["decision"]," / ".join(p["fields"]),p["affiliation_url"],
                           public.get("homepage") or p["homepage"] or pending,public.get("cvUrl") or p["cv"] or pending,
                           metric.get("articles", pending),metric.get("citations", pending),metric.get("url", ""),metric.get("checkedAt", ""),
                           " | ".join(f"{x['text']} [{x['url']}]" for x in p["topic_sources"])])
    (ROOT / "review-queue.csv.tmp").replace(ROOT / "review-queue.csv")
    scope_size = db.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    checked = len({row["school"] for row in sources if row["status"] == "parsed"})
    profile_count = sum(row["url"] in profile_urls for row in db.execute("SELECT url FROM profiles WHERE status='parsed'"))
    metrics = sum(bool(p.get("metrics")) for p in seed["people"] + patch["people"])
    cv_count = sum(bool(p.get("cvUrl")) for p in seed["people"] + patch["people"])
    homepage_count = sum(bool(p.get("homepage")) for p in seed["people"] + patch["people"])
    lines = [
        "# 几何学者库进度",
        "",
        f"更新日期 {now_date()}。学校任务池 {scope_size} 所，已登记来源 {len({row['school'] for row in sources})} 所，已解析来源 {checked} 所。",
        f"目录去重后共 {len(candidates)} 条学者与学校记录，来源外的任职或研究交叉需要继续复核。",
        f"网页收录 {len(seed['people']) + len(patch['people'])} 位，其中 {len(patch['people'])} 位来自逐校采集。",
        f"有个人主页 {homepage_count} 位、公开 CV {cv_count} 位、OpenAlex 论文及引用指标 {metrics} 位。缺失字段标为待核。",
        f"已解析 {profile_count} 个个人页面。校级全名单对账完成 0 所。",
        "",
        "| 学校 | 状态 | 官方来源 | 网页学者 | 主页 / CV / 指标 | 待核任职或方向 |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for school in seed["schools"]:
        sl = [row for row in sources if row["school"] == school["id"]]
        pl = [p for p in candidates if p["school"] == school["id"]]
        listed = [person for person in seed["people"] + patch["people"] if any(a["schoolId"] == school["id"] for a in person["affiliations"])]
        label = "待发现来源" if not sl else "工作名单" if listed or any(row["status"] == "parsed" for row in sl) else "来源待复核"
        links = " · ".join(f"[{r['label']}]({r['url']})" for r in sl)
        coverage = " / ".join(str(sum(bool(p.get(field)) for p in listed)) for field in ("homepage","cvUrl","metrics"))
        pending = sum(p["decision"] in ("topic_review","role_review","affiliation_review") for p in pl)
        lines.append(f"| {school['nameZh']} | {label} | {links} | {len(listed)} | {coverage} | {pending} |")
    lines += ["", "## 来源待处理", ""]
    for row in sources:
        if row["status"] != "parsed":
            school = next(s for s in seed["schools"] if s["id"] == row["school"])
            lines.append(f"- {school['nameZh']} · {row['label']}。{row['note']} [{row['label']}]({row['url']})")
    lines += ["", "完整逐条复核记录见同目录 review-queue.csv。"]
    atomic_write(ROOT / "PROGRESS.md","\n".join(lines)+"\n")
    print(json_text({"schools":scope_size,"parsedSchools":checked,"rosterRows":len(candidates),"decisions":dict(decisions),
                     "profilePages":profile_count,"newProfiles":len(patch["people"]),"totalProfiles":len(seed["people"])+len(patch["people"]),
                     "cvLinks":cv_count,"metrics":metrics}),flush=True)


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
