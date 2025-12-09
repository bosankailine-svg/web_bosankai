# main.py
#
# 「みんなの墓参会」用 API サーバ
# - /ping
# - /api/visits          墓参記録（複数写真・動画対応）
# - /api/donations       寄付メモ
# - /api/memories        思い出の品
# - /api/memory_comments 思い出の品へのコメント
#
# 事前に:
#   pip install fastapi "uvicorn[standard]" python-multipart
#
# ローカル起動:
#   uvicorn main:app --reload

import os
import uuid
import sqlite3
import json
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = "bosankai.db"
UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)


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

  # 寄付メモ
  cur.execute(
    """
    CREATE TABLE IF NOT EXISTS donations (
      id TEXT PRIMARY KEY,
      community_id TEXT,
      visit_id TEXT NOT NULL,
      donor_name TEXT,
      amount INTEGER NOT NULL,
      message TEXT,
      created_at TEXT NOT NULL
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
      created_by TEXT,
      media_paths TEXT,
      created_at TEXT NOT NULL
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
      created_at TEXT NOT NULL
    )
    """
  )

  # 既存DBに media_paths や community_id 列が無かった場合に追加
  def ensure_column(table: str, col_name: str, col_type: str):
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r["name"] for r in cur.fetchall()]
    if col_name not in cols:
      cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")

  ensure_column("visits", "media_paths", "TEXT")
  ensure_column("donations", "community_id", "TEXT")

  conn.commit()
  conn.close()


init_db()

# ==== モデル ====


class MediaItem(BaseModel):
  url: str
  media_type: str  # "image" or "video"


class VisitLog(BaseModel):
  id: str
  community_id: str
  visit_date: str
  visitor_name: str
  kind: str
  message: Optional[str] = None
  media: List[MediaItem]
  created_at: str


class Donation(BaseModel):
  id: str
  community_id: Optional[str]
  visit_id: str
  donor_name: Optional[str] = None
  amount: int
  message: Optional[str] = None
  created_at: str


class MemoryItem(BaseModel):
  id: str
  community_id: str
  title: str
  description: Optional[str] = None
  created_by: Optional[str] = None
  media: List[MediaItem]
  created_at: str


class MemoryComment(BaseModel):
  id: str
  community_id: str
  memory_id: str
  author_name: Optional[str] = None
  message: str
  created_at: str


# ==== FastAPI 本体 ====


app = FastAPI()

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def build_media_list(media_paths: Optional[str]) -> List[MediaItem]:
  if not media_paths:
    return []
  try:
    names = json.loads(media_paths)
  except Exception:
    names = []
  items: List[MediaItem] = []
  for name in names:
    if not name:
      continue
    ext = os.path.splitext(name)[1].lower()
    media_type = "video" if ext in [".mp4", ".mov", ".webm", ".m4v", ".avi"] else "image"
    items.append(
      MediaItem(
        url=f"/uploads/{name}",
        media_type=media_type,
      )
    )
  return items


async def save_files(files: Optional[List[UploadFile]], prefix: str) -> str:
  """
  複数ファイルを保存して、ファイル名リストを JSON 文字列で返す
  """
  if not files:
    return json.dumps([])
  names: List[str] = []
  for f in files:
    if not f or not f.filename:
      continue
    ext = os.path.splitext(f.filename)[1].lower()
    if not ext:
      ext = ".bin"
    file_id = f"{prefix}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, file_id)
    data = await f.read()
    with open(path, "wb") as out:
      out.write(data)
    names.append(file_id)
  return json.dumps(names)


@app.get("/ping")
def ping():
  return {"status": "ok"}


# ==== 墓参記録 ====


