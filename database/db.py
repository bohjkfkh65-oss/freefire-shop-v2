import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE = BASE_DIR / "database" / "shop.db"


def get_connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    return get_connection()


def init_database():
    conn = get_connection()

    # =========================
    # Users
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT,
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            telegram_chat_id TEXT,
            whatsapp TEXT,
            recovery_id TEXT
        )
    """)

    # =========================
    # Products
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Orders
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Payment Methods
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_number TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    # =========================
    # Deposits
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method_id INTEGER NOT NULL,
            transaction_number TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Banned Users
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Account Sales
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            price REAL NOT NULL,
            images TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Suggestions
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Active Visitors
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_visitors (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Admins
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by TEXT
        )
    """)

    # =========================
    # Offers
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            old_price REAL NOT NULL,
            offer_price REAL NOT NULL,
            duration_minutes INTEGER NOT NULL,
            active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            description TEXT DEFAULT '',
            duration_unit TEXT DEFAULT 'days'
        )
    """)

    # =========================
    # Google Products
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS google_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            category TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =========================
    # Products الأساسية
    # =========================
    products = [
        (
            4,
            "💎 100 Diamonds",
            "100 الماسة Free Fire",
            8000,
            "freefire"
        ),
        (
            5,
            "💎 210 Diamonds",
            "210 الماسة Free Fire",
            16000,
            "freefire"
        ),
        (
            6,
            "💎 530 Diamonds",
            "530 الماسة Free Fire",
            39500,
            "freefire"
        ),
        (
            7,
            "💎 1080 Diamonds",
            "1080 الماسة Free Fire",
            78500,
            "freefire"
        ),
        (
            8,
            "💎 2200 Diamonds",
            "2200 الماسة Free Fire",
            156500,
            "freefire"
        ),
        (
            9,
            "👑 عضوية أسبوعية",
            "عضوية Free Fire الأسبوعية",
            18000,
            "freefire"
        ),
        (
            10,
            "👑 عضوية شهرية",
            "عضوية Free Fire الشهرية",
            86000,
            "freefire"
        ),
        (
            11,
            "🔵 حساب Google",
            "حساب Google جاهز للشراء",
            2000,
            "google"
        ),
    ]

    for product_id, name, description, price, category in products:
        conn.execute("""
            INSERT OR IGNORE INTO products
            (id, name, description, price, category, active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (
            product_id,
            name,
            description,
            price,
            category
        ))

    # =========================
    # طرق الدفع الأساسية
    # =========================
    payment_methods = [
        ("بنكك", "8229209", "ايمن عبدالوهاب"),
        ("ماي كاشي", "661205", "ايمن عبدالوهاب"),
        ("فوري", "52017677", "ايمن عبدالوهاب"),
    ]

    for name, account_number, owner_name in payment_methods:
        exists = conn.execute("""
            SELECT id
            FROM payment_methods
            WHERE name = ?
              AND account_number = ?
            LIMIT 1
        """, (
            name,
            account_number
        )).fetchone()

        if exists is None:
            conn.execute("""
                INSERT INTO payment_methods
                (name, account_number, owner_name, active)
                VALUES (?, ?, ?, 1)
            """, (
                name,
                account_number,
                owner_name
            ))

    conn.commit()
    conn.close()
