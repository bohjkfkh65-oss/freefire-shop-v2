import os
import sys
import html
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database.db import get_db
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()


def esc(value):
    return html.escape(str(value))


def is_admin(telegram_id):
    telegram_id = str(telegram_id)

    if telegram_id == ADMIN_CHAT_ID:
        return True

    db = get_db()
    row = db.execute(
        "SELECT id FROM admins WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()
    db.close()

    return bool(row)


# حفظ العضو الذي اختاره الأدمن لإعادة تعيين كلمة المرور
pending_password_resets = {}
pending_admin_add = set()
pending_price_updates = {}
pending_offer_creates = {}
pending_offer_recipients = {}

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    # التحقق من صلاحية الإدارة
    if not is_admin(query.from_user.id):
        await query.answer(
            "❌ غير مصرح لك باستخدام هذا الزر",
            show_alert=True
        )
        return

    # =========================
    # الإيداعات
    # =========================

    if data.startswith("deposit_approve:"):
        try:
            deposit_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الإيداع غير صحيح", show_alert=True)
            return

        await approve_deposit(query, deposit_id)
        return

    if data.startswith("deposit_reject:"):
        try:
            deposit_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الإيداع غير صحيح", show_alert=True)
            return

        await reject_deposit(query, deposit_id)
        return

    # =========================
    # حسابات للبيع
    # =========================

    if data.startswith("account_approve:"):
        try:
            account_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الحساب غير صحيح", show_alert=True)
            return

        await approve_account(query, account_id)
        return

    if data.startswith("account_reject:"):
        try:
            account_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الحساب غير صحيح", show_alert=True)
            return

        await reject_account(query, account_id)
        return

    # =========================
    # طلبات الشحن
    # =========================

    if data.startswith("order_approve:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الطلب غير صحيح", show_alert=True)
            return

        await approve_order(query, order_id)
        return

    if data.startswith("order_reject:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم الطلب غير صحيح", show_alert=True)
            return

        await reject_order(query, order_id)
        return

    if data.startswith("member_finance:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم العضو غير صحيح", show_alert=True)
            return

        db = get_db()

        user = db.execute("""
            SELECT id, username, email, whatsapp, balance
            FROM users
            WHERE id = ?
        """, (user_id,)).fetchone()

        if not user:
            db.close()
            await query.answer("العضو غير موجود", show_alert=True)
            return

        deposits = db.execute("""
            SELECT amount, status, transaction_number, created_at
            FROM deposits
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
        """, (user_id,)).fetchall()

        orders = db.execute("""
            SELECT
                o.amount,
                o.status,
                o.player_id,
                o.created_at,
                p.name AS product_name
            FROM orders o
            LEFT JOIN products p ON p.id = o.product_id
            WHERE o.user_id = ?
            ORDER BY o.id DESC
            LIMIT 10
        """, (user_id,)).fetchall()

        total_deposited = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM deposits
            WHERE user_id = ?
              AND status = 'approved'
        """, (user_id,)).fetchone()[0]

        total_spent = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM orders
            WHERE user_id = ?
              AND status = 'approved'
        """, (user_id,)).fetchone()[0]

        approved_deposits = db.execute("""
            SELECT COUNT(*)
            FROM deposits
            WHERE user_id = ?
              AND status = 'approved'
        """, (user_id,)).fetchone()[0]

        approved_orders = db.execute("""
            SELECT COUNT(*)
            FROM orders
            WHERE user_id = ?
              AND status = 'approved'
        """, (user_id,)).fetchone()[0]

        db.close()

        text = (
            "📊 <b>التفاصيل المالية للعضو</b>\n\n"
            f"🆔 ID: <b>{user['id']}</b>\n"
            f"👤 المستخدم: <b>{esc(user['username'])}</b>\n"
            f"📧 البريد: <b>{esc(user['email'])}</b>\n"
            f"📱 واتساب: <b>{esc(user['whatsapp'] or 'غير مسجل')}</b>\n\n"
            "💰 <b>الملخص المالي</b>\n"
            f"💵 الرصيد الحالي: <b>{user['balance'] or 0}</b> جنيه\n"
            f"💳 إجمالي الإيداعات المقبولة: <b>{total_deposited}</b> جنيه\n"
            f"🛒 إجمالي المصروفات المقبولة: <b>{total_spent}</b> جنيه\n"
            f"📥 عدد الإيداعات المقبولة: <b>{approved_deposits}</b>\n"
            f"📦 عدد الطلبات المقبولة: <b>{approved_orders}</b>\n\n"
        )

        text += "📋 <b>آخر الطلبات</b>\n"

        if orders:
            for order in orders:
                product_name = order["product_name"] or "منتج غير معروف"
                text += (
                    f"• {esc(product_name)}\n"
                    f"  💸 {order['amount']} جنيه | "
                    f"📌 {esc(order['status'])}\n"
                    f"  🎮 ID اللاعب: <code>{esc(order['player_id'])}</code>\n"
                    f"  🕐 {esc(order['created_at'])}\n"
                )
        else:
            text += "لا توجد طلبات.\n"

        text += "\n💳 <b>آخر الإيداعات</b>\n"

        if deposits:
            for deposit in deposits:
                text += (
                    f"• 💵 {deposit['amount']} جنيه | "
                    f"📌 {esc(deposit['status'])}\n"
                    f"  🔢 العملية: <code>{esc(deposit['transaction_number'])}</code>\n"
                    f"  🕐 {esc(deposit['created_at'])}\n"
                )
        else:
            text += "لا توجد إيداعات.\n"

        await query.answer("تم تحميل التفاصيل المالية")

        await query.message.reply_text(
            text,
            parse_mode="HTML"
        )
        return

    if data.startswith("member_ban_confirm:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم العضو غير صحيح", show_alert=True)
            return

        db = get_db()

        user = db.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        existing = db.execute(
            "SELECT id FROM banned_users WHERE user_id = ? LIMIT 1",
            (user_id,)
        ).fetchone()

        if not user:
            db.close()
            await query.answer("العضو غير موجود", show_alert=True)
            return

        if existing:
            db.close()
            await query.answer("العضو محظور بالفعل", show_alert=True)
            return

        db.execute(
            "INSERT INTO banned_users (user_id, reason) VALUES (?, ?)",
            (user_id, "حظر بواسطة الإدارة")
        )
        db.commit()
        db.close()

        await query.answer("🚫 تم حظر العضو", show_alert=True)
        await query.message.reply_text(
            f"🚫 <b>تم حظر العضو بنجاح</b>\n\n"
            f"🆔 ID: <b>{user_id}</b>\n"
            f"👤 المستخدم: <b>{esc(user['username'])}</b>",
            parse_mode="HTML"
        )
        return

    if data.startswith("member_unban:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم العضو غير صحيح", show_alert=True)
            return

        db = get_db()

        user = db.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        if not user:
            db.close()
            await query.answer("العضو غير موجود", show_alert=True)
            return

        db.execute(
            "DELETE FROM banned_users WHERE user_id = ?",
            (user_id,)
        )
        db.commit()
        db.close()

        await query.answer("✅ تم فك الحظر", show_alert=True)
        await query.message.reply_text(
            f"✅ <b>تم فك الحظر عن العضو</b>\n\n"
            f"🆔 ID: <b>{user_id}</b>\n"
            f"👤 المستخدم: <b>{esc(user['username'])}</b>",
            parse_mode="HTML"
        )
        return

    if data == "admin_offers":
        if not is_admin(query.from_user.id):
            await query.answer("❌ غير مصرح لك", show_alert=True)
            return

        keyboard = [
            [InlineKeyboardButton("➕ إنشاء عرض", callback_data="offer_create")],
            [InlineKeyboardButton("💰 تحديد السعر القديم", callback_data="offer_old_price")],
            [InlineKeyboardButton("💵 تحديد سعر العرض", callback_data="offer_price")],
            [InlineKeyboardButton("⏱️ تحديد مدة العرض", callback_data="offer_duration")],
            [InlineKeyboardButton("🟢 تفعيل العرض", callback_data="offer_enable")],
            [InlineKeyboardButton("🔴 إيقاف العرض", callback_data="offer_disable")],
            [InlineKeyboardButton("✏️ تعديل العرض", callback_data="offer_edit")],
            [InlineKeyboardButton("🗑️ حذف العرض", callback_data="offer_delete")],
            [InlineKeyboardButton("📋 العروض الحالية", callback_data="offer_list")],
        ]

        await query.answer()
        await query.message.reply_text(
            "🎁 <b>إدارة العروض</b>\n\n"
            "اختر العملية التي تريد تنفيذها:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "offer_create":
        if not is_admin(query.from_user.id):
            await query.answer("❌ غير مصرح لك", show_alert=True)
            return

        db = get_db()
        products = db.execute("""
            SELECT id, name, price
            FROM products
            WHERE active = 1
            ORDER BY id
        """).fetchall()
        db.close()

        keyboard = []

        for product in products:
            keyboard.append([
                InlineKeyboardButton(
                    f"{product['name']} — {product['price']:,.0f}",
                    callback_data=f"offer_product:{product['id']}"
                )
            ])

        await query.answer("اختر المنتج")
        await query.message.reply_text(
            "➕ <b>إنشاء عرض جديد</b>\n\n"
            "اختر المنتج الذي تريد إنشاء العرض له:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("offer_product:"):
        if not is_admin(query.from_user.id):
            await query.answer("❌ غير مصرح لك", show_alert=True)
            return

        product_id = int(data.split(":")[1])

        db = get_db()
        product = db.execute(
            "SELECT id, name, price FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        db.close()

        if not product:
            await query.answer("❌ المنتج غير موجود", show_alert=True)
            return

        pending_offer_creates[query.from_user.id] = {
            "product_id": product_id,
            "product_name": product["name"]
        }

        await query.answer()
        await query.message.reply_text(
            f"🎁 <b>إنشاء عرض</b>\n\n"
            f"📦 المنتج: <b>{esc(product['name'])}</b>\n"
            f"💰 السعر الحالي: <b>{product['price']:,.0f}</b>\n\n"
            "أرسل الآن <b>السعر القديم</b> للعرض:",
            parse_mode="HTML"
        )
        return

    if data.startswith("offer_unit:"):
        if not is_admin(query.from_user.id):
            await query.answer("❌ غير مصرح لك", show_alert=True)
            return

        user_id = query.from_user.id
        state = pending_offer_creates.get(user_id)

        if not state:
            await query.answer("❌ لا يوجد عرض قيد الإنشاء", show_alert=True)
            return

        unit = data.split(":", 1)[1]

        if unit not in ("hours", "days"):
            await query.answer("❌ وحدة غير صحيحة", show_alert=True)
            return

        state["duration_unit"] = unit
        state["step"] = "duration"

        if unit == "hours":
            message = (
                "⏱️ <b>مدة العرض بالساعات</b>\n\n"
                "أرسل عدد الساعات.\n"
                "مثال: <b>6</b>"
            )
        else:
            message = (
                "📅 <b>مدة العرض بالأيام</b>\n\n"
                "أرسل عدد الأيام.\n"
                "مثال: <b>3</b>"
            )

        await query.answer()
        await query.message.reply_text(
            message,
            parse_mode="HTML"
        )
        return

    # =========================
    # اختيار أعضاء العرض
    # =========================
    if data.startswith("offer_recipient:"):
        admin_id = query.from_user.id
        state = pending_offer_recipients.get(admin_id)

        if not state:
            await query.answer("❌ لا يوجد عرض قيد الاختيار", show_alert=True)
            return

        try:
            member_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("❌ عضو غير صحيح", show_alert=True)
            return

        if state.get("all"):
            state["all"] = False
            state["selected"] = set()

        selected = state.setdefault("selected", set())

        if member_id in selected:
            selected.remove(member_id)
            await query.answer("☐ تم إلغاء اختيار العضو")
        else:
            selected.add(member_id)
            await query.answer("☑️ تم اختيار العضو")

        db = get_db()
        members = db.execute(
            """
            SELECT id, username, telegram_chat_id
            FROM users
            WHERE telegram_chat_id IS NOT NULL
              AND telegram_chat_id != ''
            ORDER BY id
            """
        ).fetchall()

        offer = db.execute(
            """
            SELECT o.*, p.name AS product_name
            FROM offers o
            JOIN products p ON p.id = o.product_id
            WHERE o.id = ?
            """,
            (state["offer_id"],)
        ).fetchone()
        db.close()

        keyboard = []

        for member in members:
            name = member["username"] or f"عضو #{member['id']}"
            mark = "☑️" if member["id"] in selected else "☐"

            keyboard.append([
                InlineKeyboardButton(
                    f"{mark} {name}",
                    callback_data=f"offer_recipient:{member['id']}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "📢 تحديد جميع الأعضاء",
                callback_data="offer_select_all"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                f"🚀 نشر العرض ({len(selected)})",
                callback_data="offer_publish"
            ),
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="offer_cancel"
            )
        ])

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "offer_select_all":
        admin_id = query.from_user.id
        state = pending_offer_recipients.get(admin_id)

        if not state:
            await query.answer("❌ لا يوجد عرض قيد الاختيار", show_alert=True)
            return

        state["all"] = True
        state["selected"] = set()

        await query.answer("📢 سيتم إرسال العرض لجميع الأعضاء")

        keyboard = [
            [
                InlineKeyboardButton(
                    "☑️ جميع الأعضاء محددين",
                    callback_data="offer_select_all"
                )
            ],
            [
                InlineKeyboardButton(
                    "🚀 نشر العرض للجميع",
                    callback_data="offer_publish"
                ),
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data="offer_cancel"
                )
            ]
        ]

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "offer_cancel":
        admin_id = query.from_user.id
        state = pending_offer_recipients.pop(admin_id, None)

        if state:
            db = get_db()
            db.execute(
                "DELETE FROM offers WHERE id = ? AND active = 0",
                (state["offer_id"],)
            )
            db.commit()
            db.close()

        await query.answer("❌ تم إلغاء العرض")
        await query.edit_message_text(
            "❌ <b>تم إلغاء إنشاء العرض.</b>",
            parse_mode="HTML"
        )
        return

    if data == "offer_publish":
        admin_id = query.from_user.id
        state = pending_offer_recipients.get(admin_id)

        if not state:
            await query.answer("❌ لا يوجد عرض قيد النشر", show_alert=True)
            return

        db = get_db()

        offer = db.execute(
            """
            SELECT
                o.*,
                p.name AS product_name
            FROM offers o
            JOIN products p ON p.id = o.product_id
            WHERE o.id = ?
            """,
            (state["offer_id"],)
        ).fetchone()

        if not offer:
            db.close()
            pending_offer_recipients.pop(admin_id, None)
            await query.answer("❌ العرض غير موجود", show_alert=True)
            return

        if state.get("all"):
            members = db.execute(
                """
                SELECT id, telegram_chat_id
                FROM users
                WHERE telegram_chat_id IS NOT NULL
                  AND telegram_chat_id != ''
                """
            ).fetchall()
        else:
            selected_ids = list(state.get("selected", set()))

            if not selected_ids:
                db.close()
                await query.answer(
                    "⚠️ اختر عضوًا واحدًا على الأقل أو اضغط تحديد الجميع",
                    show_alert=True
                )
                return

            placeholders = ",".join("?" for _ in selected_ids)

            members = db.execute(
                f"""
                SELECT id, telegram_chat_id
                FROM users
                WHERE id IN ({placeholders})
                  AND telegram_chat_id IS NOT NULL
                  AND telegram_chat_id != ''
                """,
                selected_ids
            ).fetchall()

        db.execute(
            "UPDATE offers SET active = 1 WHERE id = ?",
            (state["offer_id"],)
        )
        db.commit()
        db.close()

        from datetime import datetime

        description = esc(offer["description"] or "")

        duration_minutes = int(offer["duration_minutes"] or 0)

        if offer["duration_unit"] == "hours":
            duration_value = max(1, duration_minutes // 60)
            duration_label = f"{duration_value} ساعة"
        else:
            duration_value = max(1, duration_minutes // (24 * 60))
            duration_label = f"{duration_value} يوم"

        announcement = (
            "🎉 <b>عرض جديد!</b> 🎉\n\n"
            f"{description}\n\n"
            f"📦 <b>{esc(offer['product_name'])}</b>\n\n"
            f"💰 السعر القديم: <s>{offer['old_price']:,.0f}</s>\n"
            f"🔥 سعر العرض: <b>{offer['offer_price']:,.0f}</b>\n"
            f"⏱️ مدة العرض: <b>{duration_label}</b>\n"
            f"📅 ينتهي: <b>{esc(offer['expires_at'])}</b>\n\n"
            "🚀 <b>اغتنم العرض قبل انتهاء العرض!</b>"
        )

        sent = 0
        failed = 0

        for member in members:
            try:
                await context.bot.send_message(
                    chat_id=member["telegram_chat_id"],
                    text=announcement,
                    parse_mode="HTML"
                )
                sent += 1
            except Exception:
                failed += 1

        pending_offer_recipients.pop(admin_id, None)

        await query.answer("🚀 تم نشر العرض")

        await query.edit_message_text(
            "🎉 <b>تم نشر العرض بنجاح!</b>\n\n"
            f"📦 المنتج: <b>{esc(offer['product_name'])}</b>\n"
            f"🔥 سعر العرض: <b>{offer['offer_price']:,.0f}</b>\n"
            f"⏱️ المدة: <b>{duration_label}</b>\n\n"
            f"📨 تم إرسال العرض إلى: <b>{sent}</b> عضو\n"
            f"❌ فشل الإرسال إلى: <b>{failed}</b> عضو",
            parse_mode="HTML"
        )
        return

    if data == "admin_prices":
        if not is_admin(query.from_user.id):
            await query.answer(
                "❌ غير مصرح لك",
                show_alert=True
            )
            return

        db = get_db()
        products = db.execute("""
            SELECT id, name, price
            FROM products
            ORDER BY id
        """).fetchall()
        db.close()

        keyboard = []

        for product in products:
            keyboard.append([
                InlineKeyboardButton(
                    f"{product['name']} — {product['price']:,.0f}",
                    callback_data=f"price_edit:{product['id']}"
                )
            ])

        await query.answer("اختر المنتج")
        await query.message.reply_text(
            "💰 <b>إدارة أسعار المنتجات</b>\n\n"
            "اختر المنتج الذي تريد تعديل سعره:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("price_edit:"):
        if not is_admin(query.from_user.id):
            await query.answer(
                "❌ غير مصرح لك",
                show_alert=True
            )
            return

        try:
            product_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer(
                "❌ رقم المنتج غير صحيح",
                show_alert=True
            )
            return

        db = get_db()
        product = db.execute(
            "SELECT id, name, price FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        db.close()

        if not product:
            await query.answer(
                "❌ المنتج غير موجود",
                show_alert=True
            )
            return

        pending_price_updates[query.from_user.id] = product_id

        await query.answer("تم")
        await query.message.reply_text(
            "💰 <b>تعديل السعر</b>\n\n"
            f"📦 المنتج: <b>{esc(product['name'])}</b>\n"
            f"💵 السعر الحالي: <b>{product['price']:,.0f}</b>\n\n"
            "✏️ أرسل السعر الجديد الآن.\n"
            "مثال:\n"
            "<code>8500</code>",
            parse_mode="HTML"
        )
        return

    if data == "admin_add":
        if str(query.from_user.id) != ADMIN_CHAT_ID:
            await query.answer(
                "❌ الأدمن الرئيسي فقط يستطيع إضافة أدمن",
                show_alert=True
            )
            return

        pending_admin_add.add(query.from_user.id)

        await query.answer("تم")
        await query.message.reply_text(
            "➕ <b>إضافة أدمن جديد</b>\n\n"
            "أرسل الآن <b>Telegram ID</b> الخاص بالشخص.\n\n"
            "مثال:\n"
            "<code>123456789</code>\n\n"
            "⚠️ أرسل الرقم فقط.",
            parse_mode="HTML"
        )
        return

    if data == "admin_remove":
        if str(query.from_user.id) != ADMIN_CHAT_ID:
            await query.answer(
                "❌ الأدمن الرئيسي فقط يستطيع إزالة أدمن",
                show_alert=True
            )
            return

        db = get_db()
        admins = db.execute("""
            SELECT telegram_id, username
            FROM admins
            ORDER BY id ASC
        """).fetchall()
        db.close()

        if not admins:
            await query.answer(
                "لا يوجد أدمن إضافيون",
                show_alert=True
            )
            return

        keyboard = []

        for admin in admins:
            name = admin["username"] or admin["telegram_id"]
            keyboard.append([
                InlineKeyboardButton(
                    f"❌ إزالة {name}",
                    callback_data=f"admin_remove_confirm:{admin['telegram_id']}"
                )
            ])

        await query.answer("اختر الأدمن")
        await query.message.reply_text(
            "➖ <b>إزالة أدمن</b>\n\n"
            "اختر الأدمن الذي تريد إزالته:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("admin_remove_confirm:"):
        if str(query.from_user.id) != ADMIN_CHAT_ID:
            await query.answer(
                "❌ الأدمن الرئيسي فقط يستطيع إزالة أدمن",
                show_alert=True
            )
            return

        telegram_id = data.split(":", 1)[1]

        db = get_db()

        admin = db.execute(
            "SELECT telegram_id, username FROM admins WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()

        if not admin:
            db.close()
            await query.answer(
                "❌ الأدمن غير موجود",
                show_alert=True
            )
            return

        db.execute(
            "DELETE FROM admins WHERE telegram_id = ?",
            (telegram_id,)
        )
        db.commit()
        db.close()

        await query.answer("تمت الإزالة", show_alert=True)

        await query.message.reply_text(
            "✅ <b>تمت إزالة الأدمن</b>\n\n"
            f"🆔 Telegram ID: <code>{esc(telegram_id)}</code>",
            parse_mode="HTML"
        )
        return

    if data.startswith("member_ban:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم العضو غير صحيح", show_alert=True)
            return

        db = get_db()

        user = db.execute(
            "SELECT id, username, email FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        banned = db.execute(
            "SELECT reason FROM banned_users WHERE user_id = ? LIMIT 1",
            (user_id,)
        ).fetchone()

        db.close()

        if not user:
            await query.answer("العضو غير موجود", show_alert=True)
            return

        if banned:
            keyboard = [[
                InlineKeyboardButton(
                    "✅ فك الحظر",
                    callback_data=f"member_unban:{user_id}"
                )
            ]]

            status = (
                "🚫 <b>العضو محظور حاليًا</b>\n"
                f"📝 السبب: {esc(banned['reason'] or 'غير محدد')}"
            )
        else:
            keyboard = [[
                InlineKeyboardButton(
                    "🚫 تأكيد حظر العضو",
                    callback_data=f"member_ban_confirm:{user_id}"
                )
            ]]

            status = "🟢 <b>العضو غير محظور حاليًا</b>"

        await query.answer("تم تحميل حالة العضو")

        await query.message.reply_text(
            "👤 <b>حالة العضو</b>\n\n"
            f"🆔 ID: <b>{user['id']}</b>\n"
            f"👤 المستخدم: <b>{esc(user['username'])}</b>\n"
            f"📧 البريد: <b>{esc(user['email'])}</b>\n\n"
            f"{status}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("member_reset:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم العضو غير صحيح", show_alert=True)
            return

        db = get_db()
        user = db.execute(
            "SELECT id, username, email FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        db.close()

        if not user:
            await query.answer("العضو غير موجود", show_alert=True)
            return

        pending_password_resets[update.effective_user.id] = user["id"]

        await query.answer("تم اختيار العضو", show_alert=True)

        await query.message.reply_text(
            "🔐 <b>إعادة تعيين كلمة المرور</b>\n\n"
            f"🆔 ID: <b>{user['id']}</b>\n"
            f"👤 المستخدم: <b>{esc(user['username'])}</b>\n"
            f"📧 البريد: <b>{esc(user['email'])}</b>\n\n"
            "✍️ أرسل الآن كلمة المرور الجديدة في رسالة منفصلة.\n"
            "⚠️ لا ترسل أي معلومات أخرى في نفس الرسالة.",
            parse_mode="HTML"
        )
        return

    await query.answer("هذا الزر غير معروف", show_alert=True)


# ==========================================================
#                    الإيداعات
# ==========================================================

async def approve_deposit(query, deposit_id):
    db = get_db()

    deposit = db.execute("""
        SELECT
            deposits.id,
            deposits.user_id,
            deposits.amount,
            deposits.transaction_number,
            deposits.status,
            users.username,
            users.email
        FROM deposits
        JOIN users ON users.id = deposits.user_id
        WHERE deposits.id = ?
    """, (deposit_id,)).fetchone()

    if not deposit:
        db.close()
        await query.answer("الإيداع غير موجود", show_alert=True)
        return

    if deposit["status"] != "pending":
        db.close()
        await query.answer(
            "تمت معالجة هذا الإيداع مسبقًا",
            show_alert=True
        )
        return

    db.execute("""
        UPDATE deposits
        SET status = 'accepted'
        WHERE id = ? AND status = 'pending'
    """, (deposit_id,))

    db.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE id = ?
    """, (
        deposit["amount"],
        deposit["user_id"]
    ))

    db.commit()

    new_balance = db.execute("""
        SELECT balance
        FROM users
        WHERE id = ?
    """, (deposit["user_id"],)).fetchone()["balance"]

    db.close()

    await query.answer("تم قبول الإيداع ✅", show_alert=True)

    await query.edit_message_text(
        "💰 <b>طلب إيداع</b>\n\n"
        f"🆔 رقم الإيداع: <b>#{deposit_id}</b>\n"
        f"👤 المستخدم: <b>{esc(deposit['username'])}</b>\n"
        f"💵 المبلغ: <b>{deposit['amount']} جنيه</b>\n"
        f"🧾 رقم العملية: <b>{esc(deposit['transaction_number'])}</b>\n\n"
        "✅ الحالة: <b>تم القبول</b>\n"
        f"💳 الرصيد الجديد: <b>{new_balance} جنيه</b>",
        parse_mode="HTML"
    )


async def reject_deposit(query, deposit_id):
    db = get_db()

    deposit = db.execute("""
        SELECT
            deposits.id,
            deposits.user_id,
            deposits.amount,
            deposits.transaction_number,
            deposits.status,
            users.username
        FROM deposits
        JOIN users ON users.id = deposits.user_id
        WHERE deposits.id = ?
    """, (deposit_id,)).fetchone()

    if not deposit:
        db.close()
        await query.answer("الإيداع غير موجود", show_alert=True)
        return

    if deposit["status"] != "pending":
        db.close()
        await query.answer(
            "تمت معالجة هذا الإيداع مسبقًا",
            show_alert=True
        )
        return

    db.execute("""
        UPDATE deposits
        SET status = 'rejected'
        WHERE id = ? AND status = 'pending'
    """, (deposit_id,))

    db.commit()
    db.close()

    await query.answer("تم رفض الإيداع ❌", show_alert=True)

    await query.edit_message_text(
        "💰 <b>طلب إيداع</b>\n\n"
        f"🆔 رقم الإيداع: <b>#{deposit_id}</b>\n"
        f"👤 المستخدم: <b>{esc(deposit['username'])}</b>\n"
        f"💵 المبلغ: <b>{deposit['amount']} جنيه</b>\n"
        f"🧾 رقم العملية: <b>{esc(deposit['transaction_number'])}</b>\n\n"
        "❌ الحالة: <b>مرفوض</b>",
        parse_mode="HTML"
    )


# ==========================================================
#                    طلبات الشحن
# ==========================================================


async def approve_account(query, account_id):
    db = get_db()

    account = db.execute("""
        SELECT id, title, status
        FROM account_sales
        WHERE id = ?
    """, (account_id,)).fetchone()

    if not account:
        db.close()
        await query.answer("❌ الحساب غير موجود", show_alert=True)
        return

    if account["status"] != "pending":
        db.close()
        await query.answer("⚠️ تمت معالجة هذا الحساب مسبقًا", show_alert=True)
        return

    db.execute("""
        UPDATE account_sales
        SET status = 'approved'
        WHERE id = ?
    """, (account_id,))

    db.commit()
    db.close()

    await query.answer("✅ تم قبول الحساب")

    try:
        await query.edit_message_caption(
            caption=(
                "🎮 <b>حساب معروض للبيع</b>\n\n"
                f"🆔 رقم الحساب: <b>#{account_id}</b>\n"
                f"🎮 الاسم: <b>{esc(account['title'])}</b>\n\n"
                "✅ <b>تم قبول الحساب وأصبح ظاهرًا في المتجر.</b>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=(
                    "🎮 <b>حساب للبيع</b>\n\n"
                    f"🆔 #{account_id}\n"
                    f"🎮 {esc(account['title'])}\n\n"
                    "✅ <b>تم قبول الحساب وأصبح ظاهرًا في المتجر.</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print("⚠️ تعذر تحديث رسالة Telegram:", e)


async def reject_account(query, account_id):
    db = get_db()

    account = db.execute("""
        SELECT id, title, status
        FROM account_sales
        WHERE id = ?
    """, (account_id,)).fetchone()

    if not account:
        db.close()
        await query.answer("❌ الحساب غير موجود", show_alert=True)
        return

    if account["status"] != "pending":
        db.close()
        await query.answer("⚠️ تمت معالجة هذا الحساب مسبقًا", show_alert=True)
        return

    db.execute("""
        UPDATE account_sales
        SET status = 'rejected'
        WHERE id = ?
    """, (account_id,))

    db.commit()
    db.close()

    await query.answer("❌ تم رفض الحساب")

    try:
        await query.edit_message_caption(
            caption=(
                "🎮 <b>حساب للبيع</b>\n\n"
                f"🆔 رقم الحساب: <b>#{account_id}</b>\n"
                f"🎮 الاسم: <b>{esc(account['title'])}</b>\n\n"
                "❌ <b>تم رفض الحساب ولن يظهر في المتجر.</b>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=(
                    "🎮 <b>حساب للبيع</b>\n\n"
                    f"🆔 #{account_id}\n"
                    f"🎮 {esc(account['title'])}\n\n"
                    "❌ <b>تم رفض الحساب ولن يظهر في المتجر.</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print("⚠️ تعذر تحديث رسالة Telegram:", e)


async def approve_order(query, order_id):
    db = get_db()

    order = db.execute("""
        SELECT
            orders.id,
            orders.user_id,
            orders.product_id,
            orders.player_id,
            orders.amount,
            orders.status,
            products.name AS product_name,
            users.username,
            users.email
        FROM orders
        JOIN products ON products.id = orders.product_id
        JOIN users ON users.id = orders.user_id
        WHERE orders.id = ?
    """, (order_id,)).fetchone()

    if not order:
        db.close()
        await query.answer(
            "❌ الطلب غير موجود",
            show_alert=True
        )
        return

    if order["status"] != "pending":
        db.close()
        await query.answer(
            f"تمت معالجة الطلب مسبقًا ({order['status']})",
            show_alert=True
        )
        return

    cursor = db.execute("""
        UPDATE orders
        SET status = 'completed'
        WHERE id = ? AND status = 'pending'
    """, (order_id,))

    if cursor.rowcount != 1:
        db.close()
        await query.answer(
            "تمت معالجة الطلب بالفعل",
            show_alert=True
        )
        return

    db.commit()
    db.close()

    await query.answer(
        "تم تنفيذ الطلب بنجاح ✅",
        show_alert=True
    )

    await query.edit_message_text(
        "🛒 <b>طلب شحن</b>\n\n"
        f"🆔 رقم الطلب: <b>#{order_id}</b>\n"
        f"👤 المستخدم: <b>{esc(order['username'])}</b>\n"
        f"📧 البريد: <b>{esc(order['email'])}</b>\n"
        f"💎 الباقة: <b>{esc(order['product_name'])}</b>\n"
        f"💵 السعر: <b>{order['amount']} جنيه</b>\n"
        f"🎮 Player ID: <b>{esc(order['player_id'])}</b>\n\n"
        "✅ الحالة: <b>تم تنفيذ الطلب</b>",
        parse_mode="HTML"
    )


async def reject_order(query, order_id):
    db = get_db()

    order = db.execute("""
        SELECT
            orders.id,
            orders.user_id,
            orders.player_id,
            orders.amount,
            orders.status,
            products.name AS product_name,
            users.username
        FROM orders
        JOIN products ON products.id = orders.product_id
        JOIN users ON users.id = orders.user_id
        WHERE orders.id = ?
    """, (order_id,)).fetchone()

    if not order:
        db.close()
        await query.answer(
            "❌ الطلب غير موجود",
            show_alert=True
        )
        return

    if order["status"] != "pending":
        db.close()
        await query.answer(
            f"تمت معالجة الطلب مسبقًا ({order['status']})",
            show_alert=True
        )
        return

    # تغيير الحالة أولاً، وبشرط أنها ما زالت pending
    cursor = db.execute("""
        UPDATE orders
        SET status = 'rejected'
        WHERE id = ? AND status = 'pending'
    """, (order_id,))

    if cursor.rowcount != 1:
        db.close()
        await query.answer(
            "تمت معالجة الطلب بالفعل",
            show_alert=True
        )
        return

    # إعادة المبلغ للمحفظة
    db.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE id = ?
    """, (
        order["amount"],
        order["user_id"]
    ))

    db.commit()

    new_balance = db.execute("""
        SELECT balance
        FROM users
        WHERE id = ?
    """, (order["user_id"],)).fetchone()["balance"]

    db.close()

    await query.answer(
        "تم رفض الطلب وإعادة المبلغ ✅",
        show_alert=True
    )

    await query.edit_message_text(
        "🛒 <b>طلب شحن</b>\n\n"
        f"🆔 رقم الطلب: <b>#{order_id}</b>\n"
        f"👤 المستخدم: <b>{esc(order['username'])}</b>\n"
        f"💎 الباقة: <b>{esc(order['product_name'])}</b>\n"
        f"💵 المبلغ: <b>{order['amount']} جنيه</b>\n"
        f"🎮 Player ID: <b>{esc(order['player_id'])}</b>\n\n"
        "❌ الحالة: <b>تم رفض الطلب</b>\n"
        f"💰 تمت إعادة <b>{order['amount']} جنيه</b> للمحفظة\n"
        f"💳 الرصيد الجديد: <b>{new_balance} جنيه</b>",
        parse_mode="HTML"
    )


# ==========================================================
#                       تشغيل البوت
# ==========================================================

async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك باستخدام هذا الأمر")
        return

    db = get_db()

    users = db.execute("""
        SELECT
            u.id,
            u.username,
            u.email,
            u.whatsapp,
            u.balance,

            (SELECT COUNT(*)
             FROM deposits d
             WHERE d.user_id = u.id
               AND d.status = 'approved') AS deposit_count,

            (SELECT COALESCE(SUM(d.amount), 0)
             FROM deposits d
             WHERE d.user_id = u.id
               AND d.status = 'approved') AS total_deposited,

            (SELECT COUNT(*)
             FROM orders o
             WHERE o.user_id = u.id) AS order_count,

            (SELECT COALESCE(SUM(o.amount), 0)
             FROM orders o
             WHERE o.user_id = u.id
               AND o.status = 'approved') AS total_spent

        FROM users u
        ORDER BY u.id DESC
    """).fetchall()

    db.close()

    if not users:
        await update.message.reply_text(
            "👥 <b>إدارة الأعضاء</b>\n\n"
            "لا يوجد أعضاء مسجلون حاليًا.",
            parse_mode="HTML"
        )
        return

    text = "👥 <b>إدارة الأعضاء</b>\n"
    text += f"📊 عدد الأعضاء: <b>{len(users)}</b>\n\n"

    keyboard = []

    for user in users:
        text += (
            "━━━━━━━━━━━━━━\n"
            f"🆔 <b>ID:</b> {user['id']}\n"
            f"👤 <b>الاسم:</b> {esc(user['username'])}\n"
            f"📧 <b>البريد:</b> {esc(user['email'])}\n"
            f"📱 <b>واتساب:</b> {esc(user['whatsapp'] or 'غير مسجل')}\n"
            f"💰 <b>الرصيد:</b> {user['balance'] or 0} جنيه\n"
            f"💳 <b>الإيداعات:</b> {user['deposit_count']} | "
            f"💵 {user['total_deposited']} جنيه\n"
            f"🛒 <b>الطلبات:</b> {user['order_count']} | "
            f"💸 {user['total_spent']} جنيه\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"📊 التفاصيل المالية #{user['id']}",
                callback_data=f"member_finance:{user['id']}"
            ),
            InlineKeyboardButton(
                f"🔐 إعادة تعيين كلمة مرور #{user['id']}",
                callback_data=f"member_reset:{user['id']}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                f"🚫 حظر / فك الحظر #{user['id']}",
                callback_data=f"member_ban:{user['id']}"
            )
        ])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



async def price_update_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        return

    if admin_id not in pending_price_updates:
        return

    value = (update.message.text or "").strip().replace(",", "")

    try:
        new_price = float(value)
    except ValueError:
        await update.message.reply_text(
            "❌ السعر غير صحيح.\n"
            "أرسل رقمًا فقط، مثال: 8500"
        )
        return

    if new_price <= 0:
        await update.message.reply_text(
            "❌ السعر يجب أن يكون أكبر من صفر."
        )
        return

    product_id = pending_price_updates[admin_id]

    db = get_db()

    product = db.execute(
        "SELECT id, name, price FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        pending_price_updates.pop(admin_id, None)
        await update.message.reply_text(
            "❌ المنتج غير موجود."
        )
        return

    old_price = product["price"]

    db.execute(
        "UPDATE products SET price = ? WHERE id = ?",
        (new_price, product_id)
    )
    db.commit()
    db.close()

    pending_price_updates.pop(admin_id, None)

    await update.message.reply_text(
        "✅ <b>تم تعديل السعر بنجاح</b>\n\n"
        f"📦 المنتج: <b>{esc(product['name'])}</b>\n"
        f"💵 السعر السابق: <b>{old_price:,.0f}</b>\n"
        f"💰 السعر الجديد: <b>{new_price:,.0f}</b>",
        parse_mode="HTML"
    )


async def admin_add_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    admin_id = update.effective_user.id

    if str(admin_id) != ADMIN_CHAT_ID:
        return

    if admin_id not in pending_admin_add:
        return

    telegram_id = (update.message.text or "").strip()

    if not telegram_id.isdigit():
        await update.message.reply_text(
            "❌ Telegram ID يجب أن يكون أرقامًا فقط.\n"
            "أرسله مرة أخرى."
        )
        return

    db = get_db()

    existing = db.execute(
        "SELECT id FROM admins WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()

    if existing:
        db.close()
        pending_admin_add.discard(admin_id)

        await update.message.reply_text(
            "⚠️ هذا الشخص أدمن بالفعل."
        )
        return

    if telegram_id == ADMIN_CHAT_ID:
        db.close()
        pending_admin_add.discard(admin_id)

        await update.message.reply_text(
            "⚠️ هذا هو الأدمن الرئيسي بالفعل."
        )
        return

    db.execute(
        """
        INSERT INTO admins (telegram_id, username, added_by)
        VALUES (?, ?, ?)
        """,
        (telegram_id, None, str(admin_id))
    )
    db.commit()
    db.close()

    pending_admin_add.discard(admin_id)

    await update.message.reply_text(
        "✅ <b>تمت إضافة الأدمن بنجاح</b>\n\n"
        f"🆔 Telegram ID: <code>{esc(telegram_id)}</code>",
        parse_mode="HTML"
    )



async def offer_create_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    if not update.message:
        return

    state = pending_offer_creates.get(user_id)

    if not state:
        return

    text = update.message.text.strip().replace(",", "")

    # =========================
    # السعر القديم
    # =========================
    if state.get("step") is None:
        try:
            old_price = float(text)
            if old_price <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ السعر غير صحيح.\n"
                "أرسل رقمًا أكبر من صفر، مثل: 10000"
            )
            return

        state["old_price"] = old_price
        state["step"] = "offer_price"

        await update.message.reply_text(
            f"✅ السعر القديم: <b>{old_price:,.0f}</b>\n\n"
            "💵 الآن أرسل <b>سعر العرض</b>:\n"
            "مثال: <b>8000</b>",
            parse_mode="HTML"
        )
        return

    # =========================
    # سعر العرض
    # =========================
    if state.get("step") == "offer_price":
        try:
            offer_price = float(text)
            if offer_price <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ سعر العرض غير صحيح.\n"
                "أرسل رقمًا أكبر من صفر، مثل: 8000"
            )
            return

        if offer_price >= state["old_price"]:
            await update.message.reply_text(
                "❌ سعر العرض يجب أن يكون أقل من السعر القديم.\n\n"
                f"💰 السعر القديم: <b>{state['old_price']:,.0f}</b>\n"
                "💵 أرسل سعر العرض مرة أخرى:",
                parse_mode="HTML"
            )
            return

        state["offer_price"] = offer_price
        state["step"] = "description"

        await update.message.reply_text(
            f"✅ سعر العرض: <b>{offer_price:,.0f}</b>\n\n"
            "📝 الآن اكتب <b>نص العرض</b>.\n"
            "مثال:\n"
            "<i>🔥 عرض خاص بمناسبة حدث كذا! لا تفوّت الفرصة.</i>",
            parse_mode="HTML"
        )
        return

    # =========================
    # نص العرض
    # =========================
    if state.get("step") == "description":
        state["description"] = update.message.text.strip()

        if not state["description"]:
            await update.message.reply_text(
                "❌ نص العرض لا يمكن أن يكون فارغًا. أرسل نص العرض:"
            )
            return

        state["step"] = "duration_unit"

        keyboard = [
            [
                InlineKeyboardButton(
                    "⏱️ ساعات",
                    callback_data="offer_unit:hours"
                ),
                InlineKeyboardButton(
                    "📅 أيام",
                    callback_data="offer_unit:days"
                )
            ]
        ]

        await update.message.reply_text(
            "⏱️ <b>حدد وحدة مدة العرض:</b>\n\n"
            "اختر <b>ساعات</b> أو <b>أيام</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # =========================
    # مدة العرض وحفظه
    # =========================
    if state.get("step") == "duration":
        try:
            duration_value = int(text)
            if duration_value <= 0:
                raise ValueError
        except ValueError:
            unit_label = (
                "الساعات"
                if state.get("duration_unit") == "hours"
                else "الأيام"
            )

            await update.message.reply_text(
                f"❌ المدة غير صحيحة.\\n"
                f"أرسل عدد {unit_label} فقط، مثل: <b>6</b>",
                parse_mode="HTML"
            )
            return

        from datetime import datetime, timedelta

        duration_unit = state.get("duration_unit", "days")

        if duration_unit == "hours":
            duration_minutes = duration_value * 60
            expires_at = datetime.now() + timedelta(hours=duration_value)
            duration_label = f"{duration_value} ساعة"
        else:
            duration_minutes = duration_value * 24 * 60
            expires_at = datetime.now() + timedelta(days=duration_value)
            duration_label = f"{duration_value} يوم"

        db = get_db()

        # إيقاف أي عرض سابق لنفس المنتج
        db.execute(
            "UPDATE offers SET active = 0 WHERE product_id = ?",
            (state["product_id"],)
        )

        # إنشاء العرض كمسودة حتى يتم اختيار المستلمين ثم نشره
        cursor = db.execute(
            """
            INSERT INTO offers
            (
                product_id,
                old_price,
                offer_price,
                duration_minutes,
                active,
                expires_at,
                description,
                duration_unit
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                state["product_id"],
                state["old_price"],
                state["offer_price"],
                duration_minutes,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                state.get("description", ""),
                duration_unit
            )
        )

        offer_id = cursor.lastrowid

        members = db.execute(
            """
            SELECT id, username, telegram_chat_id
            FROM users
            WHERE telegram_chat_id IS NOT NULL
              AND telegram_chat_id != ''
            ORDER BY id
            """
        ).fetchall()

        db.commit()
        db.close()

        pending_offer_recipients[user_id] = {
            "offer_id": offer_id,
            "selected": set(),
            "all": False
        }

        keyboard = []

        for member in members:
            name = member["username"] or f"عضو #{member['id']}"
            keyboard.append([
                InlineKeyboardButton(
                    f"☐ {name}",
                    callback_data=f"offer_recipient:{member['id']}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "📢 تحديد جميع الأعضاء",
                callback_data="offer_select_all"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🚀 نشر العرض",
                callback_data="offer_publish"
            ),
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="offer_cancel"
            )
        ])

        await update.message.reply_text(
            "🎉 <b>تم تجهيز العرض!</b>\\n\\n"
            f"📦 المنتج: <b>{esc(state['product_name'])}</b>\\n"
            f"💰 السعر القديم: <s>{state['old_price']:,.0f}</s>\\n"
            f"🔥 سعر العرض: <b>{state['offer_price']:,.0f}</b>\\n"
            f"⏱️ المدة: <b>{duration_label}</b>\\n"
            f"📅 ينتهي: <b>{expires_at.strftime('%Y-%m-%d %H:%M')}</b>\\n\\n"
            f"📝 <b>نص العرض:</b>\\n{esc(state.get('description', ''))}\\n\\n"
            "👥 <b>الآن اختر أعضاء الموقع الذين تريد إرسال العرض لهم:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        pending_offer_creates.pop(user_id, None)
        return


async def password_reset_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        return

    if admin_id not in pending_password_resets:
        return

    new_password = update.message.text or ""

    if len(new_password) < 6:
        await update.message.reply_text(
            "❌ كلمة المرور يجب أن تكون 6 أحرف على الأقل.\n"
            "أرسل كلمة المرور الجديدة مرة أخرى."
        )
        return

    member_id = pending_password_resets[admin_id]

    db = get_db()

    user = db.execute(
        "SELECT id, username FROM users WHERE id = ?",
        (member_id,)
    ).fetchone()

    if not user:
        db.close()
        pending_password_resets.pop(admin_id, None)
        await update.message.reply_text("❌ العضو غير موجود.")
        return

    password_hash = generate_password_hash(new_password)

    db.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (password_hash, member_id)
    )

    db.commit()
    db.close()

    pending_password_resets.pop(admin_id, None)

    await update.message.reply_text(
        "✅ <b>تم تغيير كلمة المرور بنجاح</b>\n\n"
        f"🆔 ID العضو: <b>{member_id}</b>\n"
        f"👤 المستخدم: <b>{esc(user['username'])}</b>\n\n"
        "🔒 تم حفظ كلمة المرور بشكل مشفّر.",
        parse_mode="HTML"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    admin_id = str(update.effective_user.id)

    # الأدمن الرئيسي
    if admin_id == ADMIN_CHAT_ID:
        authorized = True
    else:
        db = get_db()
        row = db.execute(
            "SELECT id FROM admins WHERE telegram_id = ?",
            (admin_id,)
        ).fetchone()
        db.close()
        authorized = bool(row)

    if not authorized:
        await update.message.reply_text("❌ غير مصرح لك باستخدام لوحة الإدارة.")
        return

    db = get_db()
    admins = db.execute("""
        SELECT telegram_id, username, added_at
        FROM admins
        ORDER BY id ASC
    """).fetchall()
    db.close()

    text = "👑 <b>إدارة الأدمن</b>\n\n"
    text += f"⭐ الأدمن الرئيسي: <code>{esc(ADMIN_CHAT_ID)}</code>\n\n"

    if admins:
        text += "👥 <b>الأدمن الإضافيون:</b>\n"
        for admin in admins:
            username = admin["username"] or "بدون اسم"
            text += (
                f"• <code>{esc(admin['telegram_id'])}</code>"
                f" — {esc(username)}\n"
            )
    else:
        text += "📭 لا يوجد أدمن إضافيون حاليًا.\n"

    keyboard = [
        [
            InlineKeyboardButton(
                "💰 إدارة الأسعار",
                callback_data="admin_prices"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 إدارة العروض",
                callback_data="admin_offers"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ إضافة أدمن",
                callback_data="admin_add"
            )
        ],
        [
            InlineKeyboardButton(
                "➖ إزالة أدمن",
                callback_data="admin_remove"
            )
        ]
    ]

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود في .env")
        return

    if not ADMIN_CHAT_ID:
        print("❌ ADMIN_CHAT_ID غير موجود في .env")
        return

    print("🤖 TELEGRAM BOT STARTED")
    print("🗄️ Database: local shared database")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        CommandHandler("members", members_command)
    )
    application.add_handler(
        CommandHandler("admin", admin_command)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            price_update_message
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_add_message
        ),
        group=1
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            offer_create_message
        ),
        group=2
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            password_reset_message
        ),
        group=3
    )

    application.run_polling()


if __name__ == "__main__":
    main()
