import httpx, asyncio
async def test():
    async with httpx.AsyncClient() as client:
        r = await client.post("http://localhost:20128/v1beta/models/gemini-2.5-flash-preview-tts:generateContent", json={
            "contents": [{"parts": [{"text": "hello"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
            }
        }, headers={"Authorization": "Bearer ANY"})
        print(r.status_code)
        print(r.text[:500])
asyncio.run(test())
