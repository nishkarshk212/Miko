import os
import json
import sqlite3
import pymongo
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb+srv://lily_music:Nishkarsh123@lilymusic.3bdrl7s.mongodb.net/?appName=lilymusic"
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "radha_data.db")


def sanitize_doc(data):
    if isinstance(data, dict):
        return {k: sanitize_doc(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_doc(v) for v in data]
    elif hasattr(data, "isoformat"):
        return data.isoformat()
    return data


def export():
    print(f"Connecting to MongoDB...")
    client = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    mongo_db = client.get_database("miko_bot")

    print(f"Opening SQLite database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, data TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS groups (chat_id TEXT PRIMARY KEY, data TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS chats (chat_id TEXT PRIMARY KEY, title TEXT, username TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users_chats (user_id TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS whispers (whisper_id TEXT PRIMARY KEY, data TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sudoers (user_id TEXT PRIMARY KEY)")
    conn.commit()

    # 1. Users
    user_count = 0
    for doc in mongo_db.users.find({}):
        uid = str(doc.pop("_id", None))
        if uid:
            doc = sanitize_doc(doc)
            cur.execute("INSERT OR REPLACE INTO users (user_id, data) VALUES (?, ?)", (uid, json.dumps(doc)))
            user_count += 1
    print(f"Migrated {user_count} users.")

    # 2. Groups
    grp_count = 0
    for doc in mongo_db.groups.find({}):
        gid = str(doc.pop("_id", None))
        if gid:
            doc = sanitize_doc(doc)
            cur.execute("INSERT OR REPLACE INTO groups (chat_id, data) VALUES (?, ?)", (gid, json.dumps(doc)))
            grp_count += 1
    print(f"Migrated {grp_count} groups.")

    # 3. Chats
    chat_count = 0
    for doc in mongo_db.chats.find({}):
        cid = str(doc.get("chat_id") or doc.get("_id"))
        title = doc.get("title", "")
        uname = doc.get("username", "")
        if cid:
            cur.execute("INSERT OR REPLACE INTO chats (chat_id, title, username) VALUES (?, ?, ?)", (cid, title, uname))
            chat_count += 1
    print(f"Migrated {chat_count} chats.")

    # 4. User Chats
    uc_count = 0
    for doc in mongo_db.users_chats.find({}):
        uid = str(doc.get("user_id") or doc.get("_id"))
        if uid:
            cur.execute("INSERT OR REPLACE INTO users_chats (user_id) VALUES (?)", (uid,))
            uc_count += 1
    print(f"Migrated {uc_count} user chats.")

    # 5. Whispers
    w_count = 0
    for doc in mongo_db.whispers.find({}):
        wid = str(doc.pop("_id", None))
        if wid:
            doc = sanitize_doc(doc)
            cur.execute("INSERT OR REPLACE INTO whispers (whisper_id, data) VALUES (?, ?)", (wid, json.dumps(doc)))
            w_count += 1
    print(f"Migrated {w_count} whispers.")

    # 6. Sudoers
    s_count = 0
    for doc in mongo_db.sudoers.find({}):
        suid = str(doc.get("user_id") or doc.get("_id"))
        if suid:
            cur.execute("INSERT OR REPLACE INTO sudoers (user_id) VALUES (?)", (suid,))
            s_count += 1
    print(f"Migrated {s_count} sudoers.")

    conn.commit()
    conn.close()
    print("✅ All data successfully exported to SQLite!")


if __name__ == "__main__":
    export()
