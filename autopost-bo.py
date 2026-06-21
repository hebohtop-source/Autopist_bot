import asyncio
import random
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

from telethon import TelegramClient, errors
from telethon.tl.functions.messages import SearchGlobalRequest, ImportChatInviteRequest
from telethon.tl.types import InputMessagesFilterEmpty
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# ===== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) =====
BOT_TOKEN = "8864019564:AAEdfy6VHruk4HjXXc4zqHIYiLhvD4CIHvg"  # Токен от @BotFather
ADMIN_ID = 5871588845  # Твой Telegram ID

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

CHANNEL_USERNAME = "fgeuwuxhe"  # Твой канал (без @)

SESSIONS_DIR = "sessions"
DATA_FILE = "chats_db.json"
WARMUP_DAYS = 3
MIN_CHATS_BEFORE_SPAM = 10

# ===== КЛЮЧЕВЫЕ СЛОВА =====
SEARCH_KEYWORDS = [
    "куколд", "cuckold", "cuck", "измена", "рогоносец",
    "шлюха", "проститутка", "whore", "slut", "bitch",
    "свингер", "swinger", "оргия", "group sex",
    "18+", "adult", "nsfw", "порно", "sex", "секс",
    "знакомства для взрослых", "взрослый контент",
    "bdsm", "госпожа", "раб", "домина",
    "школьницы", "шкoльниц", "teen", "young"
]

VIDEO_KEYWORDS = [
    "шкoльниц", "студенток", "куколд", "шлюх", "свингеров",
    "госпож", "рабов", "нимфеток", "молодых", "групповух"
]

def generate_spam_message():
    keyword = random.choice(VIDEO_KEYWORDS)
    templates = [
        f"Видео {keyword} и не только - t.me/{CHANNEL_USERNAME}",
        f"Слив {keyword} бесплатно - t.me/{CHANNEL_USERNAME}",
        f"Эксклюзив: {keyword} без цензуры - t.me/{CHANNEL_USERNAME}",
        f"Смотреть {keyword} онлайн - t.me/{CHANNEL_USERNAME}",
        f"Топ {keyword} за сегодня - t.me/{CHANNEL_USERNAME}",
        f"Полный слив {keyword} - t.me/{CHANNEL_USERNAME}",
        f"Сборник {keyword} без рекламы - t.me/{CHANNEL_USERNAME}",
        f"Лучшее {keyword} в Telegram - t.me/{CHANNEL_USERNAME}",
        f"Порно-архив {keyword} - t.me/{CHANNEL_USERNAME}",
        f"Секретный архив {keyword} - t.me/{CHANNEL_USERNAME}"
    ]
    return random.choice(templates)

# ===== ИНИЦИАЛИЗАЦИЯ =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

Path(SESSIONS_DIR).mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

accounts: Dict[str, dict] = {}
chats_db: Dict[int, dict] = {}
flood_stats = {"total": 0, "last": None, "by_account": {}}

def load_db():
    global chats_db
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            chats_db = {int(k): v for k, v in data.items()}
        logger.info(f"Загружено {len(chats_db)} чатов")

def save_db():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(chats_db, f, ensure_ascii=False, indent=2)

load_db()

# ===== УВЕДОМЛЕНИЯ =====
async def notify_admin(text: str, error: bool = False):
    try:
        emoji = "⚠️" if error else "📨"
        await bot.send_message(ADMIN_ID, f"{emoji} {text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Не отправить уведомление: {e}")

# ===== БАЗА ЧАТОВ =====
def get_free_chats(phone: str, limit: int = 10) -> List[int]:
    my_chats = set()
    for cid, data in chats_db.items():
        if phone in data.get("accounts", []):
            my_chats.add(cid)
    free = []
    for cid in list(chats_db.keys()):
        if cid not in my_chats:
            free.append((cid, len(chats_db[cid].get("accounts", []))))
    free.sort(key=lambda x: x[1])
    return [cid for cid, _ in free[:limit]]

def add_chat_to_db(chat_id: int, title: str, phone: str):
    if chat_id not in chats_db:
        chats_db[chat_id] = {"title": title, "accounts": []}
    if phone not in chats_db[chat_id]["accounts"]:
        chats_db[chat_id]["accounts"].append(phone)
        save_db()

def remove_chat_from_account(phone: str, chat_id: int):
    if phone in accounts and chat_id in accounts[phone].get("chats", []):
        accounts[phone]["chats"].remove(chat_id)
    if chat_id in chats_db and phone in chats_db[chat_id]["accounts"]:
        chats_db[chat_id]["accounts"].remove(phone)
        if not chats_db[chat_id]["accounts"]:
            del chats_db[chat_id]
        save_db()

