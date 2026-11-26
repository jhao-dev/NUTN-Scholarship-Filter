"""抓取南大以外的公開資源，輸出 JSON 給網站的「全網搜索」使用。

來源：
  1. 教育部圓夢助學網（民間團體、政府機關獎助學金）
  2. 教育部青年發展署活動專區（報名中／即將開始的活動）

用法：python scraper/external.py [輸出 json 路徑]
任一來源失敗只會記在 errors，不影響其他來源；全部抓不到則結束碼非 0，不覆蓋舊資料。
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "external.json"
TW = timezone(timedelta(hours=8))
MOE = "https://www.edu.tw/helpdreams/"
MOE_LISTS = [
    ("private", MOE + "Grants.aspx?n=2BBF7170197CE7D3&sms=0A01A72AAB9E5CD4"),
    ("gov", MOE + "Grants.aspx?n=11EFF33070D6DF4B&sms=931FF851D2FB2128"),
]
YDA = "https://www.yda.gov.tw/EventList.aspx?uid=101&pid=56"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (compatible; ScholarshipFinder/1.0)"


def soup(url):
    r = session.get(url, timeout=40)
    r.raise_for_status()
    time.sleep(0.3)
    return BeautifulSoup(r.content, "html.parser")


def roc_date(text):
    m = re.search(r"(\d{3})[-/.](\d{1,2})[-/.](\d{1,2})", text or "")
    return f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def clean(el):
    return re.sub(r"\n\s*\n+", "\n", el.get_text("\n")).strip() if el else ""


def moe_detail(url):
    page = soup(url)
    fields = {}
    for box in page.select("div.open-control-wrap"):
        title = box.select_one(".title")
        if title:
            fields[re.sub(r"\s", "", title.get_text())] = clean(box.select_one(".content"))
    return fields


def moe(today, errors):
    items = []
    for kind, list_url in MOE_LISTS:
        try:
            seen, page_no = set(), 1
            while page_no <= 10:
                page = soup(f"{list_url}&page={page_no}&PageSize=100")
                fresh = 0
                for a in page.select("a.css_mark[href*='Grants_Content']"):
                    url = urljoin(MOE, a["href"])
                    if url in seen:
                        continue
                    seen.add(url)
                    fresh += 1
                    cells = [c.get_text(strip=True) for c in a.find_parent("tr").find_all("td")]
                    deadline = roc_date(cells[-1]) if cells else None
                    if deadline and deadline < today:
                        continue
                    try:
                        f = moe_detail(url)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"圓夢助學網 {a.get_text(strip=True)}: {e}")
                        continue
                    items.append({
                        "category": "scholar", "source": kind, "from": "教育部圓夢助學網",
                        "title": a.get_text(strip=True), "org": cells[1] if len(cells) > 1 else "",
                        "url": url, "deadline_iso": deadline,
                        "stage": f.get("學制", ""), "grade": f.get("成績", ""),
                        "identity": f.get("獎助身分", ""), "qualification": f.get("獎助資格", ""),
                        "residency": f.get("戶籍地限制", ""), "discipline": f.get("學門", ""),
                        "method": f.get("申請方式", "")[:1500], "limits": f.get("限制條件", "")[:3000],
                    })
                if not fresh:
                    break
                page_no += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"圓夢助學網清單（{kind}）: {e}")
    return items


def yda(today, errors):
    items, seen = [], set()
    try:
        for page_no in range(1, 5):
            for box in soup(f"{YDA}&page={page_no}").select("div.event-box"):
                a = box.select_one("a.title")
                status = clean(box.select_one(".status"))
                if not a or status not in ("報名中", "即將開始"):
                    continue
                url = urljoin(YDA, a["href"])
                dates = re.findall(r"\d{3}-\d{2}-\d{2}", clean(box.select_one(".date")))
                end = roc_date(dates[-1]) if dates else None
                if url in seen or (end and end < today):
                    continue
                seen.add(url)
                title = a.get_text(strip=True)
                category = "camp" if re.search(r"營", title) else "contest" if re.search(r"競賽|比賽|徵選|徵件|黑客松", title) else "event"
                items.append({
                    "category": category, "source": "gov", "from": "教育部青年發展署",
                    "title": title, "org": "教育部青年發展署", "url": url, "status": status,
                    "start_iso": roc_date(dates[0]) if dates else None, "end_iso": end,
                    "tag": clean(box.select_one(".tag-box")),
                })
    except Exception as e:  # noqa: BLE001
        errors.append(f"青年署活動: {e}")
    return items


def main():
    today = datetime.now(TW).strftime("%Y-%m-%d")
    errors = []
    items = moe(today, errors) + yda(today, errors)
    if not items:
        sys.exit("外部來源都沒有抓到資料：" + "；".join(errors))
    data = {"updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": errors, "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kinds = {}
    for i in items:
        kinds[(i["from"], i["category"])] = kinds.get((i["from"], i["category"]), 0) + 1
    print(f"完成：{len(items)} 筆，失敗 {len(errors)}；{kinds} → {OUT}")


if __name__ == "__main__":
    main()
