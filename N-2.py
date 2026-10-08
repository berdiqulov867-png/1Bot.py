import os
from aiohttp import web
import asyncio
import io
import logging
import random
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO)

# ============================================================
# TELEGRAM BOT TOKEN
# Pydroid 3 uchun: yangi tokenni quyidagi qo'shtirnoq ichiga qo'ying.
# Masalan: BOT_TOKEN = "123456:AA..."
# Eski/tokeningizni bu yerga yubormang yoki chatga yozmang.
# ============================================================
BOT_TOKEN = "8475334969:AAEJPUg5nhc85gs6bFF_2zRtwXXAig6f6G4"

# Agar terminalda BOT_TOKEN berilgan bo'lsa, undan foydalanadi;
# aks holda yuqoridagi BOT_TOKEN ishlatiladi.
TOKEN = os.environ.get("BOT_TOKEN") or BOT_TOKEN.strip()

if not TOKEN or TOKEN == "BU_YERGA_YANGI_BOT_TOKENINGIZNI_QOYING":
    raise RuntimeError(
        "BOT TOKEN TOPILMADI! N.py faylidagi BOT_TOKEN = \"...\" qatoriga "
        "@BotFather bergan YANGI tokenni yozing va qayta Play bosing."
    )
DEFAULT_ADMIN_PASSWORD = "1234"
SUPER_ADMIN_PASSWORD = "super_admin_secret_999"  # Asosiy Super Admin uchun maxfiy parol

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_NAME = "school_bot_pro_v24.db"

