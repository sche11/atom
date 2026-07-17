#!/usr/bin/env python3
"""扫描当前目录下所有 .xml 文件，生成 feeds.json（排除 index.html 等）"""

import json
import os
import sys

OUTPUT_FILE = "feeds.json"
SCAN_DIR = os.getenv("SCAN_DIR", ".")


def load_meta(xml_file):
    meta_file = os.path.splitext(xml_file)[0] + ".meta.json"
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def generate():
    feeds = []
    for fname in sorted(os.listdir(SCAN_DIR)):
        if not fname.endswith(".xml") or fname == "sitemap.xml":
            continue
        path = os.path.join(SCAN_DIR, fname)
        if not os.path.isfile(path):
            continue
        meta = load_meta(path)
        title = meta.get("title", os.path.splitext(fname)[0])
        description = meta.get("description", "")
        feeds.append({"title": title, "url": fname, "description": description})

    with open(os.path.join(SCAN_DIR, OUTPUT_FILE), "w", encoding="utf-8") as f:
        json.dump(feeds, f, ensure_ascii=False, indent=2)
    print(f"✅ 生成 {OUTPUT_FILE}，包含 {len(feeds)} 个源")


if __name__ == "__main__":
    generate()