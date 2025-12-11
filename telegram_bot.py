#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Email Validator Telegram Bot v2.0
Проверка Gmail через MailApi.dev - упрощенная версия
"""

import asyncio
import aiohttp
import json
import os
from typing import List, Tuple, Set
from io import BytesIO, StringIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)

# ═══════════════════════════════════════════════════════════════════════════════
#                              КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8535404887:AAFSYrEd3Fz7ymBtmRBKraYVQHl6oPkUvBw"
MAILAPI_URL = "https://api.mailapi.dev/v1/verify"
CONFIG_FILE = "bot_config.json"

# Состояния для ConversationHandler
WAITING_API_KEY, WAITING_SINGLE_EMAIL = range(2)

# ═══════════════════════════════════════════════════════════════════════════════
#                              ХРАНИЛИЩЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════════════════════════

class UserConfig:
    """Конфигурация пользователя"""
    def __init__(self):
        self.configs = self.load_configs()
    
    def load_configs(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_configs(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, indent=2)
        except:
            pass
    
    def get_user_config(self, user_id: int) -> dict:
        uid = str(user_id)
        if uid not in self.configs:
            self.configs[uid] = {
                'mailapi_key': '',
                'selector': 'seller'
            }
            self.save_configs()
        return self.configs[uid]
    
    def set_api_key(self, user_id: int, key: str):
        uid = str(user_id)
        config = self.get_user_config(user_id)
        config['mailapi_key'] = key
        self.save_configs()
    
    def get_api_key(self, user_id: int) -> str:
        return self.get_user_config(user_id).get('mailapi_key', '')

user_config = UserConfig()

# ═══════════════════════════════════════════════════════════════════════════════
#                              MAILAPI ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════════

async def mailapi_verify_single(session, email: str, api_key: str) -> Tuple[str, str, int]:
    """Проверка одного email через MailApi.dev"""
    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        params = {'email': email}

        async with session.get(
            MAILAPI_URL,
            headers=headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
            ssl=False
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                credits = data.get('creditsRemaining', -1)
                is_valid = data.get('valid', False)
                validators = data.get('validators', {})
                is_disposable = validators.get('is_disposable', False)

                if is_valid and not is_disposable:
                    return email, 'valid', credits
                else:
                    return email, 'invalid', credits

            elif resp.status == 401:
                return email, 'error_key', -1
            elif resp.status == 402:
                return email, 'error_credits', -1
            else:
                return email, 'error', -1

    except:
        return email, 'error', -1

async def mailapi_test_connection(api_key: str) -> Tuple[bool, str, int]:
    """Тест API ключа"""
    try:
        connector = aiohttp.TCPConnector(ssl=False, force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            headers = {'Authorization': f'Bearer {api_key}'}
            params = {'email': 'test@gmail.com'}

            async with session.get(
                MAILAPI_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    credits = data.get('creditsRemaining', 0)
                    return True, "✅ API работает!", credits
                elif resp.status == 401:
                    return False, "❌ Неверный ключ", 0
                elif resp.status == 402:
                    return False, "❌ Нет кредитов", 0
                else:
                    return False, f"❌ HTTP {resp.status}", 0

    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:30]}", 0

# ═══════════════════════════════════════════════════════════════════════════════
#                              ПАРСИНГ ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════════════════════

def parse_json_content(content: str, selector: str = 'seller') -> List[str]:
    """Парсинг JSON контента - извлекаем seller"""
    try:
        data = json.loads(content)
        nicknames = []
        
        if isinstance(data, dict):
            # Перебираем все записи (0, 1, 2, ...)
            for key, value in data.items():
                if isinstance(value, dict) and selector in value:
                    seller = value[selector]
                    if seller and isinstance(seller, str):
                        nicknames.append(seller)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and selector in item:
                    seller = item[selector]
                    if seller and isinstance(seller, str):
                        nicknames.append(seller)
        
        return nicknames
    except:
        return []

def parse_txt_content(content: str) -> List[str]:
    """Парсинг TXT контента"""
    return [line.strip() for line in content.split('\n') if line.strip()]

# ═══════════════════════════════════════════════════════════════════════════════
#                              ОБРАБОТКА EMAILS
# ═══════════════════════════════════════════════════════════════════════════════

async def check_emails_batch(
    nicknames: List[str],
    api_key: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> Tuple[List[str], int]:
    """Массовая проверка emails - упрощенная версия"""
    
    # Дедупликация
    seen: Set[str] = set()
    unique = []
    for nick in nicknames:
        nl = nick.lower()
        if nl not in seen:
            seen.add(nl)
            unique.append(nick)
    
    emails = [f"{n}@gmail.com" for n in unique]
    valid_emails = []
    last_credits = -1
    
    # Начальное сообщение
    status_msg = await context.bot.send_message(
        chat_id,
        f"⏳ Начинаю проверку...\n\n"
        f"📊 Найдено: {len(nicknames)} seller\n"
        f"🔄 Уникальных: {len(unique)}\n"
        f"⏱ Примерное время: ~{len(emails)} сек"
    )
    
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        for idx, email in enumerate(emails, 1):
            result_email, status, credits = await mailapi_verify_single(session, email, api_key)
            
            if credits >= 0:
                last_credits = credits
            
            # Проверяем ошибки API
            if status == 'error_key':
                await status_msg.edit_text("❌ Неверный API ключ!")
                return [], -1
            elif status == 'error_credits':
                await status_msg.edit_text("❌ Кончились кредиты!")
                return valid_emails, last_credits
            
            # Сохраняем только валидные
            if status == 'valid':
                valid_emails.append(result_email)
            
            # Обновление статуса каждые 10 проверок
            if idx % 10 == 0 or idx == len(emails):
                try:
                    await status_msg.edit_text(
                        f"⏳ Проверка: {idx}/{len(emails)}\n\n"
                        f"✅ Валидных: {len(valid_emails)}\n"
                        f"💳 Кредитов: {last_credits if last_credits >= 0 else '?'}"
                    )
                except:
                    pass
            
            # Rate limit: 1 запрос/сек
            await asyncio.sleep(1.0)
    
    return valid_emails, last_credits

# ═══════════════════════════════════════════════════════════════════════════════
#                              КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    config = user_config.get_user_config(user_id)
    has_api = bool(config.get('mailapi_key'))
    
    keyboard = []
    
    if has_api:
        keyboard.append([InlineKeyboardButton("📄 Проверить JSON файл", callback_data="check_json")])
        keyboard.append([InlineKeyboardButton("📝 Проверить TXT файл", callback_data="check_txt")])
        keyboard.append([InlineKeyboardButton("✉️ Один email", callback_data="check_single")])
        keyboard.append([InlineKeyboardButton("🔑 Сменить API", callback_data="change_api")])
    else:
        keyboard.append([InlineKeyboardButton("⚙️ Настроить API", callback_data="setup_api")])
    
    keyboard.append([InlineKeyboardButton("ℹ️ Помощь", callback_data="help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🤖 <b>Email Validator Bot</b>\n\n"
        "Автоматическая проверка Gmail через MailApi.dev\n\n"
    )
    
    if has_api:
        welcome_text += "✅ API настроен - можете проверять!\n\n<b>Просто отправьте файл:</b>\n• JSON (Depop формат)\n• TXT (список никнеймов)"
    else:
        welcome_text += "⚠️ Сначала настройте API ключ\n👇 Нажмите кнопку ниже"
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "setup_api" or query.data == "change_api":
        await query.edit_message_text(
            "🔑 <b>Настройка API ключа</b>\n\n"
            "<b>Шаги:</b>\n"
            "1️⃣ Перейдите на https://app.mailapi.dev\n"
            "2️⃣ Зарегистрируйтесь (5000 FREE!)\n"
            "3️⃣ Скопируйте API ключ\n"
            "4️⃣ Отправьте его мне\n\n"
            "Или используйте:\n"
            "<code>/setapi ваш_ключ</code>",
            parse_mode='HTML'
        )
        return WAITING_API_KEY
    
    elif query.data == "check_single":
        config = user_config.get_user_config(query.from_user.id)
        if not config.get('mailapi_key'):
            await query.edit_message_text("❌ Сначала настройте API ключ!")
            return ConversationHandler.END
        
        await query.edit_message_text(
            "✉️ <b>Проверка одного email</b>\n\n"
            "Отправьте никнейм или email:\n"
            "Пример: <code>username</code> или <code>user@gmail.com</code>",
            parse_mode='HTML'
        )
        return WAITING_SINGLE_EMAIL
    
    elif query.data == "help":
        help_text = (
            "📖 <b>Как использовать бота</b>\n\n"
            "<b>1. Настройка API:</b>\n"
            "• Получите ключ на app.mailapi.dev\n"
            "• 5000 бесплатных проверок!\n"
            "• Используйте /setapi ключ\n\n"
            "<b>2. Проверка файлов:</b>\n"
            "• Просто отправьте JSON или TXT файл\n"
            "• JSON: формат Depop (поле 'seller')\n"
            "• TXT: список никнеймов (по строкам)\n\n"
            "<b>3. Результат:</b>\n"
            "• Получите TXT с валидными Gmail\n"
            "• Готово к использованию!\n\n"
            "<b>Команды:</b>\n"
            "/start - Главное меню\n"
            "/setapi - Установить API ключ\n"
            "/help - Эта справка"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == "back_to_main":
        await start_from_callback(update, context)

async def start_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню из callback"""
    query = update.callback_query
    user_id = query.from_user.id
    config = user_config.get_user_config(user_id)
    has_api = bool(config.get('mailapi_key'))
    
    keyboard = []
    
    if has_api:
        keyboard.append([InlineKeyboardButton("📄 Отправить файл", callback_data="info_file")])
        keyboard.append([InlineKeyboardButton("✉️ Один email", callback_data="check_single")])
        keyboard.append([InlineKeyboardButton("🔑 Сменить API", callback_data="change_api")])
    else:
        keyboard.append([InlineKeyboardButton("⚙️ Настроить API", callback_data="setup_api")])
    
    keyboard.append([InlineKeyboardButton("ℹ️ Помощь", callback_data="help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = "🤖 <b>Email Validator Bot</b>\n\n"
    
    if has_api:
        welcome_text += "✅ API настроен\n\n<b>Отправьте файл для проверки</b>"
    else:
        welcome_text += "⚠️ Настройте API ключ"
    
    await query.edit_message_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def setapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /setapi"""
    if not context.args:
        await update.message.reply_text(
            "Использование:\n<code>/setapi ваш_ключ</code>\n\n"
            "Получите ключ на https://app.mailapi.dev",
            parse_mode='HTML'
        )
        return
    
    api_key = context.args[0].strip()
    user_id = update.effective_user.id
    
    msg = await update.message.reply_text("⏳ Проверяю ключ...")
    
    ok, message, credits = await mailapi_test_connection(api_key)
    
    if ok:
        user_config.set_api_key(user_id, api_key)
        await msg.edit_text(
            f"✅ <b>API ключ сохранен!</b>\n\n"
            f"{message}\n"
            f"💳 Доступно: {credits} кредитов\n\n"
            f"Теперь отправьте файл для проверки!",
            parse_mode='HTML'
        )
    else:
        await msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n{message}\n\n"
            f"Проверьте ключ и попробуйте снова.",
            parse_mode='HTML'
        )

async def handle_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка API ключа"""
    api_key = update.message.text.strip()
    user_id = update.effective_user.id
    
    msg = await update.message.reply_text("⏳ Проверяю ключ...")
    
    ok, message, credits = await mailapi_test_connection(api_key)
    
    if ok:
        user_config.set_api_key(user_id, api_key)
        await msg.edit_text(
            f"✅ <b>API ключ сохранен!</b>\n\n"
            f"{message}\n"
            f"💳 Доступно: {credits} кредитов\n\n"
            f"Теперь отправьте файл для проверки!",
            parse_mode='HTML'
        )
    else:
        await msg.edit_text(
            f"❌ <b>Ошибка</b>\n\n{message}",
            parse_mode='HTML'
        )
    
    return ConversationHandler.END

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загруженного файла - АВТОМАТИЧЕСКАЯ"""
    user_id = update.effective_user.id
    config = user_config.get_user_config(user_id)
    api_key = config.get('mailapi_key', '')
    
    if not api_key:
        await update.message.reply_text(
            "❌ API ключ не настроен!\n\n"
            "Используйте /setapi для настройки"
        )
        return
    
    document = update.message.document
    file_name = document.file_name.lower()
    
    # Скачиваем файл
    try:
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        content = file_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка загрузки файла: {str(e)}")
        return
    
    # Парсим файл
    nicknames = []
    if file_name.endswith('.json'):
        nicknames = parse_json_content(content, config.get('selector', 'seller'))
        file_type = "JSON"
    elif file_name.endswith('.txt'):
        nicknames = parse_txt_content(content)
        file_type = "TXT"
    else:
        await update.message.reply_text(
            "❌ Неподдерживаемый формат!\n\n"
            "Используйте:\n• .json (Depop формат)\n• .txt (список никнеймов)"
        )
        return
    
    if not nicknames:
        await update.message.reply_text(
            f"❌ Не удалось извлечь данные из {file_type} файла!\n\n"
            f"Проверьте формат файла"
        )
        return
    
    # Проверяем emails
    valid_emails, credits = await check_emails_batch(
        nicknames, api_key, update.effective_chat.id, context
    )
    
    if not valid_emails:
        await update.message.reply_text(
            "😔 <b>Валидные email не найдены</b>\n\n"
            f"Проверено: {len(nicknames)} seller\n"
            f"💳 Осталось кредитов: {credits if credits >= 0 else '?'}",
            parse_mode='HTML'
        )
        return
    
    # Формируем результат
    result_text = (
        f"✅ <b>Проверка завершена!</b>\n\n"
        f"📊 Всего seller: {len(nicknames)}\n"
        f"✅ Валидных: {len(valid_emails)}\n"
        f"❌ Невалидных: {len(nicknames) - len(valid_emails)}\n"
    )
    if credits >= 0:
        result_text += f"\n💳 Осталось кредитов: {credits}"
    
    await update.message.reply_text(result_text, parse_mode='HTML')
    
    # Отправляем файл с результатами
    valid_content = '\n'.join(valid_emails)
    await update.message.reply_document(
        document=BytesIO(valid_content.encode()),
        filename='valid_emails.txt',
        caption=f'✅ {len(valid_emails)} валидных Gmail адресов'
    )

async def handle_single_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка одного email"""
    user_id = update.effective_user.id
    config = user_config.get_user_config(user_id)
    api_key = config.get('mailapi_key', '')
    
    user_input = update.message.text.strip()
    email = f"{user_input}@gmail.com" if '@' not in user_input else user_input
    
    msg = await update.message.reply_text(f"⏳ Проверяю {email}...")
    
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        result_email, status, credits = await mailapi_verify_single(session, email, api_key)
    
    if status == 'valid':
        result = f"✅ <b>VALID</b>\n\n📧 {result_email}"
    elif status == 'invalid':
        result = f"❌ <b>INVALID</b>\n\n📧 {result_email}"
    elif status == 'error_key':
        result = f"❌ <b>Неверный API ключ</b>"
    elif status == 'error_credits':
        result = f"❌ <b>Нет кредитов</b>"
    else:
        result = f"❓ <b>Ошибка проверки</b>\n\n📧 {result_email}"
    
    if credits >= 0:
        result += f"\n\n💳 Кредитов: {credits}"
    
    await msg.edit_text(result, parse_mode='HTML')
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    await update.message.reply_text("❌ Операция отменена. Используйте /start")
    return ConversationHandler.END

async def help_command(update: Updat
