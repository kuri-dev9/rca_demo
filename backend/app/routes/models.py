from fastapi import APIRouter
import httpx

from app.config import settings

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models():
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{settings.ollama_base_url}/api/tags")
        data = response.json()
        return [
            {
                "name": m["name"],
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
            }
            for m in data.get("models", [])
        ]
