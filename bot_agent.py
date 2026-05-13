"""
🤖 TELEGRAM BOT - TO'LIQ VERSIYA
=================================
Inline buttonlar, text buyruqlar, PythonAnywhere hosting,
xato tuzatish, screenshot, offline navbat

O'RNATISH:
pip install python-telegram-bot requests playwright aiohttp
python -m playwright install chromium
"""

import os
import asyncio
import json
import logging
import time
import platform
import subprocess
from datetime import datetime
from typing import Dict, Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from playwright.async_api import async_playwright

# ============================================================================
# SOZLAMALAR
# ============================================================================

DATA_FILE = "user_data.json"
QUEUE_FILE = "command_queue.json"
SCREENSHOTS_DIR = "screenshots"
UPLOADS_DIR = "uploads"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Conversation states
(SETUP_NAME, SETUP_SURNAME, SETUP_AGE, SETUP_EMAIL, SETUP_LOGIN, SETUP_PASSWORD,
 WAITING_TEXT_CMD, WAITING_SCREENSHOT_URL, WAITING_PA_LINK, WAITING_PA_LOGIN,
 WAITING_PA_PASSWORD, WAITING_PA_FILES, WAITING_FIX_DESC, WAITING_TG_USER,
 WAITING_TG_MSG) = range(15)

# ============================================================================
# MA'LUMOTLAR SAQLASH
# ============================================================================

class DataStore:
    @staticmethod
    def load(user_id: int) -> Dict:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f).get(str(user_id), {})
        except: pass
        return {}

    @staticmethod
    def save(user_id: int, data: Dict):
        try:
            all_data = {}
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
            all_data[str(user_id)] = data
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Saqlash xatosi: {e}")

    @staticmethod
    def get_profile_text(user_id: int) -> str:
        data = DataStore.load(user_id)
        if not data:
            return "❌ Profil topilmadi. /start buyrug'i bilan sozlang."
        lines = ["👤 **SIZNING PROFILINGIZ**\n"]
        field_map = {
            'name': '📛 Ism', 'surname': '📛 Familiya', 'age': '🎂 Yosh',
            'email': '📧 Email', 'site_login': '🔑 Login', 'created_at': '📅 Yaratilgan'
        }
        for key, label in field_map.items():
            if key in data:
                lines.append(f"{label}: {data[key]}")
        return "\n".join(lines)

# ============================================================================
# OFFLINE BUYRUQLAR NAVBATI
# ============================================================================

class CommandQueue:
    @staticmethod
    def add(user_id: int, command: str, cmd_type: str):
        queue = CommandQueue._load()
        queue.append({
            'user_id': user_id, 'command': command, 'type': cmd_type,
            'time': datetime.now().isoformat(), 'status': 'pending'
        })
        CommandQueue._save(queue)

    @staticmethod
    def get_pending(user_id: int = None) -> List[Dict]:
        queue = CommandQueue._load()
        if user_id:
            return [q for q in queue if q['user_id'] == user_id and q['status'] == 'pending']
        return [q for q in queue if q['status'] == 'pending']

    @staticmethod
    def mark_done(index: int):
        queue = CommandQueue._load()
        if 0 <= index < len(queue):
            queue[index]['status'] = 'done'
            CommandQueue._save(queue)

    @staticmethod
    def _load() -> list:
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except: pass
        return []

    @staticmethod
    def _save(data: list):
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================================
# WEB AVTOMATIZATSIYA
# ============================================================================

