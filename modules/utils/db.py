from __future__ import annotations

import os
import json
import sqlite3
import threading
from typing import Optional, Dict, Any, List, Set
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join(BASE_DIR, "radha_data.db"))

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        _local.conn = conn
    return _local.conn


def _init_db():
    conn = _get_conn()
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS groups (chat_id TEXT PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS chats (chat_id TEXT PRIMARY KEY, title TEXT, username TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS users_chats (user_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS whispers (whisper_id TEXT PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS sudoers (user_id TEXT PRIMARY KEY)")
    print("✅ Local VPS SQLite Storage Initialized Successfully!")


_init_db()


# Compatibility dummies
def get_redis_client() -> None:
    return None


def get_mongo_db() -> None:
    return None


# --- CHATS & USERS TRACKING FOR BROADCAST ---

def add_chat(chat_id: int, title: Optional[str] = None, username: Optional[str] = None) -> None:
    cid = str(chat_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO chats (chat_id, title, username) VALUES (?, ?, ?)",
                (cid, title or "Telegram Group", username or "")
            )
    except Exception as e:
        print(f"Error adding chat to SQLite: {e}")


def rm_chat(chat_id: int) -> None:
    cid = str(chat_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute("DELETE FROM chats WHERE chat_id = ?", (cid,))
    except Exception as e:
        print(f"Error removing chat from SQLite: {e}")


def get_chats() -> List[int]:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM chats")
        rows = cur.fetchall()
        return [int(r[0]) for r in rows if r[0] and (r[0].startswith("-") or r[0].isdigit())]
    except Exception as e:
        print(f"Error getting chats from SQLite: {e}")
        return []


def add_user_chat(user_id: int) -> None:
    uid = str(user_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO users_chats (user_id) VALUES (?)", (uid,))
    except Exception as e:
        print(f"Error adding user chat to SQLite: {e}")


def rm_user_chat(user_id: int) -> None:
    uid = str(user_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute("DELETE FROM users_chats WHERE user_id = ?", (uid,))
    except Exception as e:
        print(f"Error removing user chat from SQLite: {e}")


def get_user_chats() -> List[int]:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users_chats")
        rows = cur.fetchall()
        return [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    except Exception as e:
        print(f"Error getting user chats from SQLite: {e}")
        return []


def _json_serial(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code (e.g. datetime)."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _sanitize_doc(data: Any) -> Any:
    """Recursively converts non-serializable objects into JSON-compatible types."""
    if isinstance(data, dict):
        return {k: _sanitize_doc(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_sanitize_doc(v) for v in data]
    elif hasattr(data, "isoformat"):
        return data.isoformat()
    return data


# --- USER DATA LOCAL LAYER ---

def db_load_user(user_id: int) -> Optional[Dict[str, Any]]:
    uid = str(user_id)
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT data FROM users WHERE user_id = ?", (uid,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        print(f"Error loading user {uid} from SQLite: {e}")
    return None


def db_save_user(user_id: int, udata: Dict[str, Any]) -> None:
    uid = str(user_id)
    try:
        udata = _sanitize_doc(udata)
        serialized = json.dumps(udata, default=_json_serial)
        conn = _get_conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO users (user_id, data) VALUES (?, ?)", (uid, serialized))
            conn.execute("INSERT OR REPLACE INTO users_chats (user_id) VALUES (?)", (uid,))
    except Exception as e:
        print(f"Error saving user {uid} to SQLite: {e}")


def warmup_redis_cache() -> None:
    """Initializes local storage if needed."""
    _init_db()


def db_load_all_users() -> Dict[str, Dict[str, Any]]:
    res: Dict[str, Dict[str, Any]] = {}
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id, data FROM users")
        for uid, data_str in cur.fetchall():
            if data_str:
                try:
                    res[str(uid)] = json.loads(data_str)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error loading all users from SQLite: {e}")
    return res


# --- SUDOERS LOCAL LAYER ---

DEFAULT_SUDOERS = {7408854697, 6605051662, 5971488185, 7810795240}


def get_owner_id() -> int:
    env_owner = os.getenv("OWNER_ID")
    if env_owner:
        try:
            return int(env_owner)
        except ValueError:
            pass
    return 7408854697


def get_all_sudoers() -> Set[int]:
    sudoers = set(DEFAULT_SUDOERS)
    sudoers.add(get_owner_id())
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM sudoers")
        for (uid,) in cur.fetchall():
            if uid and uid.isdigit():
                sudoers.add(int(uid))
    except Exception as e:
        print(f"Error loading sudoers from SQLite: {e}")
    return sudoers


def add_sudoer_to_db(user_id: int) -> None:
    DEFAULT_SUDOERS.add(user_id)
    suid = str(user_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO sudoers (user_id) VALUES (?)", (suid,))
    except Exception as e:
        print(f"Error adding sudoer to SQLite: {e}")


def remove_sudoer_from_db(user_id: int) -> None:
    if user_id in DEFAULT_SUDOERS:
        DEFAULT_SUDOERS.remove(user_id)
    suid = str(user_id)
    try:
        conn = _get_conn()
        with conn:
            conn.execute("DELETE FROM sudoers WHERE user_id = ?", (suid,))
    except Exception as e:
        print(f"Error removing sudoer from SQLite: {e}")


def is_user_sudoer(user_id: int) -> bool:
    return user_id in get_all_sudoers()


add_sudo_user = add_sudoer_to_db
rm_sudo_user = remove_sudoer_from_db


def get_sudo_users() -> List[int]:
    return list(get_all_sudoers())


is_sudo_user = is_user_sudoer


# --- GROUP SETTINGS LOCAL LAYER ---

def db_load_group(chat_id: int) -> Optional[Dict[str, Any]]:
    cid = str(chat_id)
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT data FROM groups WHERE chat_id = ?", (cid,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        print(f"Error loading group {cid} from SQLite: {e}")
    return None


def db_save_group(chat_id: int, gdata: Dict[str, Any]) -> None:
    cid = str(chat_id)
    try:
        gdata = _sanitize_doc(gdata)
        serialized = json.dumps(gdata, default=_json_serial)
        conn = _get_conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO groups (chat_id, data) VALUES (?, ?)", (cid, serialized))
            conn.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (cid, gdata.get("title", "Telegram Group")))
    except Exception as e:
        print(f"Error saving group {cid} to SQLite: {e}")


# --- WHISPERS LOCAL LAYER ---

def db_save_whisper(whisper_id: str, data: Dict[str, Any]) -> None:
    try:
        data = _sanitize_doc(data)
        serialized = json.dumps(data, default=_json_serial)
        conn = _get_conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO whispers (whisper_id, data) VALUES (?, ?)", (whisper_id, serialized))
    except Exception as e:
        print(f"Error saving whisper {whisper_id} to SQLite: {e}")


def db_load_whisper(whisper_id: str) -> Optional[Dict[str, Any]]:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT data FROM whispers WHERE whisper_id = ?", (whisper_id,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        print(f"Error loading whisper {whisper_id} from SQLite: {e}")
    return None
