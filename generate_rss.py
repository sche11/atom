#!/usr/bin/env python3
"""
RSS 生成器：监控 AI API 公益站导航页面的更新
源地址: https://bubblevv.github.io/ai-api-gongyi-nav/

解析逻辑:
- div.stat 中 <span>更新日期</span> 对应的 <b> 标签获取全局更新日期
- 每个站点条目: h2=站名, p.domain=域名, p.note=描述, p.added-date=添加日期
- 优先使用 added-date 作为条目时间，其次使用描述中的【MMDD新增/更新】标签
- 按日期排序后生成 RSS feed
"""

import re
import sys
import hashlib
from datetime import datetime, timedelta
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString
from html.parser import HTMLParser

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error

    class _Requests:
        @staticmethod
        def get(url, timeout=30):
            try:
                resp = urllib.request.urlopen(url, timeout=timeout)
                class R:
                    text = resp.read().decode("utf-8", errors="replace")
                    status_code = resp.getcode()
                return R()
            except urllib.error.HTTPError as e:
                class R:
                    text = e.read().decode("utf-8", errors="replace")
                    status_code = e.code
                return R()

    requests = _Requests()


# ─── 配置 ───────────────────────────────────────────────
SOURCE_URL = "https://bubblevv.github.io/ai-api-gongyi-nav/"
RSS_TITLE = "AI API 公益站导航 - 更新监控"
RSS_LINK = SOURCE_URL
RSS_DESC = "监控 AI API 公益站导航页面的最新更新，包括新增站点和站点信息变更"
RSS_FILE = "rss.xml"
MAX_ITEMS = 30
DEFAULT_DAYS_AGO = 60


# ─── HTML 解析器 ─────────────────────────────────────────
class NavPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.update_date = None
        self.entries = []

        self._in_stat = False
        self._in_stat_b = False
        self._in_stat_span = False
        self._stat_span_text = ""
        self._stat_b_text = ""

        self._in_h2 = False
        self._in_domain = False
        self._in_note = False
        self._in_added_date = False
        self._skip_data = False          # 跳过 <span> 内的文本

        self._current_name = ""
        self._current_domain = ""
        self._current_note = ""
        self._current_added_date = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "div" and attrs_dict.get("class") == "stat":
            self._in_stat = True
            self._stat_span_text = ""
            self._stat_b_text = ""
        elif self._in_stat and tag == "b":
            self._in_stat_b = True
        elif self._in_stat and tag == "span":
            self._in_stat_span = True
        elif tag == "h2":
            self._in_h2 = True
            self._current_name = ""
        elif tag == "p" and attrs_dict.get("class") == "domain":
            self._in_domain = True
            self._current_domain = ""
        elif tag == "p" and attrs_dict.get("class") == "note":
            self._in_note = True
            self._current_note = ""
        elif tag == "p" and attrs_dict.get("class") == "added-date":
            self._in_added_date = True
            self._current_added_date = ""

        # 进入 added-date 内部的 span 时，标记跳过文本
        if self._in_added_date and tag == "span":
            self._skip_data = True

    def handle_endtag(self, tag):
        if tag == "b" and self._in_stat_b:
            self._in_stat_b = False
        elif tag == "span" and self._in_stat_span:
            self._in_stat_span = False
        elif tag == "div" and self._in_stat:
            self._in_stat = False
            if "更新日期" in self._stat_span_text:
                self.update_date = self._stat_b_text.strip()
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
        elif tag == "p" and self._in_domain:
            self._in_domain = False
        elif tag == "p" and self._in_note:
            self._in_note = False
        elif tag == "p" and self._in_added_date:
            self._in_added_date = False
            # added-date 结束，认为一条完整条目已解析完毕
            if self._current_name:
                self.entries.append({
                    "name": self._current_name.strip(),
                    "domain": self._current_domain.strip(),
                    "note": self._current_note.strip(),
                    "added_date": self._current_added_date.strip(),
                })
                # 重置
                self._current_name = ""
                self._current_domain = ""
                self._current_note = ""
                self._current_added_date = ""

        # 结束 span 时取消跳过标记
        if tag == "span" and self._skip_data:
            self._skip_data = False

    def handle_data(self, data):
        if self._skip_data:
            return
        if self._in_stat_b:
            self._stat_b_text += data
        elif self._in_stat_span:
            self._stat_span_text += data
        elif self._in_h2:
            self._current_name += data
        elif self._in_domain:
            self._current_domain += data
        elif self._in_note:
            self._current_note += data
        elif self._in_added_date:
            self._current_added_date += data


# ─── 日期提取 ───────────────────────────────────────────
def extract_date_from_note(note: str, year_hint: int = None) -> datetime:
    m = re.search(r"【(\d{4})(?:新增|更新|修改)?】", note)
    if m:
        mmdd = m.group(1)
        mm, dd = int(mmdd[:2]), int(mmdd[2:])
        year = year_hint or datetime.now().year
        try:
            dt = datetime(year, mm, dd)
            if dt > datetime.now() + timedelta(days=1):
                dt = datetime(year - 1, mm, dd)
            return dt
        except ValueError:
            pass
    return None


