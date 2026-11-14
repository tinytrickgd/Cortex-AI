import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from cortex.web import app
from cortex.bot import bot, TOKEN

async def run_bot():
    try:
        await bot.start(TOKEN)
    except Exception as e:
        print(f"Bot crashed: {e}")
        await bot.close()

async def run_web():
    port = int(os.getenv("PORT", 10000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    # add a safe shutdown if Render stops the server
    try:
        await asyncio.gather(run_web(), run_bot())
    except asyncio.CancelledError:
        print("Shutting down safely...")
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
