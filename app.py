import io
import re
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE_URL = "https://campus.nutn.edu.tw/newsPost3/"
LIST_URL = "https://campus.nutn.edu.tw/newsPost3/default.aspx?board=18"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


@dataclass
class Scholarship:
    title: str = ""
    url: str = ""
    board_no: str = ""
    department: str = ""
    posted_date: str = ""
    deadline: str = ""
    detail: str = ""
    attachment_text: str = ""
    attachment_names: str = ""
    poverty_status: str = "未提及"
    academic_requirement: str = "無明確要求"
    academic_min: float | None = None
    conduct_requirement: str = "無明確要求"
    conduct_min: float | None = None
    other_requirements: str = ""
    needs_manual_check: bool = False
    match: str = "待判斷"
    match_reason: str = ""
    residency_requirement: str = "未偵測"
    indigenous_requirement: str = "未偵測"
    major_requirement: str = "未偵測"
    remaining_days: int | None = None
    match_score: int = 0
    difficulty: str = "未評估"


def clean_text(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch(url, timeout=60):
    for attempt in range(3):
        try:
            skip_ssl_verify = "campus.nutn.edu.tw" in url
            
            r = SESSION.get(url, timeout=timeout,verify=not skip_ssl_verify)
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            if attempt < 2:
                time.sleep(3)
            else:
                raise


def parse_listing() -> list[dict]:
    """抓取 board=18 列表上的所有 readPost.aspx?boardNo=... 連結。"""
    html = fetch(LIST_URL).text
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r"readPost\.aspx\?boardNo=(\d+)", href, re.I)
        if not m:
            continue
        board_no = m.group(1)
        if board_no in seen:
            continue
        seen.add(board_no)
        title = clean_text(a.get_text(" ", strip=True))
        results.append({
            "board_no": board_no,
            "title": title,
            "url": urljoin(BASE_URL, href),
        })

    # 備援：有些 ASP.NET 頁面可能讓 BeautifulSoup 沒抓到 anchor text，改用 regex 找 boardNo
    if not results:
        for board_no in re.findall(r"readPost\.aspx\?boardNo=(\d+)", html, flags=re.I):
            if board_no in seen:
                continue
            seen.add(board_no)
            results.append({
                "board_no": board_no,
                "title": "",
                "url": urljoin(BASE_URL, f"readPost.aspx?boardNo={board_no}"),
            })

    return results


def get_table_value(soup: BeautifulSoup, labels: list[str]) -> str:
    """從詳細頁常見的 table 欄位中找 Subject/Department/Detail 等資料。"""
    for cell in soup.find_all(["td", "th"]):
        label_text = clean_text(cell.get_text(" ", strip=True))
        if any(label in label_text for label in labels):
            sib = cell.find_next_sibling(["td", "th"])
            if sib:
                return clean_text(sib.get_text("\n", strip=True))
    return ""


