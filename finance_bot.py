import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import aiohttp
import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Читаем конфиг из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'port': int(os.getenv("DB_PORT", 5432)),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'database': os.getenv("DB_NAME")
}
CURRENCY_SERVICE_URL = os.getenv("CURRENCY_SERVICE_URL")

# Состояния FSM
class RegistrationStates(StatesGroup):
    waiting_for_name = State()

class OperationStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_amount = State()
    waiting_for_date = State()
    waiting_for_comment = State()

class ViewOperationsStates(StatesGroup):
    waiting_for_currency = State()

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                chat_id BIGINT UNIQUE NOT NULL
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS operations (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                chat_id BIGINT NOT NULL,
                type_operation VARCHAR(10) NOT NULL CHECK (type_operation IN ('ДОХОД', 'РАСХОД')),
                comment TEXT,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id)
            )
        ''')

async def is_user_registered(chat_id: int) -> bool:
    async with db_pool.acquire() as conn:
        cnt = await conn.fetchval('SELECT COUNT(*) FROM users WHERE chat_id = $1', chat_id)
        return cnt > 0

async def get_exchange_rate(currency: str) -> Optional[float]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{CURRENCY_SERVICE_URL}?currency={currency}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('rate')
    except Exception as e:
        logging.error(f"Error getting exchange rate: {e}")
    return None

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Добро пожаловать в бота учета финансов!\n\n"
        "Доступные команды:\n"
        "/reg - Регистрация\n"
        "/add_operation - Добавить операцию\n"
        "/operations - Просмотр операций"
    )

@router.message(Command("reg"))
async def cmd_register(message: Message, state: FSMContext):
    chat_id = message.chat.id
    if await is_user_registered(chat_id):
        await message.answer("Вы уже зарегистрированы!")
        return
    await message.answer("Введите ваш логин:")
    await state.set_state(RegistrationStates.waiting_for_name)

@router.message(StateFilter(RegistrationStates.waiting_for_name))
async def process_registration(message: Message, state: FSMContext):
    name = message.text.strip()
    chat_id = message.chat.id
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO users (name, chat_id) VALUES ($1, $2)',
                name, chat_id
            )
        await message.answer("Вы успешно зарегистрированы!")
        await state.clear()
    except Exception:
        logging.exception("Registration error")
        await message.answer("Произошла ошибка при регистрации. Попробуйте еще раз.")

@router.message(Command("add_operation"))
async def cmd_add_operation(message: Message, state: FSMContext):
    chat_id = message.chat.id
    if not await is_user_registered(chat_id):
        await message.answer("Сначала необходимо зарегистрироваться! Используйте команду /reg")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="ДОХОД", callback_data="operation_type:ДОХОД"),
        InlineKeyboardButton(text="РАСХОД", callback_data="operation_type:РАСХОД"),
    ]])
    await message.answer("Выберите тип операции:", reply_markup=kb)
    await state.set_state(OperationStates.waiting_for_type)

@router.callback_query(F.data.startswith("operation_type:"))
async def process_operation_type(cq: CallbackQuery, state: FSMContext):
    op_type = cq.data.split(":", 1)[1].strip()
    await state.update_data(operation_type=op_type)
    await cq.message.edit_text(f"Выбран тип: {op_type}")
    await cq.message.answer("Введите сумму операции в рублях:")
    await state.set_state(OperationStates.waiting_for_amount)

@router.message(StateFilter(OperationStates.waiting_for_amount))
async def process_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.replace(",", "."))
        await state.update_data(amount=amt)
        await message.answer("Введите дату операции в формате ДД.MM.ГГГГ:")
        await state.set_state(OperationStates.waiting_for_date)
    except ValueError:
        await message.answer("Некорректная сумма. Введите число.")

@router.message(StateFilter(OperationStates.waiting_for_date))
async def process_date(message: Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        await state.update_data(date=d)
        await message.answer("Введите комментарий для операции:")
        await state.set_state(OperationStates.waiting_for_comment)
    except ValueError:
        await message.answer("Некорректная дата. Используйте формат ДД.MM.ГГГГ.")

@router.message(StateFilter(OperationStates.waiting_for_comment))
async def process_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text.strip()
    op_type = data['operation_type'].strip()

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO operations (date, amount, chat_id, type_operation, comment) '
                'VALUES ($1, $2, $3, $4, $5)',
                data['date'], data['amount'], message.chat.id, op_type, comment
            )
        await message.answer("Операция успешно добавлена!")
        await state.clear()
    except Exception:
        logging.exception("Add operation error")
        await message.answer("Произошла ошибка при добавлении операции.")

@router.message(Command("operations"))
async def cmd_operations(message: Message, state: FSMContext):
    chat_id = message.chat.id
    if not await is_user_registered(chat_id):
        await message.answer("Сначала необходимо зарегистрироваться! Используйте команду /reg")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="RUB", callback_data="currency:RUB"),
        InlineKeyboardButton(text="EUR", callback_data="currency:EUR"),
        InlineKeyboardButton(text="USD", callback_data="currency:USD"),
    ]])
    await message.answer("Выберите валюту для отображения операций:", reply_markup=kb)
    await state.set_state(ViewOperationsStates.waiting_for_currency)

@router.callback_query(F.data.startswith("currency:"))
async def process_currency(cq: CallbackQuery, state: FSMContext):
    curr = cq.data.split(":", 1)[1].strip()
    chat_id = cq.message.chat.id
    await cq.message.edit_text(f"Выбрана валюта: {curr}")

    rate = 1.0
    if curr in ("EUR", "USD"):
        rate = await get_exchange_rate(curr)
        if rate is None:
            await cq.message.answer("Ошибка получения курса валюты")
            await state.clear()
            return

    try:
        async with db_pool.acquire() as conn:
            ops = await conn.fetch(
                'SELECT date, amount, type_operation, comment '
                'FROM operations WHERE chat_id=$1 ORDER BY date DESC',
                chat_id
            )

        if not ops:
            await cq.message.answer("У вас пока нет операций.")
            await state.clear()
            return

        total_inc = total_exp = 0.0
        lines = [f"Ваши операции (в {curr}):\n"]
        for op in ops:
            conv = float(op["amount"]) / rate
            ds = op["date"].strftime("%d.%m.%Y")
            cm = op["comment"] or "Без комментария"
            if op["type_operation"] == "ДОХОД":
                total_inc += conv
                lines.append(f"📈 {ds} | +{conv:.2f} {curr} | {cm}")
            else:
                total_exp += conv
                lines.append(f"📉 {ds} | -{conv:.2f} {curr} | {cm}")

        bal = total_inc - total_exp
        lines.append(f"\n💰 Итого доходов: {total_inc:.2f} {curr}")
        lines.append(f"💸 Итого расходов: {total_exp:.2f} {curr}")
        lines.append(f"💵 Баланс: {bal:.2f} {curr}")

        await cq.message.answer("\n".join(lines))
        await state.clear()
    except Exception:
        logging.exception("Operations view error")
        await cq.message.answer("Произошла ошибка при получении операций.")
        await state.clear()

# Роутер и запуск
dp.include_router(router)

async def main():
    await init_db()
    logging.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())