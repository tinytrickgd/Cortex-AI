import asyncio
import os
import uvicorn
from cortex.web import app
from cortex.bot import bot, TOKEN

async def run_bot():
    # starts the discord bot without blocking the thread
    await bot.start(TOKEN)

async def run_web():
    # starts the fastapi server on render's assigned port
    port = int(os.getenv("PORT", 10000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    # run both at the same time
    await asyncio.gather(run_web(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())