def assign_dates(entries, update_date_str):
    """优先使用 added_date，其次 note 内标签，最后回退"""
    year_hint = None
    if update_date_str:
        try:
            year_hint = int(update_date_str[:4])
        except ValueError:
            pass
    if year_hint is None:
        year_hint = datetime.now().year

    for entry in entries:
        # 1) added_date 优先
        added = entry.get("added_date", "").strip()
        if added:
            try:
                dt = datetime.strptime(added, "%Y-%m-%d")
                entry["date"] = dt
                continue
            except ValueError:
                pass
        # 2) note 日期标签
        dt = extract_date_from_note(entry.get("note", ""), year_hint)
        if dt:
            entry["date"] = dt
            continue
        # 3) 回退
        entry["date"] = datetime.now() - timedelta(days=DEFAULT_DAYS_AGO)
    return entries


# ─── RSS 生成 ───────────────────────────────────────────
def build_item_link(domain):
    """
    根据域名生成可访问的链接：
    - 如果已包含协议头则直接返回
    - 否则补全 https://
    - 如果域名为空则返回导航页链接
    """
    domain = domain.strip()
    if not domain:
        return SOURCE_URL
    if domain.startswith("http"):
        return domain
    return f"https://{domain}"


def generate_rss(entries, update_date_str):
    rss = Element("rss", version="2.0", **{"xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = RSS_TITLE
    SubElement(channel, "link").text = RSS_LINK
    SubElement(channel, "description").text = RSS_DESC
    SubElement(channel, "language").text = "zh-CN"
    SubElement(channel, "generator").text = "ai-api-nav-rss-generator"

    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", RSS_LINK)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    now_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    SubElement(channel, "lastBuildDate").text = now_str
    if update_date_str:
        try:
            ud = datetime.strptime(update_date_str, "%Y-%m-%d")
            SubElement(channel, "pubDate").text = ud.strftime("%a, %d %b %Y 00:00:00 GMT")
        except ValueError:
            SubElement(channel, "pubDate").text = now_str
    else:
        SubElement(channel, "pubDate").text = now_str

    sorted_entries = sorted(entries, key=lambda e: e["date"], reverse=True)[:MAX_ITEMS]

    for entry in sorted_entries:
        item = SubElement(channel, "item")

        date_label = entry["date"].strftime("%m月%d日")
        if "新增" in entry["note"]:
            action = "新增"
        elif "更新" in entry["note"]:
            action = "更新"
        else:
            action = "更新"
        SubElement(item, "title").text = f"[{action}] {entry['name']} - {date_label}"

        # 链接
        link = build_item_link(entry["domain"])
        SubElement(item, "link").text = link

        # 描述
        desc_parts = [
            f"<b>{entry['name']}</b>",
            f"<br/>域名: {entry['domain']}",
            f"<br/>{entry['note']}",
        ]
        SubElement(item, "description").text = "".join(desc_parts)

        # pubDate
        pub = entry["date"].strftime("%a, %d %b %Y 00:00:00 GMT")
        SubElement(item, "pubDate").text = pub

        # guid
        guid_val = hashlib.md5(entry["domain"].encode()).hexdigest()
        guid_el = SubElement(item, "guid")
        guid_el.set("isPermaLink", "false")
        guid_el.text = f"ai-api-nav-{guid_val}"

    raw = tostring(rss, encoding="unicode", xml_declaration=False)
    pretty = parseString(raw).toprettyxml(indent="  ", encoding=None)
    lines = pretty.split("\n")
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(lines)


# ─── 主流程 ─────────────────────────────────────────────
def main():
    print(f"[*] 获取页面: {SOURCE_URL}")
    resp = requests.get(SOURCE_URL, timeout=30)
    if hasattr(resp, "status_code") and resp.status_code != 200:
        print(f"[!] HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)

    html = resp.text
    print(f"[*] 页面大小: {len(html)} bytes")

    parser = NavPageParser()
    parser.feed(html)
    print(f"[*] 全局更新日期: {parser.update_date}")
    print(f"[*] 解析到 {len(parser.entries)} 个站点条目")

    entries = assign_dates(parser.entries, parser.update_date)

    dated = sum(1 for e in entries if e["date"] > datetime.now() - timedelta(days=DEFAULT_DAYS_AGO))
    print(f"[*] 其中有日期标签的: {dated} 条")

    rss_xml = generate_rss(entries, parser.update_date)

    with open(RSS_FILE, "w", encoding="utf-8") as f:
        f.write(rss_xml)
    print(f"[*] RSS 已写入: {RSS_FILE}")

    sorted_entries = sorted(entries, key=lambda e: e["date"], reverse=True)
    print("\n── 最新 5 条 ──")
    for e in sorted_entries[:5]:
        print(f"  {e['date'].strftime('%Y-%m-%d')} | {e['name']:12s} | {e['domain']}")
        print(f"  {'':14s}| 链接: {build_item_link(e['domain'])}")
        print(f"  {'':14s}| {e['note'][:60]}")


if __name__ == "__main__":
    main()