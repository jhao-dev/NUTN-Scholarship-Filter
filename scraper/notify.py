"""找出「這次才出現、而且你可能符合」的公告，印出通知內容（沒有輸出代表不用通知）。

用法：python scraper/notify.py 舊資料夾 新資料夾
條件放在環境變數 NUTN_PROFILE（GitHub 的私密設定），格式：
  {"city":"新竹市","dept":"資訊工程學系","gpa":80,"conduct":85,"low":false,"ind":false,"unsure":true}
通知內容會出現在公開的 issue，所以只列公告名稱與連結，不寫任何個人條件或不符合原因。
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TW = timezone(timedelta(hours=8))


def load_rules():
    """沿用 scrape.py 載入的 app.py 判斷函式。"""
    argv = sys.argv
    sys.argv = ["notify", str(HERE.parent / "app.py")]
    sys.path.insert(0, str(HERE))
    try:
        import scrape
    finally:
        sys.argv = argv
    # 資料檔裡已是分析好的條件（含戶籍簡稱修正），不要讓 evaluate_match 重新分析蓋掉
    scrape.ns["enrich_requirements"] = lambda obj: obj
    return scrape.ns


def read_items(folder, name):
    try:
        return json.loads((Path(folder) / name).read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return None


def new_items(old_dir, new_dir, name, key):
    old, new = read_items(old_dir, name), read_items(new_dir, name)
    if old is None or new is None:  # 沒有舊資料可比時不通知，避免一次寄出全部
        return []
    seen = {i[key] for i in old}
    return [i for i in new if i[key] not in seen]


def match_nutn(item, p, ns):
    fields = dict(item["with_att"])
    obj = ns["Scholarship"](title=item["title"], **fields)
    ns["evaluate_match"](
        obj,
        user_academic=float(p["gpa"]), user_conduct=float(p["conduct"]),
        has_poverty_proof=bool(p.get("low")),
        allow_poverty_qualification_unknown=bool(p.get("unsure", True)),
        user_residency=p["city"], is_indigenous=bool(p.get("ind")), user_major=p.get("dept", ""),
    )
    return obj.match


def match_external(item, p):
    """只用結構化欄位粗篩（戶籍、學制、成績），其餘請看原文。"""
    def open_(v):
        return not v or re.match(r"(不拘|不限|無)", v)

    tw = lambda v: v.replace("台", "臺")  # noqa: E731
    if not open_(item.get("residency")) and tw(p["city"]) not in tw(item["residency"]):
        return "不符合"
    if not open_(item.get("stage")) and not re.search(p.get("stage", "大專|大學"), item["stage"]):
        return "不符合"
    for label, mine in (("智育", p["gpa"]), ("平均", p["gpa"]), (r"德育\(操行\)", p["conduct"])):
        m = re.search(label + r"\s*[:：]\s*(\d{2,3})", item.get("grade", ""))
        if m and float(mine) < int(m[1]):
            return "不符合"
    return "可能符合（需確認）"


def line(title, url, match, deadline):
    # 公告文字是外部內容：避免 @ 通知到別人、避免破壞連結格式
    title = re.sub(r"[\[\]<>`]", " ", title).replace("@", "＠").replace("#", "＃")
    url = url if re.match(r"https://[^\s()]+$", url) else ""
    name = f"[{title}]({url})" if url else title
    return f"- {name}（{match}，截止 {deadline or '請看原文'}）"


def build(old_dir, new_dir, profile, ns, today):
    lines = []
    for item in new_items(old_dir, new_dir, "scholarships.json", "board_no"):
        if item.get("deadline_iso") and item["deadline_iso"] < today:
            continue
        m = match_nutn(item, profile, ns)
        if m != "不符合":
            lines.append(line(item["title"], item["url"], m, item.get("deadline_iso")))
    for item in new_items(old_dir, new_dir, "external.json", "url"):
        if item["category"] == "scholar":
            m = match_external(item, profile)
            if m != "不符合":
                lines.append(line(item["title"], item["url"], m, item.get("deadline_iso")))
        else:
            lines.append(line(item["title"], item["url"], "新活動", item.get("end_iso")))
    return "\n".join(lines)


def main():
    raw = os.environ.get("NUTN_PROFILE", "").strip()
    if not raw:
        print("尚未設定 NUTN_PROFILE，略過通知", file=sys.stderr)
        return
    try:
        profile = json.loads(raw)
        float(profile["gpa"]), float(profile["conduct"]), profile["city"]
    except (ValueError, KeyError, TypeError):
        sys.exit("NUTN_PROFILE 格式不正確（需要 city、gpa、conduct）")  # 不印出內容
    body = build(sys.argv[1], sys.argv[2], profile, load_rules(), datetime.now(TW).strftime("%Y-%m-%d"))
    if body:
        print(body)


if __name__ == "__main__":
    main()
