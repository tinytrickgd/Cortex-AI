import aiosqlite
import datetime

DB_PATH = "cortex.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (id TEXT PRIMARY KEY, mode TEXT DEFAULT 'default', custom_prompt TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS history 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        # New table for token tracking
        await db.execute('''CREATE TABLE IF NOT EXISTS token_usage 
            (user_id TEXT PRIMARY KEY, date TEXT, tokens INTEGER DEFAULT 0)''')
        await db.commit()

async def get_user_settings(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT mode, custom_prompt FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row if row else ("default", None)

async def update_user_mode(user_id, mode):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (id, mode) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET mode=excluded.mode", (user_id, mode))
        await db.commit()

async def add_history(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
        await db.commit()

async def get_history(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return list(reversed(rows))

async def clear_history(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM history") as c:
            msgs = (await c.fetchone())[0]
        return users, msgs

# --- NEW TOKEN FUNCTIONS ---
async def get_token_usage(user_id):
    today = datetime.date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tokens FROM token_usage WHERE user_id = ? AND date = ?", (user_id, today)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_token_usage(user_id, tokens):
    today = datetime.date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # If it's a new day, reset the tokens. If it's today, add to the total.
        await db.execute('''
            INSERT INTO token_usage (user_id, date, tokens) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
            tokens = CASE WHEN token_usage.date = excluded.date THEN token_usage.tokens + excluded.tokens ELSE excluded.tokens END,
            date = excluded.date
        ''', (user_id, today, tokens))
        await db.commit()
