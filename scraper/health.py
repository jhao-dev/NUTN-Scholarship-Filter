"""檢查這次自動更新有沒有問題；有問題就把說明印出來（沒有輸出代表正常）。

環境變數 NUTN_OUTCOME / EXTERNAL_OUTCOME 由 GitHub Actions 傳入。
"""
import json
import os
from pathlib import Path

NUTN_MAX_ERRORS = 5  # 南大公告偶爾單則抓不到屬正常，超過這個數量才提醒


def problems(nutn_outcome, external_outcome, data_dir):
    out = []
    for name, outcome, file, limit in [
        ("南大公告", nutn_outcome, "scholarships.json", NUTN_MAX_ERRORS),
        ("外部資源", external_outcome, "external.json", 0),
    ]:
        if outcome != "success":
            out.append(f"{name}抓取步驟沒有成功（{outcome or '未執行'}）")
            continue
        try:
            errors = json.loads((Path(data_dir) / file).read_text(encoding="utf-8")).get("errors", [])
        except (OSError, ValueError) as e:
            out.append(f"{name}資料檔讀不到：{e}")
            continue
        if len(errors) > limit:
            out.append(f"{name}有 {len(errors)} 筆抓取失敗，例如：{errors[0]}")
    return out


if __name__ == "__main__":
    for p in problems(os.environ.get("NUTN_OUTCOME"), os.environ.get("EXTERNAL_OUTCOME"), "data"):
        print(f"- {p}")
