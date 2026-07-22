import os
import asyncio
import logging
import json
from datetime import datetime, timedelta
from flask import Flask, request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
import gspread
from google.oauth2.service_account import Credentials
import speech_recognition as sr
from pydub import AudioSegment
import io
import tempfile
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8656704437:AAEZxBboXqIGWUPbdLPc8t9a2jo4tqTVSdE")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID")
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "GTS Tasks Manager")
app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MOTIVATIONS = [
    "🔥 Сегодня ты продуктивнее, чем вчера!",
    "⚡ Каждая галочка — шаг к цели!",
    "💪 Начни с самого сложного — остальное покажется мелочью!",
    "🎯 Фокус на важном, остальное подождёт!",
    "🚀 Ты уже на полпути — просто продолжай!",
    "⭐ Маленькие победы складываются в большой результат!",
    "💎 Качество важнее количества — сделай одно, но идеально!",
    "🌟 Ты справишься. Всегда справлялся.",
    "🏆 Победитель не тот, кто не падает, а тот, кто встаёт!",
    "⚡ Действуй сейчас — идеальный момент уже наступил!",
]

URGENT_KEYWORDS = ['срочно', 'сегодня', 'завтра', 'немедленно', 'важно', 'критично', 'военкомат', 'суд', 'иск', 'оплата', 'отгрузка сегодня', 'срочная']
IMPORTANT_KEYWORDS = ['клиент', 'заявка', 'счёт', 'счет', 'отгрузка', 'поставщик', 'водоканал', 'станкор', 'промторг', 'спасск', 'астафьев']

def get_gsheet_client():
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            creds_info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        else:
            creds_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
            if os.path.exists(creds_path):
                creds = Credentials.from_service_account_file(creds_path, scopes=SCOPE)
            else:
                return None
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
        return None

def get_or_create_sheet():
    client = get_gsheet_client()
    if not client:
        return None
    try:
        spreadsheet = client.open(SPREADSHEET_NAME)
        sheet = spreadsheet.sheet1
        logger.info(f"Таблица '{SPREADSHEET_NAME}' открыта")
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create(SPREADSHEET_NAME)
        sheet = spreadsheet.sheet1
        sheet.append_row(['ID', 'Дата создания', 'Задача', 'Приоритет', 'Статус', 'Теги', 'Дедлайн', 'Дата выполнения', 'Chat ID'])
        spreadsheet.share('', perm_type='anyone', role='reader')
        logger.info(f"Таблица '{SPREADSHEET_NAME}' создана")
    return sheet

def add_task_to_sheet(task_text, chat_id, priority='normal', tags='', deadline=''):
    sheet = get_or_create_sheet()
    if not sheet:
        return False, "Ошибка подключения к Google Sheets"
    task_id = str(int(datetime.now().timestamp()))
    date_str = datetime.now().strftime('%d.%m.%Y %H:%M')
    try:
        sheet.append_row([task_id, date_str, task_text, priority, 'Активна', tags, deadline, '', str(chat_id)])
        logger.info(f"Задача добавлена: {task_text}")
        return True, task_id
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        return False, str(e)

def get_all_tasks(chat_id=None):
    sheet = get_or_create_sheet()
    if not sheet:
        return []
    try:
        records = sheet.get_all_records()
        active = [r for r in records if r.get('Статус') == 'Активна']
        if chat_id:
            active = [r for r in active if str(r.get('Chat ID', '')) == str(chat_id)]
        return active
    except Exception as e:
        logger.error(f"Ошибка получения задач: {e}")
        return []

def mark_task_done(task_index, chat_id=None):
    sheet = get_or_create_sheet()
    if not sheet:
        return False, "Ошибка подключения"
    try:
        records = sheet.get_all_records()
        active_indices = []
        for i, r in enumerate(records):
            if r.get('Статус') == 'Активна':
                if chat_id is None or str(r.get('Chat ID', '')) == str(chat_id):
                    active_indices.append(i + 2)
        if 0 <= task_index < len(active_indices):
            row_num = active_indices[task_index]
            task_text = records[row_num - 2].get('Задача', '')
            sheet.update_cell(row_num, 5, 'Выполнена')
            sheet.update_cell(row_num, 8, datetime.now().strftime('%d.%m.%Y %H:%M'))
            return True, task_text
        return False, "Неверный номер задачи"
    except Exception as e:
        return False, str(e)

