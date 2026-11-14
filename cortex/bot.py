import os, json, logging, datetime
from pathlib import Path
from datetime import timedelta
import aiohttp, discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI
from . import db

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "1561009085405466714"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
ai = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)

ADMIN_FILE = Path("cortex_admins.json")
LOG_FILE = Path("cortex_logs.json")

def load_json(path, default):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return default
def save_json(path, data): path.write_text(json.dumps(data, indent=2))

admins = {int(k): v for k, v in load_json(ADMIN_FILE, {}).items()}
audit_logs = load_json(LOG_FILE, [])

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cortex-bot")

MODES = {
    "coding": "You are an expert programming assistant. Provide clean, functional code.",
    "research": "You are a research assistant. Provide factual info.",
    "creative": "You are a creative writing assistant.",
    "cyber": "You are a defensive cybersecurity assistant.",
    "game": "You are a game development assistant."
}

def get_level(user_id):
    if user_id == OWNER_ID: return 3
    return admins.get(user_id, 0)

def save_admins(): save_json(ADMIN_FILE, {str(k): v for k, v in admins.items()})

def log_action(actor_id, action, target, details=""):
    audit_logs.append({"time": str(datetime.datetime.now()), "actor": actor_id, "action": action, "target": str(target), "details": details})
    save_json(LOG_FILE, audit_logs[-500:])

async def level_check(interaction: discord.Interaction, required: int):
    if get_level(interaction.user.id) < required:
        raise app_commands.CheckFailure(f"Requires Level {required}. You are Level {get_level(interaction.user.id)}.")
    return True

def is_owner(): return lambda i: level_check(i, 3)
def is_senior(): return lambda i: level_check(i, 2)
def is_mod(): return lambda i: level_check(i, 1)

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    await db.init_db()
    synced = await bot.tree.sync()
    log.info("Ready as %s; synced %d commands", bot.user, len(synced))

@bot.tree.error
async def errors(i, error):
    msg = str(error) if isinstance(error, app_commands.CheckFailure) else "Command failed."
    if not isinstance(error, app_commands.CheckFailure): log.exception("Command error", exc_info=error)
    if i.response.is_done(): await i.followup.send(msg, ephemeral=True)
    else: await i.response.send_message(msg, ephemeral=True)

# --- Public AI Commands ---
@bot.tree.command(name="cortex_help", description="Show Cortex AI commands")
async def cortex_help(i: discord.Interaction):
    embed = discord.Embed(title="Cortex AI v1.7", color=discord.Color.purple())
    embed.add_field(name="/ask", value="Ask the AI a question", inline=False)
    embed.add_field(name="/cortex_mode", value="Set your AI mode", inline=False)
    embed.add_field(name="/cortex_history", value="View your last 10 messages", inline=False)
    embed.add_field(name="/cortex_clear", value="Clear your history", inline=False)
    await i.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ask", description="Ask Cortex a question")
async def ask(i: discord.Interaction, question: str):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        mode, custom = await db.get_user_settings(str(i.user.id))
        sys_prompt = MODES.get(mode, "You are Cortex, a helpful AI assistant.")
        if custom: sys_prompt += f"\nUser instructions: {custom}"
        
        await db.add_history(str(i.user.id), "user", question)
        history = await db.get_history(str(i.user.id), 6)
        
        messages = [{"role": "system", "content": sys_prompt}]
        for r, c in history: messages.append({"role": r, "content": c})
        
        r = await ai.chat.completions.create(model=MODEL, messages=messages)
        answer = r.choices[0].message.content or "No response."
        await db.add_history(str(i.user.id), "assistant", answer)
        
        for start in range(0, len(answer), 1900):
            await i.followup.send(answer[start:start+1900], ephemeral=True)
    except Exception as e:
        await i.followup.send(f"AI Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="cortex_mode", description="Set your AI mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="Default", value="default"),
    app_commands.Choice(name="Coding", value="coding"),
    app_commands.Choice(name="Research", value="research"),
    app_commands.Choice(name="Creative", value="creative"),
    app_commands.Choice(name="Cybersecurity", value="cyber"),
    app_commands.Choice(name="Game Dev", value="game"),
])
async def cortex_mode(i: discord.Interaction, mode: app_commands.Choice[str]):
    await db.update_user_mode(str(i.user.id), mode.value)
    await i.response.send_message(f"Mode set to **{mode.name}**.", ephemeral=True)

