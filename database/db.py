import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE = BASE_DIR / "database" / "shop.db"


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn



def get_db():
    return get_connection()

def init_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT UNIQUE,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            balance REAL DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            account_number TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method_id INTEGER NOT NULL,
            transaction_number TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (payment_method_id)
                REFERENCES payment_methods(id)
        )
    """)

    payment_methods = [
        ("بنكك", "8229209", "ايمن عبدالوهاب"),
        ("ماي كاشي", "661205", "ايمن عبدالوهاب"),
        ("فوري", "52017677", "ايمن عبدالوهاب"),
    ]

    for name, account_number, owner_name in payment_methods:
        conn.execute("""
            INSERT OR IGNORE INTO payment_methods
            (name, account_number, owner_name)
            VALUES (?, ?, ?)
        """, (
            name,
            account_number,
            owner_name
        ))

    conn.commit()
    conn.close()


def create_user(username, email, password):
    conn = get_connection()

    password_hash = generate_password_hash(password)

    cursor = conn.execute("""
        INSERT INTO users
        (username, email, password_hash)
        VALUES (?, ?, ?)
    """, (
        username,
        email,
        password_hash
    ))

    conn.commit()

    user_id = cursor.lastrowid

    conn.close()

    return user_id


def find_user_by_email(email):
    conn = get_connection()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (email,)).fetchone()

    conn.close()

    return user


def find_user_by_id(user_id):
    conn = get_connection()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()

    conn.close()

    return user


def get_payment_methods():
    conn = get_connection()

    methods = conn.execute("""
        SELECT *
        FROM payment_methods
        WHERE active = 1
        ORDER BY id
    """).fetchall()

    conn.close()

    return methods


def get_payment_method(method_id):
    conn = get_connection()

    method = conn.execute("""
        SELECT *
        FROM payment_methods
        WHERE id = ? AND active = 1
    """, (method_id,)).fetchone()

    conn.close()

    return method


def create_deposit(
    user_id,
    amount,
    payment_method_id,
    transaction_number
):
    conn = get_connection()

    cursor = conn.execute("""
        INSERT INTO deposits
        (
            user_id,
            amount,
            payment_method_id,
            transaction_number
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        amount,
        payment_method_id,
        transaction_number
    ))

    conn.commit()

    deposit_id = cursor.lastrowid

    conn.close()

    return deposit_id


def get_user_deposits(user_id):
    conn = get_connection()

    deposits = conn.execute("""
        SELECT
            deposits.*,
            payment_methods.name AS payment_method_name
        FROM deposits
        JOIN payment_methods
            ON deposits.payment_method_id =
               payment_methods.id
        WHERE deposits.user_id = ?
        ORDER BY deposits.id DESC
    """, (user_id,)).fetchall()

    conn.close()

    return deposits


# ==========================================================
#                دوال إدارة الإيداعات
# ==========================================================

def get_deposit(deposit_id):
    """
    جلب معلومات طلب إيداع معين.
    """

    conn = get_connection()

    deposit = conn.execute("""
        SELECT
            deposits.*,

            users.username,
            users.email,

            payment_methods.name AS payment_method_name

        FROM deposits

        JOIN users
            ON deposits.user_id = users.id

        JOIN payment_methods
            ON deposits.payment_method_id =
               payment_methods.id

        WHERE deposits.id = ?
    """, (deposit_id,)).fetchone()

    conn.close()

    return deposit


def approve_deposit(deposit_id):
    """
    قبول الإيداع وإضافة المبلغ للمحفظة.

    الدالة تمنع إضافة نفس الإيداع مرتين.
    """

    conn = get_connection()

    try:

        # بدء معاملة
        conn.execute("BEGIN")

        deposit = conn.execute("""
            SELECT *
            FROM deposits
            WHERE id = ?
        """, (deposit_id,)).fetchone()

        if deposit is None:
            conn.rollback()
            return {
                "success": False,
                "message": "طلب الإيداع غير موجود"
            }

        # إذا كان مقبولًا مسبقًا
        if deposit["status"] == "approved":
            conn.rollback()

            return {
                "success": False,
                "message": "تم قبول هذا الإيداع مسبقًا"
            }

        # إذا كان مرفوضًا
        if deposit["status"] == "rejected":
            conn.rollback()

            return {
                "success": False,
                "message": "هذا الإيداع مرفوض مسبقًا"
            }

        # إضافة الرصيد للمستخدم
        conn.execute("""
            UPDATE users

            SET balance = balance + ?

            WHERE id = ?
        """, (
            deposit["amount"],
            deposit["user_id"]
        ))

        # تغيير حالة الإيداع
        conn.execute("""
            UPDATE deposits

            SET status = 'approved'

            WHERE id = ?
        """, (deposit_id,))

        conn.commit()

        # جلب الرصيد الجديد
        user = conn.execute("""
            SELECT balance
            FROM users
            WHERE id = ?
        """, (
            deposit["user_id"],
        )).fetchone()

        return {
            "success": True,
            "message": "تم قبول الإيداع بنجاح",
            "user_id": deposit["user_id"],
            "amount": deposit["amount"],
            "balance": user["balance"]
        }

    except Exception as e:

        conn.rollback()

        print("Approve deposit error:", e)

        return {
            "success": False,
            "message": "حدث خطأ أثناء قبول الإيداع"
        }

    finally:
        conn.close()


def reject_deposit(deposit_id):
    """
    رفض طلب الإيداع بدون إضافة أي مبلغ.
    """

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

            return {
                "success": False,
                "message": "طلب الإيداع غير موجود"
            }

        if deposit["status"] == "approved":
            conn.rollback()

            return {
                "success": False,
                "message": "لا يمكن رفض إيداع تم قبوله"
            }

        if deposit["status"] == "rejected":
            conn.rollback()

            return {
                "success": False,
                "message": "تم رفض هذا الإيداع مسبقًا"
            }

        conn.execute("""
            UPDATE deposits

            SET status = 'rejected'

            WHERE id = ?
        """, (deposit_id,))

        conn.commit()

        return {
            "success": True,
            "message": "تم رفض الإيداع",
            "user_id": deposit["user_id"],
            "amount": deposit["amount"]
        }

    except Exception as e:

        conn.rollback()

        print("Reject deposit error:", e)

        return {
            "success": False,
            "message": "حدث خطأ أثناء رفض الإيداع"
        }

    finally:
        conn.close()
