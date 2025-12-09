# main.py
#
# オンライン墓参りログ（実験版）API
# - /ping              動作確認
# - /api/visits        お参り・日記ログ（GET/POST）
# - /api/donations     寄付のメモ（GET/POST）

import os
import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# ========= 保存場所 =========

DATA_DIR = "data"
UPLOAD_DIR = "uploads"
VISIT_FILE = os.path.join(DATA_DIR, "visit_logs.json")
DONATION_FILE = os.path.join(DATA_DIR, "donations.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ========= データモデル =========

class VisitLog(BaseModel):
    id: str
    created_at: str            # 登録日時
    visit_date: str            # 日付（実際の参拝日 or 家で手を合わせた日）
    visitor_name: str          # 記録した人の名前
    target: str = "先祖のお墓"  # どの方のお墓・記録か（例：祖父○○のお墓）
    kind: str = "visit"        # "visit"（実際にお墓へ） or "diary"（家からの手合わせ・日記）
    message: str               # メモ
    photo_url: Optional[str] = None  # 写真のURL（/uploads/...）

    # 以前のJSONに cost などが残っていても、そのまま無視される想定


class Donation(BaseModel):
    id: str
    created_at: str          # 記録日時
    visit_id: str            # どのログへの寄付か
    donor_name: str          # 寄付した人
    amount: int              # 金額（メモ用）
    message: str = ""        # メッセージ


# ========= JSON 読み書き =========

def load_visits() -> List[VisitLog]:
    if not os.path.exists(VISIT_FILE):
        return []
    try:
        with open(VISIT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [VisitLog(**item) for item in data]
    except Exception:
        return []


def save_visits(logs: List[VisitLog]) -> None:
    data = [log.dict() for log in logs]
    with open(VISIT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_donations() -> List[Donation]:
    if not os.path.exists(DONATION_FILE):
        return []
    try:
        with open(DONATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Donation(**item) for item in data]
    except Exception:
        return []


def save_donations(items: List[Donation]) -> None:
    data = [d.dict() for d in items]
    with open(DONATION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ========= FastAPI 本体 =========

app = FastAPI(title="Bosankai Log API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 実験版なので全許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 写真の配信
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/ping")
def ping():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ----- お参り・日記ログ -----

@app.get("/api/visits", response_model=List[VisitLog])
def get_visits():
    logs = load_visits()
    logs_sorted = sorted(logs, key=lambda x: x.created_at, reverse=True)
    return logs_sorted


@app.post("/api/visits", response_model=VisitLog)
async def create_visit(
    visit_date: str = Form(...),
    visitor_name: str = Form(...),
    target: str = Form("先祖のお墓"),
    kind: str = Form("visit"),    # "visit" or "diary"
    message: str = Form(""),
    photo: Optional[UploadFile] = File(None),
):
    logs = load_visits()

    visit_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    photo_url: Optional[str] = None

    # 写真があれば保存
    if photo is not None:
        original_name = photo.filename or "photo.jpg"
        _, ext = os.path.splitext(original_name)
        if ext == "":
            ext = ".jpg"
        filename = f"{visit_id}{ext}"
        save_path = os.path.join(UPLOAD_DIR, filename)

        with open(save_path, "wb") as f:
            content = await photo.read()
            f.write(content)

        photo_url = f"/uploads/{filename}"

    new_log = VisitLog(
        id=visit_id,
        created_at=created_at,
        visit_date=visit_date,
        visitor_name=visitor_name,
        target=target,
        kind=kind,
        message=message,
        photo_url=photo_url,
    )

    logs.append(new_log)
    save_visits(logs)

    return new_log


# ----- 寄付（メモ用） -----

@app.get("/api/donations", response_model=List[Donation])
def get_donations(visit_id: Optional[str] = None):
    """
    visit_id を指定すると、そのログの寄付だけを返す。
    指定なしなら全部返す。
    """
    items = load_donations()
    if visit_id:
        items = [d for d in items if d.visit_id == visit_id]
    items_sorted = sorted(items, key=lambda x: x.created_at)
    return items_sorted


@app.post("/api/donations", response_model=Donation)
async def create_donation(
    visit_id: str = Form(...),
    donor_name: str = Form(...),
    amount: int = Form(...),
    message: str = Form(""),
):
    """
    寄付の「記録」だけを行う。
    実際のお金のやりとりは、このAPIの外でやる前提。
    """
    donations = load_donations()

    donation_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_item = Donation(
        id=donation_id,
        created_at=created_at,
        visit_id=visit_id,
        donor_name=donor_name,
        amount=amount,
        message=message,
    )

    donations.append(new_item)
    save_donations(donations)

    return new_item


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