def extract_deadline(title: str, detail: str) -> str:
    text = title + "\n" + detail[:1800]
    patterns = [
        r"(?:截止|收件至|申請至|期限)[：:\s]*(?:民國)?(\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?)",
        r"\((\d{1,2}/\d{1,2})\s*截止\)",
        r"(\d{1,2}/\d{1,2})\s*(?:前|止|截止)",
        r"(\d{2,3}年\d{1,2}月\d{1,2}日)\s*(?:前|止|截止)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    if "隨時" in text:
        return "隨時"
    return "未辨識"


def extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return clean_text("\n".join(chunks))
    except Exception:
        return ""


def extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
        texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
        return clean_text(" ".join(texts))
    except Exception:
        return ""


def extract_odt_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("content.xml")
        root = ET.fromstring(xml)
        texts = [node.text for node in root.iter() if node.text]
        return clean_text(" ".join(texts))
    except Exception:
        return ""


def extract_attachment_text(url: str) -> tuple[str, bool]:
    """回傳 (文字, 是否需要人工確認)。掃描 PDF 或未知格式會標人工確認。"""
    try:
        r = fetch(url, timeout=35)
        content = r.content
        path = url.lower().split("?")[0]
        if path.endswith(".pdf"):
            text = extract_pdf_text(content)
            return text, len(text) < 40
        if path.endswith(".docx"):
            text = extract_docx_text(content)
            return text, len(text) < 20
        if path.endswith(".odt"):
            text = extract_odt_text(content)
            return text, len(text) < 20
        if path.endswith((".txt", ".csv")):
            try:
                return clean_text(r.text), False
            except Exception:
                return "", True
        # xls/xlsx/doc/jpg/png 等先不強行解析，避免誤判
        return "", True
    except Exception:
        return "", True


def parse_detail(item: dict, include_attachments=True) -> Scholarship:
    html = fetch(item["url"]).text
    soup = BeautifulSoup(html, "html.parser")

    title = get_table_value(soup, ["主旨", "Subject"]) or item.get("title", "")
    department = get_table_value(soup, ["公告單位", "Department"])
    posted = get_table_value(soup, ["公告時間", "Time Posted"])
    detail = get_table_value(soup, ["內容", "Detail"])

    # 備援：如果 table 格式變了，抓整頁文字，至少仍可分類
    if not detail:
        page_text = clean_text(soup.get_text("\n", strip=True))
        marker = re.search(r"(?:內容\s*\(Detail\)|內容)\s*[:：]?\s*(.*)", page_text, re.S)
        detail = clean_text(marker.group(1)) if marker else page_text

    attachment_names = []
    attachment_chunks = []
    manual = False

    if include_attachments:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            name = clean_text(a.get_text(" ", strip=True))
            ext_match = re.search(r"\.(pdf|docx?|odt|xlsx?|txt|csv|jpg|jpeg|png)(?:\?|$)", href, re.I)
            if not ext_match:
                continue
            full = urljoin(item["url"], href)
            attachment_names.append(name or full.rsplit("/", 1)[-1])
            text, need_manual = extract_attachment_text(full)
            if text:
                attachment_chunks.append(f"【附件：{name}】\n{text}")
            manual = manual or need_manual
            time.sleep(0.08)

    obj = Scholarship(
        title=title,
        url=item["url"],
        board_no=item["board_no"],
        department=department,
        posted_date=posted,
        deadline=extract_deadline(title, detail),
        detail=detail,
        attachment_text="\n\n".join(attachment_chunks),
        attachment_names="；".join(attachment_names),
        needs_manual_check=manual,
    )
    analyze_requirements(obj)
    return obj


def find_scores(text: str, kind: str) -> list[float]:
    """尋找學業/操行附近的分數門檻，盡量只抓『以上/不得低於』類條件。"""
    if kind == "academic":
        keys = r"(?:學業(?:成績)?|學期成績|總平均|平均成績|智育|學業平均)"
    else:
        keys = r"(?:操行(?:成績)?|德育(?:成績)?|品德(?:成績)?|操行平均)"

    score_patterns = [
        rf"{keys}.{{0,35}}?(\d{{2,3}}(?:\.\d+)?)\s*分?\s*(?:以上|含以上|或以上|不得低於|不低於|達)",
        rf"{keys}.{{0,20}}?(?:須|需|應)?\s*(?:達|滿|為)?\s*(\d{{2,3}}(?:\.\d+)?)\s*分",
        rf"(\d{{2,3}}(?:\.\d+)?)\s*分?\s*(?:以上|含以上|或以上).{{0,20}}?{keys}",
    ]
    scores = []
    for p in score_patterns:
        for m in re.finditer(p, text, re.I | re.S):
            try:
                val = float(m.group(1))
                if 50 <= val <= 100:
                    scores.append(val)
            except Exception:
                pass
    return sorted(set(scores))


def has_explicit_no_requirement(text: str, kind: str) -> bool:
    if kind == "academic":
        return bool(re.search(r"(?:學業|成績).{0,15}(?:不限|無限制|不拘|無要求)", text))
    return bool(re.search(r"(?:操行|德育|品德).{0,15}(?:不限|無限制|不拘|無要求)", text))


def poverty_classification(text: str) -> str:
    # 真正「證明文件」要求優先
    proof_patterns = [
        r"(?:清寒|低收入|中低收入|弱勢).{0,20}(?:證明|證明書|證明文件)",
        r"(?:證明|證明書|證明文件).{0,20}(?:清寒|低收入|中低收入|弱勢)",
        r"清寒證明",
    ]
    if any(re.search(p, text, re.I | re.S) for p in proof_patterns):
        return "需要清寒/弱勢證明"

    if re.search(r"(?:家境|家庭).{0,12}(?:清寒|困難)|清寒學生|經濟弱勢|低收入戶|中低收入戶", text, re.I | re.S):
        return "有清寒/弱勢資格（證明方式需確認）"

    if re.search(r"(?:不以清寒|無清寒限制|不限家境|家境不拘)", text, re.I | re.S):
        return "不要求清寒"

    return "未提及"


def extract_other_requirements(text: str) -> str:
    """抓最常見、會直接影響資格的其他限制，讓使用者快速人工確認。"""
    tags = []
    rules = [
        (r"設籍.{0,20}(?:縣|市|鄉|鎮|區)", "設籍限制"),
        (r"原住民|原住民族", "原住民身分"),
        (r"新住民|新住民子女", "新住民身分"),
        (r"身心障礙|視障|聽障", "身心障礙/特定身分"),
        (r"癌症|癌友|重大傷病|罕見疾病|心臟病", "疾病/家庭身分限制"),
        (r"(?:資訊|電機|電子|能源|工程).{0,12}(?:系|所|科)", "科系限制"),
        (r"(?:大一|一年級|大二|二年級|大三|三年級|大四|四年級|研究所|碩士|博士)", "年級/學制限制"),
        (r"不得.{0,20}(?:領取|兼領).{0,20}(?:獎學金|補助)", "不得兼領其他獎助"),
        (r"服務學習|志工|服務時數", "服務/志工要求"),
        (r"戶籍|設籍", "戶籍要求"),
    ]
    for pat, tag in rules:
        if re.search(pat, text, re.I | re.S) and tag not in tags:
            tags.append(tag)
    return "、".join(tags) if tags else "未偵測到常見額外限制"


def analyze_requirements(obj: Scholarship):
    text = clean_text(obj.title + "\n" + obj.detail + "\n" + obj.attachment_text)
    obj.poverty_status = poverty_classification(text)

    academic = find_scores(text, "academic")
    conduct = find_scores(text, "conduct")

    if academic:
        obj.academic_min = min(academic)
        vals = " / ".join(str(int(v)) if v.is_integer() else str(v) for v in academic)
        obj.academic_requirement = f"偵測到門檻：{vals} 分以上"
    elif has_explicit_no_requirement(text, "academic"):
        obj.academic_requirement = "明確寫無學業限制"
    else:
        obj.academic_requirement = "無明確要求"

    if conduct:
        obj.conduct_min = min(conduct)
        vals = " / ".join(str(int(v)) if v.is_integer() else str(v) for v in conduct)
        obj.conduct_requirement = f"偵測到門檻：{vals} 分以上"
    elif has_explicit_no_requirement(text, "conduct"):
        obj.conduct_requirement = "明確寫無操行限制"
    else:
        obj.conduct_requirement = "無明確要求"

    obj.other_requirements = extract_other_requirements(text)

    if obj.attachment_names and not obj.attachment_text:
        obj.needs_manual_check = True



TAIWAN_PLACES = [
    "臺北市","台北市","新北市","桃園市","臺中市","台中市","臺南市","台南市","高雄市",
    "基隆市","新竹市","嘉義市","新竹縣","苗栗縣","彰化縣","南投縣","雲林縣","嘉義縣",
    "屏東縣","宜蘭縣","花蓮縣","臺東縣","台東縣","澎湖縣","金門縣","連江縣"
]

def norm_place(x: str) -> str:
    return (x or "").replace("台", "臺").strip()

def extract_residency(text: str) -> str:
    hits = []
    for place in TAIWAN_PLACES:
        p = norm_place(place)
        # Only treat place as a hard residency condition when nearby wording indicates household registration.
        if re.search(rf"(?:設籍|戶籍|籍設|戶籍地).{{0,25}}{re.escape(place)}|{re.escape(place)}.{{0,25}}(?:設籍|戶籍)", text, re.S):
            if p not in hits:
                hits.append(p)
    return "、".join(hits) if hits else "未偵測"

def extract_indigenous(text: str) -> str:
    if re.search(r"(?:限|須|需|具|具有|身分為).{0,15}(?:原住民|原住民族)|(?:原住民|原住民族).{0,15}(?:學生|身分|資格)", text, re.S):
        return "限原住民/原住民族"
    return "未偵測"

def extract_major(text: str) -> str:
    majors = []
    mapping = {
        "資訊工程": r"資訊工程|資工",
        "電機工程": r"電機工程|電機系",
        "電子工程": r"電子工程|電子系",
        "資訊相關": r"資訊相關(?:科|系|學系)|資訊類",
        "電機電子相關": r"電機.{0,6}電子|電子.{0,6}電機|電資",
    }
    hard_context = bool(re.search(r"(?:限|限定|就讀|系所|科系|學系|相關科系|相關系所)", text))
    if not hard_context:
        return "未偵測"
    for name, pat in mapping.items():
        if re.search(pat, text, re.S):
            majors.append(name)
    return "、".join(majors) if majors else "未偵測"

def parse_date_loose(value: str, reference_year=None):
    if not value or value in ("未辨識", "隨時"):
        return None
    now = datetime.now()
    ref = reference_year or now.year
    nums = [int(x) for x in re.findall(r"\d+", value)]
    try:
        if len(nums) >= 3:
            y, m, d = nums[0], nums[1], nums[2]
            if y < 1911:
                y += 1911
            return datetime(y, m, d)
        if len(nums) == 2:
            m, d = nums
            candidate = datetime(ref, m, d)
            # Around year boundaries, prefer a date reasonably near now.
            if candidate < now - timedelta(days=180):
                candidate = datetime(ref + 1, m, d)
            return candidate
    except ValueError:
        return None
    return None

def parse_posted_date(value: str):
    nums = [int(x) for x in re.findall(r"\d+", value or "")]
    try:
        if len(nums) >= 3:
            y, m, d = nums[0], nums[1], nums[2]
            if y < 1911:
                y += 1911
            return datetime(y, m, d)
    except ValueError:
        pass
    return None

def calc_difficulty(text: str) -> str:
    keys = {
        "推薦函": 2, "自傳": 2, "讀書計畫": 2, "心得": 1, "戶籍謄本": 1,
        "清寒證明": 1, "低收入戶": 1, "中低收入戶": 1, "成績單": 1,
        "服務證明": 1, "志工": 1, "面試": 3, "紙本": 1, "郵寄": 1,
    }
    score = sum(w for k, w in keys.items() if k in text)
    if score >= 7:
        return "🔴 高"
    if score >= 3:
        return "🟡 中"
    return "🟢 低"

def major_matches(user_major: str, requirement: str) -> bool:
    if requirement == "未偵測":
        return True
    u = user_major.replace("學系","").replace("系","")
    if "資訊工程" in requirement and ("資訊工程" in u or "資工" in u):
        return True
    if "資訊相關" in requirement and ("資訊" in u or "資工" in u):
        return True
    # 電機/電子限定不把資工自動視為符合，避免過度寬鬆。
    if ("電機工程" in requirement or "電子工程" in requirement or "電機電子相關" in requirement):
        return ("電機" in u or "電子" in u)
    return False

def enrich_requirements(obj: Scholarship):
    text = clean_text(obj.title + "\n" + obj.detail + "\n" + obj.attachment_text)
    obj.residency_requirement = extract_residency(text)
    obj.indigenous_requirement = extract_indigenous(text)
    obj.major_requirement = extract_major(text)
    obj.difficulty = calc_difficulty(text)
    deadline_dt = parse_date_loose(obj.deadline)
    if deadline_dt:
        obj.remaining_days = (deadline_dt.date() - datetime.now().date()).days
    return obj


def evaluate_match(
    obj: Scholarship,
    user_academic: float,
    user_conduct: float,
    has_poverty_proof: bool,
    allow_poverty_qualification_unknown: bool,
    user_residency: str,
    is_indigenous: bool,
    user_major: str,
) -> Scholarship:
    enrich_requirements(obj)
    failures, warnings = [], []
    checks, passed = 0, 0

    def check(ok, fail_text):
        nonlocal checks, passed
        checks += 1
        if ok:
            passed += 1
        else:
            failures.append(fail_text)

    if obj.academic_min is not None:
        check(user_academic >= obj.academic_min, f"學業 {user_academic:g} < 要求 {obj.academic_min:g}")
    if obj.conduct_min is not None:
        check(user_conduct >= obj.conduct_min, f"操行 {user_conduct:g} < 要求 {obj.conduct_min:g}")

    if obj.poverty_status == "需要清寒/弱勢證明":
        check(has_poverty_proof, "需要清寒/弱勢證明，但你設定為沒有")
    elif obj.poverty_status == "有清寒/弱勢資格（證明方式需確認）" and not has_poverty_proof:
        if allow_poverty_qualification_unknown:
            warnings.append("有清寒/弱勢資格限制，需再確認")
        else:
            failures.append("有清寒/弱勢資格限制")

    if obj.residency_requirement != "未偵測":
        allowed = [norm_place(x) for x in obj.residency_requirement.split("、")]
        check(norm_place(user_residency) in allowed,
              f"戶籍限制為 {obj.residency_requirement}，你的戶籍為 {user_residency}")

    if obj.indigenous_requirement != "未偵測":
        check(is_indigenous, "限原住民/原住民族身分")

    if obj.major_requirement != "未偵測":
        check(major_matches(user_major, obj.major_requirement),
              f"科系限制為 {obj.major_requirement}，你的科系為 {user_major}")

    if obj.needs_manual_check:
        warnings.append("附件可能無法完整自動讀取")

    # Unknown requirements are not counted as failures; score is confidence-weighted.
    base = 100 if checks == 0 else round(passed / checks * 100)
    if warnings:
        base = max(0, base - min(15, 5 * len(warnings)))
    obj.match_score = base

    if failures:
        obj.match = "不符合"
        obj.match_reason = "；".join(failures)
    elif warnings:
        obj.match = "可能符合（需確認）"
        obj.match_reason = "；".join(warnings)
    else:
        obj.match = "符合"
        obj.match_reason = "目前偵測到的硬性條件均符合"
    return obj


def threshold_bucket(value: float | None, choices=(70, 75, 80)) -> str:
    if value is None:
        return "無要求/未偵測"
    # 顯示最接近的常用門檻；不硬把 78 分錯標成 75
    if value in choices:
        return f"{int(value)}+"
    return f"{value:g}+"


def to_display_df(items: list[Scholarship]) -> pd.DataFrame:
    rows = []
    for x in items:
        rows.append({
            "符合狀態": x.match,
            "相符度": f"{x.match_score}%",
            "剩餘天數": x.remaining_days if x.remaining_days is not None else "未辨識",
            "難易度": x.difficulty,
            "公告": x.title,
            "截止日": x.deadline,
            "戶籍限制": x.residency_requirement,
            "原住民限制": x.indigenous_requirement,
            "科系限制": x.major_requirement,
            "清寒/弱勢": x.poverty_status,
            "學業門檻": threshold_bucket(x.academic_min),
            "操行門檻": threshold_bucket(x.conduct_min, (75, 80, 85)),
            "判斷理由": x.match_reason,
            "公告日期": x.posted_date,
            "附件": x.attachment_names,
            "網址": x.url,
        })
    return pd.DataFrame(rows)


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")



def is_thesis_related(obj: Scholarship) -> bool:
    """排除以碩博士論文、學位論文、論文獎等為主題的公告。
    避免只因一般公告內提到「論文」兩字就誤殺。
    """
    title = clean_text(obj.title)
    detail_head = clean_text(obj.detail[:1200])
    strong_title_patterns = [
        r"碩博士.*論文",
        r"博士.*論文",
        r"碩士.*論文",
        r"學位論文",
        r"論文獎",
        r"優秀論文",
        r"論文徵選",
        r"論文競賽",
        r"論文獎助",
        r"論文獎學金",
    ]
    if any(re.search(p, title, re.I | re.S) for p in strong_title_patterns):
        return True

    # 內文明確限定碩/博士生，且核心內容是論文，才排除。
    has_grad = bool(re.search(r"碩士|博士|碩博士|研究生", detail_head))
    has_thesis = bool(re.search(r"學位論文|博士論文|碩士論文|論文徵選|論文獎|論文競賽", detail_head))
    return has_grad and has_thesis
def is_award_result_related(obj: Scholarship) -> bool:
    """
    排除已經是公布結果的公告，
    例如：獲獎名單、得獎名單、錄取名單、獲獎公告等。
    """

    title = clean_text(obj.title)
    detail_head = clean_text(obj.detail[:1200])

    # 標題只要明確是公布結果，直接排除
    title_patterns = [
        r"獲獎名單",
        r"得獎名單",
        r"錄取名單",
        r"獲獎公告",
        r"得獎公告",
        r"錄取公告",
        r"獲獎結果",
        r"得獎結果",
        r"錄取結果",
        r"審查結果",
        r"評選結果",
        r"評審結果",
        r"核定名單",
        r"通過名單",
        r"獎助名單",
        r"獎學金名單",
        r"獎助學金名單",
        r"獎學金獲獎",
        r"獎助學金獲獎",
        r"獎學金得獎",
        r"獎助學金得獎",
    ]

    if any(re.search(pattern, title, re.I) for pattern in title_patterns):
        return True

    # 避免標題寫得很模糊，
    # 如果內文明確是在公布已完成的評選結果，也排除
    result_keywords = [
        r"獲獎者如下",
        r"得獎者如下",
        r"錄取者如下",
        r"獲獎學生如下",
        r"得獎學生如下",
        r"錄取學生如下",
        r"獲獎名單如下",
        r"得獎名單如下",
        r"錄取名單如下",
        r"審查結果如下",
        r"評選結果如下",
        r"核定名單如下",
    ]

    if any(re.search(pattern, detail_head, re.I) for pattern in result_keywords):
        return True

    return False

st.set_page_config(page_title="南大獎助學金篩選器", page_icon="🎓", layout="wide")
st.title("🎓 南大獎助學金自動篩選器")
st.caption("自動抓取 NUTN 獎助學金公告 → 自動屏蔽碩博士論文類訊息 → 戶籍／科系／原住民／清寒／成績篩選 → 顯示相符度、難易度與剩餘天數")

with st.sidebar:
    st.header("你的條件")
    user_residency = st.selectbox("戶籍地", ["新竹市","新竹縣","臺北市","新北市","桃園市","臺中市","臺南市","高雄市","基隆市","嘉義市","苗栗縣","彰化縣","南投縣","雲林縣","嘉義縣","屏東縣","宜蘭縣","花蓮縣","臺東縣","澎湖縣","金門縣","連江縣"])
    user_major = st.text_input("科系", value="資訊工程學系")
    is_indigenous = st.checkbox("我具有原住民／原住民族身分", value=False)
    user_academic = st.number_input("學業平均成績", min_value=0.0, max_value=100.0, value=80.0, step=1.0)
    user_conduct = st.number_input("操行成績", min_value=0.0, max_value=100.0, value=85.0, step=1.0)
    has_poverty_proof = st.checkbox("我有清寒／低收／中低收等相關證明", value=False)
    uncertain_ok = st.checkbox("清寒資格寫得不清楚時，先保留讓我人工確認", value=True)
    include_attachments = st.checkbox("讀取 PDF / DOCX / ODT 附件（較完整但較慢）", value=True)
    only_current = st.checkbox("只顯示符合 + 可能符合", value=True)
    max_posts = st.number_input("最多掃描公告數（0 = 全部）", min_value=0, max_value=500, value=0, step=10)

st.info(
    "程式會把『無明確要求』視為不因該項成績淘汰；但若公告有戶籍、年級、科系、特定身分等限制，會另外標示，請最後再人工確認。"
)

if st.button("🔎 開始抓取並篩選", type="primary", use_container_width=True):
    progress = st.progress(0, text="正在讀取公告列表…")
    try:
        listing = parse_listing()
        if max_posts:
            listing = listing[: int(max_posts)]
        if not listing:
            st.error("沒有抓到公告連結。網站版型可能已更新，請檢查網路或更新解析規則。")
            st.stop()

        results = []
        errors = []
        total = len(listing)
        for i, item in enumerate(listing, start=1):
            progress.progress((i - 1) / total, text=f"正在分析 {i}/{total}：{item.get('title') or item['board_no']}")
            try:
                obj = parse_detail(item, include_attachments=include_attachments)

                # 屏蔽碩博士論文／學位論文／論文獎等非大學生獎助學金訊息
                if is_thesis_related(obj):
                    continue

                #  排除獲獎／得獎／錄取名單
                if is_award_result_related(obj):
                    continue

                # 最近半年發布 + 已截止不顯示
                posted_dt = parse_posted_date(obj.posted_date)
                if posted_dt and posted_dt < datetime.now() - timedelta(days=183):
                    continue
                enrich_requirements(obj)
                if obj.remaining_days is not None and obj.remaining_days < 0:
                    continue

                obj = evaluate_match(
                    obj,
                    user_academic=user_academic,
                    user_conduct=user_conduct,
                    has_poverty_proof=has_poverty_proof,
                    allow_poverty_qualification_unknown=uncertain_ok,
                    user_residency=user_residency,
                    is_indigenous=is_indigenous,
                    user_major=user_major,
                )
                results.append(obj)
            except Exception as e:
                errors.append(f"{item.get('title') or item['board_no']}: {e}")
            time.sleep(0.12)  # 對校方網站友善一點，避免短時間大量請求

        progress.progress(1.0, text="完成！")
        st.session_state["scholarship_results"] = results
        st.session_state["scholarship_errors"] = errors
    except Exception as e:
        st.exception(e)

results = st.session_state.get("scholarship_results", [])
if results:
    df_all = to_display_df(results)
    if only_current:
        df_show = df_all[df_all["符合狀態"].isin(["符合", "可能符合（需確認）"])].copy()
    else:
        df_show = df_all.copy()

    order = pd.Categorical(df_show["符合狀態"], categories=["符合", "可能符合（需確認）", "不符合"], ordered=True)
    df_show = df_show.assign(_order=order)
    df_show["_days_sort"] = pd.to_numeric(df_show["剩餘天數"], errors="coerce").fillna(99999)
    df_show["_score_sort"] = pd.to_numeric(df_show["相符度"].astype(str).str.rstrip("%"), errors="coerce").fillna(0)
    df_show = df_show.sort_values(["_order", "_score_sort", "_days_sort"], ascending=[True, False, True]).drop(columns=["_order","_days_sort","_score_sort"])

    c1, c2, c3 = st.columns(3)
    c1.metric("✅ 符合", int((df_all["符合狀態"] == "符合").sum()))
    c2.metric("⚠️ 可能符合", int((df_all["符合狀態"] == "可能符合（需確認）").sum()))
    c3.metric("❌ 不符合", int((df_all["符合狀態"] == "不符合").sum()))

    st.subheader("篩選結果")
    st.dataframe(
        df_show,
        use_container_width=True,
        hide_index=True,
        column_config={"網址": st.column_config.LinkColumn("網址", display_text="開啟公告")},
    )

    st.download_button(
        "⬇️ 匯出目前結果 CSV",
        data=csv_bytes(df_show),
        file_name=f"NUTN_獎助學金篩選_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.subheader("逐篇查看抓到的內容")
    matching_objs = [x for x in results if (not only_current or x.match != "不符合")]
    for x in matching_objs:
        with st.expander(f"{x.match}｜{x.title}"):
            st.write(f"**相符度：** {x.match_score}%　｜　**剩餘天數：** {x.remaining_days if x.remaining_days is not None else '未辨識'}　｜　**難易度：** {x.difficulty}")
            st.write(f"**戶籍限制：** {x.residency_requirement}")
            st.write(f"**原住民限制：** {x.indigenous_requirement}")
            st.write(f"**科系限制：** {x.major_requirement}")
            st.write(f"**清寒/弱勢：** {x.poverty_status}")
            st.write(f"**學業：** {x.academic_requirement}")
            st.write(f"**操行：** {x.conduct_requirement}")
            st.write(f"**其他限制：** {x.other_requirements}")
            st.write(f"**判斷：** {x.match_reason}")
            st.link_button("開啟原公告", x.url)
            st.text_area("公告內文", x.detail, height=220, key=f"detail_{x.board_no}")
            if x.attachment_text:
                st.text_area("附件擷取文字", x.attachment_text, height=220, key=f"att_{x.board_no}")

errors = st.session_state.get("scholarship_errors", [])
if errors:
    with st.expander(f"⚠️ {len(errors)} 則公告抓取失敗"):
        st.code("\n".join(errors))
