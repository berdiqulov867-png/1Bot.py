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

TOKEN = "8875022301:AAG_oa4lSl30b0YjHnY7ur89Y2J-KGOxCyY"
DEFAULT_ADMIN_PASSWORD = "1234"

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_NAME = "school_bot_pro_v20.db"

# --- 1. MA'LUMOTLAR BAZASI ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fio TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                parent_chat_id INTEGER DEFAULT 0,
                tarix INTEGER DEFAULT 0,
                geo INTEGER DEFAULT 0,
                vazifa INTEGER DEFAULT 0,
                davomat TEXT DEFAULT 'Keldi',
                payment_amount INTEGER DEFAULT 0,
                payment_status TEXT DEFAULT 'To''lanmagan',
                payment_date TEXT DEFAULT '-',
                phone TEXT DEFAULT 'Kiritilmagan',
                group_name TEXT DEFAULT 'Asosiy guruh'
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
        
        # Boshlang'ich parolni bazaga yozish
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_password'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO settings (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASSWORD,))
            
        conn.commit()

init_db()

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
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, fio, code, tarix, geo, vazifa, parent_chat_id, davomat, payment_amount, payment_status, payment_date, phone, group_name FROM students")
        rows = cursor.fetchall()
        return {
            r[0]: {
                "fio": r[1], "code": r[2], "tarix": r[3],
                "geo": r[4], "vazifa": r[5], "parent_chat_id": r[6], 
                "davomat": r[7] if r[7] else "Keldi",
                "payment_amount": r[8] if r[8] else 0,
                "payment_status": r[9] if r[9] else "To'lanmagan",
                "payment_date": r[10] if r[10] else "-",
                "phone": r[11] if r[11] else "Kiritilmagan",
                "group_name": r[12] if r[12] else "Asosiy guruh"
            } for r in rows
        }

def db_add_student(fio, code):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO students (fio, code) VALUES (?, ?)", (fio, code))
        conn.commit()

