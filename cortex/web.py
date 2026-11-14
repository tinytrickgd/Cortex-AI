import os, secrets, time
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import pypdf
import io
from . import db

load_dotenv()
APP_SECRET = os.getenv("APP_SECRET")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OWNER_ID = os.getenv("BOT_OWNER_ID", "1561009085405466714")

app = FastAPI(title="Cortex AI v1.7")
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET or "fallback-secret", https_only=False, same_site="lax")
ai = AsyncOpenAI(api_key=OPENAI_API_KEY)
rate = {}

MODES = {
    "default": "You are Cortex, a helpful AI assistant.",
    "coding": "You are an expert programming assistant. Provide clean, functional code.",
    "research": "You are a research assistant. Provide factual, well-structured info.",
    "creative": "You are a creative writing assistant. Use vivid prose.",
    "cyber": "You are a defensive cybersecurity assistant. Help with hardening.",
    "game": "You are a game development assistant. Help with engines and math."
}

INDEX = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cortex AI v1.7</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#090812;color:#eee;font:16px system-ui;min-height:100vh}
main{max-width:900px;margin:6vh auto;padding:24px}.brand{color:#b78aff;letter-spacing:.2em;font-weight:900}
h1{font-size:clamp(2.5rem,8vw,5rem);margin:.15em 0}.muted{color:#aaa}
a,button{background:#7137c8;color:white;border:0;border-radius:10px;padding:12px 18px;text-decoration:none;font-weight:700;cursor:pointer}
.panel{background:#151321;border:1px solid #302640;border-radius:18px;padding:20px;margin-top:24px}
textarea{width:100%;min-height:110px;background:#0c0b13;color:white;border:1px solid #514066;border-radius:12px;padding:14px;font:inherit}
#answer{white-space:pre-wrap;line-height:1.6;margin-top:18px}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}
button:disabled{opacity:.5}footer{margin-top:32px;color:#888;font-size:13px}select{background:#0c0b13;color:white;border:1px solid #514066;border-radius:12px;padding:8px;margin-bottom:10px;}
</style></head><body><main><div class="top"><div class="brand">CORTEX / 1.7</div><div id="account" class="muted"></div></div>
<h1>Think beyond limits.</h1><p class="muted">Your creative and technical assistant.</p><div id="login"><a href="/login">Continue with Discord</a></div>
<section class="panel" id="chat" hidden>
    <div style="margin-bottom:10px;">
        <select id="mode">
            <option value="default">Default</option>
            <option value="coding">Coding</option>
            <option value="research">Research</option>
            <option value="creative">Creative</option>
            <option value="cyber">Cybersecurity</option>
            <option value="game">Game Dev</option>
        </select>
        <button id="clear" style="background:#393342;padding:8px 12px;font-size:14px;">Clear History</button>
    </div>
    <textarea id="q" maxlength="6000" placeholder="Ask Cortex anything..."></textarea>
    <p><button id="send">Send message</button> <button id="logout" style="background:#393342">Sign out</button></p>
    <div id="answer"></div>
</section>
<footer>Access restricted to mutual servers. v1.7</footer></main><script>
async function init(){let r=await fetch('/api/me');let d=await r.json();if(d.user){document.getElementById('login').hidden=true;document.getElementById('chat').hidden=false;document.getElementById('account').textContent=d.user.username;}else{document.getElementById('chat').hidden=true;}}
document.getElementById('send').onclick=async()=>{let q=document.getElementById('q').value.trim();if(!q)return;let b=document.getElementById('send'),a=document.getElementById('answer'),m=document.getElementById('mode').value;b.disabled=true;a.textContent='Thinking...';try{let r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,mode:m})});let d=await r.json();a.textContent=d.answer||d.detail||'Failed';}catch(e){a.textContent='Network error';}finally{b.disabled=false;}};
document.getElementById('clear').onclick=async()=>{await fetch('/api/clear',{method:'POST'});document.getElementById('answer').textContent='History cleared.';};
document.getElementById('logout').onclick=async()=>{await fetch('/logout',{method:'POST'});location.reload();};init();
</script></body></html>"""

def current_user(request: Request):
    user = request.session.get("user")
    if not user: raise HTTPException(401, "Sign in first.")
    return user

@app.on_event("startup")
async def startup(): await db.init_db()

@app.get("/", response_class=HTMLResponse)
async def home(): return INDEX

@app.get("/health")
async def health(): return {"ok": True, "version": "1.7"}

@app.get("/login")
async def login(request: Request):
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = {"client_id": DISCORD_CLIENT_ID, "redirect_uri": DISCORD_REDIRECT_URI, "response_type": "code", "scope": "identify guilds", "state": state}
    return RedirectResponse("https://discord.com/oauth2/authorize?" + urlencode(params))

@app.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    if not code or not state or not secrets.compare_digest(state, request.session.pop("oauth_state", "")):
        raise HTTPException(400, "Invalid state.")
    async with httpx.AsyncClient(timeout=15) as client:
        t = await client.post("https://discord.com/api/oauth2/token", data={"client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET, "grant_type": "authorization_code", "code": code, "redirect_uri": DISCORD_REDIRECT_URI}, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if t.status_code != 200: raise HTTPException(401, "Auth failed.")
        at = t.json()["access_token"]
        me = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {at}"})
        user = me.json()
        ug = await client.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {at}"})
        bg = await client.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"})
        if not ({g["id"] for g in ug.json()} & {g["id"] for g in bg.json()}):
            raise HTTPException(403, "Access Denied: Share a server with the bot.")
    request.session.clear()
    request.session["user"] = {"id": user["id"], "username": user.get("global_name") or user["username"]}
    return RedirectResponse("/", status_code=303)

@app.get("/api/me")
async def me(request: Request): return {"user": request.session.get("user")}

@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}

@app.post("/api/clear")
async def clear(request: Request):
    user = current_user(request)
    await db.clear_history(user["id"])
    return {"ok": True}

class ChatInput(BaseModel):
    message: str
    mode: str = "default"

@app.post("/api/chat")
async def chat(payload: ChatInput, request: Request):
    user = current_user(request)
    now = time.time()
    recent = [t for t in rate.get(user["id"], []) if now - t < 60]
    if len(recent) >= 10: raise HTTPException(429, "Rate limit.")
    recent.append(now); rate[user["id"]] = recent

    sys_prompt = MODES.get(payload.mode, MODES["default"])
    await db.add_history(user["id"], "user", payload.message)
    hist = await db.get_history(user["id"], 8)
    
    messages = [{"role": "system", "content": sys_prompt}]
    for r, c in hist: messages.append({"role": r, "content": c})
    
    resp = await ai.chat.completions.create(model=OPENAI_MODEL, messages=messages)
    answer = resp.choices[0].message.content or "(No text)"
    await db.add_history(user["id"], "assistant", answer)
    return {"answer": answer}