def delete_task(task_index, chat_id=None):
    sheet = get_or_create_sheet()
    if not sheet:
        return False, "Ошибка подключения"
    try:
        records = sheet.get_all_records()
        active_indices = []
        for i, r in enumerate(records):
            if r.get('Статус') == 'Активна':
                if chat_id is None or str(r.get('Chat ID', '')) == str(chat_id):
                    active_indices.append(i + 2)
        if 0 <= task_index < len(active_indices):
            row_num = active_indices[task_index]
            task_text = records[row_num - 2].get('Задача', '')
            sheet.delete_row(row_num)
            return True, task_text
        return False, "Неверный номер задачи"
    except Exception as e:
        return False, str(e)

def analyze_priority(text):
    text_lower = text.lower()
    if any(kw in text_lower for kw in URGENT_KEYWORDS):
        return '🔥 КРИТИЧНО', 'urgent'
    elif any(kw in text_lower for kw in IMPORTANT_KEYWORDS):
        return '⚡ ВАЖНО', 'important'
    return '📅 ОБЫЧНО', 'normal'

def get_tags(text):
    text_lower = text.lower()
    tags = []
    tag_map = {
        'военкомат': '🏛️', 'суд': '⚖️', 'иск': '⚖️',
        'клиент': '🏭', 'заявка': '📋', 'счёт': '💰', 'счет': '💰',
        'оплата': '💰', 'отгрузка': '📦', 'поставщик': '🏭',
        'водоканал': '🏭', 'станкор': '🏭', 'промторг': '🏭',
        'спасск': '🏭', 'астафьев': '🏭', 'crm': '💻',
        'документ': '📄', 'чек': '📄', 'заказ': '📦',
        'позвонить': '📞', 'уточнить': '❓', 'согласовать': '🤝',
    }
    for kw, emoji in tag_map.items():
        if kw in text_lower and emoji not in tags:
            tags.append(emoji)
    return ' '.join(tags) if tags else '📝'

def format_task_list(tasks, title="📋 ТВОИ ЗАДАЧИ"):
    if not tasks:
        return "📭 Список задач пуст. Добавь первую: просто напиши текст!"
    lines = []
    lines.append("<b>" + title + ":</b>")
    lines.append("")
    for i, task in enumerate(tasks, 1):
        priority = task.get('Приоритет', 'normal')
        emoji = '🔥' if priority == 'urgent' else '⚡' if priority == 'important' else '📅'
        tags = task.get('Теги', '📝')
        date = task.get('Дата создания', '')
        task_text = task.get('Задача', '')
        if len(task_text) > 100:
            task_text = task_text[:97] + "..."
        lines.append(emoji + ' <b>#' + str(i) + '</b> ' + task_text)
        lines.append('   ' + tags + ' | ' + date)
        lines.append("")
    lines.append("")
    lines.append("<i>Всего активных: " + str(len(tasks)) + "</i>")
    return "\n".join(lines)

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="🔥 Срочные"), KeyboardButton(text="✅ Выполнено")],
        [KeyboardButton(text="➕ Новая задача"), KeyboardButton(text="🗑️ Удалить")],
    ],
    resize_keyboard=True
)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    lines = []
    lines.append("👋 <b>Привет!</b> Я твой личный помощник по задачам.")
    lines.append("")
    lines.append("<b>Как пользоваться:</b>")
    lines.append("• Просто напиши задачу — я добавлю в список")
    lines.append("• Используй кнопки или команды")
    lines.append("")
    lines.append("<b>Команды:</b>")
    lines.append("/add [текст] — добавить задачу")
    lines.append("/list — все задачи")
    lines.append("/done [номер] — отметить выполненной")
    lines.append("/priority — топ-5 срочных")
    lines.append("/delete [номер] — удалить")
    lines.append("")
    lines.append(MOTIVATIONS[0])
    await message.answer("\n".join(lines), reply_markup=main_kb, parse_mode='HTML')

@dp.message(Command("add"))
async def cmd_add(message: Message):
    task_text = message.text.replace('/add', '').strip()
    if not task_text:
        await message.answer("❌ Напиши задачу после команды. Например: /add Позвонить клиенту")
        return
    await process_new_task(message, task_text)

@dp.message(Command("list"))
async def cmd_list(message: Message):
    tasks = get_all_tasks(chat_id=message.chat.id)
    await message.answer(format_task_list(tasks), parse_mode='HTML')

