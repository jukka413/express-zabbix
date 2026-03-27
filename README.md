# zabbix-bot

Телеграм-бот для eXpress, который умеет принимать сообщения извне и доставлять их пользователям по AD-логину (признак можно изменить, изменив код)

## Что умеет

- Отвечает на входящие сообщения в чате - обычный зеркальный колбэк
- По команде `zabbix` регистрирует пользователя — запоминает его AD-логин и ID чата
- Принимает HTTP-запросы извне и доставляет сообщение нужному пользователю по AD-логину
- Дубли при регистрации тихо игнорирует

## Стек

- **Python 3.12**
- **FastAPI** + **uvicorn**
- **pybotx** — SDK для работы с eXpress
- **asyncpg** — асинхронный драйвер PostgreSQL
- **pydantic-settings** — конфигурация через переменные окружения

## Быстрый старт

### 1. Переменные окружения

Создай `.env` в корне проекта:

```env
CTS_URL=https://cts.example.com
BOT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SECRET_KEY=your-secret-key

PORT=8081

DB_HOST=172.17.0.1
DB_PORT=5432
DB_NAME=zabbix_bot
DB_USER=your-db-user
DB_PASSWORD=your-db-password
```

### 2. Запуск через Docker Compose

```bash
docker compose up --build
```

### 3. Или просто docker run

```bash
docker build -t zabbix-bot .

docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  --env-file .env \
  -p 8081:8081 \
  zabbix-bot
```

## API

### Отправить сообщение пользователю

```
POST /api/send
```

```json
{
  "ad_login": "ivanov",
  "message": "Внимание: триггер сработал на хосте db-01"
}
```

AD-логин регистронезависим — `Ivanov`, `IVANOV` и `ivanov` одно и то же.

Пример через curl:

```bash
curl -X POST http://localhost:8081/api/send \
  -H "Content-Type: application/json" \
  -d '{"ad_login": "ivanov", "message": "Тревога!"}'
```

Пример через Python:

```python
import requests

requests.post(
    "http://localhost:8081/api/send",
    json={"ad_login": "ivanov", "message": "Тревога!"}
)
```

### Остальные эндпоинты

|Метод|Путь|Назначение|
|---|---|---|
|`POST`|`/command`|Webhook для входящих команд от eXpress|
|`GET`|`/status`|Статус бота для eXpress|
|`POST`|`/notification/callback`|Колбэки от BotX|

## База данных

Таблица создаётся автоматически при первом запуске:

```sql
CREATE TABLE zbx_user (
    group_chat_id TEXT,
    ad_login      TEXT NOT NULL UNIQUE
);
```

Пользователь попадает в таблицу когда пишет боту слово `zabbix`. Повторная отправка ничего не ломает — запись просто не дублируется.

## Структура проекта

```
.
├── main.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── .env          # не коммитить
```