# --- 1. MA'LUMOTLAR BAZASI ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fio TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                tarix INTEGER DEFAULT 0,
                geo INTEGER DEFAULT 0,
                vazifa INTEGER DEFAULT 0,
                davomat TEXT DEFAULT 'Kutilmoqda',
                payment_amount INTEGER DEFAULT 0,
                payment_status TEXT DEFAULT 'To''lanmagan',
                payment_date TEXT DEFAULT '-',
                phone TEXT DEFAULT 'Kiritilmagan',
                group_name TEXT DEFAULT 'Guruhsiz',
                teacher_note TEXT DEFAULT 'Izoh mavjud emas',
                last_score_date TEXT DEFAULT ''
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parent_children (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_chat_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                UNIQUE(parent_chat_id, student_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                student_fio TEXT,
                login_time TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                date_str TEXT,
                davomat TEXT,
                tarix INTEGER,
                geo INTEGER,
                vazifa INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS super_admins (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                parent_chat_id INTEGER,
                parent_name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_title TEXT NOT NULL,
                event_date TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_text TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_password'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO settings (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASSWORD,))

        cursor.execute("SELECT value FROM settings WHERE key = 'super_admin_password'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO settings (key, value) VALUES ('super_admin_password', ?)", (SUPER_ADMIN_PASSWORD,))
            
        conn.commit()

init_db()

def check_and_reset_daily_data():
    today = datetime.now().strftime("%d.%m.%Y")
    last_reset = db_get_setting("last_daily_reset")
    if last_reset != today:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE students SET davomat = 'Kutilmoqda'")
            conn.commit()
        db_set_setting("last_daily_reset", today)

def db_get_admin_password():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_password'")
        row = cursor.fetchone()
        return row[0] if row else DEFAULT_ADMIN_PASSWORD

def db_set_admin_password(new_pass):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('admin_password', ?)", (new_pass,))
        conn.commit()

def db_get_super_admin_password():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'super_admin_password'")
        row = cursor.fetchone()
        return row[0] if row else SUPER_ADMIN_PASSWORD

def db_set_super_admin_password(new_pass):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('super_admin_password', ?)", (new_pass,))
        conn.commit()

def normalize_button_name(fio, limit=22):
    """Telegram tugmalarida uzun F.I.O. ni o'qilishi qulay ko'rinishga keltiradi."""
    name = " ".join((fio or "Noma'lum").split())
    if len(name) <= limit:
        return name
    parts = name.split()
    if len(parts) >= 2:
        compact = f"{parts[0]} {parts[1][0]}."
        if len(compact) <= limit:
            return compact
    return name[:limit - 1].rstrip() + "…"

def score_field_name(field):
    return {
        "tarix": "📜 Tarix test bali",
        "geo": "🌍 Geografiya test bali",
        "vazifa": "📑 Uy vazifasi",
    }.get(field, field)

def build_score_student_text(st):
    return (
        "📝 **Ball kiritish**\n\n"
        f"👤 **{st['fio']}**\n"
        f"🏫 {st['group_name']}\n\n"
        f"📜 Tarix: **{st['tarix']}%**\n"
        f"🌍 Geografiya: **{st['geo']}%**\n"
        f"📑 Uy vazifasi: **{st['vazifa']}%**\n\n"
        "👇 Qaysi bo'limga ball qo'yasiz?"
    )

def build_score_field_keyboard(s_id, field):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Qo'lda kiritish", callback_data=f"sc_manual_{s_id}_{field}")],
        [InlineKeyboardButton(text="10%", callback_data=f"sc_set_{s_id}_{field}_10"), InlineKeyboardButton(text="30%", callback_data=f"sc_set_{s_id}_{field}_30"), InlineKeyboardButton(text="50%", callback_data=f"sc_set_{s_id}_{field}_50")],
        [InlineKeyboardButton(text="70%", callback_data=f"sc_set_{s_id}_{field}_70"), InlineKeyboardButton(text="90%", callback_data=f"sc_set_{s_id}_{field}_90"), InlineKeyboardButton(text="100%", callback_data=f"sc_set_{s_id}_{field}_100")],
        [InlineKeyboardButton(text="⬅️ O'quvchiga qaytish", callback_data=f"sc_st_{s_id}")],
        [InlineKeyboardButton(text="📋 O'quvchilar ro'yxati", callback_data="manage_scores"), InlineKeyboardButton(text="🏠 Panel", callback_data="panel_teacher")]
    ])

def db_set_setting(key, value):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def db_get_setting(key):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

def db_get_all():
    check_and_reset_daily_data()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, fio, code, tarix, geo, vazifa, davomat, payment_amount, payment_status, payment_date, phone, group_name, teacher_note, last_score_date FROM students")
        rows = cursor.fetchall()
        return {
            r[0]: {
                "fio": r[1], "code": r[2], "tarix": r[3],
                "geo": r[4], "vazifa": r[5], 
                "davomat": r[6] if r[6] else "Kutilmoqda",
                "payment_amount": r[7] if r[7] else 0,
                "payment_status": r[8] if r[8] else "To'lanmagan",
                "payment_date": r[9] if r[9] else "-",
                "phone": r[10] if r[10] else "Kiritilmagan",
                "group_name": r[11] if r[11] else "Guruhsiz",
                "teacher_note": r[12] if r[12] else "Izoh mavjud emas",
                "last_score_date": r[13] if r[13] else ""
            } for r in rows
        }

def db_log_student_login(s_id, fio):
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO student_logs (student_id, student_fio, login_time) VALUES (?, ?, ?)", (s_id, fio, now_str))
        conn.commit()

def db_get_recent_login_logs():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT student_fio, login_time FROM student_logs ORDER BY id DESC LIMIT 15")
        return cursor.fetchall()

def db_add_child_to_parent(parent_chat_id, student_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO parent_children (parent_chat_id, student_id) VALUES (?, ?)", (parent_chat_id, student_id))
        conn.commit()

def db_get_parent_children(parent_chat_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT student_id FROM parent_children WHERE parent_chat_id = ?", (parent_chat_id,))
        s_ids = [r[0] for r in cursor.fetchall()]
        all_data = db_get_all()
        return [all_data[s_id] for s_id in s_ids if s_id in all_data]

def db_get_parent_chat_ids_for_student(student_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT parent_chat_id FROM parent_children WHERE student_id = ?", (student_id,))
        return [r[0] for r in cursor.fetchall()]

def db_add_student(fio, code, group_name="Guruhsiz"):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO students (fio, code, group_name) VALUES (?, ?, ?)", (fio, code, group_name))
        conn.commit()

def db_delete_student(s_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM students WHERE id = ?", (s_id,))
        cursor.execute("DELETE FROM attendance_history WHERE student_id = ?", (s_id,))
        cursor.execute("DELETE FROM parent_children WHERE student_id = ?", (s_id,))
        conn.commit()

def db_save_daily_history(s_id, davomat, tarix, geo, vazifa):
    today = datetime.now().strftime("%d.%m.%Y")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance_history WHERE student_id = ? AND date_str = ?", (s_id, today))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE attendance_history SET davomat = ?, tarix = ?, geo = ?, vazifa = ? WHERE id = ?", (davomat, tarix, geo, vazifa, row[0]))
        else:
            cursor.execute("INSERT INTO attendance_history (student_id, date_str, davomat, tarix, geo, vazifa) VALUES (?, ?, ?, ?, ?, ?)", (s_id, today, davomat, tarix, geo, vazifa))
        conn.commit()

def db_get_student_history(s_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT date_str, davomat, tarix, geo, vazifa FROM attendance_history WHERE student_id = ? ORDER BY id DESC LIMIT 15", (s_id,))
        return cursor.fetchall()

def db_update_attendance(s_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET davomat = ? WHERE id = ?", (status, s_id))
        conn.commit()
    data = db_get_all()
    st = data.get(s_id)
    if st:
        db_save_daily_history(s_id, status, st["tarix"], st["geo"], st["vazifa"])

def db_set_score_exact(s_id, field, value):
    today = datetime.now().strftime("%d.%m.%Y")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE students SET {field} = MAX(0, MIN(100, ?)), last_score_date = ? WHERE id = ?", (value, today, s_id))
        conn.commit()
    data = db_get_all()
    st = data.get(s_id)
    if st:
        db_save_daily_history(s_id, st["davomat"], st["tarix"], st["geo"], st["vazifa"])

def db_update_payment_amount(s_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET payment_amount = ? WHERE id = ?", (amount, s_id))
        conn.commit()

def db_update_payment_status(s_id, status):
    today = datetime.now().strftime("%d.%m.%Y") if status == "To'langan" else "-"
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET payment_status = ?, payment_date = ? WHERE id = ?", (status, today, s_id))
        conn.commit()

def db_update_teacher_note(s_id, note):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET teacher_note = ? WHERE id = ?", (note, s_id))
        conn.commit()

def db_add_admin(chat_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (chat_id,))
        conn.commit()

def db_get_admins():
    """Barcha oddiy adminlarning Telegram chat ID larini qaytaradi."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM admins")
        return [r[0] for r in cursor.fetchall()]

def db_add_super_admin(chat_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO super_admins (chat_id) VALUES (?)", (chat_id,))
        conn.commit()

def db_get_super_admins():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM super_admins")
        return [r[0] for r in cursor.fetchall()]

def db_add_pending(student_id, parent_chat_id, parent_name):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO pending_requests (student_id, parent_chat_id, parent_name) VALUES (?, ?, ?)", (student_id, parent_chat_id, parent_name))
        return cursor.lastrowid

def db_get_pending(req_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT student_id, parent_chat_id FROM pending_requests WHERE id = ?", (req_id,))
        return cursor.fetchone()

def db_delete_pending(req_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_requests WHERE id = ?", (req_id,))
        conn.commit()

def db_approve_student(student_id, parent_chat_id):
    db_add_child_to_parent(parent_chat_id, student_id)

def db_add_event(title, date_str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO calendar_events (event_title, event_date) VALUES (?, ?)", (title, date_str))
        conn.commit()

def db_get_events():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, event_title, event_date FROM calendar_events")
        return cursor.fetchall()

def db_delete_event(event_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        conn.commit()

# --- 2. FSM HOLATLARI ---
class AdminStates(StatesGroup):
    waiting_for_password = State()
    waiting_for_new_password = State()
    waiting_for_super_password = State()
    waiting_for_new_super_password = State()
    waiting_for_student_name = State()
    waiting_for_student_group = State()
    waiting_for_broadcast = State()
    waiting_for_event_title = State()
    waiting_for_event_date = State()
    waiting_for_admin_note = State()
    waiting_for_custom_payment = State()
    waiting_for_channel_id = State()
    waiting_for_search_query = State()
    waiting_for_custom_score = State()
    waiting_for_teacher_note = State()

class ParentStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_student_code = State()
    waiting_for_leave_reason = State()
    waiting_for_phone = State()

def get_font(size, bold=False):
    font_names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()

async def safe_delete_message(message: types.Message, delay: int = 0):
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

async def send_auto_clean_message(chat_id, text, reply_markup=None, parse_mode="Markdown", delay: int = 120):
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    asyncio.create_task(safe_delete_message(msg, delay))
    return msg

async def send_and_clean_both(message: types.Message, text: str, reply_markup=None, parse_mode="Markdown", delay: int = 120):
    asyncio.create_task(safe_delete_message(message, 0))
    bot_msg = await bot.send_message(chat_id=message.chat.id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    asyncio.create_task(safe_delete_message(bot_msg, delay))
    return bot_msg

# --- 3. RASM GENERATORLARI (Tarix va Geografiya test ballari aniq ajratildi) ---
def create_student_card_image(student, rank, badge):
    img = Image.new("RGB", (950, 602), color="#F8FAFC")
    draw = ImageDraw.Draw(img)
    
    title_font = get_font(20, bold=True)
    bold_font = get_font(16, bold=True)
    font = get_font(15)

    draw.rectangle([20, 20, 930, 80], fill="#0284C7")
    draw.text((475, 50), "O'QUVCHI SHAXSIY NATIJALAR KARTASI", fill="#FFFFFF", font=title_font, anchor="mm")

    draw.rectangle([20, 100, 930, 200], fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.text((40, 120), f"F.I.O: {student['fio']}", fill="#0F172A", font=bold_font)
    draw.text((40, 155), f"Reyting: {rank}-o'rin | Daraja: {badge} | Guruh: {student['group_name']}", fill="#0369A1", font=bold_font)
    
    pay_text = f"To'lov: {student['payment_status']} ({student['payment_amount']:,} so'm)"
    draw.text((550, 120), pay_text, fill="#334155", font=font)
    draw.text((550, 155), f"Davomat: {student['davomat']} | Tel: {student['phone']}", fill="#334155", font=font)

    sub_y = 220
    draw.rectangle([20, sub_y, 930, sub_y + 40], fill="#E0F2FE", outline="#0284C7", width=2)
    draw.text((50, sub_y + 20), "Fan / Bo'lim yo'nalishi", fill="#0369A1", font=bold_font, anchor="lm")
    draw.text((450, sub_y + 20), "O'zlashtirish foizi", fill="#0369A1", font=bold_font, anchor="mm")
    draw.text((800, sub_y + 20), "Baholash", fill="#0369A1", font=bold_font, anchor="mm")

    subjects = [("Tarix test bali", student["tarix"]), ("Geografiya test bali", student["geo"]), ("Uy vazifasi", student["vazifa"])]
    row_y = sub_y + 40
    for subj, val in subjects:
        draw.rectangle([20, row_y, 930, row_y + 55], fill="#FFFFFF", outline="#E2E8F0")
        draw.text((50, row_y + 27), subj, fill="#1E293B", font=font, anchor="lm")

        bar_x, bar_y, bar_w, bar_h = 350, row_y + 17, 250, 20
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill="#F1F5F9")
        filled_w = int(bar_w * (val / 100))
        bar_color = "#22C55E" if val >= 80 else ("#EAB308" if val >= 60 else "#EF4444")
        if filled_w > 0:
            draw.rectangle([bar_x, bar_y, bar_x + filled_w, bar_y + bar_h], fill=bar_color)
        draw.text((bar_x + bar_w + 20, bar_y + 10), f"{val}%", fill="#0F172A", font=bold_font, anchor="lm")

        grade_text = "A'lo 🌟" if val >= 90 else ("Yaxshi 👍" if val >= 70 else ("Qoniqarli ⚡" if val >= 50 else "Qayta topshirish ⚠️"))
        draw.text((800, row_y + 27), grade_text, fill="#334155", font=font, anchor="mm")
        row_y += 55

    footer_y = 510
    draw.rectangle([20, footer_y, 930, 570], fill="#F1F5F9", outline="#CBD5E1")
    draw.text((40, footer_y + 30), f"Sana: {datetime.now().strftime('%d.%m.%Y')}", fill="#64748B", font=font, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def create_daily_report_images_batched(data):
    items_list = list(data.items())
    if not items_list:
        img = Image.new("RGB", (950, 602), color="#FFFFFF")
        draw = ImageDraw.Draw(img)
        title_font = get_font(20, bold=True)
        draw.rectangle([20, 20, 930, 75], fill="#1E40AF")
        draw.text((475, 47), "O'QUV MARKAZ / MAKTAB KUNLIK HISOBOTI", fill="#FFFFFF", font=title_font, anchor="mm")
        draw.text((475, 300), "Hozircha o'quvchilar bazada yo'q!", fill="#EF4444", font=title_font, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return [buf.getvalue()]

    batch_size = 10
    images_bytes = []
    total_batches = (len(items_list) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        chunk = items_list[batch_idx * batch_size : (batch_idx + 1) * batch_size]
        
        img = Image.new("RGB", (950, 602), color="#FFFFFF")
        draw = ImageDraw.Draw(img)
        font = get_font(14)
        bold_font = get_font(14, bold=True)
        title_font = get_font(18, bold=True)

        draw.rectangle([20, 20, 930, 75], fill="#1E40AF")
        today_date = datetime.now().strftime("%d.%m.%Y")
        header_title = f"KUNLIK HISOBOT ({today_date}) — {batch_idx + 1}-sahifa"
        draw.text((475, 47), header_title, fill="#FFFFFF", font=title_font, anchor="mm")

        col_tr, col_fio, col_dav, col_sub = 50, 370, 130, 120
        sub_y = 90
        headers = [("T/R", col_tr), ("F.I.O", col_fio), ("DAVOMAT", col_dav), ("TARIX TEST", col_sub), ("GEO TEST", col_sub), ("VAZIFA", col_sub)]
        
        curr_x = 20
        for title, w in headers:
            draw.rectangle([curr_x, sub_y, curr_x + w, sub_y + 35], fill="#DBEAFE", outline="#1E3A8A", width=2)
            draw.text((curr_x + w // 2, sub_y + 17), title, fill="#000000", font=bold_font, anchor="mm")
            curr_x += w

        y = sub_y + 35
        row_height = 42
        
        for offset, (s_id, item) in enumerate(chunk):
            idx = batch_idx * batch_size + offset + 1
            x = 20
            draw.rectangle([x, y, x + col_tr, y + row_height], outline="#94A3B8")
            draw.text((x + col_tr // 2, y + row_height // 2), str(idx), fill="#000000", font=bold_font, anchor="mm")
            x += col_tr

            draw.rectangle([x, y, x + col_fio, y + row_height], outline="#94A3B8")
            draw.text((x + 15, y + row_height // 2), item["fio"], fill="#000000", font=bold_font, anchor="lm")
            x += col_fio

            dav_status = item.get("davomat", "Kutilmoqda")
            dav_bg = "#A7F3D0" if dav_status == "Keldi" else ("#FECACA" if dav_status == "Kelmadi" else "#FEF08A")
            draw.rectangle([x, y, x + col_dav, y + row_height], fill=dav_bg, outline="#94A3B8")
            draw.text((x + col_dav // 2, y + row_height // 2), dav_status, fill="#000000", font=bold_font, anchor="mm")
            x += col_dav

            for val in [item["tarix"], item["geo"], item["vazifa"]]:
                draw.rectangle([x, y, x + col_sub, y + row_height], outline="#94A3B8")
                draw.text((x + col_sub // 2, y + row_height // 2), f"{val}%", fill="#000000", font=font, anchor="mm")
                x += col_sub

            y += row_height

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        images_bytes.append(buf.getvalue())

    return images_bytes

def create_leaderboard_image(data):
    img = Image.new("RGB", (950, 602), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    bold_font = get_font(16, bold=True)
    title_font = get_font(20, bold=True)

    draw.rectangle([20, 20, 930, 75], fill="#7C3AED")
    draw.text((475, 47), "🏆 TOP O'QUVCHILAR REYTINGI (TOP 10)", fill="#FFFFFF", font=title_font, anchor="mm")

    sorted_students = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)[:10]

    sub_y = 90
    headers = [("O'RIN", 90), ("O'QUVCHI F.I.O", 410), ("TARIX TEST", 140), ("GEO TEST", 140), ("VAZIFA", 130)]
    curr_x = 20
    for title, w in headers:
        draw.rectangle([curr_x, sub_y, curr_x + w, sub_y + 35], fill="#EDE9FE", outline="#5B21B6", width=2)
        draw.text((curr_x + w // 2, sub_y + 17), title, fill="#000000", font=bold_font, anchor="mm")
        curr_x += w

    y = sub_y + 35
    row_height = 42
    for idx, item in enumerate(sorted_students, 1):
        x = 20
        medal = "🥇 1" if idx == 1 else ("🥈 2" if idx == 2 else ("🥉 3" if idx == 3 else f"{idx}"))
        
        draw.rectangle([x, y, x + 90, y + row_height], outline="#CBD5E1")
        draw.text((x + 45, y + row_height // 2), medal, fill="#000000", font=bold_font, anchor="mm")
        x += 90

        draw.rectangle([x, y, x + 410, y + row_height], outline="#CBD5E1")
        draw.text((x + 15, y + row_height // 2), item["fio"], fill="#000000", font=bold_font, anchor="lm")
        x += 410

        for val, w in [(item["tarix"], 140), (item["geo"], 140), (item["vazifa"], 130)]:
            draw.rectangle([x, y, x + w, y + row_height], fill="#FEF3C7", outline="#CBD5E1")
            draw.text((x + w // 2, y + row_height // 2), f"{val}%", fill="#D97706", font=bold_font, anchor="mm")
            x += w

        y += row_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

# --- 4. BOT HANDLERLARI & ASOSIY ADMIN / O'QITUVCHI PANEL ---

@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 O'quvchi Kabineti", callback_data="student_login_prompt"), InlineKeyboardButton(text="👨‍👩‍👧‍👦 Ota-ona Kabineti", callback_data="auth_parent")],
            [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar")],
            [InlineKeyboardButton(text="🔐 O'qituvchi Paneli", callback_data="teacher_login_prompt"), InlineKeyboardButton(text="⚙️ Super Admin Paneli", callback_data="super_admin_login_prompt")],
            [InlineKeyboardButton(text="❓ Ko'p Savollar (FAQ)", callback_data="faq_menu")]
        ]
    )
    await send_and_clean_both(message, "✨ **Maktab va Kurs Boshqaruv Tizimiga Xush Kelibsiz!**\n\n_Quyidagi bo'limlardan birini tanlang._", reply_markup=kb, delay=120)

# --- O'QITUVCHI PANEL GA KIRISH ---
@dp.message(Command("admin"), F.chat.type == "private")
async def admin_cmd(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_password)
    await send_and_clean_both(message, "🔐 **O'qituvchi paneliga kirish uchun parolni kiriting:**", delay=60)

@dp.callback_query(F.data == "teacher_login_prompt")
async def teacher_login_prompt(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_home")]])
    await call.message.edit_text("🔐 **O'qituvchi paneliga kirish uchun parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_password, F.chat.type == "private")
async def check_admin_password(message: types.Message, state: FSMContext):
    current_pass = db_get_admin_password()
    if message.text.strip() == current_pass:
        db_add_admin(message.chat.id)
        await state.clear()
        asyncio.create_task(safe_delete_message(message, 0))
        await show_teacher_panel_msg(message)
    else:
        await send_and_clean_both(message, "❌ **Parol noto'g'ri!** Qaytadan urinib ko'ring yoki /start bosing.", delay=30)

async def show_teacher_panel_msg(message: types.Message):
    channel = db_get_setting("channel_id") or "Ulanmagan"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi O'quvchi", callback_data="add_student"), InlineKeyboardButton(text="🗑 O'quvchini O'chirish", callback_data="delete_student_menu")],
            [InlineKeyboardButton(text="📌 Davomat Belgilash", callback_data="manage_attendance"), InlineKeyboardButton(text="📝 Test Ballari (Tarix & Geo)", callback_data="manage_scores")],
            [InlineKeyboardButton(text="👁 Kabinetga Kirganlar (Log)", callback_data="view_student_logs")],
            [InlineKeyboardButton(text="💳 Oylik To'lovlar", callback_data="manage_payments"), InlineKeyboardButton(text="🔍 O'quvchini Qidirish", callback_data="search_student")],
            [InlineKeyboardButton(text="💬 O'quvchiga Izoh Yozish", callback_data="manage_teacher_notes")],
            [InlineKeyboardButton(text="📅 Taqvim va Tadbirlar", callback_data="manage_calendar"), InlineKeyboardButton(text="📝 Shaxsiy Eslatmalar", callback_data="admin_notes_list")],
            [InlineKeyboardButton(text="📋 O'quvchilar & Kodlar", callback_data="list_students_admin"), InlineKeyboardButton(text="📊 Admin Dashboard", callback_data="admin_dashboard")],
            [InlineKeyboardButton(text="📅 Kunlik Hisobot Rasmlari", callback_data="get_daily_img"), InlineKeyboardButton(text="🏆 Reyting Rasmi", callback_data="get_leaderboard_img")],
            [InlineKeyboardButton(text="📢 Kanalni Sozlash", callback_data="setup_channel"), InlineKeyboardButton(text="🚀 Kanalga Post Yuborish", callback_data="post_to_channel")],
            [InlineKeyboardButton(text="🔑 Parolni O'zgartirish", callback_data="change_password_start"), InlineKeyboardButton(text="📢 E'lon Yuborish", callback_data="broadcast_start")],
            [InlineKeyboardButton(text="🔙 Chiqish", callback_data="back_home")]
        ]
    )
    await send_auto_clean_message(message.chat.id, f"👨‍🏫 **O'qituvchi Boshqaruv Paneli:**\n\n📢 Ulangan kanal: `{channel}`", reply_markup=kb, delay=180)

@dp.callback_query(F.data == "panel_teacher")
async def teacher_panel_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    channel = db_get_setting("channel_id") or "Ulanmagan"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi O'quvchi", callback_data="add_student"), InlineKeyboardButton(text="🗑 O'quvchini O'chirish", callback_data="delete_student_menu")],
            [InlineKeyboardButton(text="📌 Davomat Belgilash", callback_data="manage_attendance"), InlineKeyboardButton(text="📝 Test Ballari (Tarix & Geo)", callback_data="manage_scores")],
            [InlineKeyboardButton(text="👁 Kabinetga Kirganlar (Log)", callback_data="view_student_logs")],
            [InlineKeyboardButton(text="💳 Oylik To'lovlar", callback_data="manage_payments"), InlineKeyboardButton(text="🔍 O'quvchini Qidirish", callback_data="search_student")],
            [InlineKeyboardButton(text="💬 O'quvchiga Izoh Yozish", callback_data="manage_teacher_notes")],
            [InlineKeyboardButton(text="📅 Taqvim va Tadbirlar", callback_data="manage_calendar"), InlineKeyboardButton(text="📝 Shaxsiy Eslatmalar", callback_data="admin_notes_list")],
            [InlineKeyboardButton(text="📋 O'quvchilar & Kodlar", callback_data="list_students_admin"), InlineKeyboardButton(text="📊 Admin Dashboard", callback_data="admin_dashboard")],
            [InlineKeyboardButton(text="📅 Kunlik Hisobot Rasmlari", callback_data="get_daily_img"), InlineKeyboardButton(text="🏆 Reyting Rasmi", callback_data="get_leaderboard_img")],
            [InlineKeyboardButton(text="📢 Kanalni Sozlash", callback_data="setup_channel"), InlineKeyboardButton(text="🚀 Kanalga Post Yuborish", callback_data="post_to_channel")],
            [InlineKeyboardButton(text="🔑 Parolni O'zgartirish", callback_data="change_password_start"), InlineKeyboardButton(text="📢 E'lon Yuborish", callback_data="broadcast_start")],
            [InlineKeyboardButton(text="🔙 Chiqish", callback_data="back_home")]
        ]
    )
    await call.message.edit_text(f"👨‍🏫 **O'qituvchi Boshqaruv Paneli:**\n\n📢 Ulangan kanal: `{channel}`", reply_markup=kb, parse_mode="Markdown")


# --- ASOSIY SUPER ADMIN PANEL ---
@dp.message(Command("superadmin"), F.chat.type == "private")
async def superadmin_cmd(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_super_password)
    await send_and_clean_both(message, "⚙️ **Asosiy Super Admin paneliga kirish uchun maxfiy parolni kiriting:**", delay=60)

@dp.callback_query(F.data == "super_admin_login_prompt")
async def super_admin_login_prompt(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_super_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_home")]])
    await call.message.edit_text("⚙️ **Asosiy Super Admin paneliga kirish uchun maxfiy parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_super_password, F.chat.type == "private")
async def check_super_admin_password(message: types.Message, state: FSMContext):
    current_super_pass = db_get_super_admin_password()
    if message.text.strip() == current_super_pass:
        db_add_super_admin(message.chat.id)
        await state.clear()
        asyncio.create_task(safe_delete_message(message, 0))
        await show_super_admin_panel_msg(message)
    else:
        await send_and_clean_both(message, "❌ **Super Admin paroli noto'g'ri!**", delay=30)

async def show_super_admin_panel_msg(message: types.Message):
    data = db_get_all()
    total_st = len(data)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Barcha O'quvchilar Ballarini Nolga tushirish", callback_data="sa_reset_scores")],
            [InlineKeyboardButton(text="🔑 O'qituvchi Parolini Almashtirish", callback_data="sa_change_teacher_pass")],
            [InlineKeyboardButton(text="🔐 Super Admin Kodini Almashtirish", callback_data="sa_change_super_pass")],
            [InlineKeyboardButton(text="🗑 Barcha Ma'lumotlarni Tozalash (Reset DB)", callback_data="sa_danger_reset")],
            [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
        ]
    )
    text = (
        f"⚙️ **ASOSIY ADMIN PANELI (SUPER ADMIN)**\n\n"
        f"📊 Tizimdagi jami o'quvchilar: **{total_st} ta**\n"
        f"🛠 Bu yerda o'qituvchi panelidan tashqari barcha ustun va parametrlarni global boshqarishingiz mumkin."
    )
    await bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "panel_super_admin")
async def super_admin_panel_cb(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    total_st = len(data)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Barcha O'quvchilar Ballarini Nolga tushirish", callback_data="sa_reset_scores")],
            [InlineKeyboardButton(text="🔑 O'qituvchi Parolini Almashtirish", callback_data="sa_change_teacher_pass")],
            [InlineKeyboardButton(text="🔐 Super Admin Kodini Almashtirish", callback_data="sa_change_super_pass")],
            [InlineKeyboardButton(text="🗑 Barcha Ma'lumotlarni Tozalash (Reset DB)", callback_data="sa_danger_reset")],
            [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
        ]
    )
    text = (
        f"⚙️ **ASOSIY ADMIN PANELI (SUPER ADMIN)**\n\n"
        f"📊 Tizimdagi jami o'quvchilar: **{total_st} ta**\n"
        f"🛠 Global boshqaruv paneli."
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "sa_reset_scores")
async def sa_reset_scores(call: types.CallbackQuery):
    await call.answer()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET tarix = 0, geo = 0, vazifa = 0, last_score_date = ''")
        conn.commit()
    await call.answer("✅ Barcha o'quvchilarning Tarix va Geografiya test ballari 0 qilindi!", show_alert=True)
    await super_admin_panel_cb(call)

@dp.callback_query(F.data == "sa_change_teacher_pass")
async def sa_change_teacher_pass(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_new_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_super_admin")]])
    await call.message.edit_text("🔑 **O'qituvchi paneli uchun yangi parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "sa_change_super_pass")
async def sa_change_super_pass(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_new_super_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_super_admin")]])
    await call.message.edit_text("⚙️ **Super Admin uchun yangi maxfiy parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_new_super_password, F.chat.type == "private")
async def process_new_super_password(message: types.Message, state: FSMContext):
    new_pass = (message.text or "").strip()
    if len(new_pass) < 6:
        await send_and_clean_both(message, "❌ **Parol kamida 6 ta belgidan iborat bo'lsin.**\n\nQaytadan kiriting:", delay=20)
        return
    if new_pass.lower() in {"123456", "password", "admin123", "superadmin"}:
        await send_and_clean_both(message, "❌ **Juda oddiy parol.** Boshqa parol tanlang:", delay=20)
        return
    db_set_super_admin_password(new_pass)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚙️ Super Admin Panelga Qaytish", callback_data="panel_super_admin")]])
    await send_and_clean_both(message, "✅ **Super Admin paroli muvaffaqiyatli yangilandi!**\n🔐 Yangi parol keyingi kirishdan boshlab ishlaydi.", reply_markup=kb, delay=60)


# --- BALLARNI BOSHQARISH: qulay 3 bosqichli oqim ---
@dp.callback_query(F.data == "manage_scores")
async def manage_scores(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel", callback_data="panel_teacher")]])
        await call.message.edit_text("👥 **Hozircha o'quvchilar yo'q.**", reply_markup=kb, parse_mode="Markdown")
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        done1 = "🟢" if d1.get("last_score_date") == datetime.now().strftime("%d.%m.%Y") else "🟡"
        row.append(InlineKeyboardButton(text=f"{done1} {normalize_button_name(d1['fio'])}", callback_data=f"sc_st_{s_id1}"))
        if i + 1 < len(items):
            s_id2, d2 = items[i + 1]
            done2 = "🟢" if d2.get("last_score_date") == datetime.now().strftime("%d.%m.%Y") else "🟡"
            row.append(InlineKeyboardButton(text=f"{done2} {normalize_button_name(d2['fio'])}", callback_data=f"sc_st_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="🏠 Panelga qaytish", callback_data="panel_teacher")])
    await call.message.edit_text(
        "📝 **Ball kiritish**\n\n🟢 Bugun kamida bitta ball saqlangan\n🟡 Hali baholanmagan\n\nO'quvchini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("sc_st_"))
async def sc_select_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    st = data.get(s_id)
    if not st:
        await call.answer("O'quvchi topilmadi!", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Tarix test bali", callback_data=f"sc_fld_{s_id}_tarix"), InlineKeyboardButton(text="🌍 Geografiya test bali", callback_data=f"sc_fld_{s_id}_geo")],
        [InlineKeyboardButton(text="📑 Uy vazifasi", callback_data=f"sc_fld_{s_id}_vazifa")],
        [InlineKeyboardButton(text="⬅️ O'quvchilar ro'yxati", callback_data="manage_scores"), InlineKeyboardButton(text="🏠 Panel", callback_data="panel_teacher")]
    ])
    await call.message.edit_text(build_score_student_text(st), reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("sc_fld_"))
async def sc_select_field(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    s_id, field = int(parts[2]), parts[3]
    data = db_get_all()
    st = data.get(s_id)
    if not st or field not in {"tarix", "geo", "vazifa"}:
        await call.answer("Ma'lumot topilmadi!", show_alert=True)
        return

    field_name = score_field_name(field)
    await call.message.edit_text(
        f"👤 **{st['fio']}**\n"
        f"🎯 {field_name}\n"
        f"📌 Hozirgi ball: **{st[field]}%**\n\n"
        "📊 Yangi ballni tanlang yoki qo'lda kiriting:",
        reply_markup=build_score_field_keyboard(s_id, field), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("sc_manual_"))
async def sc_manual_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split("_")
    s_id, field = int(parts[2]), parts[3]
    data = db_get_all()
    st = data.get(s_id)
    if not st:
        await call.answer("O'quvchi topilmadi!", show_alert=True)
        return

    prompt_msg = await call.message.edit_text(
        f"👤 **{st['fio']}**\n"
        f"🎯 {score_field_name(field)}\n\n"
        "✏️ **0 dan 100 gacha ball kiriting:**\n"
        "Masalan: `85`",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Ball bo'limiga qaytish", callback_data=f"sc_fld_{s_id}_{field}")]
        ]), parse_mode="Markdown"
    )
    await state.update_data(score_student_id=s_id, score_field=field, prompt_msg_id=prompt_msg.message_id)
    await state.set_state(AdminStates.waiting_for_custom_score)

async def notify_parents_score_updated(s_id, student):
    p_chats = db_get_parent_chat_ids_for_student(s_id)
    for p_id in p_chats:
        try:
            msg = (
                f"📊 **Farzandingiz ({student['fio']}) natijalari yangilandi:**\n\n"
                f"📜 Tarix test bali: **{student['tarix']}%**\n"
                f"🌍 Geografiya test bali: **{student['geo']}%**\n"
                f"📑 Uy vazifasi: **{student['vazifa']}%**"
            )
            await bot.send_message(p_id, msg, parse_mode="Markdown")
        except Exception:
            pass

async def show_score_field_after_save(call, s_id, field, student, value):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✍️ Yana {score_field_name(field)}", callback_data=f"sc_fld_{s_id}_{field}")],
        [InlineKeyboardButton(text="👤 Shu o'quvchining boshqa bali", callback_data=f"sc_st_{s_id}")],
        [InlineKeyboardButton(text="📋 Boshqa o'quvchini tanlash", callback_data="manage_scores")],
        [InlineKeyboardButton(text="🏠 Panel", callback_data="panel_teacher")]
    ])
    await call.message.edit_text(
        f"✅ **{student['fio']}** uchun {score_field_name(field)} **{value}%** saqlandi.\n\n"
        "💡 Endi orqaga bossangiz faqat ball menyusiga qaytasiz — paneldan chiqib ketmaysiz.",
        reply_markup=kb, parse_mode="Markdown"
    )

@dp.message(AdminStates.waiting_for_custom_score, F.chat.type == "private")
async def process_custom_score(message: types.Message, state: FSMContext):
    state_data = await state.get_data()
    prompt_msg_id = state_data.get("prompt_msg_id")
    if prompt_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except Exception:
            pass

    raw = (message.text or "").strip()
    if not raw.isdigit():
        await send_and_clean_both(message, "❌ Faqat 0-100 oralig'idagi raqam kiriting.", delay=20)
        return

    val = int(raw)
    if not 0 <= val <= 100:
        await send_and_clean_both(message, "❌ Ball **0 dan 100 gacha** bo'lishi kerak.", delay=20)
        return

    s_id = state_data.get("score_student_id")
    field = state_data.get("score_field")
    if not s_id or field not in {"tarix", "geo", "vazifa"}:
        await state.clear()
        await send_and_clean_both(message, "❌ Ball kiritish sessiyasi eskirgan. Qaytadan boshlang.", delay=20)
        return

    db_set_score_exact(s_id, field, val)
    student = db_get_all().get(s_id)
    await notify_parents_score_updated(s_id, student)
    await state.clear()

    # Xabarni yuborish o'rniga shu scoring oqimini saqlab qolamiz.
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 O'quvchi ballariga qaytish", callback_data=f"sc_st_{s_id}")],
        [InlineKeyboardButton(text="📋 O'quvchilar ro'yxati", callback_data="manage_scores"), InlineKeyboardButton(text="🏠 Panel", callback_data="panel_teacher")]
    ])
    await message.answer(
        f"✅ **{student['fio']}** uchun {score_field_name(field)} **{val}%** saqlandi.",
        reply_markup=kb, parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("sc_set_"))
async def sc_apply_value(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    _, _, s_id, field, val = parts[0], parts[1], int(parts[2]), parts[3], int(parts[4])
    if field not in {"tarix", "geo", "vazifa"} or not 0 <= val <= 100:
        await call.answer("Noto'g'ri ball!", show_alert=True)
        return

    db_set_score_exact(s_id, field, val)
    student = db_get_all().get(s_id)
    if not student:
        await call.answer("O'quvchi topilmadi!", show_alert=True)
        return
    await notify_parents_score_updated(s_id, student)
    await show_score_field_after_save(call, s_id, field, student, val)

# --- BOSHQA YORDAMCHI MENULAR VA BOSHQARUVLAR ---
@dp.callback_query(F.data == "view_student_logs")
async def view_student_logs(call: types.CallbackQuery):
    await call.answer()
    logs = db_get_recent_login_logs()
    text = "👁 **Oxirgi bo'lib Kabinetga kirganlar (Top 15):**\n\n"
    if logs:
        for fio, l_time in logs:
            text += f"👤 **{fio}** — 🕒 `{l_time}`\n"
    else:
        text += "_Hozircha hech kim kabinetga kirmagan._"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panelga qaytish", callback_data="panel_teacher")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "change_password_start")
async def change_password_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_new_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("🔑 **O'qituvchi paneli uchun yangi parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_new_password, F.chat.type == "private")
async def process_new_password(message: types.Message, state: FSMContext):
    new_pass = message.text.strip()
    if len(new_pass) < 3:
        await send_and_clean_both(message, "❌ Parol juda qisqa! Kamida 3 ta belgi bo'lishi kerak:")
        return
    
    db_set_admin_password(new_pass)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins")
        conn.commit()
    
    await state.clear()
    await send_and_clean_both(
        message,
        f"✅ **Admin paroli muvaffaqiyatli o'zgartirildi!**\n\n"
        f"🔐 Barcha adminlarning sessiyalari yopildi. Yangi parol bilan kirish uchun /start ni bosing.",
        delay=60
    )

@dp.callback_query(F.data == "delete_student_menu")
async def delete_student_menu(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        await call.answer("O'quvchilar yo'q!", show_alert=True)
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        row.append(InlineKeyboardButton(text=f"🗑 {normalize_button_name(d1['fio'])}", callback_data=f"confirm_del_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            row.append(InlineKeyboardButton(text=f"🗑 {normalize_button_name(d2['fio'])}", callback_data=f"confirm_del_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("🗑 **O'chirish uchun o'quvchini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("confirm_del_"))
async def confirm_delete_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    student = data.get(s_id)
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, O'chirilsin", callback_data=f"do_del_{s_id}"), InlineKeyboardButton(text="❌ Yo'q, Bekor qilish", callback_data="delete_student_menu")]
        ]
    )
    await call.message.edit_text(f"⚠️ **Rostdan ham {student['fio']} o'quvchisini bazadan o'chirmoqchimisiz?**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("do_del_"))
async def do_delete_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    db_delete_student(s_id)
    await call.message.edit_text("✅ **O'quvchi bazadan o'chirildi!**")
    await delete_student_menu(call)

@dp.callback_query(F.data == "search_student")
async def search_student_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_search_query)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("🔍 **O'quvchining ismi yoki 4 xonali kodini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_search_query, F.chat.type == "private")
async def process_search_query(message: types.Message, state: FSMContext):
    query = message.text.strip().lower()
    await state.clear()
    data = db_get_all()
    
    results = [d for d in data.values() if query in d["fio"].lower() or query == d["code"]]
    if not results:
        await send_and_clean_both(message, "❌ **Natija topilmadi!**", delay=30)
        await show_teacher_panel_msg(message)
        return

    text = f"🔍 **Qidiruv natijalari ({len(results)} ta):**\n\n"
    for r in results:
        text += f"🔹 **{r['fio']}** ({r['group_name']})\n   🔑 Kod: `{r['code']}` | Tarix test: {r['tarix']}% | Geo test: {r['geo']}%\n   📌 Davomat: {r['davomat']} | To'lov: {r['payment_status']}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Panelga qaytish", callback_data="panel_teacher")]])
    await send_and_clean_both(message, text, reply_markup=kb, delay=120)

@dp.callback_query(F.data == "setup_channel")
async def setup_channel_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_channel_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("📢 **Kanal username (masalan `@kanalim`) yoki ID sini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_channel_id, F.chat.type == "private")
async def process_channel_id(message: types.Message, state: FSMContext):
    ch_id = message.text.strip()
    db_set_setting("channel_id", ch_id)
    await state.clear()
    await send_and_clean_both(message, f"✅ **Kanal muvaffaqiyatli saqlandi:** `{ch_id}`", delay=60)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data == "post_to_channel")
async def post_to_channel_cb(call: types.CallbackQuery):
    await call.answer()
    channel_id = db_get_setting("channel_id")
    if not channel_id:
        await call.answer("❌ Avval kanalni sozlang!", show_alert=True)
        return

    msg = await call.message.answer("⏳ **Hisobot rasmlari kanalga yuklanmoqda...**")
    data = db_get_all()
    images_list = create_daily_report_images_batched(data)
    
    try:
        for idx, img_bytes in enumerate(images_list, 1):
            await bot.send_photo(
                chat_id=channel_id,
                photo=BufferedInputFile(img_bytes, filename=f"daily_report_part_{idx}.png"),
                caption=f"📊 **Kunlik Test Ballari va Davomat Hisoboti ({idx}-sahifa)**\n📅 Sana: {datetime.now().strftime('%d.%m.%Y')}"
            )
        await msg.edit_text(f"✅ **Barcha sahifali hisobotlar kanalga yuborildi!**")
    except Exception as e:
        await msg.edit_text(f"❌ **Kanalga yuborishda xatolik:** {e}")

@dp.callback_query(F.data == "admin_dashboard")
async def admin_dashboard(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    total_students = len(data)
    paid_count = sum(1 for d in data.values() if d["payment_status"] == "To'langan")
    unpaid_count = total_students - paid_count
    total_sum = sum(d["payment_amount"] for d in data.values() if d["payment_status"] == "To'langan")

    text = (
        f"📊 **Admin Dashboard & Umumiy Statistika:**\n\n"
        f"👥 Jami o'quvchilar: **{total_students} ta**\n"
        f"✅ To'laganlar: **{paid_count} ta**\n"
        f"❌ To'lamaganlar: **{unpaid_count} ta**\n"
        f"💰 Yig'ilgan to'lov: **{total_sum:,} so'm**\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_notes_list")
async def admin_notes_list(call: types.CallbackQuery):
    await call.answer()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, note_text FROM admin_notes")
        notes = cursor.fetchall()

    text = "📝 **O'qituvchining Shaxsiy Eslatmalari:**\n\n"
    buttons = []
    if notes:
        for n_id, n_text in notes:
            text += f"• {n_text}\n"
            buttons.append([InlineKeyboardButton(text=f"❌ O'chirish: {n_text[:15]}", callback_data=f"del_note_{n_id}")])
    else:
        text += "_Hozircha eslatmalar yo'q._\n"

    buttons.append([InlineKeyboardButton(text="➕ Yangi Eslatma", callback_data="add_note_start"), InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data == "add_note_start")
async def add_note_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_admin_note)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_notes_list")]])
    await call.message.edit_text("📝 **Yangi eslatma matnini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_admin_note, F.chat.type == "private")
async def process_admin_note(message: types.Message, state: FSMContext):
    note = message.text.strip()
    await state.clear()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO admin_notes (note_text) VALUES (?)", (note,))
        conn.commit()
    await send_and_clean_both(message, "✅ Eslatma saqlandi!", delay=30)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data.startswith("del_note_"))
async def delete_note_cb(call: types.CallbackQuery):
    await call.answer()
    n_id = int(call.data.split("_")[2])
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admin_notes WHERE id = ?", (n_id,))
        conn.commit()
    await admin_notes_list(call)

@dp.callback_query(F.data == "manage_calendar")
async def manage_calendar(call: types.CallbackQuery):
    await call.answer()
    events = db_get_events()
    text = "📅 **Mavjud Taqvim va Tadbirlar:**\n\n"
    buttons = []
    if events:
        for ev_id, title, date_str in events:
            text += f"• **{title}** — _({date_str})_\n"
            buttons.append([InlineKeyboardButton(text=f"❌ O'chirish: {title[:20]}", callback_data=f"del_ev_{ev_id}")])
    else:
        text += "_Hozircha tadbirlar kiritilmagan._\n"

    buttons.append([InlineKeyboardButton(text="➕ Yangi Tadbir", callback_data="add_event_start"), InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data == "add_event_start")
async def add_event_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_event_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="manage_calendar")]])
    await call.message.edit_text("📌 **Yangi tadbir nomini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_event_title, F.chat.type == "private")
async def process_event_title(message: types.Message, state: FSMContext):
    await state.update_data(event_title=message.text.strip())
    await state.set_state(AdminStates.waiting_for_event_date)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="manage_calendar")]])
    await send_and_clean_both(message, "📅 **Tadbir yoki imtihon vaqtini kiriting:**", reply_markup=kb, delay=60)

@dp.message(AdminStates.waiting_for_event_date, F.chat.type == "private")
async def process_event_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("event_title")
    date_str = message.text.strip()
    db_add_event(title, date_str)
    await state.clear()
    await send_and_clean_both(message, f"✅ **Tadbir qo'shildi:**\n\n📌 {title}\n📅 {date_str}", delay=60)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data.startswith("del_ev_"))
async def delete_event_cb(call: types.CallbackQuery):
    await call.answer()
    ev_id = int(call.data.split("_")[2])
    db_delete_event(ev_id)
    await manage_calendar(call)

@dp.callback_query(F.data == "add_student")
async def add_student_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_student_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("👤 **Yangi o'quvchining F.I.O. sini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_student_name, F.chat.type == "private")
async def save_student_name(message: types.Message, state: FSMContext):
    fio = message.text.strip()
    await state.update_data(new_student_fio=fio)
    await state.set_state(AdminStates.waiting_for_student_group)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await send_and_clean_both(message, "🏫 **O'quvchi qaysi guruh/sinfga tegishli?**\n\n_Masalan: 10-A, Tarix guruh_", reply_markup=kb, delay=60)

@dp.message(AdminStates.waiting_for_student_group, F.chat.type == "private")
async def save_student_group(message: types.Message, state: FSMContext):
    group_name = message.text.strip()
    state_data = await state.get_data()
    fio = state_data.get("new_student_fio")
    code = str(random.randint(1000, 9999))
    
    db_add_student(fio, code, group_name)
    await state.clear()
    await send_and_clean_both(message, f"✅ O'quvchi **{fio}** ({group_name}) bazaga qo'shildi!\n🔑 Kirish kodi: `{code}`", delay=60)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data == "manage_teacher_notes")
async def manage_teacher_notes(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        await call.answer("O'quvchilar yo'q!", show_alert=True)
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        row.append(InlineKeyboardButton(text=f"💬 {normalize_button_name(d1['fio'])}", callback_data=f"tnote_st_{s_id1}"))
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            row.append(InlineKeyboardButton(text=f"💬 {normalize_button_name(d2['fio'])}", callback_data=f"tnote_st_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("💬 **O'quvchiga izoh yozish uchun uni tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("tnote_st_"))
async def tnote_select_student(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    st = data.get(s_id)
    await state.update_data(note_student_id=s_id)
    await state.set_state(AdminStates.waiting_for_teacher_note)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="manage_teacher_notes")]])
    await call.message.edit_text(
        f"👤 Tanlangan o'quvchi: **{st['fio']}**\n"
        f"💬 Joriy izoh: _{st['teacher_note']}_\n\n"
        f"✍️ **Yangi tavsiya yoki izoh yozing:**", 
        reply_markup=kb, parse_mode="Markdown"
    )

@dp.message(AdminStates.waiting_for_teacher_note, F.chat.type == "private")
async def process_teacher_note(message: types.Message, state: FSMContext):
    note_text = message.text.strip()
    state_data = await state.get_data()
    s_id = state_data.get("note_student_id")
    db_update_teacher_note(s_id, note_text)
    
    data = db_get_all()
    student = data.get(s_id)
    p_chats = db_get_parent_chat_ids_for_student(s_id)
    for p_id in p_chats:
        try:
            await bot.send_message(p_id, f"💬 **O'qituvchidan farzandingizga ({student['fio']}) izoh:**\n\n_{note_text}_", parse_mode="Markdown")
        except Exception:
            pass

    await state.clear()
    await send_and_clean_both(message, "✅ Izoh saqlandi va ota-onaga yuborildi!", delay=45)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data == "manage_attendance")
async def manage_attendance(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        await call.answer("O'quvchilar mavjud emas!", show_alert=True)
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        st_icon1 = "✅" if d1["davomat"] == "Keldi" else ("❌" if d1["davomat"] == "Kelmadi" else "🟡")
        row.append(InlineKeyboardButton(text=f"{st_icon1} {normalize_button_name(d1['fio'])}", callback_data=f"set_att_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            st_icon2 = "✅" if d2["davomat"] == "Keldi" else ("❌" if d2["davomat"] == "Kelmadi" else "🟡")
            row.append(InlineKeyboardButton(text=f"{st_icon2} {normalize_button_name(d2['fio'])}", callback_data=f"set_att_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("📌 **Davomatni o'zgartirish uchun o'quvchini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_att_"))
async def set_attendance_status(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    st = data.get(s_id)
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Keldi", callback_data=f"save_att_{s_id}_Keldi"), InlineKeyboardButton(text="❌ Kelmadi", callback_data=f"save_att_{s_id}_Kelmadi")],
            [InlineKeyboardButton(text="🟡 Sababli", callback_data=f"save_att_{s_id}_Sababli"), InlineKeyboardButton(text="⬅️ Orqaga", callback_data="manage_attendance")]
        ]
    )
    await call.message.edit_text(f"👤 O'quvchi: **{st['fio']}**\n📌 **Davomat statusini tanlang:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("save_att_"))
async def save_attendance_status(call: types.CallbackQuery):
    await call.answer()
    _, _, s_id, status = call.data.split("_")
    s_id = int(s_id)
    db_update_attendance(s_id, status)
    
    data = db_get_all()
    student = data.get(s_id)
    p_chats = db_get_parent_chat_ids_for_student(s_id)
    for p_id in p_chats:
        try:
            await bot.send_message(p_id, f"📌 **Farzandingiz ({student['fio']}) davomati:** {status}", parse_mode="Markdown")
        except Exception:
            pass

    await manage_attendance(call)

@dp.callback_query(F.data == "manage_payments")
async def manage_payments(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        await call.answer("O'quvchilar mavjud emas!", show_alert=True)
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        st_icon1 = "✅" if d1["payment_status"] == "To'langan" else "❌"
        row.append(InlineKeyboardButton(text=f"{st_icon1} {normalize_button_name(d1['fio'], 18)}", callback_data=f"pay_st_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            st_icon2 = "✅" if d2["payment_status"] == "To'langan" else "❌"
            row.append(InlineKeyboardButton(text=f"{st_icon2} {normalize_button_name(d2['fio'], 18)}", callback_data=f"pay_st_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("💳 **To'lovni boshqarish uchun o'quvchini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("pay_st_"))
async def pay_select_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    student = data.get(s_id)

    st_btn = "❌ To'lanmagan qilish" if student["payment_status"] == "To'langan" else "✅ To'landi deb belgilash"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=st_btn, callback_data=f"pay_toggle_{s_id}")],
            [InlineKeyboardButton(text="💰 Summani Qo'lda Kiritish", callback_data=f"pay_custom_{s_id}")],
            [InlineKeyboardButton(text="💵 150,000 so'm", callback_data=f"pay_set_amt_{s_id}_150000"), InlineKeyboardButton(text="💵 200,000 so'm", callback_data=f"pay_set_amt_{s_id}_200000")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="manage_payments")]
        ]
    )

    text = (
        f"👤 O'quvchi: **{student['fio']}**\n"
        f"💰 Oylik To'lov: **{student['payment_amount']:,} so'm**\n"
        f"📌 Holati: **{student['payment_status']}**\n"
        f"📅 Sanasi: **{student['payment_date']}**"
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("pay_custom_"))
async def pay_custom_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    await state.update_data(pay_student_id=s_id)
    await state.set_state(AdminStates.waiting_for_custom_payment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"pay_st_{s_id}")]])
    await call.message.edit_text("💰 **Oylik to'lov summasini kiriting (faqat raqamlarda):**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_custom_payment, F.chat.type == "private")
async def process_custom_payment(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await send_and_clean_both(message, "❌ Noto'g'ri format! Faqat raqam kiriting:", delay=20)
        return
    
    amount = int(message.text.strip())
    state_data = await state.get_data()
    s_id = state_data.get("pay_student_id")
    
    db_update_payment_amount(s_id, amount)
    await state.clear()
    await send_and_clean_both(message, f"✅ Oylik to'lov summasi **{amount:,} so'm** qilib belgilandi!", delay=45)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data.startswith("pay_toggle_"))
async def pay_toggle_status(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    student = data.get(s_id)

    if student:
        new_status = "To'lanmagan" if student["payment_status"] == "To'langan" else "To'langan"
        db_update_payment_status(s_id, new_status)
        p_chats = db_get_parent_chat_ids_for_student(s_id)
        for p_id in p_chats:
            try:
                msg = f"✅ **Farzandingiz ({student['fio']}) to'lovi qabul qilindi!**" if new_status == "To'langan" else f"⚠ **To'lov holati o'zgartirildi.**"
                await bot.send_message(p_id, msg, parse_mode="Markdown")
            except Exception:
                pass
        await pay_select_student(call)

@dp.callback_query(F.data.startswith("pay_set_amt_"))
async def pay_set_amount_value(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    s_id, amount = int(parts[3]), int(parts[4])
    db_update_payment_amount(s_id, amount)
    await pay_select_student(call)

@dp.callback_query(F.data == "get_daily_img")
async def send_daily_table(call: types.CallbackQuery):
    await call.answer()
    msg = await call.message.answer("⏳ Hisobot rasmlari tayyorlanmoqda...")
    data = db_get_all()
    images_list = create_daily_report_images_batched(data)
    
    for idx, img_bytes in enumerate(images_list, 1):
        await call.message.answer_photo(
            photo=BufferedInputFile(img_bytes, filename=f"daily_part_{idx}.png"),
            caption=f"📌 **Kunlik Hisobot — {idx}-sahifa**",
            parse_mode="Markdown"
        )
    await safe_delete_message(msg)

@dp.callback_query(F.data == "get_leaderboard_img")
async def send_leaderboard_table(call: types.CallbackQuery):
    await call.answer()
    msg = await call.message.answer("⏳ Reyting tayyorlanmoqda...")
    data = db_get_all()
    img_bytes = create_leaderboard_image(data)
    await call.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="leaderboard_950x602.png"), caption="🏆 **O'quvchilar Test Reytingi**", parse_mode="Markdown")
    await safe_delete_message(msg)

@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_broadcast)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("📢 **Barcha ota-onalarga yubormoqchi bo'lgan e'loningizni yozing:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_broadcast, F.chat.type == "private")
async def broadcast_send(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    
    all_parents = set()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT parent_chat_id FROM parent_children")
        for r in cursor.fetchall():
            all_parents.add(r[0])

    sent_count = 0
    for p_id in all_parents:
        try:
            await bot.send_message(p_id, f"📢 **E'lon:**\n\n{text}", parse_mode="Markdown")
            sent_count += 1
        except Exception:
            pass
    await send_and_clean_both(message, f"✅ Xabar muvaffaqiyatli **{sent_count} ta** ota-onaga yuborildi!", delay=45)
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data == "list_students_admin")
async def list_students_admin(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    if not data:
        await call.answer("Hozircha o'quvchilar yo'q!", show_alert=True)
        return

    text = "📋 **O'quvchilar va Kodlar:**\n\n"
    for s_id, d in data.items():
        text += f"🔹 **{d['fio']}** ({d['group_name']}) — KOD: `{d['code']}` | Tel: {d['phone']}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


# --- 5A. O'QUVCHI KABINETI ---
async def render_student_cabinet(call: types.CallbackQuery, state: FSMContext, s_id: int):
    data = db_get_all()
    student = data.get(s_id)
    if not student:
        await call.answer("❌ O'quvchi topilmadi!", show_alert=True)
        return

    db_log_student_login(s_id, student["fio"])
    sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
    rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == student["fio"]), 1)
    badge = "💎 Diamond" if student["tarix"] >= 90 else ("🥇 Oltin" if student["tarix"] >= 75 else "🥈 Kumush")
    pay_icon = "🟢" if student["payment_status"] == "To'langan" else "🔴"

    text = (
        f"🎓 **O'QUVCHI SHAXSIY KABINETI**\n\n"
        f"👤 F.I.O: **{student['fio']}**\n"
        f"🏫 Guruh/Sinf: _{student['group_name']}_\n"
        f"🏆 Reyting: **{rank}-o'rin** | 🏅 Daraja: **{badge}**\n"
        f"📌 Davomat: **{student['davomat']}**\n"
        f"💳 To'lov: **{pay_icon} {student['payment_status']}**\n\n"
        f"📜 Tarix testi: **{student['tarix']}%**\n"
        f"🌍 Geografiya testi: **{student['geo']}%**\n"
        f"📑 Uy vazifasi: **{student['vazifa']}%**\n\n"
        f"💬 O'qituvchi izohi: _{student['teacher_note']}_"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Shaxsiy Karta", callback_data=f"get_student_card_img_{s_id}"),
         InlineKeyboardButton(text="📅 Kunlik Tarix", callback_data=f"view_full_history_{s_id}")],
        [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar")],
        [InlineKeyboardButton(text="📞 Telefon raqam", callback_data="set_student_phone")],
        [InlineKeyboardButton(text="🔄 Boshqa kod bilan kirish", callback_data="student_login_prompt")],
        [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "student_login_prompt")
async def student_login_prompt(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_student_code)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_home")]
    ])
    await call.message.edit_text(
        "🎓 **O'quvchi kabinetiga kirish**\n\n🔑 O'qituvchi bergan **4 xonali o'quvchi kodini** kiriting:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.message(ParentStates.waiting_for_student_code, F.chat.type == "private")
async def check_student_login_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    if not code.isdigit() or len(code) != 4:
        await send_and_clean_both(message, "❌ Kod 4 xonali raqam bo'lishi kerak. Qaytadan kiriting:", delay=20)
        return

    data = db_get_all()
    matched = next(((s_id, student) for s_id, student in data.items() if str(student["code"]) == code), None)
    if not matched:
        await send_and_clean_both(message, "❌ **Kod noto'g'ri!** O'qituvchidan o'quvchi kodingizni tekshiring va qaytadan kiriting.", delay=25)
        return

    s_id, student = matched
    await state.clear()
    await state.update_data(student_id=s_id)
    db_log_student_login(s_id, student["fio"])

    # Message ichidan to'liq kabinetni chiqarish uchun vaqtinchalik callback obyektiga ehtiyoj yo'q.
    sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
    rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == student["fio"]), 1)
    badge = "💎 Diamond" if student["tarix"] >= 90 else ("🥇 Oltin" if student["tarix"] >= 75 else "🥈 Kumush")
    pay_icon = "🟢" if student["payment_status"] == "To'langan" else "🔴"
    text = (
        f"🎓 **O'QUVCHI SHAXSIY KABINETI**\n\n"
        f"👤 F.I.O: **{student['fio']}**\n"
        f"🏫 Guruh/Sinf: _{student['group_name']}_\n"
        f"🏆 Reyting: **{rank}-o'rin** | 🏅 Daraja: **{badge}**\n"
        f"📌 Davomat: **{student['davomat']}**\n"
        f"💳 To'lov: **{pay_icon} {student['payment_status']}**\n\n"
        f"📜 Tarix testi: **{student['tarix']}%**\n"
        f"🌍 Geografiya testi: **{student['geo']}%**\n"
        f"📑 Uy vazifasi: **{student['vazifa']}%**\n\n"
        f"💬 O'qituvchi izohi: _{student['teacher_note']}_"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Shaxsiy Karta", callback_data=f"get_student_card_img_{s_id}"),
         InlineKeyboardButton(text="📅 Kunlik Tarix", callback_data=f"view_full_history_{s_id}")],
        [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar")],
        [InlineKeyboardButton(text="📞 Telefon raqam", callback_data="set_student_phone")],
        [InlineKeyboardButton(text="🔄 Boshqa kod bilan kirish", callback_data="student_login_prompt")],
        [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
    ])
    await send_and_clean_both(message, text, reply_markup=kb, delay=300)

@dp.callback_query(F.data == "student_cabinet")
async def student_cabinet_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    s_id = data.get("student_id")
    if not s_id:
        await student_login_prompt(call, state)
        return
    await render_student_cabinet(call, state, int(s_id))

@dp.callback_query(F.data == "set_student_phone")
async def set_student_phone_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    s_id = data.get("student_id")
    if not s_id:
        await call.answer("Avval o'quvchi kodi bilan kiring.", show_alert=True)
        return
    await state.update_data(student_phone_id=int(s_id))
    await state.set_state(ParentStates.waiting_for_phone)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kabinetga qaytish", callback_data="student_cabinet")]])
    await call.message.edit_text("📞 **Telefon raqamingizni kiriting:**\n\n_Masalan: +998901234567_", reply_markup=kb, parse_mode="Markdown")

# --- 5. OTA-ONA / O'QUVCHI KABINETI ---
@dp.callback_query(F.data == "auth_parent")
async def open_parent_cabinet(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    children = db_get_parent_children(call.from_user.id)

    if children:
        state_data = await state.get_data()
        active_s_id = state_data.get("active_child_id", children[0]["code"])
        
        m = next((c for c in children if c["code"] == active_s_id), children[0])
        s_id = next(s_id for s_id, d in db_get_all().items() if d["code"] == m["code"])

        db_log_student_login(s_id, m["fio"])

        data = db_get_all()
        sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
        rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == m["fio"]), 1)

        badge = "💎 Diamond" if m["tarix"] >= 90 else ("🥇 Oltin" if m["tarix"] >= 75 else "🥈 Kumush")
        pay_icon = "🟢" if m["payment_status"] == "To'langan" else "🔴"

        text = (
            f"📊 **Farzandingiz Shaxsiy Nazorat Paneli:**\n\n"
            f"👤 Tanlangan farzand: **{m['fio']}**\n"
            f"🏫 Guruh/Sinf: _{m['group_name']}_\n"
            f"🏆 Reyting: **{rank}-o'rin** | 🏅 Daraja: **{badge}**\n"
            f"📌 Davomat: **{m['davomat']}** | 💳 To'lov: **{pay_icon} {m['payment_status']}**\n"
            f"📜 Tarix test: **{m['tarix']}%** | 🌍 Geo test: **{m['geo']}%** | 📑 Vazifa: **{m['vazifa']}%**\n"
            f"💬 O'qituvchi izohi: _{m['teacher_note']}_\n"
            f"📞 Telefon: `{m['phone']}`"
        )

        buttons = []
        if len(children) > 1:
            child_sw_btns = []
            for ch in children:
                st_icon = "🔘" if ch["code"] == m["code"] else "👶"
                child_sw_btns.append(InlineKeyboardButton(text=f"{st_icon} {ch['fio'][:10]}", callback_data=f"switch_child_{ch['code']}"))
            buttons.append(child_sw_btns)

        cabinet_actions = [
            InlineKeyboardButton(text="🖼 Shaxsiy Karta", callback_data=f"get_student_card_img_{s_id}"),
            InlineKeyboardButton(text="📅 Kunlik Tarix", callback_data=f"view_full_history_{s_id}")
        ]
        
        if len(children) < 3:
            cabinet_actions.append(InlineKeyboardButton(text="➕ Yana Farzand Qo'shish", callback_data="reg_select_list"))

        buttons.extend([
            cabinet_actions,
            [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar"), InlineKeyboardButton(text="📞 Telefon raqam", callback_data="set_phone_number")],
            [InlineKeyboardButton(text="📝 Sababli Ariza", callback_data=f"send_leave_req_{s_id}"), InlineKeyboardButton(text="🔄 Profilni Uzish", callback_data="reset_account")],
            [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
        ])

        await call.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Ro'yxatdan farzandni tanlab ulanish", callback_data="reg_select_list")],
                [InlineKeyboardButton(text="🔑 Maxsus kod bilan ulanish", callback_data="reg_enter_code")],
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_home")]
            ]
        )
        await call.message.edit_text("👨‍👩‍👧‍👦 **Kabinetga kirish uchun farzandingizni tanlang yoki kod bilan ulaning:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("switch_child_"))
async def switch_child(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    code = call.data.split("_")[2]
    await state.update_data(active_child_id=code)
    await open_parent_cabinet(call, state)

@dp.callback_query(F.data == "reg_select_list")
async def reg_select_list(call: types.CallbackQuery):
    await call.answer()
    children = db_get_parent_children(call.from_user.id)
    if len(children) >= 3:
        await call.answer("⚠️ Maksimal 3 tagacha farzand biriktirish mumkin!", show_alert=True)
        return

    data = db_get_all()
    if not data:
        await call.answer("O'quvchilar yo'q!", show_alert=True)
        return

    buttons = []
    items = list(data.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        row.append(InlineKeyboardButton(text=f"👤 {normalize_button_name(d1['fio'])}", callback_data=f"req_link_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            row.append(InlineKeyboardButton(text=f"👤 {normalize_button_name(d2['fio'])}", callback_data=f"req_link_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="auth_parent")])
    await call.message.edit_text("📋 **Biriktirish uchun farzandingiz ismini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("req_link_"))
async def request_link_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    data = db_get_all()
    student = data.get(s_id)
    
    if not student:
        await call.answer("Topilmadi!", show_alert=True)
        return

    req_id = db_add_pending(s_id, call.from_user.id, call.from_user.full_name)
    admins = db_get_admins()
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_app_{req_id}"), InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_rej_{req_id}")]
        ]
    )
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, f"🚨 **Ulanish so'rovi!**\n\n👤 O'quvchi: **{student['fio']}**", reply_markup=admin_kb, parse_mode="Markdown")
        except Exception:
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]])
    await call.message.edit_text("⏳ **So'rov adminga yuborildi! Tasdiqlangach kabinetingiz faollashadi.**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("adm_app_") | F.data.startswith("adm_rej_"))
async def admin_process_request(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    action, req_id = parts[1], int(parts[2])
    
    req_data = db_get_pending(req_id)
    if not req_data:
        await call.message.edit_text("⚠️ Bu so'rov allaqachon ko'rib chiqilgan.")
        return

    student_id, parent_chat_id = req_data
    data = db_get_all()
    student = data.get(student_id)

    if action == "app":
        db_approve_student(student_id, parent_chat_id)
        db_delete_pending(req_id)
        await call.message.edit_text(f"✅ **Tasdiqlandi!** {student['fio']} ota-onasiga biriktirildi.")
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Kabinetni Ochish", callback_data="auth_parent")]])
            await bot.send_message(parent_chat_id, f"🎉 **Tabriklaymiz!** Admin ulanishni tasdiqladi.", reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    else:
        db_delete_pending(req_id)
        await call.message.edit_text(f"❌ **Rad etildi.**")
        try:
            await bot.send_message(parent_chat_id, "❌ Afsuski, admin ulanish so'rovini rad etdi.")
        except Exception:
            pass

@dp.callback_query(F.data == "reg_enter_code")
async def reg_enter_code_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_code)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("🔑 **Farzandingizning 4 xonali kodini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_code, F.chat.type == "private")
async def check_parent_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = db_get_all()
    matched = next(((s_id, d) for s_id, d in data.items() if d["code"] == code), None)

    if matched:
        s_id, student = matched
        await state.clear()
        req_id = db_add_pending(s_id, message.chat.id, message.from_user.full_name)
        admins = db_get_admins()
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_app_{req_id}"), InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_rej_{req_id}")]
            ]
        )
        for admin_id in admins:
            try:
                await bot.send_message(admin_id, f"🚨 **Kod orqali ulanish so'rovi!**\n\n👤 O'quvchi: **{student['fio']}**", reply_markup=admin_kb, parse_mode="Markdown")
            except Exception:
                pass
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]])
        await send_and_clean_both(message, "⏳ **So'rov adminga yuborildi!**", reply_markup=kb, delay=60)
    else:
        await send_and_clean_both(message, "❌ Noto'g'ri kod! Qaytadan kiriting:", delay=20)

@dp.callback_query(F.data.startswith("view_full_history_"))
async def view_full_history(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[3])
    data = db_get_all()
    m = data.get(s_id)
    if not m:
        await call.answer("Topilmadi!", show_alert=True)
        return

    history = db_get_student_history(s_id)
    text = f"📅 **{m['fio']} uchun kunlik tarix arxivi:**\n\n"
    if history:
        for date_str, dav, t_score, g_score, v_score in history:
            text += f"🗓 **Sana: {date_str}**\n   📌 Davomat: {dav} | 📜 Tarix test: {t_score}% | 🌍 Geo test: {g_score}% | 📑 Vazifa: {v_score}%\n\n"
    else:
        text += "_Hozircha kunlik tarix yozuvlari mavjud emas._"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kabinetga qaytish", callback_data="auth_parent")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("get_student_card_img_"))
async def send_student_card_img(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[4])
    data = db_get_all()
    m = data.get(s_id)
    if not m:
        await call.answer("Xatolik!", show_alert=True)
        return

    msg = await call.message.answer("⏳ Shaxsiy karta tayyorlanmoqda...")
    sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
    rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == m["fio"]), 1)
    badge = "💎 Diamond" if m["tarix"] >= 90 else ("🥇 Oltin" if m["tarix"] >= 75 else "🥈 Kumush")

    img_bytes = create_student_card_image(m, rank, badge)
    await call.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="student_card_950x602.png"), caption=f"🖼 **{m['fio']} uchun Shaxsiy Natijalar Kartasi**", parse_mode="Markdown")
    await safe_delete_message(msg)

@dp.callback_query(F.data == "set_phone_number")
async def set_phone_number_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_phone)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("📞 **Bog'lanish uchun telefon raqamingizni kiriting:**\n\n_Masalan: +998901234567_", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_phone, F.chat.type == "private")
async def process_phone_number(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    state_data = await state.get_data()
    student_phone_id = state_data.get("student_phone_id")

    if student_phone_id:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE students SET phone = ? WHERE id = ?", (phone, int(student_phone_id)))
            conn.commit()
        await state.update_data(student_phone_id=None)
        await state.set_state(None)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 O'quvchi kabinetiga qaytish", callback_data="student_cabinet")]])
        await send_and_clean_both(message, "✅ Telefon raqamingiz muvaffaqiyatli saqlandi!", reply_markup=kb, delay=45)
        return

    await state.clear()
    children = db_get_parent_children(message.chat.id)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for ch in children:
            cursor.execute("UPDATE students SET phone = ? WHERE code = ?", (phone, ch["code"]))
        conn.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Kabinetga qaytish", callback_data="auth_parent")]])
    await send_and_clean_both(message, "✅ Telefon raqamingiz muvaffaqiyatli saqlandi!", reply_markup=kb, delay=45)

@dp.callback_query(F.data == "faq_menu")
async def faq_menu(call: types.CallbackQuery):
    await call.answer()
    text = (
        "❓ **Ko'p Beriladigan Savollar (FAQ):**\n\n"
        "1. **Botga qanday ulanaman?**\n"
        "   _Ro'yxatdan farzandingiz ismini tanlang yoki 4 xonali kodi orqali bog'laning._\n\n"
        "2. **To'lov qachon amalga oshirilishi kerak?**\n"
        "   _Har oyning 1-chisidan 5-chisigacha._\n\n"
        "3. **Kabinetga nechta farzand qo'shsa bo'ladi?**\n"
        "   _Bitta kabinetga 3 tagacha farzand biriktirishingiz mumkin._"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "view_school_calendar")
async def view_school_calendar(call: types.CallbackQuery):
    await call.answer()
    events = db_get_events()
    text = "📅 **Maktab va Kurs Taqvim Tadbirlari:**\n\n"
    if events:
        for idx, (_, title, date_str) in enumerate(events, 1):
            text += f"{idx}. **{title}**\n   🕒 Vaqti: _{date_str}_\n\n"
    else:
        text += "_Hozircha tadbirlar belgilanmagan._"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("send_leave_req_"))
async def send_leave_req(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    s_id = int(call.data.split("_")[3])
    await state.update_data(leave_student_id=s_id)
    await state.set_state(ParentStates.waiting_for_leave_reason)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("📝 **Farzandingiz darsga kelolmasligi sababini yozing:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_leave_reason, F.chat.type == "private")
async def process_leave_reason(message: types.Message, state: FSMContext):
    reason = message.text.strip()
    state_data = await state.get_data()
    s_id = state_data.get("leave_student_id")
    await state.clear()

    data = db_get_all()
    student_name = data[s_id]["fio"] if s_id in data else "O'quvchi"
    admins = db_get_admins()
    for admin_id in admins:
        try:
            await bot.send_message(
                admin_id, 
                f"🚨 **Sababli kelmaslik arizasi!**\n\n👤 O'quvchi: **{student_name}**\n✍️ Sabab: {reason}", 
                parse_mode="Markdown"
            )
        except Exception:
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]])
    await send_and_clean_both(message, "✅ **Arizangiz o'qituvchiga yetkazildi!**", reply_markup=kb, delay=45)

@dp.callback_query(F.data == "reset_account")
async def reset_account(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM parent_children WHERE parent_chat_id = ?", (call.from_user.id,))
        conn.commit()
    await call.message.answer("🔄 Profil muvaffaqiyatli uzildi.")

@dp.callback_query(F.data == "back_home")
async def back_home(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 O'quvchi Kabineti", callback_data="student_login_prompt"), InlineKeyboardButton(text="👨‍👩‍👧‍👦 Ota-ona Kabineti", callback_data="auth_parent")],
            [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar")],
            [InlineKeyboardButton(text="🔐 O'qituvchi Paneli", callback_data="teacher_login_prompt"), InlineKeyboardButton(text="⚙️ Super Admin Paneli", callback_data="super_admin_login_prompt")],
            [InlineKeyboardButton(text="❓ Ko'p Savollar (FAQ)", callback_data="faq_menu")]
        ]
    )
    await call.message.edit_text("✨ **Maktab va Kurs Boshqaruv Tizimiga Xush Kelibsiz!**\n\n_Quyidagi bo'limlardan birini tanlang._", reply_markup=kb, parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