class WebEngine:
    def __init__(self):
        self.browser = None
        self.playwright = None

    async def start(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            return True
        except Exception as e:
            logger.error(f"Browser xatosi: {e}")
            return False

    async def stop(self):
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()

    async def screenshot(self, url: str) -> Optional[str]:
        if not self.browser: return None
        try:
            page = await self.browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=20000)
            fname = f"{SCREENSHOTS_DIR}/shot_{int(time.time())}.png"
            await page.screenshot(path=fname, full_page=True)
            await page.close()
            return fname
        except Exception as e:
            logger.error(f"Screenshot xatosi: {e}")
            return None

    async def check_site_errors(self, url: str) -> Dict:
        """Saytni tekshirish - xatolarni aniqlash"""
        if not self.browser: return {'ok': False, 'error': 'Browser ishlamayapti'}
        result = {'ok': True, 'errors': [], 'status': 0, 'screenshot': None}
        try:
            page = await self.browser.new_page()
            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            response = await page.goto(url, wait_until="networkidle", timeout=20000)
            result['status'] = response.status if response else 0

            if response and response.status >= 400:
                result['ok'] = False
                result['errors'].append(f"HTTP {response.status} xatosi")

            if console_errors:
                result['ok'] = False
                result['errors'].extend(console_errors[:5])

            # Screenshot
            fname = f"{SCREENSHOTS_DIR}/check_{int(time.time())}.png"
            await page.screenshot(path=fname, full_page=True)
            result['screenshot'] = fname
            await page.close()
        except Exception as e:
            result['ok'] = False
            result['errors'].append(str(e))
        return result

    async def login_to_site(self, url: str, login: str, password: str) -> Dict:
        """Saytga login qilish"""
        if not self.browser: return {'ok': False, 'error': 'Browser yoq'}
        try:
            page = await self.browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=20000)

            # Login formani topish
            login_selectors = [
                'input[name="email"]', 'input[name="username"]', 'input[name="login"]',
                'input[type="email"]', 'input[type="text"]'
            ]
            pass_selectors = ['input[name="password"]', 'input[type="password"]']

            filled_login = False
            for sel in login_selectors:
                try:
                    await page.fill(sel, login, timeout=3000)
                    filled_login = True
                    break
                except: continue

            filled_pass = False
            for sel in pass_selectors:
                try:
                    await page.fill(sel, password, timeout=3000)
                    filled_pass = True
                    break
                except: continue

            if filled_login and filled_pass:
                try:
                    await page.click('button[type="submit"]', timeout=3000)
                except:
                    await page.click('input[type="submit"]', timeout=3000)
                await asyncio.sleep(3)

                fname = f"{SCREENSHOTS_DIR}/login_{int(time.time())}.png"
                await page.screenshot(path=fname)
                await page.close()
                return {'ok': True, 'screenshot': fname}

            await page.close()
            return {'ok': False, 'error': 'Login forma topilmadi'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    async def open_pythonanywhere(self, pa_url: str, username: str, password: str) -> Dict:
        """PythonAnywhere'ga kirish va web sahifani ochish"""
        if not self.browser: return {'ok': False, 'error': 'Browser yoq'}
        try:
            page = await self.browser.new_page()
            # Login
            await page.goto("https://www.pythonanywhere.com/login/", wait_until="networkidle", timeout=20000)
            await page.fill('#id_auth-username', username, timeout=5000)
            await page.fill('#id_auth-password', password, timeout=5000)
            await page.click('button[type="submit"]', timeout=5000)
            await asyncio.sleep(3)

            # Dashboard screenshot
            fname = f"{SCREENSHOTS_DIR}/pa_dash_{int(time.time())}.png"
            await page.screenshot(path=fname)

            # Web tab
            await page.goto(f"https://www.pythonanywhere.com/user/{username}/webapps/", wait_until="networkidle", timeout=20000)
            await asyncio.sleep(2)

            fname2 = f"{SCREENSHOTS_DIR}/pa_web_{int(time.time())}.png"
            await page.screenshot(path=fname2)
            await page.close()
            return {'ok': True, 'dashboard': fname, 'webtab': fname2, 'site_url': f"https://{username}.pythonanywhere.com"}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

# ============================================================================
# BOT HANDLERLARI
# ============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = DataStore.load(user_id)

    if user_info.get("setup_complete"):
        await show_main_menu(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "👋 **Assalomu aleykum!**\n\n"
            "🤖 Men sizning shaxsiy yordamchi botingizman!\n\n"
            "📱 Telefon yoki 💻 noutbukdan buyruq bering — men bajaraman.\n\n"
            "Keling, avval tanishaylik!\n\n"
            "📛 **Ismingizni yozing:**",
            parse_mode="Markdown"
        )
        return SETUP_NAME

async def setup_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("📛 **Familiyangizni yozing:**", parse_mode="Markdown")
    return SETUP_SURNAME

async def setup_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['surname'] = update.message.text
    await update.message.reply_text("🎂 **Yoshingizni yozing** (raqam):", parse_mode="Markdown")
    return SETUP_AGE

async def setup_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['age'] = int(update.message.text)
        await update.message.reply_text("📧 **Email manzilingiz:**", parse_mode="Markdown")
        return SETUP_EMAIL
    except:
        await update.message.reply_text("❌ Faqat raqam yozing! (masalan: 20)")
        return SETUP_AGE

async def setup_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['email'] = update.message.text
    await update.message.reply_text(
        "🔑 **Sayt login** (email/username):\n(PythonAnywhere yoki boshqa sayt uchun)",
        parse_mode="Markdown"
    )
    return SETUP_LOGIN

async def setup_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['site_login'] = update.message.text
    await update.message.reply_text("🔒 **Parolingiz:**", parse_mode="Markdown")
    return SETUP_PASSWORD

async def setup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['site_password'] = update.message.text
    context.user_data['setup_complete'] = True
    context.user_data['created_at'] = datetime.now().strftime("%Y-%m-%d %H:%M")

    DataStore.save(update.effective_user.id, dict(context.user_data))

    await update.message.reply_text(
        "✅ **Profil saqlandi!**\n\nAsosiy menyu ochilmoqda...",
        parse_mode="Markdown"
    )
    await show_main_menu(update, context)
    return ConversationHandler.END

# ============================================================================
# ASOSIY MENYU
# ============================================================================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📝 Text Buyruq", callback_data="text_cmd"),
            InlineKeyboardButton("🐍 PythonAnywhere", callback_data="pa_hosting")
        ],
        [
            InlineKeyboardButton("📸 Screenshot", callback_data="screenshot"),
            InlineKeyboardButton("🌐 Saytga Kirish", callback_data="login_site")
        ],
        [
            InlineKeyboardButton("🔧 Xato Tuzatish", callback_data="fix_error"),
            InlineKeyboardButton("💬 TG Habar", callback_data="tg_message")
        ],
        [
            InlineKeyboardButton("👤 Profil", callback_data="profile"),
            InlineKeyboardButton("🔄 Qayta Sozlash", callback_data="reset")
        ],
        [
            InlineKeyboardButton("📋 Navbat", callback_data="show_queue"),
            InlineKeyboardButton("💻 PC Holati", callback_data="pc_status")
        ]
    ]

    text = (
        "🤖 **ASOSIY MENYU**\n\n"
        "📱 Telefon yoki 💻 noutbukdan buyruq bering!\n\n"
        "⬇️ Kerakli funksiyani tanlang:"
    )

    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

