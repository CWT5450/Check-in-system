#!/usr/bin/env python3
"""下載 TronClass（創課平台）某個作業的學生繳交內容，供後續批閱。

用法（在你自己的電腦上執行）：
  1. 用瀏覽器登入 https://tronclass.cgust.edu.tw
  2. 按 F12 -> Application(應用程式) -> Cookies -> tronclass.cgust.edu.tw
     複製名為 session 的那一列的值
  3. 執行：
       # macOS / Linux
       export TRONCLASS_SESSION='貼上 session 值'
       python3 fetch_submissions.py
       # Windows PowerShell
       $env:TRONCLASS_SESSION='貼上 session 值'
       python3 fetch_submissions.py
  4. 把輸出的 out/ 資料夾（或其中的 summary.md）交給 Claude 批閱。

Cookie 只從環境變數讀取，不會寫入任何檔案。請勿把 Cookie 貼到對話或上傳到 GitHub。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("TRONCLASS_BASE", "https://tronclass.cgust.edu.tw")
COURSE_ID = os.environ.get("TRONCLASS_COURSE", "20621")
ACTIVITY_ID = os.environ.get("TRONCLASS_ACTIVITY", "149611")
OUT = os.environ.get("TRONCLASS_OUT", "out")

# 各校版本路徑不一，依序嘗試；成功的都會存檔。
CANDIDATES = {
    "activity": ["/api/activities/{a}"],
    "course_activities": ["/api/courses/{c}/activities"],
    "submission_list": [
        "/api/course/{c}/homework-scores?activity_id={a}&page=1&page_size=500",
        "/api/activities/{a}/submissions?page=1&page_size=500",
        "/api/course/activities/{a}/submission-list",
        "/api/activities/{a}/students",
    ],
    "score_list": [
        "/api/course/{c}/activities/{a}/scores",
        "/api/activities/{a}/scores",
    ],
}


def get(path, raw=False):
    req = urllib.request.Request(
        BASE + path,
        headers={
            "Cookie": "session=" + os.environ["TRONCLASS_SESSION"],
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return body if raw else json.loads(body.decode("utf-8"))


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def walk(o):
    """遞迴走訪 JSON，產生所有 dict。"""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def safe(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(s))[:80]


def main():
    if not os.environ.get("TRONCLASS_SESSION"):
        sys.exit("請先設定環境變數 TRONCLASS_SESSION（見檔案開頭說明）")

    found = {}
    for key, paths in CANDIDATES.items():
        for tpl in paths:
            path = tpl.format(c=COURSE_ID, a=ACTIVITY_ID)
            try:
                data = get(path)
            except urllib.error.HTTPError as e:
                print(f"[{e.code}] {path}")
                if e.code in (401, 403) and key == "activity":
                    sys.exit("未授權：session 可能已過期或複製錯誤，請重新登入後再試。")
                continue
            except Exception as e:  # 網路錯誤、非 JSON 等
                print(f"[錯誤] {path}: {e}")
                continue
            print(f"[OK ] {path}")
            save(f"{key}.json", data)
            found[key] = data
            break

    if not found:
        sys.exit("所有候選路徑都失敗。請把上面的訊息給 Claude 以調整路徑。")

    # 下載所有找得到的附件（upload id）。
    uploads = {}
    for data in found.values():
        for d in walk(data):
            uid = d.get("id") if "name" in d and "size" in d else None
            ref = d.get("reference_id")
            if uid and d.get("name"):
                uploads[uid] = d["name"]
            elif ref and d.get("name"):
                uploads[ref] = d["name"]

    fdir = os.path.join(OUT, "files")
    os.makedirs(fdir, exist_ok=True)
    for uid, name in uploads.items():
        try:
            blob = get(f"/api/uploads/{uid}/blob", raw=True)
        except Exception as e:
            print(f"[附件失敗] {uid} {name}: {e}")
            continue
        with open(os.path.join(fdir, f"{uid}_{safe(name)}"), "wb") as f:
            f.write(blob)
        print(f"[附件] {name}")

    print(f"\n完成。請把 {os.path.abspath(OUT)} 交給 Claude。")


if __name__ == "__main__":
    main()
