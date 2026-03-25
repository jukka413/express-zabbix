import asyncio
import uvicorn
from contextlib import asynccontextmanager
from http import HTTPStatus
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from pybotx import (
    Bot,
    BotAccountWithSecret,
    HandlerCollector,
    IncomingMessage,
    build_command_accepted_response,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    cts_url: str         # только хост, например: cts.example.com (переменная CTS_URL в .env)
    bot_id: UUID
    secret_key: str
    port: int = 8081


settings = Settings()


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

collector = HandlerCollector()


@collector.default_message_handler
async def default_handler(message: IncomingMessage, bot: Bot) -> None:
    text = (message.body or "").strip()
    if not text:
        await bot.answer_message("йо")
        return
    await bot.answer_message(f"Ты написал: {text}")


bot = Bot(
    collectors=[collector],
    bot_accounts=[
        BotAccountWithSecret(
            id=settings.bot_id,
            cts_url=settings.cts_url,
            secret_key=settings.secret_key,
        ),
    ],
)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.startup()
    yield
    await bot.shutdown()


app = FastAPI(title="BotX backend", lifespan=lifespan)


# ---------------------------------------------------------------------------
# BotX webhook endpoints
# ---------------------------------------------------------------------------

@app.post("/command")
async def command_handler(request: Request) -> JSONResponse:
    # Fire-and-forget: BotX обрабатывает команду асинхронно
    asyncio.create_task(
        bot.async_execute_raw_bot_command(
            await request.json(),
            request_headers=request.headers,
        )
    )
    return JSONResponse(
        build_command_accepted_response(),
        status_code=HTTPStatus.ACCEPTED,
    )


@app.get("/status")
async def status_handler(request: Request) -> JSONResponse:
    status = await bot.raw_get_status(
        dict(request.query_params),
        request_headers=request.headers,
    )
    return JSONResponse(status)


@app.post("/notification/callback")
async def callback_handler(request: Request) -> JSONResponse:
    # verify_request=False: колбэки приходят из внутренней сети без подписи
    await bot.set_raw_botx_method_result(
        await request.json(),
        verify_request=False,
    )
    return JSONResponse(
        build_command_accepted_response(),
        status_code=HTTPStatus.ACCEPTED,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    chat_id: str
    message: str


@app.post("/api/send")
async def send_message_to_chat(payload: SendMessageRequest) -> JSONResponse:
    try:
        chat_id = UUID(payload.chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="chat_id must be valid UUID") from exc

    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message must not be empty")

    try:
        await bot.send_message(
            bot_id=settings.bot_id,
            chat_id=chat_id,
            body=text,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BotX error: {exc}") from exc

    return JSONResponse(
        {"status": "ok", "chat_id": str(chat_id), "message": text},
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port)