# ===== ПОИСК И ВСТУПЛЕНИЕ =====
async def search_chats(client, limit: int = 3):
    found = []
    seen = set()
    for kw in SEARCH_KEYWORDS:
        try:
            res = await client(SearchGlobalRequest(q=kw, filter=InputMessagesFilterEmpty(), offset_id=0, add_offset=0, limit=limit))
            for msg in res.messages:
                if msg.chat_id and msg.chat_id not in seen:
                    try:
                        chat = await client.get_entity(msg.chat_id)
                        if hasattr(chat, 'title') and chat.title:
                            seen.add(msg.chat_id)
                            found.append({"id": msg.chat_id, "title": chat.title, "link": f"https://t.me/{chat.username}" if hasattr(chat, 'username') and chat.username else None})
                    except:
                        pass
            await asyncio.sleep(0.5)
        except:
            pass
    return found

async def join_chats(client, chats: List[dict], phone: str):
    joined = []
    free_chat_ids = set(get_free_chats(phone, len(chats)))
    for chat in chats:
        if chat["id"] not in free_chat_ids:
            continue
        try:
            if chat.get("link"):
                if "+" in chat["link"]:
                    await client(ImportChatInviteRequest(chat["link"].split("+")[1]))
                else:
                    await client.join_channel(chat["link"].split("t.me/")[1])
            else:
                await client.join_channel(chat["id"])
            add_chat_to_db(chat["id"], chat["title"], phone)
            joined.append(chat["id"])
            if phone in accounts and chat["id"] not in accounts[phone].get("chats", []):
                accounts[phone]["chats"].append(chat["id"])
            await asyncio.sleep(random.randint(5, 15))
        except Exception as e:
            logger.error(f"Ошибка вступления {phone}: {e}")
    return joined

# ===== РАССЫЛКА =====
async def send_spam(client, chat_ids: List[int], phone: str):
    sent = 0
    floods = 0
    for cid in chat_ids:
        try:
            if phone not in accounts or cid not in accounts[phone].get("chats", []):
                continue
            await client.send_message(cid, generate_spam_message())
            sent += 1
            await asyncio.sleep(random.randint(30, 90))
        except errors.FloodWaitError as e:
            floods += 1
            flood_stats["total"] += 1
            flood_stats["last"] = datetime.now()
            flood_stats["by_account"][phone] = flood_stats["by_account"].get(phone, 0) + 1
            await notify_admin(f"🚫 **СПАМ-БЛОК!**\nАккаунт: `{phone}`\nЖдать: `{e.seconds}` сек", error=True)
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"Ошибка отправки {phone}: {e}")
            if "not found" in str(e).lower() or "left" in str(e).lower():
                remove_chat_from_account(phone, cid)
    return sent, floods

# ===== ПРОГРЕВ =====
async def warmup(client, phone: str):
    await notify_admin(f"🔥 **Прогрев** `{phone}` начат!")
    try:
        me = await client.get_me()
        logger.info(f"Прогрев {phone} - {me.first_name}")
    except:
        return False
    try:
        dialogs = await client.get_dialogs()
    except:
        dialogs = []
    if len(dialogs) < 3:
        for chat in ["durov", "telegram"]:
            try:
                await client.join_channel(chat)
                await asyncio.sleep(5)
            except:
                pass
    # День 1
    logger.info(f"{phone}: День 1/3")
    chats = await search_chats(client, 2)
    if chats:
        joined = await join_chats(client, chats, phone)
        await notify_admin(f"📅 День 1/3 для `{phone}`: вступил в `{len(joined)}` чатов")
    for dialog in dialogs[:10]:
        try:
            await dialog.get_messages(limit=2)
            await asyncio.sleep(random.randint(20, 60))
        except:
            pass
    await asyncio.sleep(12 * 3600)
    # День 2
    logger.info(f"{phone}: День 2/3")
    chats = await search_chats(client, 3)
    if chats:
        joined = await join_chats(client, chats, phone)
        await notify_admin(f"📅 День 2/3 для `{phone}`: +{len(joined)} чатов")
    sent = 0
    for dialog in dialogs[:5]:
        if sent >= 2:
            break
        if dialog.is_user and not dialog.is_bot:
            try:
                await client.send_message(dialog.id, "Привет! Как дела? 😊")
                sent += 1
                await asyncio.sleep(random.randint(60, 180))
            except:
                pass
    await asyncio.sleep(12 * 3600)
    # День 3
    logger.info(f"{phone}: День 3/3")
    chats = await search_chats(client, 4)
    if chats:
        joined = await join_chats(client, chats, phone)
        await notify_admin(f"📅 День 3/3 для `{phone}`: +{len(joined)} чатов")
    for dialog in dialogs[:5]:
        if dialog.is_group or dialog.is_channel:
            try:
                msgs = await dialog.get_messages(limit=3)
                for msg in msgs:
                    try:
                        await client.send_reaction(dialog.id, msg.id, ["👍"])
                        await asyncio.sleep(random.randint(15, 45))
                    except:
                        pass
            except:
                pass
    total = len(accounts.get(phone, {}).get("chats", []))
    await notify_admin(f"✅ **Прогрев** `{phone}` завершён! Чатов: `{total}`")
    return True