def db_delete_student(s_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM students WHERE id = ?", (s_id,))
        cursor.execute("DELETE FROM attendance_history WHERE student_id = ?", (s_id,))
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
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE students SET {field} = MAX(0, MIN(100, ?)) WHERE id = ?", (value, s_id))
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

def db_add_admin(chat_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (chat_id,))
        conn.commit()

def db_get_admins():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM admins")
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
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET parent_chat_id = ? WHERE id = ?", (parent_chat_id, student_id))
        conn.commit()

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
    waiting_for_student_name = State()
    waiting_for_broadcast = State()
    waiting_for_event_title = State()
    waiting_for_event_date = State()
    waiting_for_admin_note = State()
    waiting_for_custom_payment = State()
    waiting_for_channel_id = State()
    waiting_for_search_query = State()

class ParentStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_message_to_teacher = State()
    waiting_for_homework = State()
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

# --- 3. RASM GENERATORLARI (950x602) ---
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
    draw.text((40, 155), f"Reyting o'rni: {rank}-o'rin  |  Darajasi: {badge}", fill="#0369A1", font=bold_font)
    
    pay_text = f"To'lov: {student['payment_status']} ({student['payment_amount']:,} so'm)"
    draw.text((550, 120), pay_text, fill="#334155", font=font)
    draw.text((550, 155), f"Davomat: {student['davomat']} | Tel: {student['phone']}", fill="#334155", font=font)

    sub_y = 220
    draw.rectangle([20, sub_y, 930, sub_y + 40], fill="#E0F2FE", outline="#0284C7", width=2)
    draw.text((50, sub_y + 20), "Fan / Bo'lim", fill="#0369A1", font=bold_font, anchor="lm")
    draw.text((450, sub_y + 20), "O'zlashtirish foizi", fill="#0369A1", font=bold_font, anchor="mm")
    draw.text((800, sub_y + 20), "Baholash", fill="#0369A1", font=bold_font, anchor="mm")

    subjects = [("Tarix fani", student["tarix"]), ("Geografiya fani", student["geo"]), ("Uy vazifasi", student["vazifa"])]
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
    avg = (student["tarix"] + student["geo"] + student["vazifa"]) // 3
    draw.text((40, footer_y + 30), f"Umumiy o'rtacha ko'rsatkich: {avg}%", fill="#0F172A", font=bold_font, anchor="lm")
    draw.text((910, footer_y + 30), f"Sana: {datetime.now().strftime('%d.%m.%Y')}", fill="#64748B", font=font, anchor="rm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def create_daily_report_image(data):
    img = Image.new("RGB", (950, 602), color="#FFFFFF")
    draw = ImageDraw.Draw(img)
    font = get_font(14)
    bold_font = get_font(14, bold=True)
    title_font = get_font(20, bold=True)

    draw.rectangle([20, 20, 930, 75], fill="#1E40AF")
    today_date = datetime.now().strftime("%d.%m.%Y")
    draw.text((475, 47), f"O'QUV MARKAZ / MAKTAB KUNLIK HISOBOTI ({today_date})", fill="#FFFFFF", font=title_font, anchor="mm")

    if not data:
        draw.text((475, 300), "Hozircha o'quvchilar bazada yo'q!", fill="#EF4444", font=title_font, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()

    col_tr, col_fio, col_dav, col_sub, col_avg = 55, 350, 120, 115, 170
    sub_y = 90
    headers = [("T/R", col_tr), ("F.I.O", col_fio), ("DAVOMAT", col_dav), ("TARIX", col_sub), ("GEO", col_sub), ("VAZIFA", col_sub), ("O'RTACHA", col_avg)]
    
    curr_x = 20
    for title, w in headers:
        draw.rectangle([curr_x, sub_y, curr_x + w, sub_y + 35], fill="#DBEAFE", outline="#1E3A8A", width=2)
        draw.text((curr_x + w // 2, sub_y + 17), title, fill="#000000", font=bold_font, anchor="mm")
        curr_x += w

    y = sub_y + 35
    row_height = 42
    max_rows = 10  
    
    for idx, (s_id, item) in enumerate(list(data.items())[:max_rows], 1):
        x = 20
        draw.rectangle([x, y, x + col_tr, y + row_height], outline="#94A3B8")
        draw.text((x + col_tr // 2, y + row_height // 2), str(idx), fill="#000000", font=bold_font, anchor="mm")
        x += col_tr

        draw.rectangle([x, y, x + col_fio, y + row_height], outline="#94A3B8")
        draw.text((x + 15, y + row_height // 2), item["fio"], fill="#000000", font=bold_font, anchor="lm")
        x += col_fio

        dav_status = item.get("davomat", "Keldi")
        dav_bg = "#A7F3D0" if dav_status == "Keldi" else ("#FECACA" if dav_status == "Kelmadi" else "#FEF08A")
        draw.rectangle([x, y, x + col_dav, y + row_height], fill=dav_bg, outline="#94A3B8")
        draw.text((x + col_dav // 2, y + row_height // 2), dav_status, fill="#000000", font=bold_font, anchor="mm")
        x += col_dav

        for val in [item["tarix"], item["geo"], item["vazifa"]]:
            draw.rectangle([x, y, x + col_sub, y + row_height], outline="#94A3B8")
            draw.text((x + col_sub // 2, y + row_height // 2), f"{val}%", fill="#000000", font=font, anchor="mm")
            x += col_sub

        avg_val = (item["tarix"] + item["geo"] + item["vazifa"]) // 3
        draw.rectangle([x, y, x + col_avg, y + row_height], fill="#FEF3C7", outline="#94A3B8")
        draw.text((x + col_avg // 2, y + row_height // 2), f"{avg_val}% o'rtacha", fill="#D97706", font=bold_font, anchor="mm")

        y += row_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def create_leaderboard_image(data):
    img = Image.new("RGB", (950, 602), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    bold_font = get_font(16, bold=True)
    title_font = get_font(20, bold=True)

    draw.rectangle([20, 20, 930, 75], fill="#7C3AED")
    draw.text((475, 47), "🏆 TOP O'QUVCHILAR REYTINGI (TOP 10)", fill="#FFFFFF", font=title_font, anchor="mm")

    sorted_students = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)[:10]

    sub_y = 90
    headers = [("O'RIN", 90), ("O'QUVCHI F.I.O", 500), ("O'RTACHA BALL", 320)]
    curr_x = 20
    for title, w in headers:
        draw.rectangle([curr_x, sub_y, curr_x + w, sub_y + 35], fill="#EDE9FE", outline="#5B21B6", width=2)
        draw.text((curr_x + w // 2, sub_y + 17), title, fill="#000000", font=bold_font, anchor="mm")
        curr_x += w

    y = sub_y + 35
    row_height = 42
    for idx, item in enumerate(sorted_students, 1):
        x = 20
        medal = "🥇 1-o'rin" if idx == 1 else ("🥈 2-o'rin" if idx == 2 else ("🥉 3-o'rin" if idx == 3 else f"{idx}-o'rin"))
        
        draw.rectangle([x, y, x + 90, y + row_height], outline="#CBD5E1")
        draw.text((x + 45, y + row_height // 2), medal, fill="#000000", font=bold_font, anchor="mm")
        x += 90

        draw.rectangle([x, y, x + 500, y + row_height], outline="#CBD5E1")
        draw.text((x + 15, y + row_height // 2), item["fio"], fill="#000000", font=bold_font, anchor="lm")
        x += 500

        avg_score = (item["tarix"] + item["geo"] + item["vazifa"]) // 3
        draw.rectangle([x, y, x + 320, y + row_height], fill="#FEF3C7", outline="#CBD5E1")
        draw.text((x + 160, y + row_height // 2), f"{avg_score}%", fill="#D97706", font=bold_font, anchor="mm")

        y += row_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

# --- 4. BOT HANDLERLARI ---

@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Ota-ona / Kabinet", callback_data="auth_parent"), InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar")],
            [InlineKeyboardButton(text="❓ Ko'p Savollar (FAQ)", callback_data="faq_menu")]
        ]
    )
    await message.answer("✨ **Maktab va Kurs Boshqaruv Tizimiga Xush Kelibsiz!**\n\n_O'qituvchi bo'lsangiz /admin buyrug'ini yuboring._", reply_markup=kb, parse_mode="Markdown")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_password)
    await message.answer("🔐 **O'qituvchi paneliga kirish uchun parolni kiriting:**", parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_password)
async def check_admin_password(message: types.Message, state: FSMContext):
    current_pass = db_get_admin_password()
    if message.text == current_pass:
        db_add_admin(message.chat.id)
        await state.clear()
        await show_teacher_panel_msg(message)
    else:
        await message.answer("❌ **Parol noto'g'ri!** Qaytadan urinib ko'ring yoki /start bosing.", parse_mode="Markdown")

async def show_teacher_panel_msg(message: types.Message):
    channel = db_get_setting("channel_id") or "Ulanmagan"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi O'quvchi", callback_data="add_student"), InlineKeyboardButton(text="🗑 O'quvchini O'chirish", callback_data="delete_student_menu")],
            [InlineKeyboardButton(text="📌 Davomat Belgilash", callback_data="manage_attendance"), InlineKeyboardButton(text="📝 Ballar Boshqaruvi", callback_data="manage_scores")],
            [InlineKeyboardButton(text="💳 Oylik To'lovlar", callback_data="manage_payments"), InlineKeyboardButton(text="🔍 O'quvchini Qidirish", callback_data="search_student")],
            [InlineKeyboardButton(text="📅 Taqvim va Tadbirlar", callback_data="manage_calendar"), InlineKeyboardButton(text="📝 Shaxsiy Eslatmalar", callback_data="admin_notes_list")],
            [InlineKeyboardButton(text="📋 O'quvchilar & Kodlar", callback_data="list_students_admin"), InlineKeyboardButton(text="📊 Admin Dashboard", callback_data="admin_dashboard")],
            [InlineKeyboardButton(text="📅 Kunlik Hisobot (950x602)", callback_data="get_daily_img"), InlineKeyboardButton(text="🏆 Reyting (950x602)", callback_data="get_leaderboard_img")],
            [InlineKeyboardButton(text="📢 Kanalni Sozlash", callback_data="setup_channel"), InlineKeyboardButton(text="🚀 Kanalga Rasm Yuborish", callback_data="post_to_channel")],
            [InlineKeyboardButton(text="🔑 Parolni O'zgartirish", callback_data="change_password_start"), InlineKeyboardButton(text="📢 E'lon Yuborish", callback_data="broadcast_start")],
            [InlineKeyboardButton(text="🔙 Chiqish", callback_data="back_home")]
        ]
    )
    await message.answer(f"👨‍🏫 **O'qituvchi Boshqaruv Paneli:**\n\n📢 Ulangan kanal: `{channel}`", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "panel_teacher")
async def teacher_panel_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    channel = db_get_setting("channel_id") or "Ulanmagan"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi O'quvchi", callback_data="add_student"), InlineKeyboardButton(text="🗑 O'quvchini O'chirish", callback_data="delete_student_menu")],
            [InlineKeyboardButton(text="📌 Davomat Belgilash", callback_data="manage_attendance"), InlineKeyboardButton(text="📝 Ballar Boshqaruvi", callback_data="manage_scores")],
            [InlineKeyboardButton(text="💳 Oylik To'lovlar", callback_data="manage_payments"), InlineKeyboardButton(text="🔍 O'quvchini Qidirish", callback_data="search_student")],
            [InlineKeyboardButton(text="📅 Taqvim va Tadbirlar", callback_data="manage_calendar"), InlineKeyboardButton(text="📝 Shaxsiy Eslatmalar", callback_data="admin_notes_list")],
            [InlineKeyboardButton(text="📋 O'quvchilar & Kodlar", callback_data="list_students_admin"), InlineKeyboardButton(text="📊 Admin Dashboard", callback_data="admin_dashboard")],
            [InlineKeyboardButton(text="📅 Kunlik Hisobot (950x602)", callback_data="get_daily_img"), InlineKeyboardButton(text="🏆 Reyting (950x602)", callback_data="get_leaderboard_img")],
            [InlineKeyboardButton(text="📢 Kanalni Sozlash", callback_data="setup_channel"), InlineKeyboardButton(text="🚀 Kanalga Rasm Yuborish", callback_data="post_to_channel")],
            [InlineKeyboardButton(text="🔑 Parolni O'zgartirish", callback_data="change_password_start"), InlineKeyboardButton(text="📢 E'lon Yuborish", callback_data="broadcast_start")],
            [InlineKeyboardButton(text="🔙 Chiqish", callback_data="back_home")]
        ]
    )
    await call.message.edit_text(f"👨‍🏫 **O'qituvchi Boshqaruv Paneli:**\n\n📢 Ulangan kanal: `{channel}`", reply_markup=kb, parse_mode="Markdown")

# PAROLNI O'ZGARTIRISH BO'LIMI
@dp.callback_query(F.data == "change_password_start")
async def change_password_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_new_password)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("🔑 **Admin paneli uchun yangi parolni kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_new_password)
async def process_new_password(message: types.Message, state: FSMContext):
    new_pass = message.text.strip()
    if len(new_pass) < 3:
        await message.answer("❌ Parol juda qisqa! Kamida 3 ta belgi bo'lishi kerak:")
        return
    
    db_set_admin_password(new_pass)
    await state.clear()
    await message.answer(f"✅ **Admin paroli muvaffaqiyatli o'zgartirildi!**\nYangi parol: `{new_pass}`", parse_mode="Markdown")
    await show_teacher_panel_msg(message)

# O'QUVCHINI O'CHIRISH
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
        row.append(InlineKeyboardButton(text=f"🗑 {d1['fio'][:12]}", callback_data=f"confirm_del_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            row.append(InlineKeyboardButton(text=f"🗑 {d2['fio'][:12]}", callback_data=f"confirm_del_{s_id2}"))
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

# QIDIRUV TIZIMI
@dp.callback_query(F.data == "search_student")
async def search_student_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_search_query)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("🔍 **O'quvchining ismi yoki 4 xonali kodini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_search_query)
async def process_search_query(message: types.Message, state: FSMContext):
    query = message.text.strip().lower()
    await state.clear()
    data = db_get_all()
    
    results = [d for d in data.values() if query in d["fio"].lower() or query == d["code"]]
    if not results:
        await message.answer("❌ **Natija topilmadi!**")
        await show_teacher_panel_msg(message)
        return

    text = f"🔍 **Qidiruv natijalari ({len(results)} ta):**\n\n"
    for r in results:
        avg = (r["tarix"] + r["geo"] + r["vazifa"]) // 3
        text += f"🔹 **{r['fio']}**\n   🔑 Kod: `{r['code']}` | O'rtacha: {avg}%\n   📌 Davomat: {r['davomat']} | To'lov: {r['payment_status']}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Panalga qaytish", callback_data="panel_teacher")]])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# KANAL SOZLASH VA AVTO-RASM JOYLANDIGAN BO'LIM
@dp.callback_query(F.data == "setup_channel")
async def setup_channel_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_channel_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("📢 **Kanal username (masalan `@kanalim`) yoki Kanal ID sini kiriting:**\n\n_Eslatma: Bot kanalda administrator bo'lishi kerak!_", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    ch_id = message.text.strip()
    db_set_setting("channel_id", ch_id)
    await state.clear()
    await message.answer(f"✅ **Kanal muvaffaqiyatli saqlandi:** `{ch_id}`", parse_mode="Markdown")
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data == "post_to_channel")
async def post_to_channel_cb(call: types.CallbackQuery):
    await call.answer()
    channel_id = db_get_setting("channel_id")
    if not channel_id:
        await call.answer("❌ Avval kanalni sozlang!", show_alert=True)
        return

    await call.message.answer("⏳ **Hisobot rasmi kanalga yuklanmoqda...**")
    data = db_get_all()
    img_bytes = create_daily_report_image(data)
    
    try:
        await bot.send_photo(
            chat_id=channel_id,
            photo=BufferedInputFile(img_bytes, filename="daily_report.png"),
            caption=f"📊 **O'quvchilarning Bugungi Kunlik Ballari va Davomat Hisoboti**\n📅 Sana: {datetime.now().strftime('%d.%m.%Y')}\n\n✨ _Tizim avtomatik yangilandi._"
        )
        await call.message.answer("✅ **O'quvchilar natijalari kanalga rasm qilib muvaffaqiyatli tashlandi!**")
    except Exception as e:
        await call.message.answer(f"❌ **Kanalga yuborishda xatolik:** {e}\n\n_Bot kanalda administrator ekanini va kanal usernamesi to'g'riligini bering._")

# ADMIN DASHBOARD
@dp.callback_query(F.data == "admin_dashboard")
async def admin_dashboard(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    total_students = len(data)
    paid_count = sum(1 for d in data.values() if d["payment_status"] == "To'langan")
    unpaid_count = total_students - paid_count
    total_sum = sum(d["payment_amount"] for d in data.values() if d["payment_status"] == "To'langan")
    
    avg_all = 0
    if total_students > 0:
        avg_all = sum((d["tarix"] + d["geo"] + d["vazifa"]) // 3 for d in data.values()) // total_students

    text = (
        f"📊 **Admin Dashboard & Umumiy Statistika:**\n\n"
        f"👥 Jami o'quvchilar: **{total_students} ta**\n"
        f"✅ To'laganlar: **{paid_count} ta**\n"
        f"❌ To'lamaganlar: **{unpaid_count} ta**\n"
        f"💰 Yig'ilgan to'lov: **{total_sum:,} so'm**\n"
        f"📈 O'rtacha o'zlashtirish: **{avg_all}%**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# ADMIN NOTES (NOTEPAD)
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

@dp.message(AdminStates.waiting_for_admin_note)
async def process_admin_note(message: types.Message, state: FSMContext):
    note = message.text.strip()
    await state.clear()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO admin_notes (note_text) VALUES (?)", (note,))
        conn.commit()
    await message.answer("✅ Eslatma saqlandi!")
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

# ADMIN TAQVIMNI BOSHQARISH
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

@dp.message(AdminStates.waiting_for_event_title)
async def process_event_title(message: types.Message, state: FSMContext):
    await state.update_data(event_title=message.text.strip())
    await state.set_state(AdminStates.waiting_for_event_date)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="manage_calendar")]])
    await message.answer("📅 **Tadbir yoki imtihon vaqtini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_event_date)
async def process_event_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("event_title")
    date_str = message.text.strip()
    db_add_event(title, date_str)
    await state.clear()
    await message.answer(f"✅ **Tadbir qo'shildi:**\n\n📌 {title}\n📅 {date_str}", parse_mode="Markdown")
    await show_teacher_panel_msg(message)

@dp.callback_query(F.data.startswith("del_ev_"))
async def delete_event_cb(call: types.CallbackQuery):
    await call.answer()
    ev_id = int(call.data.split("_")[2])
    db_delete_event(ev_id)
    await manage_calendar(call)

# O'QUVCHI QO'SHISH
@dp.callback_query(F.data == "add_student")
async def add_student_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_student_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("👤 **Yangi o'quvchining F.I.O. sini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_student_name)
async def save_student_name(message: types.Message, state: FSMContext):
    fio = message.text.strip()
    code = str(random.randint(1000, 9999))
    db_add_student(fio, code)
    await state.clear()
    await message.answer(f"✅ O'quvchi **{fio}** bazaga qo'shildi!\n🔑 Kirish kodi: `{code}`", parse_mode="Markdown")
    await show_teacher_panel_msg(message)

# DAVOMAT TUGMALARI
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
        row.append(InlineKeyboardButton(text=f"{st_icon1} {d1['fio'][:12]}", callback_data=f"set_att_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            st_icon2 = "✅" if d2["davomat"] == "Keldi" else ("❌" if d2["davomat"] == "Kelmadi" else "🟡")
            row.append(InlineKeyboardButton(text=f"{st_icon2} {d2['fio'][:12]}", callback_data=f"set_att_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("📌 **Davomatni o'zgartirish uchun o'quvchini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_att_"))
async def set_attendance_status(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Keldi", callback_data=f"save_att_{s_id}_Keldi"), InlineKeyboardButton(text="❌ Kelmadi", callback_data=f"save_att_{s_id}_Kelmadi")],
            [InlineKeyboardButton(text="🟡 Sababli", callback_data=f"save_att_{s_id}_Sababli"), InlineKeyboardButton(text="⬅️ Orqaga", callback_data="manage_attendance")]
        ]
    )
    await call.message.edit_text("📌 **Statusni tanlang:**", reply_markup=kb)

@dp.callback_query(F.data.startswith("save_att_"))
async def save_attendance_status(call: types.CallbackQuery):
    await call.answer()
    _, _, s_id, status = call.data.split("_")
    s_id = int(s_id)
    db_update_attendance(s_id, status)
    
    data = db_get_all()
    student = data.get(s_id)
    if student and student["parent_chat_id"] != 0:
        try:
            await bot.send_message(student["parent_chat_id"], f"📌 **Farzandingiz ({student['fio']}) davomati:** {status}", parse_mode="Markdown")
        except Exception:
            pass

    await manage_attendance(call)

# BALLARni BOSHQARUVI
@dp.callback_query(F.data == "manage_scores")
async def manage_scores(call: types.CallbackQuery):
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
        avg1 = (d1["tarix"] + d1["geo"] + d1["vazifa"]) // 3
        row.append(InlineKeyboardButton(text=f"📝 {d1['fio'][:10]} ({avg1}%)", callback_data=f"sc_st_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            avg2 = (d2["tarix"] + d2["geo"] + d2["vazifa"]) // 3
            row.append(InlineKeyboardButton(text=f"📝 {d2['fio'][:10]} ({avg2}%)", callback_data=f"sc_st_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")])
    await call.message.edit_text("📝 **Ball kiritish uchun o'quvchini tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("sc_st_"))
async def sc_select_student(call: types.CallbackQuery):
    await call.answer()
    s_id = int(call.data.split("_")[2])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 Tarix balli", callback_data=f"sc_fld_{s_id}_tarix"), InlineKeyboardButton(text="🌍 Geografiya balli", callback_data=f"sc_fld_{s_id}_geo")],
            [InlineKeyboardButton(text="📑 Uy vazifasi balli", callback_data=f"sc_fld_{s_id}_vazifa"), InlineKeyboardButton(text="⬅️ Orqaga", callback_data="manage_scores")]
        ]
    )
    await call.message.edit_text("📝 **Qaysi bo'limni o'zgartirmoqchisiz?**", reply_markup=kb)

@dp.callback_query(F.data.startswith("sc_fld_"))
async def sc_select_field(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    s_id, field = int(parts[2]), parts[3]
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="10%", callback_data=f"sc_set_{s_id}_{field}_10"), InlineKeyboardButton(text="30%", callback_data=f"sc_set_{s_id}_{field}_30")],
            [InlineKeyboardButton(text="50%", callback_data=f"sc_set_{s_id}_{field}_50"), InlineKeyboardButton(text="70%", callback_data=f"sc_set_{s_id}_{field}_70")],
            [InlineKeyboardButton(text="90%", callback_data=f"sc_set_{s_id}_{field}_90"), InlineKeyboardButton(text="100%", callback_data=f"sc_set_{s_id}_{field}_100")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"sc_st_{s_id}")]
        ]
    )
    await call.message.edit_text(f"📊 **{field.upper()} uchun foizni tanlang:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("sc_set_"))
async def sc_apply_value(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split("_")
    _, _, s_id, field, val = parts[0], parts[1], int(parts[2]), parts[3], int(parts[4])
    
    db_set_score_exact(s_id, field, val)
    data = db_get_all()
    student = data.get(s_id)
    
    if student and student["parent_chat_id"] != 0:
        try:
            msg = (
                f"📊 **Farzandingiz ({student['fio']}) natijalari yangilandi:**\n\n"
                f"📜 Tarix: **{student['tarix']}%**\n"
                f"🌍 Geografiya: **{student['geo']}%**\n"
                f"📑 Vazifa: **{student['vazifa']}%**"
            )
            await bot.send_message(student["parent_chat_id"], msg, parse_mode="Markdown")
        except Exception:
            pass

    await call.message.edit_text(f"✅ **{student['fio']}** uchun o'zgarish saqlandi!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="panel_teacher")]]))

# OYLIK TO'LOV BOSHQARUVI
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
        row.append(InlineKeyboardButton(text=f"{st_icon1} {d1['fio'][:10]}", callback_data=f"pay_st_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            st_icon2 = "✅" if d2["payment_status"] == "To'langan" else "❌"
            row.append(InlineKeyboardButton(text=f"{st_icon2} {d2['fio'][:10]}", callback_data=f"pay_st_{s_id2}"))
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
    await call.message.edit_text("💰 **Oylik to'lov summasini kiriting (faqat raqamlarda):**\n\n_Masalan: 180000_", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_custom_payment)
async def process_custom_payment(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting (masalan: 180000):")
        return
    
    amount = int(message.text.strip())
    state_data = await state.get_data()
    s_id = state_data.get("pay_student_id")
    
    db_update_payment_amount(s_id, amount)
    await state.clear()
    await message.answer(f"✅ Oylik to'lov summasi **{amount:,} so'm** qilib belgilandi!", parse_mode="Markdown")
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
        if student["parent_chat_id"] != 0:
            try:
                msg = f"✅ **Farzandingiz ({student['fio']}) ning to'lovi qabul qilindi!**" if new_status == "To'langan" else f"⚠️ **To'lov holati 'To'lanmagan'ga o'zgartirildi.**"
                await bot.send_message(student["parent_chat_id"], msg, parse_mode="Markdown")
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

# RASMLI JADVALLAR (950x602)
@dp.callback_query(F.data == "get_daily_img")
async def send_daily_table(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("⏳ 950x602 o'lchamdagi hisobot tayyorlanmoqda...")
    data = db_get_all()
    img_bytes = create_daily_report_image(data)
    await call.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="daily_950x602.png"), caption="📌 **Kunlik Hisobot (950x602)**", parse_mode="Markdown")

@dp.callback_query(F.data == "get_leaderboard_img")
async def send_leaderboard_table(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("⏳ 950x602 o'lchamdagi reyting tayyorlanmoqda...")
    data = db_get_all()
    img_bytes = create_leaderboard_image(data)
    await call.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="leaderboard_950x602.png"), caption="🏆 **O'quvchilar Reytingi (950x602)**", parse_mode="Markdown")

# OMMAVIY XABAR
@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_for_broadcast)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="panel_teacher")]])
    await call.message.edit_text("📢 **Barcha ota-onalarga yubormoqchi bo'lgan e'loningizni yozing:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_broadcast)
async def broadcast_send(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    data = db_get_all()
    sent_count = 0
    for student in data.values():
        if student["parent_chat_id"] != 0:
            try:
                await bot.send_message(student["parent_chat_id"], f"📢 **E'lon:**\n\n{text}", parse_mode="Markdown")
                sent_count += 1
            except Exception:
                pass
    await message.answer(f"✅ Xabar muvaffaqiyatli **{sent_count} ta** ota-onaga yuborildi!")
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
        text += f"🔹 **{d['fio']}** — KOD: `{d['code']}` | Tel: {d['phone']}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="panel_teacher")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# --- 5. OTA-ONA / O'QUVCHI KABINETI ---
@dp.callback_query(F.data == "auth_parent")
async def open_parent_cabinet(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = db_get_all()
    matched = next(((s_id, d) for s_id, d in data.items() if d["parent_chat_id"] == call.from_user.id), None)

    if matched:
        s_id, m = matched
        sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
        rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == m["fio"]), 1)

        avg = (m["tarix"] + m["geo"] + m["vazifa"]) // 3
        badge = "💎 Diamond" if avg >= 90 else ("🥇 Oltin" if avg >= 75 else ("🥈 Kumush" if avg >= 60 else "🥉 Bronza"))
        pay_icon = "🟢" if m["payment_status"] == "To'langan" else "🔴"

        text = (
            f"📊 **Farzandingiz Shaxsiy Nazorat Paneli:**\n\n"
            f"👤 O'quvchi: **{m['fio']}**\n"
            f"🏆 Reyting: **{rank}-o'rin** | 🏅 Daraja: **{badge}**\n"
            f"📌 Davomat: **{m['davomat']}** | 💳 To'lov: **{pay_icon} {m['payment_status']}**\n"
            f"📞 Telefon: `{m['phone']}`\n"
            f"📈 O'rtacha o'zlashtirish: **{avg}%**"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🖼 Shaxsiy Natijalar Kartasi", callback_data="get_student_card_img"), InlineKeyboardButton(text="📅 Kunlik Tarix", callback_data="view_full_history")],
                [InlineKeyboardButton(text="📚 Darslar Jadvali", callback_data="view_school_calendar"), InlineKeyboardButton(text="📞 Telefon raqam", callback_data="set_phone_number")],
                [InlineKeyboardButton(text="📝 Sababli Ariza", callback_data="send_leave_req"), InlineKeyboardButton(text="⭐ So'rovnoma", callback_data="feedback_menu")],
                [InlineKeyboardButton(text="✉️ O'qituvchiga Xabar", callback_data="parent_send_msg"), InlineKeyboardButton(text="🔄 Kabinetni Uzish", callback_data="reset_account")],
                [InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]
            ]
        )
        await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Ro'yxatdan tanlash", callback_data="reg_select_list"), InlineKeyboardButton(text="🔑 Kod bilan kirish", callback_data="reg_enter_code")],
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_home")]
            ]
        )
        await call.message.edit_text("👨‍👩‍👧‍👦 **Kabinetga kirish uchun usulni tanlang:**", reply_markup=kb, parse_mode="Markdown")

# BARCHA KUNLIK TARIXNI KO'RISH
@dp.callback_query(F.data == "view_full_history")
async def view_full_history(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    matched = next(((s_id, d) for s_id, d in data.items() if d["parent_chat_id"] == call.from_user.id), None)
    if not matched:
        await call.answer("Xatolik!", show_alert=True)
        return

    s_id, m = matched
    history = db_get_student_history(s_id)

    text = f"📅 **{m['fio']} uchun barcha kunlik tarix arxivi:**\n\n"
    if history:
        for date_str, dav, t_score, g_score, v_score in history:
            avg_h = (t_score + g_score + v_score) // 3
            text += f"🗓 **Sana: {date_str}**\n   📌 Davomat: {dav} | 📜 Tarix: {t_score}% | 🌍 Geo: {g_score}% | 📑 Vazifa: {v_score}% (O'rtacha: {avg_h}%)\n\n"
    else:
        text += "_Hozircha kunlik tarix yozuvlari mavjud emas._"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kabinetga qaytish", callback_data="auth_parent")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "get_student_card_img")
async def send_student_card_img(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("⏳ 950x602 o'lchamdagi shaxsiy karta tayyorlanmoqda...")
    data = db_get_all()
    matched = next(((s_id, d) for s_id, d in data.items() if d["parent_chat_id"] == call.from_user.id), None)
    
    if not matched:
        await call.answer("Xatolik!", show_alert=True)
        return

    s_id, m = matched
    sorted_all = sorted(data.values(), key=lambda x: (x["tarix"] + x["geo"] + x["vazifa"]), reverse=True)
    rank = next((i for i, item in enumerate(sorted_all, 1) if item["fio"] == m["fio"]), 1)
    avg = (m["tarix"] + m["geo"] + m["vazifa"]) // 3
    badge = "💎 Diamond" if avg >= 90 else ("🥇 Oltin" if avg >= 75 else ("🥈 Kumush" if avg >= 60 else "🥉 Bronza"))

    img_bytes = create_student_card_image(m, rank, badge)
    await call.message.answer_photo(photo=BufferedInputFile(img_bytes, filename="student_card_950x602.png"), caption=f"🖼 **{m['fio']} uchun Shaxsiy Natijalar Kartasi (950x602)**", parse_mode="Markdown")

# TELEFON RAQAM QO'SHISH
@dp.callback_query(F.data == "set_phone_number")
async def set_phone_number_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_phone)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("📞 **Bog'lanish uchun telefon raqamingizni kiriting:**\n\n_Masalan: +998901234567_", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_phone)
async def process_phone_number(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    await state.clear()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET phone = ? WHERE parent_chat_id = ?", (phone, message.chat.id))
        conn.commit()
    await message.answer("✅ Telefon raqamingiz muvaffaqiyatli saqlandi!")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Kabinetga qaytish", callback_data="auth_parent")]])
    await message.answer("Asosiy panel:", reply_markup=kb)

# FAQ BO'LIMI
@dp.callback_query(F.data == "faq_menu")
async def faq_menu(call: types.CallbackQuery):
    await call.answer()
    text = (
        "❓ **Ko'p Beriladigan Savollar (FAQ):**\n\n"
        "1. **Botga qanday ulanaman?**\n"
        "   _O'qituvchidan 4 xonali kodni oling yoki ro'yxatdan ismingizni tanlang._\n\n"
        "2. **To'lov qachon amalga oshirilishi kerak?**\n"
        "   _Har oyning 1-chisidan 5-chisigacha._\n\n"
        "3. **Ballar qanday hisoblanadi?**\n"
        "   _Tarix, Geografiya va Uy vazifasi foizlari asosida o'rtacha chiqariladi._"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# TAQVIM
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

# SABABLI ARIZA
@dp.callback_query(F.data == "send_leave_req")
async def send_leave_req(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_leave_reason)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("📝 **Farzandingiz darsga kelolmasligi sababini yozing:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_leave_reason)
async def process_leave_reason(message: types.Message, state: FSMContext):
    reason = message.text.strip()
    await state.clear()
    data = db_get_all()
    matched = next(((s_id, d) for s_id, d in data.items() if d["parent_chat_id"] == message.chat.id), None)
    student_name = matched[1]["fio"] if matched else "O'quvchi"
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
    await message.answer("✅ **Arizangiz o'qituvchiga yetkazildi!**", reply_markup=kb)


@dp.callback_query(F.data == "reg_select_list")
async def reg_select_list(call: types.CallbackQuery):
    await call.answer()
    data = db_get_all()
    free_students = {s_id: d for s_id, d in data.items() if d["parent_chat_id"] == 0}
    
    if not free_students:
        await call.answer("Bo'sh o'quvchilar yo'q!", show_alert=True)
        return

    buttons = []
    items = list(free_students.items())
    for i in range(0, len(items), 2):
        row = []
        s_id1, d1 = items[i]
        row.append(InlineKeyboardButton(text=f"👤 {d1['fio'][:12]}", callback_data=f"req_link_{s_id1}"))
        
        if i + 1 < len(items):
            s_id2, d2 = items[i+1]
            row.append(InlineKeyboardButton(text=f"👤 {d2['fio'][:12]}", callback_data=f"req_link_{s_id2}"))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="auth_parent")])
    await call.message.edit_text("📋 **Ro'yxatdan ismingizni tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

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
    await call.message.edit_text("⏳ **So'rov adminga yuborildi!**", reply_markup=kb, parse_mode="Markdown")

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
        await call.message.edit_text(f"✅ **Tasdiqlandi!** {student['fio']} uchun ruxsat berildi.")
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Kabinetni Ochish", callback_data="auth_parent")]])
            await bot.send_message(parent_chat_id, f"🎉 **Tabriklaymiz!** Admin kabinetingizni tasdiqladi.", reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    else:
        db_delete_pending(req_id)
        await call.message.edit_text(f"❌ **Rad etildi.**")
        try:
            await bot.send_message(parent_chat_id, "❌ Afsuski, admin so'rovingizni rad etdi.")
        except Exception:
            pass

@dp.callback_query(F.data == "reg_enter_code")
async def reg_enter_code_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_code)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("🔑 **Farzandingizning 4 xonali kodini kiriting:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_code)
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
                await bot.send_message(admin_id, f"🚨 **Kod orqali so'rov!**\n\n👤 O'quvchi: **{student['fio']}**", reply_markup=admin_kb, parse_mode="Markdown")
            except Exception:
                pass
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy Menyu", callback_data="back_home")]])
        await message.answer("⏳ **So'rov adminga yuborildi!**", reply_markup=kb)
    else:
        await message.answer("❌ Noto'g'ri kod! Qaytadan kiriting:")

@dp.callback_query(F.data == "reset_account")
async def reset_account(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET parent_chat_id = 0 WHERE parent_chat_id = ?", (call.from_user.id,))
        conn.commit()
    await call.message.answer("🔄 Kabinet muvaffaqiyatli uzildi.")
    await start_cmd(call.message, state)

@dp.callback_query(F.data == "feedback_menu")
async def feedback_menu(call: types.CallbackQuery):
    await call.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐⭐⭐⭐⭐ A'lo", callback_data="fb_done"), InlineKeyboardButton(text="⭐⭐⭐⭐ Yaxshi", callback_data="fb_done")],
            [InlineKeyboardButton(text="⬅️ Kabinetga qaytish", callback_data="auth_parent")]
        ]
    )
    await call.message.edit_text("⭐ **Darslarimiz va o'qitish sifatini baholang:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "fb_done")
async def fb_done(call: types.CallbackQuery):
    await call.answer("Fikringiz uchun rahmat! ✅", show_alert=True)
    await open_parent_cabinet(call, None)

@dp.callback_query(F.data == "parent_send_msg")
async def parent_send_msg_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(ParentStates.waiting_for_message_to_teacher)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="auth_parent")]])
    await call.message.edit_text("✍️ **O'qituvchiga yubormoqchi bo'lgan xabaringizni yozing:**", reply_markup=kb, parse_mode="Markdown")

@dp.message(ParentStates.waiting_for_message_to_teacher)
async def parent_msg_to_teacher_finish(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    admins = db_get_admins()
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, f"✉️ **Ota-onadan xabar:**\n\n{text}")
        except Exception:
            pass
    await message.answer("✅ **Xabaringiz o'qituvchiga yetkazildi!**")
    await start_cmd(message, state)

# Render talab qiladigan portni ochish uchun veb-server
async def handle_ping(request):
    return web.Response(text="Bot is online and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Veb-server {port}-portda muvaffaqiyatli ishga tushdi!")

@dp.callback_query(F.data == "back_home")
async def back_to_home(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await start_cmd(call.message, state)

async def main():
    server_task = asyncio.create_task(start_web_server())
    await asyncio.gather(server_task, dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())