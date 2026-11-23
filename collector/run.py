"""One-command resume for the public directory collection and local website."""

import argparse
import subprocess

from collect import PROJECT, add_profile_data, connect, export, fetch_profiles, ingest_rosters, node_path, seed_catalog
from metrics import scan
from snapshot import fetch_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline",action="store_true",help="使用已保存的快照更新本地项目")
    parser.add_argument("--school",action="append",default=[],help="指定学校 ID，可重复")
    parser.add_argument("--profiles",action="store_true",help="查阅目录列出的公开个人页")
    parser.add_argument("--metrics",action="store_true",help="从已核对的 DOI 重新匹配作者与指标候选")
    parser.add_argument("--refresh",action="store_true",help="重新读取所选学校的已缓存来源")
    args = parser.parse_args()
    if args.offline and (args.profiles or args.metrics or args.refresh):
        parser.error("--offline 与需要访问网站的选项不能同时使用")
    if not args.offline:
        fetch_sources(args.school,args.refresh)
    seed = seed_catalog()
    with connect() as db:
        ingest_rosters(db,seed)
        if args.profiles:
            fetch_profiles(db,set(args.school),args.refresh)
        else:
            add_profile_data(db)
        if args.metrics:
            scan(args.refresh)
        export(db,seed)
    subprocess.run([node_path(),"build-offline.mjs"],cwd=PROJECT,check=True)


if __name__ == "__main__":
    main()