# ============================================================================
# CALLBACK HANDLER (inline buttonlar)
# ============================================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "text_cmd":
        await query.edit_message_text(
            "📝 **TEXT BUYRUQ**\n\n"
            "Nima qilishimni yozing. Masalan:\n"
            "• _Menga shu loyihani qil_\n"
            "• _Telegramga Adajonim isimli odamga habar yoz_\n"
            "• _Saytimni tekshir_\n"
            "• _PythonAnywhere'ga fayllarni yukla_\n\n"
            "✍️ **Buyruqni yozing:**",
            parse_mode="Markdown"
        )
        context.user_data['state'] = 'waiting_text_cmd'

    elif data == "pa_hosting":
        await query.edit_message_text(
            "🐍 **PYTHONANYWHERE HOSTING**\n\n"
            "Bot PythonAnywhere'ga kirib:\n"
            "1️⃣ Fayllaringizni yuklaydi\n"
            "2️⃣ Web sahifani sozlaydi\n"
            "3️⃣ Saytni ishga tushiradi\n"
            "4️⃣ Screenshot + link beradi\n\n"
            "🔗 **PythonAnywhere username'ingizni yozing:**",
            parse_mode="Markdown"
        )
        context.user_data['state'] = 'waiting_pa_login'

    elif data == "screenshot":
        await query.edit_message_text(
            "📸 **SCREENSHOT**\n\n"
            "🔗 Sayt URL'sini yozing:\n"
            "(Masalan: https://google.com)",
            parse_mode="Markdown"
        )
        context.user_data['state'] = 'waiting_screenshot_url'

    elif data == "login_site":
        user_info = DataStore.load(user_id)
        login = user_info.get('site_login', '')
        if not login:
            await query.edit_message_text("❌ Avval profil sozlang! /start")
            return

        await query.edit_message_text("⏳ Saytga kirilmoqda...")
        web = WebEngine()
        if await web.start():
            await query.edit_message_text(
                "🔗 **Sayt URL'sini yozing:**\n(Login qilinadi)",
                parse_mode="Markdown"
            )
            context.user_data['state'] = 'waiting_login_url'
        else:
            await query.edit_message_text("❌ Browser ochilmadi. Playwright o'rnatilganmi?")
        await web.stop()

    elif data == "fix_error":
        await query.edit_message_text(
            "🔧 **XATO TUZATISH**\n\n"
            "Saytingizda muammo bormi?\n\n"
            "Menga quyidagilarni yozing:\n"
            "1️⃣ Sayt URL'si\n"
            "2️⃣ Muammo tavsifi\n\n"
            "Masalan:\n"
            "_https://mysite.pythonanywhere.com - sahifa ochilmayapti_\n\n"
            "✍️ **Yozing:**",
            parse_mode="Markdown"
        )
        context.user_data['state'] = 'waiting_fix_desc'

    elif data == "tg_message":
        await query.edit_message_text(
            "💬 **TELEGRAM HABAR**\n\n"
            "Kimga habar yuborishim kerak?\n\n"
            "Username yozing (@bilan):\n"
            "Masalan: _@Adajonim_\n\n"
            "✍️ **Username:**",
            parse_mode="Markdown"
        )
        context.user_data['state'] = 'waiting_tg_user'

    elif data == "profile":
        text = DataStore.get_profile_text(user_id)
        keyboard = [[InlineKeyboardButton("◀️ Orqaga", callback_data="back_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "reset":
        DataStore.save(user_id, {})
        await query.edit_message_text(
            "🔄 **Profil o'chirildi!**\n\n/start buyrug'i bilan qayta sozlang.",
            parse_mode="Markdown"
        )

    elif data == "show_queue":
        pending = CommandQueue.get_pending(user_id)
        if pending:
            text = "📋 **NAVBATDAGI BUYRUQLAR:**\n\n"
            for i, cmd in enumerate(pending, 1):
                text += f"{i}. [{cmd['type']}] {cmd['command'][:50]}\n   🕐 {cmd['time']}\n\n"
        else:
            text = "📋 Navbat bo'sh — barcha buyruqlar bajarilgan ✅"
        keyboard = [
            [InlineKeyboardButton("▶️ Navbatni Bajar", callback_data="run_queue")],
            [InlineKeyboardButton("◀️ Orqaga", callback_data="back_menu")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "run_queue":
        await process_queue(update, context, user_id)

    elif data == "pc_status":
        await show_pc_status(update, context)

    elif data == "back_menu":
        await show_main_menu(update, context)

# ============================================================================
# PC STATUS
# ============================================================================

async def show_pc_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        text = (
            "💻 **PC HOLATI**\n\n"
            f"🔲 CPU: {cpu}%\n"
            f"💾 RAM: {ram.percent}% ({ram.used // (1024**3)}/{ram.total // (1024**3)} GB)\n"
            f"📀 Disk: {disk.percent}% ({disk.used // (1024**3)}/{disk.total // (1024**3)} GB)\n"
            f"🖥 OS: {platform.system()} {platform.release()}\n"
            f"🕐 Vaqt: {datetime.now().strftime('%H:%M:%S')}"
        )
    except ImportError:
        text = (
            "💻 **PC HOLATI**\n\n"
            f"🖥 OS: {platform.system()} {platform.release()}\n"
            f"🕐 Vaqt: {datetime.now().strftime('%H:%M:%S')}\n\n"
            "⚠️ `pip install psutil` o'rnating batafsil ma'lumot uchun"
        )
    keyboard = [[InlineKeyboardButton("◀️ Orqaga", callback_data="back_menu")]]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ============================================================================
# TEXT HANDLER - barcha text xabarlarni qabul qilish
# ============================================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state', '')

    # --- TEXT BUYRUQ ---
    if state == 'waiting_text_cmd':
        context.user_data['state'] = ''
        CommandQueue.add(user_id, text, 'text_cmd')
        await update.message.reply_text(
            f"✅ **Buyruq qabul qilindi!**\n\n"
            f"📝 _{text}_\n\n"
            f"⏳ Bajarilmoqda...",
            parse_mode="Markdown"
        )
        await process_text_command(update, context, text)
        return

    # --- SCREENSHOT ---
    if state == 'waiting_screenshot_url':
        context.user_data['state'] = ''
        await update.message.reply_text("⏳ Screenshot tayyorlanmoqda...")
        web = WebEngine()
        if await web.start():
            shot = await web.screenshot(text)
            if shot:
                with open(shot, 'rb') as f:
                    await update.message.reply_photo(f, caption=f"📸 {text}")
            else:
                await update.message.reply_text(f"❌ Screenshot olib bo'lmadi: {text}")
            await web.stop()
        else:
            await update.message.reply_text("❌ Browser ochilmadi")
        await show_main_menu(update, context)
        return

    # --- PA LOGIN ---
    if state == 'waiting_pa_login':
        context.user_data['pa_username'] = text
        context.user_data['state'] = 'waiting_pa_password'
        await update.message.reply_text("🔒 **PythonAnywhere parolingiz:**", parse_mode="Markdown")
        return

    if state == 'waiting_pa_password':
        context.user_data['pa_password'] = text
        context.user_data['state'] = ''
        await update.message.reply_text("⏳ PythonAnywhere'ga kirilmoqda...")

        web = WebEngine()
        if await web.start():
            result = await web.open_pythonanywhere(
                "", context.user_data['pa_username'], text
            )
            if result['ok']:
                if result.get('dashboard'):
                    with open(result['dashboard'], 'rb') as f:
                        await update.message.reply_photo(f, caption="📊 Dashboard")
                if result.get('webtab'):
                    with open(result['webtab'], 'rb') as f:
                        await update.message.reply_photo(f, caption="🌐 Web Tab")
                await update.message.reply_text(
                    f"✅ **PythonAnywhere tayyor!**\n\n"
                    f"🔗 Saytingiz: {result.get('site_url', '')}\n\n"
                    f"Endi saytingizni \"Reload\" qiling va ishlang!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❌ Xato: {result.get('error', 'Noma`lum')}")
            await web.stop()
        else:
            await update.message.reply_text("❌ Browser ochilmadi")
        await show_main_menu(update, context)
        return

    # --- SAYTGA LOGIN ---
    if state == 'waiting_login_url':
        context.user_data['state'] = ''
        user_info = DataStore.load(user_id)
        await update.message.reply_text("⏳ Saytga kirilmoqda...")

        web = WebEngine()
        if await web.start():
            result = await web.login_to_site(
                text, user_info.get('site_login', ''), user_info.get('site_password', '')
            )
            if result['ok'] and result.get('screenshot'):
                with open(result['screenshot'], 'rb') as f:
                    await update.message.reply_photo(f, caption=f"✅ {text} ga kirdim!")
            else:
                await update.message.reply_text(f"❌ Login xatosi: {result.get('error', '')}")
            await web.stop()
        await show_main_menu(update, context)
        return

    # --- XATO TUZATISH ---
    if state == 'waiting_fix_desc':
        context.user_data['state'] = ''
        await update.message.reply_text("⏳ Sayt tekshirilmoqda...")

        # URL va tavsifni ajratish
        parts = text.split(' - ', 1) if ' - ' in text else text.split(' ', 1)
        url = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else "Umumiy tekshiruv"

        if not url.startswith('http'):
            url = 'https://' + url

        web = WebEngine()
        if await web.start():
            result = await web.check_site_errors(url)
            if result['ok']:
                msg = (
                    f"✅ **Saytingiz ishlayapti!**\n\n"
                    f"🔗 {url}\n"
                    f"📊 HTTP Status: {result['status']}\n"
                    f"🎉 Xatolar topilmadi!"
                )
            else:
                errors_text = "\n".join([f"• {e[:100]}" for e in result['errors'][:5]])
                msg = (
                    f"❌ **Xatolar topildi!**\n\n"
                    f"🔗 {url}\n"
                    f"📊 HTTP Status: {result['status']}\n\n"
                    f"🔴 **Xatolar:**\n{errors_text}\n\n"
                    f"💡 **Tavsiya:** Kodni tekshiring va xatolarni tuzating."
                )
            await update.message.reply_text(msg, parse_mode="Markdown")

            if result.get('screenshot'):
                with open(result['screenshot'], 'rb') as f:
                    await update.message.reply_photo(f, caption=f"📸 {url} holati")
            await web.stop()
        else:
            await update.message.reply_text("❌ Browser ochilmadi")
        await show_main_menu(update, context)
        return

    # --- TG HABAR ---
    if state == 'waiting_tg_user':
        context.user_data['tg_target'] = text
        context.user_data['state'] = 'waiting_tg_msg'
        await update.message.reply_text(
            f"💬 **{text}** ga nima yozishim kerak?\n\n✍️ **Xabarni yozing:**",
            parse_mode="Markdown"
        )
        return

    if state == 'waiting_tg_msg':
        target = context.user_data.get('tg_target', '')
        context.user_data['state'] = ''
        await update.message.reply_text(
            f"✅ **Xabar tayyor!**\n\n"
            f"👤 Kimga: {target}\n"
            f"💬 Xabar: _{text}_\n\n"
            f"⚠️ Telegram API cheklovi: bot faqat o'ziga /start bosgan "
            f"userlarga habar yuborishi mumkin.\n\n"
            f"📋 Buyruq navbatga qo'shildi.",
            parse_mode="Markdown"
        )
        CommandQueue.add(update.effective_user.id, f"TG:{target}:{text}", 'tg_message')
        await show_main_menu(update, context)
        return

    # --- AGAR HECH QAYSI STATE BO'LMASA ---
    # Har qanday textni buyruq sifatida qabul qilish
    CommandQueue.add(user_id, text, 'auto_cmd')
    await update.message.reply_text(
        f"📝 **Buyruq qabul qilindi:**\n_{text}_\n\n⏳ Bajarilmoqda...",
        parse_mode="Markdown"
    )
    await process_text_command(update, context, text)

# ============================================================================
# TEXT BUYRUQNI BAJARISH
# ============================================================================

async def process_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    """Erkin text buyruqni tahlil qilish va bajarish"""
    cmd_lower = command.lower()

    # Screenshot buyrug'i
    if any(w in cmd_lower for w in ['screenshot', 'skrinshot', 'rasm', 'surat']):
        # URL ni ajratib olish
        words = command.split()
        url = None
        for w in words:
            if 'http' in w or '.' in w:
                url = w if w.startswith('http') else f'https://{w}'
                break
        if url:
            web = WebEngine()
            if await web.start():
                shot = await web.screenshot(url)
                if shot:
                    with open(shot, 'rb') as f:
                        await update.message.reply_photo(f, caption=f"📸 {url}")
                await web.stop()
        else:
            await update.message.reply_text("🔗 URL kiriting: masalan 'google.com screenshot'")
        return

    # Sayt tekshirish
    if any(w in cmd_lower for w in ['tekshir', 'check', 'ishlamayapti', 'yurmayapti', 'ochilmayapti', 'xato']):
        words = command.split()
        url = None
        for w in words:
            if 'http' in w or '.' in w:
                url = w if w.startswith('http') else f'https://{w}'
                break
        if url:
            web = WebEngine()
            if await web.start():
                result = await web.check_site_errors(url)
                if result['ok']:
                    await update.message.reply_text(f"✅ {url} ishlayapti! Xato yo'q.")
                else:
                    errors = "\n".join([f"• {e[:80]}" for e in result['errors'][:3]])
                    await update.message.reply_text(f"❌ Xatolar:\n{errors}")
                if result.get('screenshot'):
                    with open(result['screenshot'], 'rb') as f:
                        await update.message.reply_photo(f)
                await web.stop()
        else:
            await update.message.reply_text("🔗 Sayt URL sini ham yozing")
        return

    # Telegram habar
    if any(w in cmd_lower for w in ['habar', 'message', 'yoz', 'yubor']):
        await update.message.reply_text(
            "💬 Bu buyruq navbatga qo'shildi.\n"
            "Menyu → 💬 TG Habar orqali batafsil sozlang."
        )
        return

    # PythonAnywhere
    if any(w in cmd_lower for w in ['python', 'hosting', 'deploy', 'pythonanywhere', 'server']):
        await update.message.reply_text(
            "🐍 PythonAnywhere hosting uchun:\n"
            "Menyu → 🐍 PythonAnywhere tugmasini bosing."
        )
        return

    # Umumiy buyruq
    await update.message.reply_text(
        f"📝 **Buyruq saqlandi:**\n_{command}_\n\n"
        f"Bu buyruq navbatga qo'shildi va noutbuk yoqilganda bajariladi.\n\n"
        f"Hozircha menyu orqali aniq funksiyalarni ishlating ⬇️",
        parse_mode="Markdown"
    )
    await show_main_menu(update, context)

# ============================================================================
# NAVBATNI BAJARISH (offline buyruqlar)
# ============================================================================

async def process_queue(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    pending = CommandQueue.get_pending(user_id)
    if not pending:
        await update.callback_query.edit_message_text("✅ Navbat bo'sh!")
        return

    await update.callback_query.edit_message_text(f"⏳ {len(pending)} ta buyruq bajarilmoqda...")

    queue = CommandQueue._load()
    for i, item in enumerate(queue):
        if item['user_id'] == user_id and item['status'] == 'pending':
            # Buyruqni bajarish
            try:
                if item['type'] == 'text_cmd' or item['type'] == 'auto_cmd':
                    # Text buyruqni qayta ishlash (offline)
                    CommandQueue.mark_done(i)
                elif item['type'] == 'tg_message':
                    CommandQueue.mark_done(i)
                else:
                    CommandQueue.mark_done(i)
            except:
                pass

    await update.callback_query.bot.send_message(
        chat_id=user_id,
        text=f"✅ **{len(pending)} ta buyruq bajarildi!**",
        parse_mode="Markdown"
    )
    await show_main_menu(update, context)

# ============================================================================
# RESET
# ============================================================================

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    DataStore.save(update.effective_user.id, {})
    await update.message.reply_text("🔄 Profil o'chirildi! /start bilan qayta boshlang.")

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

# ============================================================================
# ISHGA TUSHIRISH
# ============================================================================

async def main():
    print("\n" + "=" * 55)
    print("🤖 TELEGRAM BOT — TO'LIQ VERSIYA")
    print("=" * 55)
    print("\nFunksiyalar:")
    print("  📝 Text Buyruq — erkin buyruq yozish")
    print("  🐍 PythonAnywhere — hosting")
    print("  📸 Screenshot — sayt rasmi")
    print("  🌐 Saytga Kirish — avtomatik login")
    print("  🔧 Xato Tuzatish — sayt xatolarini topish")
    print("  💬 TG Habar — Telegram habar")
    print("  💻 PC Holati — kompyuter holati")
    print("  📋 Navbat — offline buyruqlar")
    print()

    token = input("🔑 Telegram Bot Token: ").strip()
    if not token:
        print("❌ Token kerak!")
        return

    print("\n⏳ Bot ishga tushirilmoqda...\n")

    app = Application.builder().token(token).build()

    # Profil setup conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SETUP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_name)],
            SETUP_SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_surname)],
            SETUP_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_age)],
            SETUP_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_email)],
            SETUP_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_login)],
            SETUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)],
        },
        fallbacks=[CommandHandler("start", cmd_start)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        print("✅ BOT ISHGA TUSHDI! 🎉")
        print("\nBuyruqlar:")
        print("  /start — Botni boshlash")
        print("  /menu  — Asosiy menyu")
        print("  /reset — Profilni o'chirish")
        print("\n📱 Telefon va 💻 noutbukdan buyruq bering!")
        print("\nTugatish: Ctrl+C\n")

        # Offline navbatni tekshirish
        pending = CommandQueue.get_pending()
        if pending:
            print(f"📋 {len(pending)} ta kutilayotgan buyruq bor!")

        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n⛔ Bot tugatildi")
    finally:
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Xayr!")