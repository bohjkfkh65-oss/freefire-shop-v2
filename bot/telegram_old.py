import os
import time
import requests

from dotenv import load_dotenv

from database.db import get_connection

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def telegram_request(method, data=None):

    try:

        response = requests.post(
            f"{API}/{method}",
            json=data or {},
            timeout=30
        )

        return response.json()

    except Exception as e:

        print("Telegram connection error:", e)

        return None


def approve_deposit(deposit_id):

    conn = get_connection()

    try:

        conn.execute("BEGIN")

        deposit = conn.execute("""
            SELECT *
            FROM deposits
            WHERE id = ?
        """, (deposit_id,)).fetchone()

        if deposit is None:

            conn.rollback()

            return False, "طلب الإيداع غير موجود"

        if deposit["status"] == "approved":

            conn.rollback()

            return False, "تم قبول هذا الطلب مسبقًا"

        if deposit["status"] == "rejected":

            conn.rollback()

            return False, "هذا الطلب مرفوض مسبقًا"

        conn.execute("""
            UPDATE users

            SET balance = balance + ?

            WHERE id = ?
        """, (
            deposit["amount"],
            deposit["user_id"]
        ))

        conn.execute("""
            UPDATE deposits

            SET status = 'approved'

            WHERE id = ?
        """, (deposit_id,))

        user = conn.execute("""
            SELECT username, email, balance
            FROM users
            WHERE id = ?
        """, (
            deposit["user_id"],
        )).fetchone()

        conn.commit()

        return True, (
            f"تم قبول الإيداع\n"
            f"المستخدم: {user['username']}\n"
            f"المبلغ: {deposit['amount']}\n"
            f"الرصيد الجديد: {user['balance']}"
        )

    except Exception as e:

        conn.rollback()

        print("Approve error:", e)

        return False, "حدث خطأ أثناء قبول الإيداع"

    finally:

        conn.close()


def reject_deposit(deposit_id):

    conn = get_connection()

    try:

        deposit = conn.execute("""
            SELECT *
            FROM deposits
            WHERE id = ?
        """, (deposit_id,)).fetchone()

        if deposit is None:

            return False, "طلب الإيداع غير موجود"

        if deposit["status"] == "approved":

            return False, "لا يمكن رفض إيداع تم قبوله"

        if deposit["status"] == "rejected":

            return False, "تم رفض هذا الطلب مسبقًا"

        conn.execute("""
            UPDATE deposits

            SET status = 'rejected'

            WHERE id = ?
        """, (deposit_id,))

        conn.commit()

        return True, "تم رفض الإيداع"

    except Exception as e:

        conn.rollback()

        print("Reject error:", e)

        return False, "حدث خطأ أثناء رفض الإيداع"

    finally:

        conn.close()


def process_callback(callback):

    callback_id = callback["id"]

    data = callback.get("data", "")

    message = callback.get("message", {})

    chat = message.get("chat", {})

    chat_id = chat.get("id")

    message_id = message.get("message_id")


    if chat_id != int(ADMIN_CHAT_ID):

        telegram_request(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": "غير مسموح لك باستخدام هذا الزر.",
                "show_alert": True
            }
        )

        return


    if not data.startswith("deposit_"):

        return


    parts = data.split("_")

    if len(parts) != 3:

        return


    action = parts[1]

    try:

        deposit_id = int(parts[2])

    except ValueError:

        return


    if action == "approve":

        success, result = approve_deposit(deposit_id)

        if success:

            telegram_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": "✅ تم قبول الإيداع وإضافة المبلغ للمحفظة",
                    "show_alert": True
                }
            )

            new_text = (
                f"💰 <b>طلب إيداع</b>\n\n"
                f"🆔 رقم الطلب: {deposit_id}\n\n"
                f"✅ <b>تم قبول الإيداع</b>\n\n"
                f"💵 {result}"
            )

        else:

            telegram_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": result,
                    "show_alert": True
                }
            )

            new_text = (
                f"💰 <b>طلب إيداع</b>\n\n"
                f"🆔 رقم الطلب: {deposit_id}\n\n"
                f"⚠️ {result}"
            )


    elif action == "reject":

        success, result = reject_deposit(deposit_id)

        if success:

            telegram_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": "❌ تم رفض الإيداع",
                    "show_alert": True
                }
            )

            new_text = (
                f"💰 <b>طلب إيداع</b>\n\n"
                f"🆔 رقم الطلب: {deposit_id}\n\n"
                f"❌ <b>تم رفض الإيداع</b>"
            )

        else:

            telegram_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": result,
                    "show_alert": True
                }
            )

            new_text = (
                f"💰 <b>طلب إيداع</b>\n\n"
                f"🆔 رقم الطلب: {deposit_id}\n\n"
                f"⚠️ {result}"
            )


    else:

        return


    if chat_id and message_id:

        telegram_request(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": "HTML"
            }
        )


def run_bot():

    if not BOT_TOKEN:

        print("BOT_TOKEN غير موجود في .env")

        return

    print("Telegram callback listener started...")

    offset = 0

    while True:

        try:

            result = telegram_request(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": [
                        "callback_query"
                    ]
                }
            )

            if not result or not result.get("ok"):

                time.sleep(3)

                continue


            updates = result.get("result", [])

            for update in updates:

                offset = update["update_id"] + 1

                callback = update.get("callback_query")

                if callback:

                    process_callback(callback)


        except KeyboardInterrupt:

            print("\nBot stopped.")

            break

        except Exception as e:

            print("Bot error:", e)

            time.sleep(3)


if __name__ == "__main__":

    run_bot()
