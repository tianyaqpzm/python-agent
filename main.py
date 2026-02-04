import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.core.lifecycle import lifespan
from app.api.routers import chat

app = FastAPI(lifespan=lifespan)
app.include_router(chat.router, tags=["chat"])


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
