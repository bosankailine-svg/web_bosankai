import os
import uuid
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ========= 設定 =========

DB_PATH = os.getenv("BOSANKAI_DB_PATH", "bosankai.db")
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")

os.makedirs(MEDIA_ROOT, exist_ok=True)

# ========= DB 初期化 =========

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # 墓参記録
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            visitor_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # 墓参記録にぶら下がるメディア（写真・動画）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visit_media (
            id TEXT PRIMARY KEY,
            visit_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            FOREIGN KEY (visit_id) REFERENCES visits(id) ON DELETE CASCADE
        )
        """
    )

    # 寄付（感謝の気持ち＋任意の金額）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS donations (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            visit_id TEXT NOT NULL,
            donor_name TEXT,
            amount INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (visit_id) REFERENCES visits(id) ON DELETE CASCADE
        )
        """
    )

    # 思い出の品
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT
        )
        """
    )

    # 思い出の品メディア
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_media (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        )
        """
    )

    # 思い出の品へのコメント
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_comments (
            id TEXT PRIMARY KEY,
            community_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            author_name TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()

def save_upload_file(upload: UploadFile, subdir: str, prefix: str) -> str:
    """
    アップロードされたファイルを media/<subdir>/ 以下に保存し、
    クライアントから参照するための URL パス (/media/...) を返す。
    """
    # 拡張子
    _, ext = os.path.splitext(upload.filename or "")
    if not ext:
        # とりあえず適当に
        ext = ".bin"
    ext = ext.lower()

    safe_prefix = prefix.replace("/", "_")
    token = uuid.uuid4().hex[:8]
    filename = f"{safe_prefix}_{token}{ext}"

    dir_path = os.path.join(MEDIA_ROOT, subdir)
    os.makedirs(dir_path, exist_ok=True)

    file_path = os.path.join(dir_path, filename)
    with open(file_path, "wb") as f:
        f.write(upload.file.read())

    # クライアントからは /media/... でアクセス
    url_path = f"/media/{subdir}/{filename}"
    return url_path

# 故人の顔写真（コミュニティごと 1 枚想定）は別関数で上書き保存
def save_community_avatar(upload: UploadFile, community_id: str) -> str:
    _, ext = os.path.splitext(upload.filename or "")
    if not ext:
        ext = ".jpg"
    ext = ext.lower()

    safe_id = community_id.replace("/", "_")
    filename = f"{safe_id}{ext}"

    dir_path = os.path.join(MEDIA_ROOT, "community_avatars")
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, filename)

    with open(file_path, "wb") as f:
        f.write(upload.file.read())

    return f"/media/community_avatars/{filename}"

# ========= Pydantic モデル =========

class VisitMediaOut(BaseModel):
    media_type: str
    url: str

class VisitOut(BaseModel):
    id: str
    community_id: str
    visit_date: str
    visitor_name: str
    kind: str
    message: Optional[str]
    created_at: str
    media: List[VisitMediaOut] = []

class DonationOut(BaseModel):
    id: str
    community_id: str
    visit_id: str
    donor_name: Optional[str]
    amount: int
    message: Optional[str]
    created_at: str

class MemoryMediaOut(BaseModel):
    media_type: str
    url: str

class MemoryOut(BaseModel):
    id: str
    community_id: str
    title: str
    description: Optional[str]
    created_at: str
    created_by: Optional[str]
    media: List[MemoryMediaOut] = []

class MemoryCommentOut(BaseModel):
    id: str
    community_id: str
    memory_id: str
    author_name: Optional[str]
    message: str
    created_at: str

# ========= FastAPI 本体 =========

