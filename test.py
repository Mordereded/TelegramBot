import aiohttp
import asyncio

async def test_ping():
    async with aiohttp.ClientSession() as session:
        async with session.get("http://127.0.0.1:8000/") as resp:
            text = await resp.text()
            print("Response:", text)

asyncio.run(test_ping())