  #!/usr/bin/env python3
  """
  RSS 生成器：监控 AI API 公益站导航页面的更新
  源地址: https://bubblevv.github.io/ai-api-gongyi-nav/

  解析逻辑:
  - div.stat 中 <span>更新日期</span> 对应的 <b> 标签获取全局更新日期
  - 每个站点条目: h2=站名, p.domain=域名, p.note=描述
  - 描述中的【MMDD新增/更新】标签用于提取条目更新日期
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
      # fallback to urllib
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
  # 每次运行最多输出多少条最新条目
  MAX_ITEMS = 30
  # 如果 note 中没有日期标签，默认回溯到多少天前
  DEFAULT_DAYS_AGO = 60


  # ─── HTML 解析器 ─────────────────────────────────────────
  class NavPageParser(HTMLParser):
      """解析导航页，提取更新日期和站点条目"""

      def __init__(self):
          super().__init__()
          self.update_date = None  # 全局更新日期 (YYYY-MM-DD)
          self.entries = []  # [{name, domain, note, date}]

          # 解析状态
          self._in_stat = False
          self._in_stat_b = False
          self._in_stat_span = False
          self._stat_span_text = ""
          self._stat_b_text = ""

          self._in_h2 = False
          self._in_domain = False
          self._in_note = False

          self._current_name = ""
          self._current_domain = ""
          self._current_note = ""

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
              # 收集一个完整条目
              self.entries.append({
                  "name": self._current_name.strip(),
                  "domain": self._current_domain.strip(),
                  "note": self._current_note.strip(),
              })

      def handle_data(self, data):
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


  # ─── 日期提取 ───────────────────────────────────────────
  def extract_date_from_note(note: str, year_hint: int = None) -> datetime:
      """
      从 note 中提取日期标签，格式如:
        【0531新增】 【0527更新】 【0706新增】 【0527】
      返回对应的 datetime；找不到则返回 None
      """
      m = re.search(r"【(\d{4})(?:新增|更新|修改)?】", note)
      if m:
          mmdd = m.group(1)
          mm, dd = int(mmdd[:2]), int(mmdd[2:])
          year = year_hint or datetime.now().year
          try:
              dt = datetime(year, mm, dd)
              # 如果日期在未来，说明是去年的
              if dt > datetime.now() + timedelta(days=1):
                  dt = datetime(year - 1, mm, dd)
              return dt
          except ValueError:
              pass
      return None


  def assign_dates(entries, update_date_str):
      """为每条 entry 计算排序用的 datetime"""
      # 从全局更新日期推断年份
      year_hint = None
      if update_date_str:
          try:
              year_hint = int(update_date_str[:4])
          except ValueError:
              pass
      if year_hint is None:
          year_hint = datetime.now().year

      for entry in entries:
          dt = extract_date_from_note(entry["note"], year_hint)
          if dt is None:
              # 没有日期标签的条目，回退到默认天数前
              dt = datetime.now() - timedelta(days=DEFAULT_DAYS_AGO)
          entry["date"] = dt

      return entries


  # ─── RSS 生成 ───────────────────────────────────────────
  def generate_rss(entries, update_date_str):
      """生成 RSS 2.0 XML"""
      rss = Element("rss", version="2.0", **{"xmlns:atom": "http://www.w3.org/2005/Atom"})
      channel = SubElement(rss, "channel")

      SubElement(channel, "title").text = RSS_TITLE
      SubElement(channel, "link").text = RSS_LINK
      SubElement(channel, "description").text = RSS_DESC
      SubElement(channel, "language").text = "zh-CN"
      SubElement(channel, "generator").text = "ai-api-nav-rss-generator"

      # atom:link self
      atom_link = SubElement(channel, "atom:link")
      atom_link.set("href", RSS_LINK)
      atom_link.set("rel", "self")
      atom_link.set("type", "application/rss+xml")

      # pubDate / lastBuildDate
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

      # 按日期降序排列
      sorted_entries = sorted(entries, key=lambda e: e["date"], reverse=True)
      sorted_entries = sorted_entries[:MAX_ITEMS]

      for entry in sorted_entries:
          item = SubElement(channel, "item")

          # 标题: 站名 + 日期标签
          date_label = entry["date"].strftime("%m月%d日")
          # 判断是新增还是更新
          if "新增" in entry["note"]:
              action = "新增"
          elif "更新" in entry["note"]:
              action = "更新"
          else:
              action = "更新"
          SubElement(item, "title").text = f"[{action}] {entry['name']} - {date_label}"

          # 链接: 补全 https://
          domain = entry["domain"]
          if not domain.startswith("http"):
              link = f"https://{domain}"
          else:
              link = domain
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

          # guid (基于域名哈希，保证稳定)
          guid_val = hashlib.md5(entry["domain"].encode()).hexdigest()
          guid_el = SubElement(item, "guid")
          guid_el.set("isPermaLink", "false")
          guid_el.text = f"ai-api-nav-{guid_val}"

      # 美化输出
      raw = tostring(rss, encoding="unicode", xml_declaration=False)
      pretty = parseString(raw).toprettyxml(indent="  ", encoding=None)
      # 去掉 minidom 自动加的 xml 声明，手动加一个带 encoding 的
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

      # 解析
      parser = NavPageParser()
      parser.feed(html)
      print(f"[*] 全局更新日期: {parser.update_date}")
      print(f"[*] 解析到 {len(parser.entries)} 个站点条目")

      # 分配日期
      entries = assign_dates(parser.entries, parser.update_date)

      # 统计
      dated = sum(1 for e in entries if e["date"] > datetime.now() - timedelta(days=DEFAULT_DAYS_AGO))
      print(f"[*] 其中有日期标签的: {dated} 条")

      # 生成 RSS
      rss_xml = generate_rss(entries, parser.update_date)

      # 写入文件
      with open(RSS_FILE, "w", encoding="utf-8") as f:
          f.write(rss_xml)
      print(f"[*] RSS 已写入: {RSS_FILE}")

      # 打印最新 5 条预览
      sorted_entries = sorted(entries, key=lambda e: e["date"], reverse=True)
      print("\n── 最新 5 条 ──")
      for e in sorted_entries[:5]:
          print(f"  {e['date'].strftime('%Y-%m-%d')} | {e['name']:12s} | {e['domain']}")
          print(f"  {'':14s}| {e['note'][:60]}")


  if __name__ == "__main__":
      main()
  ```