# ===== ФОНОВЫЙ ПРОЦЕСС =====
async def worker(phone: str):
    data = accounts.get(phone)
    if not data:
        return
    client = data["client"]
    if not data.get("warmed_up"):
        if await warmup(client, phone):
            data["warmed_up"] = True
            data["warmup_date"] = datetime.now()
    await notify_admin(f"▶️ **Запущен** `{phone}` (чатов: {len(data.get('chats', []))})")
    while data.get("is_active", False):
        try:
            if len(data.get("chats", [])) < MIN_CHATS_BEFORE_SPAM:
                chats = await search_chats(client, 3)
                if chats:
                    joined = await join_chats(client, chats, phone)
                    await notify_admin(f"🔍 `{phone}`: +{len(joined)} чатов")
            last = data.get("last_spam")
            if not last or (datetime.now() - last).seconds >= 3600:
                if data.get("chats"):
                    target = random.sample(data["chats"], min(20, len(data["chats"])))
                    sent, floods = await send_spam(client, target, phone)
                    data["last_spam"] = datetime.now()
                    if sent:
                        await notify_admin(f"📤 **Рассылка** `{phone}`\nОтправлено: `{sent}` | Блоков: `{floods}`")
                else:
                    logger.info(f"{phone}: нет чатов")
            await asyncio.sleep(600)
        except Exception as e:
            logger.error(f"{phone}: ошибка {e}")
            await asyncio.sleep(300)