app = FastAPI(title="Bosankai API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 必要なら絞る
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# media ディレクトリを静的配信
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

@app.on_event("startup")
def on_startup():
    init_db()

# ---------- Ping ----------

@app.get("/ping")
def ping():
    return {"status": "ok"}

# ---------- 墓参記録 ----------

@app.post("/api/visits", response_model=VisitOut)
async def create_visit(
    community_id: str = Form("default"),
    visit_date: str = Form(...),
    visitor_name: str = Form(...),
    kind: str = Form("visit"),
    message: str = Form(""),
    media: Optional[List[UploadFile]] = File(None),
):
    vid = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO visits (id, community_id, visit_date, visitor_name, kind, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (vid, community_id, visit_date, visitor_name, kind, message, now),
    )

    media_out: List[VisitMediaOut] = []
    if media:
        for up in media:
            if not up.filename:
                continue
            content_type = up.content_type or ""
            mtype = "video" if content_type.startswith("video/") else "image"
            url_path = save_upload_file(up, "visit_media", prefix=vid)
            mid = uuid.uuid4().hex
            cur.execute(
                """
                INSERT INTO visit_media (id, visit_id, media_type, file_path)
                VALUES (?, ?, ?, ?)
                """,
                (mid, vid, mtype, url_path),
            )
            media_out.append(VisitMediaOut(media_type=mtype, url=url_path))

    conn.commit()
    conn.close()

    return VisitOut(
        id=vid,
        community_id=community_id,
        visit_date=visit_date,
        visitor_name=visitor_name,
        kind=kind,
        message=message,
        created_at=now,
        media=media_out,
    )

@app.get("/api/visits", response_model=List[VisitOut])
def list_visits(
    community_id: str = Query("default"),
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            v.id,
            v.community_id,
            v.visit_date,
            v.visitor_name,
            v.kind,
            v.message,
            v.created_at
        FROM visits v
        WHERE v.community_id = ?
        ORDER BY v.visit_date DESC, v.created_at DESC
        """,
        (community_id,),
    )
    rows = cur.fetchall()

    # メディアを一気に取得
    ids = [r["id"] for r in rows]
    media_map = {vid: [] for vid in ids}
    if ids:
        qmarks = ",".join("?" for _ in ids)
        cur.execute(
            f"""
            SELECT visit_id, media_type, file_path
            FROM visit_media
            WHERE visit_id IN ({qmarks})
            """,
            ids,
        )
        for mr in cur.fetchall():
            media_map[mr["visit_id"]].append(
                VisitMediaOut(media_type=mr["media_type"], url=mr["file_path"])
            )

    conn.close()

    result: List[VisitOut] = []
    for r in rows:
        result.append(
            VisitOut(
                id=r["id"],
                community_id=r["community_id"],
                visit_date=r["visit_date"],
                visitor_name=r["visitor_name"],
                kind=r["kind"],
                message=r["message"],
                created_at=r["created_at"],
                media=media_map.get(r["id"], []),
            )
        )
    return result

# ---------- 寄付（感謝の気持ち） ----------

@app.post("/api/donations", response_model=DonationOut)
async def create_donation(
    visit_id: str = Form(...),
    donor_name: str = Form(""),
    amount: Optional[int] = Form(0),
    message: str = Form(""),
):
    # visit のコミュニティIDを引き継ぐ
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT community_id FROM visits WHERE id = ?", (visit_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="visit not found")
    community_id = row["community_id"]

    did = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    amt = int(amount or 0)

    cur.execute(
        """
        INSERT INTO donations (id, community_id, visit_id, donor_name, amount, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (did, community_id, visit_id, donor_name, amt, message, now),
    )
    conn.commit()
    conn.close()

    return DonationOut(
        id=did,
        community_id=community_id,
        visit_id=visit_id,
        donor_name=donor_name or None,
        amount=amt,
        message=message or None,
        created_at=now,
    )

@app.get("/api/donations", response_model=List[DonationOut])
def list_donations(
    community_id: str = Query("default"),
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, community_id, visit_id, donor_name, amount, message, created_at
        FROM donations
        WHERE community_id = ?
        ORDER BY created_at DESC
        """,
        (community_id,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        DonationOut(
            id=r["id"],
            community_id=r["community_id"],
            visit_id=r["visit_id"],
            donor_name=r["donor_name"],
            amount=r["amount"],
            message=r["message"],
            created_at=r["created_at"],
        )
        for r in rows
    ]

# ---------- 思い出の品 ----------

@app.post("/api/memories", response_model=MemoryOut)
async def create_memory(
    community_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    created_by: str = Form(""),
    media: Optional[List[UploadFile]] = File(None),
):
    mid = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memories (id, community_id, title, description, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (mid, community_id, title, description, now, created_by),
    )

    media_out: List[MemoryMediaOut] = []
    if media:
        for up in media:
            if not up.filename:
                continue
            content_type = up.content_type or ""
            mtype = "video" if content_type.startswith("video/") else "image"
            url_path = save_upload_file(up, "memory_media", prefix=mid)
            mmid = uuid.uuid4().hex
            cur.execute(
                """
                INSERT INTO memory_media (id, memory_id, media_type, file_path)
                VALUES (?, ?, ?, ?)
                """,
                (mmid, mid, mtype, url_path),
            )
            media_out.append(MemoryMediaOut(media_type=mtype, url=url_path))

    conn.commit()
    conn.close()

    return MemoryOut(
        id=mid,
        community_id=community_id,
        title=title,
        description=description,
        created_at=now,
        created_by=created_by or None,
        media=media_out,
    )

@app.get("/api/memories", response_model=List[MemoryOut])
def list_memories(
    community_id: str = Query("default"),
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, community_id, title, description, created_at, created_by
        FROM memories
        WHERE community_id = ?
        ORDER BY created_at DESC
        """,
        (community_id,),
    )
    rows = cur.fetchall()

    mids = [r["id"] for r in rows]
    media_map = {mid: [] for mid in mids}
    if mids:
        qmarks = ",".join("?" for _ in mids)
        cur.execute(
            f"""
            SELECT memory_id, media_type, file_path
            FROM memory_media
            WHERE memory_id IN ({qmarks})
            """,
            mids,
        )
        for mr in cur.fetchall():
            media_map[mr["memory_id"]].append(
                MemoryMediaOut(media_type=mr["media_type"], url=mr["file_path"])
            )

    conn.close()

    result: List[MemoryOut] = []
    for r in rows:
        result.append(
            MemoryOut(
                id=r["id"],
                community_id=r["community_id"],
                title=r["title"],
                description=r["description"],
                created_at=r["created_at"],
                created_by=r["created_by"],
                media=media_map.get(r["id"], []),
            )
        )
    return result

# ---------- 思い出の品 コメント ----------

@app.post("/api/memory_comments", response_model=MemoryCommentOut)
async def create_memory_comment(
    memory_id: str = Form(...),
    author_name: str = Form(""),
    message: str = Form(...),
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT community_id FROM memories WHERE id = ?",
        (memory_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="memory not found")
    community_id = row["community_id"]

    cid = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()

    cur.execute(
        """
        INSERT INTO memory_comments (id, community_id, memory_id, author_name, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (cid, community_id, memory_id, author_name, message, now),
    )
    conn.commit()
    conn.close()

    return MemoryCommentOut(
        id=cid,
        community_id=community_id,
        memory_id=memory_id,
        author_name=author_name or None,
        message=message,
        created_at=now,
    )

@app.get("/api/memory_comments", response_model=List[MemoryCommentOut])
def list_memory_comments(
    community_id: str = Query("default"),
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, community_id, memory_id, author_name, message, created_at
        FROM memory_comments
        WHERE community_id = ?
        ORDER BY created_at ASC
        """,
        (community_id,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        MemoryCommentOut(
            id=r["id"],
            community_id=r["community_id"],
            memory_id=r["memory_id"],
            author_name=r["author_name"],
            message=r["message"],
            created_at=r["created_at"],
        )
        for r in rows
    ]

# ---------- 故人の顔写真アップロード ----------

@app.post("/api/community_avatar")
async def upload_community_avatar(
    community_id: str = Form(...),
    photo: UploadFile = File(...),
):
    if not community_id:
        raise HTTPException(status_code=400, detail="community_id is required")
    url_path = save_community_avatar(photo, community_id)
    return {"community_id": community_id, "photo_url": url_path}