@bot.tree.command(name="cortex_history", description="View your recent history")
async def cortex_history(i: discord.Interaction):
    hist = await db.get_history(str(i.user.id), 10)
    if not hist: return await i.response.send_message("No history.", ephemeral=True)
    out = "\n".join([f"**{r}:** {c[:100]}..." for r, c in hist])
    await i.response.send_message(out[:2000], ephemeral=True)

@bot.tree.command(name="cortex_clear", description="Clear your history")
async def cortex_clear(i: discord.Interaction):
    await db.clear_history(str(i.user.id))
    await i.response.send_message("History cleared.", ephemeral=True)

@bot.tree.command(name="cortex_stats", description="Bot statistics")
async def cortex_stats(i: discord.Interaction):
    u, m = await db.get_stats()
    await i.response.send_message(f"**Cortex Stats**\nUsers: {u}\nMessages: {m}\nGuilds: {len(bot.guilds)}", ephemeral=True)

# --- Admin Commands (Hidden from non-admins) ---
@bot.tree.command(name="admin_grant", description="Owner: grant admin level (1=Mod, 2=Senior)")
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_owner())
async def admin_grant(i: discord.Interaction, member: discord.Member, level: app_commands.Range[int, 1, 2]):
    admins[member.id] = level
    save_admins()
    log_action(i.user.id, "admin_grant", member.id, f"Level {level}")
    await i.response.send_message(f"Granted Level {level} to {member.mention}.", ephemeral=True)

@bot.tree.command(name="admin_logs", description="View recent audit logs")
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_senior())
async def admin_logs(i: discord.Interaction):
    if not audit_logs: return await i.response.send_message("No logs.", ephemeral=True)
    out = "\n".join([f"[{l['time'][:16]}] <@{l['actor']}> {l['action']} {l['target']}" for l in audit_logs[-10:]])
    await i.response.send_message(f"**Logs**\n{out}", ephemeral=True)

@bot.tree.command(name="purge", description="Delete recent messages")
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_mod())
async def purge(i: discord.Interaction, amount: app_commands.Range[int,1,100]):
    await i.response.defer(ephemeral=True)
    deleted = await i.channel.purge(limit=amount)
    await i.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

# --- The God Mode Command ---
@bot.tree.command(name="admin_ai", description="Tell the AI to execute an action on the server")
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_senior())
async def admin_ai(i: discord.Interaction, instruction: str):
    await i.response.defer(ephemeral=True, thinking=True)
    
    sys_prompt = """You are an AI server administrator. Convert the user's instruction into a JSON object. 
    Available actions:
    {"action": "create_channel", "name": "channel-name", "type": "text"}
    {"action": "create_role", "name": "role-name", "color": "hex_code_without_hash"}
    {"action": "rename_server", "name": "new-server-name"}
    {"action": "set_nickname", "user_id": "12345", "nickname": "new-nick"}
    
    Output ONLY raw JSON, no markdown, no extra text. Example: {"action": "create_channel", "name": "gaming", "type": "text"}"""
    
    try:
        r = await ai.chat.completions.create(
            model=MODEL, 
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": instruction}],
            response_format={ "type": "json_object" }
        )
        cmd = json.loads(r.choices[0].message.content)
        action = cmd.get("action")
        
        if action == "create_channel":
            c = await i.guild.create_text_channel(name=cmd["name"])
            await i.followup.send(f"Created channel {c.mention}.", ephemeral=True)
        elif action == "create_role":
            role = await i.guild.create_role(name=cmd["name"], color=discord.Color(int(cmd.get("color", "000000"), 16)))
            await i.followup.send(f"Created role {role.name}.", ephemeral=True)
        elif action == "rename_server":
            await i.guild.edit(name=cmd["name"])
            await i.followup.send(f"Renamed server to {cmd['name']}.", ephemeral=True)
        elif action == "set_nickname":
            member = await i.guild.fetch_member(int(cmd["user_id"]))
            await member.edit(nick=cmd["nickname"])
            await i.followup.send(f"Changed {member.name}'s nickname to {cmd['nickname']}.", ephemeral=True)
        else:
            await i.followup.send(f"Unknown action generated: {action}", ephemeral=True)
            
        log_action(i.user.id, "admin_ai", "server", instruction)
    except Exception as e:
        await i.followup.send(f"God Mode Error: {str(e)}", ephemeral=True)

# NOTE: bot.run(TOKEN) is REMOVED so main.py can start both apps.
