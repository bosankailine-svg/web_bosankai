# main.py
#
# 「みんなの墓参会」用 API サーバ（Render に置く想定）
# - /ping                 疎通確認
# - /api/visits (GET)     コミュニティごとの記録一覧
# - /api/visits (POST)    新しい記録を保存（写真つき）
# - /api/donations (GET)  コミュニティごとの寄付一覧
# - /api/donations (POST) 寄付のメモを保存
#
# 必要なもの:
#   pip install fastapi "uvicorn[standard]" python-multipart
#
# 起動:
#   uvicorn main:app --reload
#   （Render では: uvicorn main:app --host 0.0.0.0 --port $PORT）

import os
import uuid
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ====== 設定 ======
DB_PATH = "bosankai.db"
UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ====== FastAPI 本体 ======
app = FastAPI()

# CORS（Netlify / LIFF から叩かれるので一旦ゆるめに全部許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 必要ならあとで絞る
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 写真用ディレクトリを /uploads で公開
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # 記録テーブル
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            visitor_name TEXT NOT NULL,
            target TEXT,
            kind TEXT NOT NULL,
            message TEXT,
            photo_path TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # 寄付テーブル
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS donations (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            visit_id TEXT NOT NULL,
            donor_name TEXT,
            amount INTEGER NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


init_db()

# ====== Pydantic モデル ======


class VisitLog(BaseModel):
    id: str
    community_id: str
    visit_date: str
    visitor_name: str
    target: Optional[str] = None
    kind: str
    message: Optional[str] = None
    photo_url: Optional[str] = None
    created_at: str


class Donation(BaseModel):
    id: str
    community_id: str
    visit_id: str
    donor_name: Optional[str] = None
    amount: int
    message: Optional[str] = None
    created_at: str


# ====== エンドポイント ======


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.get("/api/visits", response_model=List[VisitLog])
def list_visits(community_id: str = "default"):
    """
    コミュニティごとの記録一覧
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM visits
        WHERE community_id = ?
        ORDER BY visit_date DESC, created_at DESC
        """,
        (community_id,),
    )
    rows = cur.fetchall()
    conn.close()

    result: List[VisitLog] = []
    for r in rows:
        photo_url = None
        if r["photo_path"]:
            photo_url = f"/uploads/{r['photo_path']}"
        result.append(
            VisitLog(
                id=r["id"],
                community_id=r["community_id"],
                visit_date=r["visit_date"],
                visitor_name=r["visitor_name"],
                target=r["target"],
                kind=r["kind"],
                message=r["message"],
                photo_url=photo_url,
                created_at=r["created_at"],
            )
        )
    return result


@app.post("/api/visits", response_model=VisitLog)
async def create_visit(
    visit_date: str = Form(...),
    visitor_name: str = Form(...),
    target: Optional[str] = Form(None),
    kind: str = Form("visit"),
    message: Optional[str] = Form(None),
    community_id: str = Form("default"),
    photo: Optional[UploadFile] = File(None),
):
    """
    新しい記録を保存（写真つき）
    """
    visit_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    photo_filename = None
    if photo is not None and photo.filename:
        # 拡張子をざっくり決める
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            ext = ".jpg"
        photo_filename = f"{visit_id}{ext}"
        save_path = os.path.join(UPLOAD_DIR, photo_filename)
        contents = await photo.read()
        with open(save_path, "wb") as f:
            f.write(contents)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO visits (
            id, community_id, visit_date, visitor_name,
            target, kind, message, photo_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            visit_id,
            community_id,
            visit_date,
            visitor_name,
            target,
            kind,
            message,
            photo_filename,
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    photo_url = f"/uploads/{photo_filename}" if photo_filename else None

    return VisitLog(
        id=visit_id,
        community_id=community_id,
        visit_date=visit_date,
        visitor_name=visitor_name,
        target=target,
        kind=kind,
        message=message,
        photo_url=photo_url,
        created_at=created_at,
    )


@app.get("/api/donations", response_model=List[Donation])
def list_donations(community_id: str = "default"):
    """
    コミュニティごとの寄付一覧
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM donations
        WHERE community_id = ?
        ORDER BY created_at DESC
        """,
        (community_id,),
    )
    rows = cur.fetchall()
    conn.close()

    result: List[Donation] = []
    for r in rows:
        result.append(
            Donation(
                id=r["id"],
                community_id=r["community_id"],
                visit_id=r["visit_id"],
                donor_name=r["donor_name"],
                amount=int(r["amount"]),
                message=r["message"],
                created_at=r["created_at"],
            )
        )
    return result


@app.post("/api/donations", response_model=Donation)
def create_donation(
    visit_id: str = Form(...),
    donor_name: Optional[str] = Form(None),
    amount: int = Form(...),
    message: Optional[str] = Form(None),
):
    """
    寄付のメモを保存。
    community_id は visit にひもづけて自動で入れる。
    """
    conn = get_conn()
    cur = conn.cursor()

    # まず visit を探してコミュニティIDを取得
    cur.execute("SELECT community_id FROM visits WHERE id = ?", (visit_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=400, detail="元の記録が見つかりません。")

    community_id = row["community_id"]
    donation_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        INSERT INTO donations (
            id, community_id, visit_id, donor_name, amount, message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            donation_id,
            community_id,
            visit_id,
            donor_name,
            int(amount),
            message,
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    return Donation(
        id=donation_id,
        community_id=community_id,
        visit_id=visit_id,
        donor_name=donor_name,
        amount=int(amount),
        message=message,
        created_at=created_at,
    )
