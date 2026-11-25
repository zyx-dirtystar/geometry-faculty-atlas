"""Resolve OpenAlex metrics from work DOI and institutional evidence."""

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import argparse
import json
import os
import re
import time

from collect import ROOT, atomic_write, name_key, now_date

FINDINGS = ROOT / "metric-findings.json"
API = "https://api.openalex.org"
KEY_ENV = "GEOMETRY_OPENALEX_KEY"


def api(path, **params):
    if os.environ.get(KEY_ENV):
        params["api_key"] = os.environ[KEY_ENV]
    url = f"{API}{path}?{urlencode(params)}"
    request = Request(url,headers={"User-Agent":"GeometryFacultyIndex/1.0 (academic metadata verification)","Accept":"application/json"})
    with urlopen(request,timeout=18) as response:
        return json.load(response)


def inspect(anchor):
    accepted_names = {name_key(name) for name in anchor["names"]}
    identifier = ""
    institutions = set()
    papers = []
    dois = list(dict.fromkeys(anchor.get("doi", [])))
    for doi in dois:
        work_fields = "display_name,doi,authorships,publication_year"
        try:
            work = api("/works/https://doi.org/" + quote(doi,safe="/."),select=work_fields)
        except HTTPError as error:
            if error.code not in (404, 502, 504):
                raise
            doi_url = "https://doi.org/" + doi.lower()
            fallback = api("/works",filter=f"doi:{doi_url}",select=work_fields,per_page=2)
            doi_matches = [row for row in fallback.get("results", []) if (row.get("doi") or "").lower() == doi_url]
            if len(doi_matches) != 1:
                raise
            work = doi_matches[0]
        matches = [entry for entry in work.get("authorships",[]) if name_key((entry.get("author") or {}).get("display_name") or "") in accepted_names]
        if len(matches) != 1:
            return {"status":"identity_review","reason":"论文作者姓名没有唯一匹配。"}
        author = matches[0]
        new_id = (author["author"].get("id") or "").rsplit("/",1)[-1]
        if not re.fullmatch(r"A\d+",new_id) or (identifier and identifier != new_id):
            return {"status":"identity_review","reason":"同一人的论文指向不同作者档案。"}
        identifier = new_id
        institutions.update(i["display_name"] for i in author.get("institutions",[]) if i.get("display_name"))
        title = work.get("display_name") or ""
        if title.strip():
            papers.append({"title":title,"year":work.get("publication_year"),"url":"https://doi.org/" + doi})
    orcid = anchor.get("orcid","")
    if orcid and not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]",orcid):
        return {"status":"identity_review","reason":"公开 ORCID 格式待核对。"}
    if not identifier and not orcid:
        return {"status":"identity_review","reason":"缺少可确认的论文 DOI 或公开 ORCID。"}
    profile = api("/authors/" + (identifier or "https://orcid.org/" + orcid),
                  select="id,display_name,orcid,works_count,cited_by_count,summary_stats,last_known_institutions,affiliations")
    if orcid and (profile.get("orcid") != "https://orcid.org/" + orcid
                  or name_key(profile.get("display_name") or "") not in accepted_names):
        return {"status":"identity_review","reason":"OpenAlex 作者姓名或 ORCID 与院校公开档案不一致。"}
    identifier = (profile.get("id") or "").rsplit("/",1)[-1]
    if not re.fullmatch(r"A\d+",identifier):
        return {"status":"identity_review","reason":"OpenAlex 未提供有效的作者 ID。"}
    institutions.update(i["display_name"] for i in profile.get("last_known_institutions") or [] if i.get("display_name"))
    institutions.update(a["institution"]["display_name"] for a in profile.get("affiliations") or [] if a.get("institution"))
    aliases = {name_key(i) for i in anchor["institutions"]}
    institution_matches = sorted(i for i in institutions if name_key(i) in aliases)
    if not institution_matches and len(dois) < 2:
        return {"status":"identity_review","author_id":identifier,"reason":"当前与历史机构缺少可核对的匹配。"}
    articles = api("/works",filter=f"authorships.author.id:{identifier},type:article",per_page=1,select="id")
    top = api("/works",filter=f"authorships.author.id:{identifier}",per_page=5,
              select="display_name,doi,primary_topic",sort="cited_by_count:desc")
    work_samples = [{"title":w.get("display_name"),"doi":w.get("doi"),
                     "field":(w.get("primary_topic") or {}).get("field",{}).get("display_name")} for w in top["results"]]
    return {
        "status":"review_ready", "author_id":identifier, "match_name":profile.get("display_name"),"institutions":institution_matches,
        "papers":papers, "sample":work_samples, "source":anchor["source"],
        "cv":anchor.get("cv") or None, "homepage":anchor.get("homepage") or None,
        "snapshot":{
            "source":"OpenAlex","authorId":identifier,"orcid":profile.get("orcid"),
            "url":f"https://openalex.org/authors/{identifier}",
            "authorApiUrl":f"{API}/authors/{identifier}",
            "articleApiUrl":f"{API}/works?filter=authorships.author.id:{identifier},type:article&per_page=1&select=id",
            "checkedAt":now_date(),"articles":articles["meta"]["count"],"works":profile["works_count"],
            "citations":profile["cited_by_count"],"hIndex":profile["summary_stats"]["h_index"],
            "articleScope":"OpenAlex type:article","citationScope":"OpenAlex 作者档案累计引用",
        },
    }


def scan(refresh=False):
    anchors = json.loads((ROOT / "metric-anchors.json").read_text(encoding="utf-8"))
    results = json.loads(FINDINGS.read_text(encoding="utf-8")) if FINDINGS.exists() else {}
    for anchor in anchors:
        identity = anchor["id"]
        if not refresh and results.get(identity,{}).get("status") == "review_ready":
            continue
        try:
            finding = inspect(anchor)
        except HTTPError as error:
            finding = {"status":"source_error","reason":f"OpenAlex 请求返回 HTTP {error.code}"}
        except (URLError,OSError,ValueError,KeyError):
            finding = {"status":"source_error","reason":"OpenAlex 连接或返回格式待核对。"}
        results[identity] = finding
        atomic_write(FINDINGS,json.dumps(results,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({"id":identity,"status":finding["status"],"authorId":finding.get("author_id"),"reason":finding.get("reason")},ensure_ascii=False),flush=True)
        time.sleep(0.35)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refresh",action="store_true",help="更新已有快照")
    options = p.parse_args()
    scan(options.refresh)
