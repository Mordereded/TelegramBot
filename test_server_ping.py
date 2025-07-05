import aiohttp
import asyncio

async def test_ping():
    url = "https://telegrambotaccountdota-z6xi.onrender.com/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            text = await resp.text()
            print("Response status:", resp.status)
            print("Response body:", text)

asyncio.run(test_ping())