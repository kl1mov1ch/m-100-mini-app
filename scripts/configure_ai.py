"""Read a credential from stdin, verify with provider, never print it."""

import asyncio
import json
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend import store, workspaces, matcher


async def main():
    print("Waiting for API credential on stdin", flush=True)
    key = getpass.getpass("API key: ").strip()
    async with httpx.AsyncClient(timeout=35) as client:
        r = await client.get(
            "https://api.deepseek.com/models",
            headers={"Authorization": "Bearer " + key},
        )
        print("Provider status:", r.status_code, flush=True)
        if r.status_code != 200:
            return
        models = [m["id"] for m in r.json()["data"]]
        chosen = next(
            (m for m in ["deepseek-flash", "deepseek-v4-flash", "deepseek-chat"] if m in models),
            None,
        )
        if not chosen:
            print("No supported economical model available")
            return
    cfg = {
        "llm_api_key": key,
        "llm_base_url": "https://api.deepseek.com",
        "llm_model": chosen,
    }
    try:
        result = await matcher.complete('Ответь JSON {"ok":true}.', "Проверка", cfg)
        if result.get("ok") is not True:
            raise ValueError()
    except Exception as error:
        print("Verification failed:", type(error).__name__)
        return
    store.init()
    workspaces.init()
    workspaces.set_shared(cfg)
    print(json.dumps({"connected": True, "model": chosen, "thinking": False, "code_first": True}))


asyncio.run(main())
