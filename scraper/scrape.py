"""每日抓取南大獎助學金公告，輸出 JSON 給網站使用。

判斷邏輯完全沿用 app.py（Streamlit 版）：這支腳本只載入 app.py 中
「st.set_page_config 之前」的純函式（抓取、附件解析、條件分析、排除規則），
不會啟動任何網頁介面。之後若修改 app.py 的規則，這裡會自動跟著用新規則。

用法：python scraper/scrape.py [app.py 路徑] [輸出 json 路徑]
"""
import copy
import re
import json
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

HERE = Path(__file__).resolve().parent
APP_PY = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "app.py"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE.parent / "data" / "scholarships.json"

# app.py 會匯入 streamlit / pandas，但前半段的函式不需要它們實際運作
for name in ("streamlit", "pandas"):
    sys.modules.setdefault(name, MagicMock())

src = APP_PY.read_text(encoding="utf-8")
marker = "st.set_page_config("
if marker not in src:
    sys.exit("找不到 st.set_page_config，app.py 結構已改變，請更新 scrape.py")
ns: dict = {"__name__": "nutn_core"}
exec(compile(src.split(marker)[0], str(APP_PY), "exec"), ns)

parse_listing = ns["parse_listing"]
parse_detail = ns["parse_detail"]
analyze_requirements = ns["analyze_requirements"]
enrich_requirements = ns["enrich_requirements"]
is_thesis_related = ns["is_thesis_related"]
is_award_result_related = ns["is_award_result_related"]
parse_posted_date = ns["parse_posted_date"]
parse_date_loose = ns["parse_date_loose"]

FIELDS = [
    "poverty_status", "academic_requirement", "academic_min", "conduct_requirement", "conduct_min",
    "other_requirements", "needs_manual_check", "residency_requirement", "indigenous_requirement",
    "major_requirement", "difficulty", "amount",
]
DETAIL_MAX, ATT_MAX = 8000, 15000


# 只是通知、說明會、宣布截止（沒有可申請內容）的公告，不放進清單
NOTICE_TITLE = [
    r"結果通知", r"查核結果", r"說明會", r"快訊", r"今日截止", r"已截止", r"截止通知",
    r"就學貸款", r"重要通知$", r"停止(?:受理|申請)", r"取消(?:申請|受理)",
]


def is_notice_only(obj):
    title = obj.title or ""
    return any(re.search(p, title) for p in NOTICE_TITLE)


# app.py 的戶籍偵測只認得「高雄市」這種全名；公告常寫「設籍高雄」，這裡補上簡稱
_SHORT = {
    "新北": ["新北市"], "臺北": ["臺北市"], "台北": ["臺北市"], "桃園": ["桃園市"],
    "臺中": ["臺中市"], "台中": ["臺中市"], "臺南": ["臺南市"], "台南": ["臺南市"],
    "高雄": ["高雄市"], "基隆": ["基隆市"], "新竹": ["新竹市", "新竹縣"], "嘉義": ["嘉義市", "嘉義縣"],
}


def add_short_residency(obj):
    text = (obj.detail or "") + "\n" + (obj.attachment_text or "")
    found = [] if obj.residency_requirement == "未偵測" else obj.residency_requirement.split("、")
    for short, fulls in _SHORT.items():
        if re.search(rf"(?:設籍|戶籍|籍設)[^。\n]{{0,12}}{short}|{short}[^。\n]{{0,6}}(?:設籍|戶籍)", text):
            for f in fulls:
                if f not in found:
                    found.append(f)
    if found:
        obj.residency_requirement = "、".join(found)


def pick(obj):
    return {k: getattr(obj, k) for k in FIELDS}


def main():
    listing = parse_listing()
    if not listing:
        sys.exit("沒有抓到公告連結，網站版型可能已更新")
    items, errors = [], []
    now = datetime.now()
    for idx, item in enumerate(listing):
        label = item.get("title") or item["board_no"]
        try:
            obj = parse_detail(item, include_attachments=True)
            if is_thesis_related(obj) or is_award_result_related(obj) or is_notice_only(obj):
                continue
            posted = parse_posted_date(obj.posted_date)
            if posted and posted < now - timedelta(days=183):
                continue
            enrich_requirements(obj)
            add_short_residency(obj)
            dl = parse_date_loose(obj.deadline)

            # 「不解析附件」版本：同樣的規則、但不看附件文字（對應網站上的開關）
            plain = copy.deepcopy(obj)
            plain.attachment_text, plain.attachment_names, plain.needs_manual_check = "", "", False
            analyze_requirements(plain)
            enrich_requirements(plain)
            add_short_residency(plain)

            items.append({
                "idx": idx,
                "board_no": obj.board_no,
                "title": obj.title,
                "url": obj.url,
                "department": obj.department,
                "posted_date": obj.posted_date,
                "deadline": obj.deadline,
                "deadline_iso": dl.strftime("%Y-%m-%d") if dl else None,
                "detail": obj.detail[:DETAIL_MAX],
                "attachment_text": obj.attachment_text[:ATT_MAX],
                "attachment_names": obj.attachment_names,
                "with_att": pick(obj),
                "no_att": pick(plain),
            })
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
        time.sleep(0.12)

    data = {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(listing),
        "errors": errors,
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：列表 {len(listing)} 則，保留 {len(items)} 則，失敗 {len(errors)} 則 → {OUT}")


if __name__ == "__main__":
    main()