# ===== КОМАНДЫ БОТА =====
@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("❌ Доступ запрещён")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("➕ Добавить аккаунт", callback_data="add")],
        [InlineKeyboardButton("🔥 Прогреть", callback_data="warmup")],
        [InlineKeyboardButton("▶️ Запустить", callback_data="start")],
        [InlineKeyboardButton("⏹️ Остановить", callback_data="stop")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("📋 Чаты в базе", callback_data="chats")],
        [InlineKeyboardButton("🚫 Блокировки", callback_data="flood")],
        [InlineKeyboardButton("🧪 Тест", callback_data="test")]
    ])
    total_account_chats = sum(len(acc.get("chats", [])) for acc in accounts.values())
    await msg.answer(
        f"🎬 **Бот для продвижения**\n\n"
        f"📌 Канал: t.me/{CHANNEL_USERNAME}\n"
        f"👥 Аккаунтов: {len(accounts)}\n"
        f"📊 Чатов в базе: {len(chats_db)}\n"
        f"📊 Чатов у аккаунтов: {total_account_chats}\n"
        f"🚫 Блоков: {flood_stats['total']}\n\n"
        f"1️⃣ Добавь аккаунт (номер + код)\n"
        f"2️⃣ Нажми 'Прогреть' (3 дня)\n"
        f"3️⃣ Нажми 'Запустить'",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query()
async def cb_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет прав")
    await call.answer()
    if call.data == "add":
        await call.message.answer("📱 Введи номер: `+79001234567`", parse_mode="Markdown")
        dp["waiting_phone"] = True
    elif call.data == "warmup":
        if not accounts:
            return await call.message.answer("❌ Нет аккаунтов")
        await call.message.answer("🔥 Запускаю прогрев всех аккаунтов...")
        for phone, data in accounts.items():
            if not data.get("warmed_up"):
                asyncio.create_task(warmup(data["client"], phone))
                await asyncio.sleep(1)
        await call.message.answer("✅ Прогрев запущен! Следи за уведомлениями")
    elif call.data == "start":
        started = 0
        for phone, data in accounts.items():
            if not data.get("is_active"):
                if not data.get("warmed_up"):
                    await call.message.answer(f"⚠️ {phone} не прогрет! Сначала нажми 'Прогреть'")
                    continue
                data["is_active"] = True
                asyncio.create_task(worker(phone))
                started += 1
        await call.message.answer(f"✅ Запущено {started} аккаунтов")
    elif call.data == "stop":
        for data in accounts.values():
            data["is_active"] = False
        await call.message.answer("⏹️ Все аккаунты остановлены")
    elif call.data == "status":
        if not accounts:
            return await call.message.answer("❌ Нет аккаунтов")
        text = "📊 **СТАТУС АККАУНТОВ:**\n\n"
        for phone, data in accounts.items():
            my_chats = data.get("chats", [])
            text += f"📱 `{phone}`\n"
            text += f"  Активен: {'✅' if data.get('is_active') else '❌'}\n"
            text += f"  Прогрет: {'✅' if data.get('warmed_up') else '❌'}\n"
            text += f"  СВОИХ чатов: {len(my_chats)}\n"
            last = data.get("last_spam")
            if last:
                minutes = (datetime.now() - last).seconds // 60
                text += f"  Последний спам: {minutes} мин назад\n"
            text += "\n"
        await call.message.answer(text, parse_mode="Markdown")
    elif call.data == "chats":
        text = f"📋 **ОБЩАЯ БАЗА ЧАТОВ:** {len(chats_db)}\n\n"
        text += "**Топ чатов (по количеству аккаунтов):**\n"
        sorted_chats = sorted(chats_db.items(), key=lambda x: len(x[1]["accounts"]), reverse=True)
        for cid, data in sorted_chats[:15]:
            text += f"• {data['title'][:30]} ({len(data['accounts'])} акков)\n"
        text += "\n**Чаты по аккаунтам:**\n"
        for phone, data in accounts.items():
            my_chats = data.get("chats", [])
            text += f"• `{phone}`: {len(my_chats)} чатов\n"
        await call.message.answer(text, parse_mode="Markdown")
    elif call.data == "flood":
        text = f"🚫 **СТАТИСТИКА БЛОКИРОВОК:**\n\n"
        text += f"Всего: `{flood_stats['total']}`\n"
        if flood_stats["last"]:
            minutes = (datetime.now() - flood_stats["last"]).seconds // 60
            text += f"Последняя: `{minutes}` мин назад\n\n"
        text += "**По аккаунтам:**\n"
        if flood_stats["by_account"]:
            for phone, count in flood_stats["by_account"].items():
                text += f"• `{phone}`: `{count}` блоков\n"
        else:
            text += "Нет блокировок ✅"
        await call.message.answer(text, parse_mode="Markdown")
    elif call.data == "test":
        await call.message.answer(f"🧪 {generate_spam_message()}")

@dp.message()
async def text_handler(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if hasattr(dp, "waiting_phone") and dp["waiting_phone"]:
        dp["waiting_phone"] = False
        phone = msg.text.strip()
        if not re.match(r'^\+?\d{10,15}$', phone):
            return await msg.answer("❌ Неверный формат. Используй: +79001234567")
        if phone in accounts:
            return await msg.answer("❌ Этот номер уже добавлен")
        try:
            client = TelegramClient(f"{SESSIONS_DIR}/{phone}", API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(phone)
            accounts[phone] = {"client": client, "chats": [], "last_spam": None, "is_active": False, "warmed_up": False, "warmup_date": None}
            await msg.answer(f"✅ Код отправлен на {phone}\nВведи код из Telegram:")
            dp["waiting_code_for"] = phone
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    elif hasattr(dp, "waiting_code_for") and dp["waiting_code_for"]:
        phone = dp["waiting_code_for"]
        code = msg.text.strip()
        try:
            await accounts[phone]["client"].sign_in(phone, code)
            me = await accounts[phone]["client"].get_me()
            await msg.answer(f"✅ Аккаунт {me.first_name} добавлен!\n\n🔥 Нажми 'Прогреть' для начала (3 дня)")
            dp["waiting_code_for"] = None
        except errors.SessionPasswordNeededError:
            await msg.answer("🔐 Введи пароль двухфакторной аутентификации:")
            accounts[phone]["step"] = "wait_password"
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    elif any(data.get("step") == "wait_password" for data in accounts.values()):
        for phone, data in accounts.items():
            if data.get("step") == "wait_password":
                try:
                    await data["client"].sign_in(password=msg.text.strip())
                    me = await data["client"].get_me()
                    data["step"] = None
                    await msg.answer(f"✅ Аккаунт {me.first_name} добавлен!\n\n🔥 Нажми 'Прогреть' для начала (3 дня)")
                except Exception as e:
                    await msg.answer(f"❌ Ошибка: {e}")
                break

# ===== ЗАПУСК =====
async def main():
    # Удаляем старые веб-хуки
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Веб-хук удалён")
    except Exception as e:
        logger.error(f"Ошибка удаления веб-хука: {e}")
    
    print("=" * 50)
    print("🎬 Бот запущен")
    print(f"📌 Канал: t.me/{CHANNEL_USERNAME}")
    print("=" * 50)
    
    await notify_admin("🚀 **Бот запущен!** Готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())