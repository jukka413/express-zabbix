import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from http import HTTPStatus
from uuid import UUID

import asyncpg
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    cts_url: str
    bot_id: UUID
    secret_key: str
    port: int = 8081

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "zabbix_bot"
    db_user: str
    db_password: str


settings = Settings()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized")
    return db_pool


async def init_db(pool: asyncpg.Pool) -> None:
    """Создаёт таблицу если её ещё нет."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS zbx_user (
            group_chat_id TEXT,
            ad_login    TEXT NOT NULL UNIQUE
        )
    """)


async def save_user(pool: asyncpg.Pool, ad_login: str, group_chat_id: str) -> bool:
    """
    Сохраняет пользователя. Возвращает True если запись добавлена,
    False если уже существует (ON CONFLICT DO NOTHING).
    """
    result = await pool.execute(
        """
        INSERT INTO zbx_user (ad_login, group_chat_id)
        VALUES ($1, $2)
        ON CONFLICT (ad_login) DO NOTHING
        """,
        ad_login,
        group_chat_id,
    )
    # asyncpg возвращает строку вида "INSERT 0 1" или "INSERT 0 0"
    return result.endswith("1")


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

collector = HandlerCollector()


@collector.default_message_handler
async def default_handler(message: IncomingMessage, bot: Bot) -> None:
    text = (message.body or "").strip().lower()

    if text == "zabbix":
        ad_login = message.sender.ad_login
        group_chat_id = str(message.chat.id)

        if not ad_login:
            await bot.answer_message("Не удалось получить ваш AD-логин.")
            return

        pool = await get_pool()
        inserted = await save_user(pool, ad_login, group_chat_id)

        if inserted:
            await bot.answer_message(f"✅ Вы зарегистрированы: {ad_login}")
        else:
            await bot.answer_message(f"ℹ️ Вы уже зарегистрированы: {ad_login}")
        return

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
    global db_pool
    db_pool = await asyncpg.create_pool(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        min_size=2,
        max_size=10,
    )
    await init_db(db_pool)
    logger.info("Database pool created")

    await bot.startup()
    yield

    await bot.shutdown()
    await db_pool.close()
    logger.info("Database pool closed")


app = FastAPI(title="BotX backend", lifespan=lifespan)


# ---------------------------------------------------------------------------
# BotX webhook endpoints
# ---------------------------------------------------------------------------

@app.post("/command")
async def command_handler(request: Request) -> JSONResponse:
    # async_execute_raw_bot_command запускает задачу внутри себя, не возвращает корутину
    bot.async_execute_raw_bot_command(
        await request.json(),
        request_headers=request.headers,
    )
    return JSONResponse(
        build_command_accepted_response(),
        status_code=HTTPStatus.ACCEPTED,
    )


@app.get("/status")
async def status_handler(request: Request) -> JSONResponse:
    try:
        status = await bot.raw_get_status(
            dict(request.query_params),
            request_headers=request.headers,
            verify_request=False,
        )
    except ValueError:
        # Запрос без обязательных параметров (например healthcheck) — возвращаем 200
        return JSONResponse({"status": "ok"})
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