@app.get("/api/visits", response_model=List[VisitLog])
def list_visits(community_id: str = "default"):
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
    """
    SELECT id, community_id, visit_date, visitor_name,
           kind, message, media_paths, created_at
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
    media = build_media_list(r["media_paths"] if "media_paths" in r.keys() else None)
    result.append(
      VisitLog(
        id=r["id"],
        community_id=r["community_id"],
        visit_date=r["visit_date"],
        visitor_name=r["visitor_name"],
        kind=r["kind"],
        message=r["message"],
        media=media,
        created_at=r["created_at"],
      )
    )
  return result


@app.post("/api/visits", response_model=VisitLog)
async def create_visit(
  visit_date: str = Form(...),
  visitor_name: str = Form(...),
  kind: str = Form("visit"),
  message: Optional[str] = Form(None),
  community_id: str = Form("default"),
  media: Optional[List[UploadFile]] = File(None),
):
  visit_id = str(uuid.uuid4())
  created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  media_paths = await save_files(media, "visit")

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
    """
    INSERT INTO visits (
      id, community_id, visit_date, visitor_name,
      kind, message, media_paths, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
      visit_id,
      community_id,
      visit_date,
      visitor_name,
      kind,
      message,
      media_paths,
      created_at,
    ),
  )
  conn.commit()
  conn.close()

  media_list = build_media_list(media_paths)

  return VisitLog(
    id=visit_id,
    community_id=community_id,
    visit_date=visit_date,
    visitor_name=visitor_name,
    kind=kind,
    message=message,
    media=media_list,
    created_at=created_at,
  )


# ==== 寄付メモ ====


@app.get("/api/donations", response_model=List[Donation])
def list_donations(community_id: str = "default"):
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
  conn = get_conn()
  cur = conn.cursor()

  # visit から community_id を取得
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


# ==== 思い出の品 ====


@app.get("/api/memories", response_model=List[MemoryItem])
def list_memories(community_id: str = "default"):
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
    """
    SELECT id, community_id, title, description, created_by, media_paths, created_at
    FROM memories
    WHERE community_id = ?
    ORDER BY created_at DESC
    """,
    (community_id,),
  )
  rows = cur.fetchall()
  conn.close()

  result: List[MemoryItem] = []
  for r in rows:
    media = build_media_list(r["media_paths"])
    result.append(
      MemoryItem(
        id=r["id"],
        community_id=r["community_id"],
        title=r["title"],
        description=r["description"],
        created_by=r["created_by"],
        media=media,
        created_at=r["created_at"],
      )
    )
  return result


@app.post("/api/memories", response_model=MemoryItem)
async def create_memory(
  title: str = Form(...),
  description: Optional[str] = Form(None),
  community_id: str = Form("default"),
  created_by: Optional[str] = Form(None),
  media: Optional[List[UploadFile]] = File(None),
):
  memory_id = str(uuid.uuid4())
  created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  media_paths = await save_files(media, "memory")

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
    """
    INSERT INTO memories (
      id, community_id, title, description, created_by, media_paths, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    (
      memory_id,
      community_id,
      title,
      description,
      created_by,
      media_paths,
      created_at,
    ),
  )
  conn.commit()
  conn.close()

  media_list = build_media_list(media_paths)

  return MemoryItem(
    id=memory_id,
    community_id=community_id,
    title=title,
    description=description,
    created_by=created_by,
    media=media_list,
    created_at=created_at,
  )


@app.get("/api/memory_comments", response_model=List[MemoryComment])
def list_memory_comments(community_id: str = "default"):
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

  result: List[MemoryComment] = []
  for r in rows:
    result.append(
      MemoryComment(
        id=r["id"],
        community_id=r["community_id"],
        memory_id=r["memory_id"],
        author_name=r["author_name"],
        message=r["message"],
        created_at=r["created_at"],
      )
    )
  return result


@app.post("/api/memory_comments", response_model=MemoryComment)
def create_memory_comment(
  memory_id: str = Form(...),
  author_name: Optional[str] = Form(None),
  message: str = Form(...),
):
  conn = get_conn()
  cur = conn.cursor()

  # memory から community_id を取得
  cur.execute("SELECT community_id FROM memories WHERE id = ?", (memory_id,))
  row = cur.fetchone()
  if row is None:
    conn.close()
    raise HTTPException(status_code=400, detail="対象の思い出が見つかりません。")

  community_id = row["community_id"]
  comment_id = str(uuid.uuid4())
  created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  cur.execute(
    """
    INSERT INTO memory_comments (
      id, community_id, memory_id, author_name, message, created_at
    ) VALUES (?, ?, ?, ?, ?, ?)
    """,
    (
      comment_id,
      community_id,
      memory_id,
      author_name,
      message,
      created_at,
    ),
  )
  conn.commit()
  conn.close()

  return MemoryComment(
    id=comment_id,
    community_id=community_id,
    memory_id=memory_id,
    author_name=author_name,
    message=message,
    created_at=created_at,
  )