@dp.message(Command("done"))
async def cmd_done(message: Message):
    try:
        num = int(message.text.replace('/done', '').strip()) - 1
        success, result = mark_task_done(num, chat_id=message.chat.id)
        if success:
            remaining = len(get_all_tasks(chat_id=message.chat.id))
            lines = []
            lines.append("✅ <b>Готово!</b>")
            lines.append("")
            lines.append("Задача выполнена: " + result)
            lines.append("")
            lines.append("Осталось задач: " + str(remaining))
            lines.append(MOTIVATIONS[datetime.now().second % len(MOTIVATIONS)])
            await message.answer("\n".join(lines), parse_mode='HTML')
        else:
            await message.answer("❌ " + result)
    except ValueError:
        await message.answer("❌ Укажи номер задачи. Например: /done 3")

@dp.message(Command("priority"))
async def cmd_priority(message: Message):
    tasks = get_all_tasks(chat_id=message.chat.id)
    if not tasks:
        await message.answer("📭 Список задач пуст.")
        return
    urgent = [t for t in tasks if t.get('Приоритет') == 'urgent']
    important = [t for t in tasks if t.get('Приоритет') == 'important']
    normal = [t for t in tasks if t.get('Приоритет') == 'normal']
    top5 = (urgent + important + normal)[:5]
    text = format_task_list(top5, "🔥 ТОП-5 ПРИОРИТЕТНЫХ ЗАДАЧ")
    await message.answer(text + "\n\n<i>Начни с первой — остальное подождёт!</i>", parse_mode='HTML')

@dp.message(Command("delete"))
async def cmd_delete_cmd(message: Message):
    try:
        num = int(message.text.replace('/delete', '').strip()) - 1
        success, result = delete_task(num, chat_id=message.chat.id)
        if success:
            await message.answer("🗑️ Задача удалена: " + result)
        else:
            await message.answer("❌ " + result)
    except ValueError:
        await message.answer("❌ Укажи номер. Например: /delete 3")

async def process_new_task(message: Message, task_text: str):
    priority_label, priority = analyze_priority(task_text)
    tags = get_tags(task_text)
    success, result = add_task_to_sheet(task_text, message.chat.id, priority, tags)
    if success:
        lines = []
        lines.append("✅ <b>Задача добавлена!</b>")
        lines.append("")
        lines.append("📝 " + task_text)
        lines.append(priority_label)
        lines.append("🏷️ " + tags)
        lines.append("")
        lines.append(MOTIVATIONS[datetime.now().second % len(MOTIVATIONS)])
        await message.answer("\n".join(lines), parse_mode='HTML')
    else:
        await message.answer("❌ Ошибка: " + result)

@dp.message(lambda msg: msg.text and not msg.text.startswith('/'))
async def handle_text(message: Message):
    text = message.text
    if text == "📋 Мои задачи":
        await cmd_list(message)
    elif text == "🔥 Срочные":
        await cmd_priority(message)
    elif text == "✅ Выполнено":
        await message.answer("Напиши: /done [номер задачи]\n\nИли посмотри список: /list")
    elif text == "➕ Новая задача":
        await message.answer("Просто напиши задачу текстом!")
    elif text == "🗑️ Удалить":
        await message.answer("Напиши: /delete [номер задачи]")
    else:
        await process_new_task(message, text)

@dp.message(lambda msg: msg.voice is not None)
async def handle_voice(message: Message):
    await message.answer("🎤 Распознаю голосовое сообщение...")
    try:
        file = await bot.get_file(message.voice.file_id)
        voice_bytes = await bot.download_file(file.file_path)
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp_ogg:
            tmp_ogg.write(voice_bytes.read())
            ogg_path = tmp_ogg.name
        wav_path = ogg_path.replace('.ogg', '.wav')
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='ru-RU')
        os.unlink(ogg_path)
        os.unlink(wav_path)
        await message.answer("📝 <b>Распознал:</b> " + text, parse_mode='HTML')
        await process_new_task(message, text)
    except sr.UnknownValueError:
        await message.answer("❌ Не удалось распознать речь. Попробуй ещё раз или напиши текстом.")
    except sr.RequestError as e:
        await message.answer("❌ Ошибка сервиса распознавания: " + str(e))
    except Exception as e:
        logger.error(f"Ошибка обработки голосового: {e}")
        await message.answer("❌ Ошибка обработки голосового. Напиши текстом, пожалуйста.")

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        update = Update.model_validate(request.get_json())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(dp.feed_update(bot, update))
        loop.close()
        return 'ok', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
