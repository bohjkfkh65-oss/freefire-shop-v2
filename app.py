from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
from pathlib import Path
import json
import requests
from dotenv import load_dotenv
from database.db import get_db, init_database
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import quote

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '').strip()

app = Flask(__name__)

@app.template_filter("fromjson")
def fromjson_filter(value):
    try:
        return json.loads(value or "[]")
    except Exception:
        return []

app.secret_key = "freefire-shop-secret-key"

init_database()


@app.route("/")
def home():
    db = get_db()

    # تعطيل العروض المنتهية تلقائيًا
    db.execute("""
        UPDATE offers
        SET active = 0
        WHERE active = 1
          AND expires_at IS NOT NULL
          AND datetime(expires_at) <= datetime('now')
    """)
    db.commit()

    products = db.execute("""
        SELECT id, name, description, price, category
        FROM products
        WHERE active = 1
        ORDER BY id DESC
    """).fetchall()

    offers = db.execute("""
        SELECT
            offers.id,
            offers.product_id,
            offers.old_price,
            offers.offer_price,
            offers.duration_minutes,
            offers.duration_unit,
            offers.description,
            offers.expires_at,
            products.name AS product_name,
            products.description AS product_description
        FROM offers
        JOIN products ON products.id = offers.product_id
        WHERE offers.active = 1
          AND datetime(offers.expires_at) > datetime('now')
          AND products.active = 1
        ORDER BY offers.expires_at ASC
    """).fetchall()

    accounts = db.execute("""
        SELECT
            account_sales.id,
            account_sales.title,
            account_sales.description,
            account_sales.price,
            account_sales.images,
            users.username
        FROM account_sales
        JOIN users ON users.id = account_sales.user_id
        WHERE account_sales.status = 'approved'
        ORDER BY account_sales.id DESC
    """).fetchall()

    db.close()

    return render_template(
        "index.html",
        products=products,
        offers=offers,
        accounts=accounts
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip().lower()
        whatsapp = request.form["whatsapp"].strip()
        recovery_id = request.form["recovery_id"].strip()
        password = request.form["password"]

        if not username or not email or not whatsapp or not recovery_id or not password:
            flash("جميع الحقول مطلوبة")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
            return redirect(url_for("register"))

        db = get_db()

        existing = db.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing:
            db.close()
            flash("هذا البريد الإلكتروني مستخدم بالفعل")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        cursor = db.execute("""
            INSERT INTO users (username, email, password, whatsapp, recovery_id)
            VALUES (?, ?, ?, ?, ?)
        """, (username, email, password_hash, whatsapp, recovery_id))

        db_user_id = cursor.lastrowid
        db.commit()
        db.close()

        # إرسال إشعار للأدمن عند إنشاء عضو جديد
        try:
            bot_token = os.getenv("BOT_TOKEN")
            admin_chat_id = os.getenv("ADMIN_CHAT_ID")

            if bot_token and admin_chat_id:
                message = f"""🆕 عضو جديد في FreeFire Shop

🆔 ID: {db_user_id if 'db_user_id' in locals() else 'غير متوفر'}
👤 اسم المستخدم: {username}
📧 البريد الإلكتروني: {email}
📱 واتساب: {whatsapp}
🆔 Recovery ID: {recovery_id}

🎉 تم إنشاء الحساب بنجاح."""

                requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data={
                        "chat_id": admin_chat_id,
                        "text": message
                    },
                    timeout=10
                )
        except Exception as e:
            print("Telegram registration notification error:", e)

        flash("تم إنشاء الحساب بنجاح، يمكنك تسجيل الدخول الآن")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            banned = db.execute(
                "SELECT reason FROM banned_users WHERE user_id = ? LIMIT 1",
                (user["id"],)
            ).fetchone()

            if banned:
                reason = banned["reason"] or "لم يتم تحديد السبب"
                db.close()
                flash(f"🚫 هذا الحساب محظور. السبب: {reason}")
                return redirect(url_for("login"))

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            db.close()
            return redirect(url_for("home"))

        db.close()
        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة")

    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    verified = False

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        recovery_id = request.form["recovery_id"].strip()

        db = get_db()

        user = db.execute("""
            SELECT id, username, whatsapp
            FROM users
            WHERE email = ?
              AND recovery_id = ?
        """, (email, recovery_id)).fetchone()

        db.close()

        if user:
            verified = True
            flash("✅ تم التحقق من بيانات الحساب. تواصل مع الدعم لإعادة تعيين كلمة المرور.")
        else:
            flash("❌ البريد الإلكتروني أو Recovery ID غير صحيح.")

    return render_template(
        "forgot_password.html",
        verified=verified,
        support_whatsapp="0926336869"
    )


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if len(new_password) < 6:
            flash("❌ كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل")
            return redirect(url_for("change_password"))

        if new_password != confirm_password:
            flash("❌ كلمتا المرور الجديدتان غير متطابقتين")
            return redirect(url_for("change_password"))

        db = get_db()
        user = db.execute(
            "SELECT password FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

        if not user or not check_password_hash(user["password"], current_password):
            db.close()
            flash("❌ كلمة المرور الحالية غير صحيحة")
            return redirect(url_for("change_password"))

        new_hash = generate_password_hash(new_password)

        db.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (new_hash, session["user_id"])
        )
        db.commit()
        db.close()

        flash("✅ تم تغيير كلمة المرور بنجاح")
        return redirect(url_for("home"))

    return render_template("change_password.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))



@app.route("/wallet")
def wallet():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    user = db.execute(
        "SELECT id, username, balance FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    deposits = db.execute("""
        SELECT
            deposits.id,
            deposits.amount,
            deposits.transaction_number,
            deposits.status,
            deposits.created_at,
            payment_methods.name AS payment_method
        FROM deposits
        JOIN payment_methods
            ON payment_methods.id = deposits.payment_method_id
        WHERE deposits.user_id = ?
        ORDER BY deposits.id DESC
    """, (session["user_id"],)).fetchall()

    payment_methods = db.execute("""
        SELECT id, name, account_number, owner_name
        FROM payment_methods
        WHERE active = 1
        ORDER BY id
    """).fetchall()

    db.close()

    return render_template(
        "wallet.html",
        user=user,
        deposits=deposits,
        payment_methods=payment_methods
    )



def send_deposit_to_telegram(
    deposit_id,
    username,
    email,
    amount,
    payment_method,
    account_number,
    owner_name,
    transaction_number
):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("⚠️ BOT_TOKEN أو ADMIN_CHAT_ID غير موجود")
        return

    text = (
        "💰 <b>طلب إيداع جديد</b>\n\n"
        f"🆔 رقم الإيداع: <b>#{deposit_id}</b>\n"
        f"👤 المستخدم: <b>{username}</b>\n"
        f"📧 البريد: <b>{email}</b>\n"
        f"💵 المبلغ: <b>{amount} جنيه</b>\n"
        f"💳 طريقة الدفع: <b>{payment_method}</b>\n"
        f"🏦 رقم الحساب: <b>{account_number}</b>\n"
        f"👤 صاحب الحساب: <b>{owner_name}</b>\n"
        f"🧾 رقم العملية: <b>{transaction_number}</b>\n\n"
        "⏳ الحالة: <b>قيد المراجعة</b>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ قبول",
                    "callback_data": f"deposit_approve:{deposit_id}"
                },
                {
                    "text": "❌ رفض",
                    "callback_data": f"deposit_reject:{deposit_id}"
                }
            ]
        ]
    }

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard
            },
            timeout=15
        )

        if response.ok:
            print(f"✅ تم إرسال الإيداع #{deposit_id} إلى Telegram")
        else:
            print("❌ Telegram Error:", response.text)

    except Exception as e:
        print("❌ خطأ إرسال Telegram:", e)


@app.route("/deposit", methods=["POST"])
def deposit():
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError):
        flash("أدخل مبلغًا صحيحًا")
        return redirect(url_for("wallet"))

    payment_method_id = request.form["payment_method_id"]
    transaction_number = request.form["transaction_number"].strip()

    if amount <= 0:
        flash("المبلغ يجب أن يكون أكبر من صفر")
        return redirect(url_for("wallet"))

    if not transaction_number:
        flash("أدخل رقم العملية")
        return redirect(url_for("wallet"))

    db = get_db()

    payment_method = db.execute("""
        SELECT id, name, account_number, owner_name
        FROM payment_methods
        WHERE id = ? AND active = 1
    """, (payment_method_id,)).fetchone()

    if not payment_method:
        db.close()
        flash("طريقة الدفع غير متاحة")
        return redirect(url_for("wallet"))

    cursor = db.execute("""
        INSERT INTO deposits (
            user_id,
            amount,
            payment_method_id,
            transaction_number,
            status
        )
        VALUES (?, ?, ?, ?, 'pending')
    """, (
        session["user_id"],
        amount,
        payment_method_id,
        transaction_number
    ))

    deposit_id = cursor.lastrowid

    user = db.execute("""
        SELECT username, email
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    db.commit()
    db.close()

    send_deposit_to_telegram(
        deposit_id=deposit_id,
        username=user["username"],
        email=user["email"],
        amount=amount,
        payment_method=payment_method["name"],
        account_number=payment_method["account_number"],
        owner_name=payment_method["owner_name"],
        transaction_number=transaction_number
    )

    flash("تم إرسال طلب الإيداع للمراجعة ✅")
    return redirect(url_for("wallet"))


@app.route("/buy/<int:product_id>", methods=["GET", "POST"])
def buy(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    product = db.execute("""
        SELECT id, name, description, price, category
        FROM products
        WHERE id = ? AND active = 1
    """, (product_id,)).fetchone()

    if not product:
        db.close()
        flash("الباقة غير موجودة")
        return redirect(url_for("home"))

    # تحديد سعر الشراء: سعر العرض إذا كان هناك عرض فعال وغير منتهٍ
    offer = db.execute("""
        SELECT id, old_price, offer_price, duration_minutes,
               duration_unit, description, expires_at
        FROM offers
        WHERE product_id = ?
          AND active = 1
          AND datetime(expires_at) > datetime('now')
        ORDER BY expires_at ASC
        LIMIT 1
    """, (product_id,)).fetchone()

    if offer:
        purchase_price = offer["offer_price"]
    else:
        purchase_price = product["price"]

    user = db.execute("""
        SELECT id, username, email, balance
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    if request.method == "POST":
        player_id = request.form["player_id"].strip()

        if not player_id:
            db.close()
            flash("أدخل Player ID")
            return redirect(url_for("buy", product_id=product_id))

        if user["balance"] < purchase_price:
            db.close()
            flash(
                f"رصيدك غير كافٍ. السعر {purchase_price} جنيه "
                f"ورصيدك {user['balance']} جنيه"
            )
            return redirect(url_for("wallet"))

        # خصم المبلغ وإنشاء الطلب في نفس العملية
        db.execute("""
            UPDATE users
            SET balance = balance - ?
            WHERE id = ?
        """, (purchase_price, user["id"]))

        cursor = db.execute("""
            INSERT INTO orders (
                user_id,
                product_id,
                player_id,
                amount,
                status
            )
            VALUES (?, ?, ?, ?, 'pending')
        """, (
            user["id"],
            product["id"],
            player_id,
            purchase_price
        ))

        order_id = cursor.lastrowid

        db.commit()
        db.close()

        # إرسال الطلب إلى Telegram
        if BOT_TOKEN and ADMIN_CHAT_ID:
            text = (
                "🛒 <b>طلب شحن جديد</b>\n\n"
                f"🆔 رقم الطلب: <b>#{order_id}</b>\n"
                f"👤 المستخدم: <b>{user['username']}</b>\n"
                f"📧 البريد: <b>{user['email']}</b>\n"
                f"💎 الباقة: <b>{product['name']}</b>\n"
                f"💵 السعر: <b>{purchase_price} جنيه</b>\n"
                f"🎮 Player ID: <b>{player_id}</b>\n\n"
                "⏳ الحالة: <b>قيد المراجعة</b>"
            )

            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ تنفيذ الطلب",
                            "callback_data": f"order_approve:{order_id}"
                        },
                        {
                            "text": "❌ رفض الطلب",
                            "callback_data": f"order_reject:{order_id}"
                        }
                    ]
                ]
            }

            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_CHAT_ID,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard
                    },
                    timeout=15
                )

                if not response.ok:
                    print("❌ Telegram Error:", response.text)

            except Exception as e:
                print("❌ خطأ إرسال طلب الشحن:", e)

        flash(f"تم إنشاء الطلب #{order_id} وهو الآن قيد التنفيذ ⏳")
        return redirect(url_for("orders"))

    db.close()

    return render_template(
        "buy.html",
        product=product,
        user=user,
        offer=offer,
        purchase_price=purchase_price
    )




def send_account_to_telegram(
    account_id,
    username,
    whatsapp,
    title,
    description,
    price,
    image_paths
):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("⚠️ BOT_TOKEN أو ADMIN_CHAT_ID غير موجود")
        return

    text = (
        "🎮 <b>طلب حساب جديد للبيع</b>\n\n"
        f"🆔 رقم الطلب: <b>#{account_id}</b>\n"
        f"👤 البائع: <b>{username}</b>\n"
        f"📱 واتساب البائع: <code>{whatsapp}</code>\n"
        f"🎮 اسم الحساب: <b>{title}</b>\n"
        f"💰 السعر: <b>{price:.0f} جنيه</b>\n\n"
        f"📝 <b>التفاصيل:</b>\n{description}\n\n"
        "⏳ الحالة: <b>قيد المراجعة</b>"
    )

    whatsapp_number = str(whatsapp).strip().replace("+", "").replace(" ", "").replace("-", "")

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "💬 تواصل عبر واتساب",
                    "url": f"https://wa.me/{whatsapp_number}"
                }
            ],
            [
                {
                    "text": "✅ قبول الحساب",
                    "callback_data": f"account_approve:{account_id}"
                },
                {
                    "text": "❌ رفض الحساب",
                    "callback_data": f"account_reject:{account_id}"
                }
            ]
        ]
    }

    try:
        first_image = True

        for image_path in image_paths:
            full_path = os.path.join(
                app.root_path,
                "static",
                "uploads",
                "accounts",
                image_path
            )

            if not os.path.exists(full_path):
                continue

            with open(full_path, "rb") as photo:
                data = {
                    "chat_id": ADMIN_CHAT_ID
                }

                if first_image:
                    data["caption"] = text
                    data["parse_mode"] = "HTML"
                    data["reply_markup"] = json.dumps(keyboard)

                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    data=data,
                    files={"photo": photo},
                    timeout=30
                )

            first_image = False

        if first_image:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                },
                timeout=15
            )

        print(f"✅ تم إرسال طلب الحساب #{account_id} إلى Telegram")

    except Exception as e:
        print(f"⚠️ خطأ في إرسال الحساب إلى Telegram: {e}")


@app.route("/sell-account", methods=["GET", "POST"])
def sell_account():
    if "user_id" not in session:
        flash("يجب تسجيل الدخول أولاً", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price_text = request.form.get("price", "").strip()
        files = request.files.getlist("images")

        if not title or not description or not price_text:
            flash("يرجى تعبئة جميع البيانات", "error")
            return render_template("sell_account.html")

        try:
            price = float(price_text)
            if price <= 0:
                raise ValueError
        except ValueError:
            flash("السعر غير صحيح", "error")
            return render_template("sell_account.html")

        allowed_extensions = {"jpg", "jpeg", "png", "webp"}
        upload_dir = Path(app.root_path) / "static" / "uploads" / "accounts"
        upload_dir.mkdir(parents=True, exist_ok=True)

        saved_images = []

        from werkzeug.utils import secure_filename
        import uuid

        for file in files:
            if not file or not file.filename:
                continue

            original_name = secure_filename(file.filename)
            extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

            if extension not in allowed_extensions:
                continue

            filename = f"{uuid.uuid4().hex}.{extension}"
            file.save(upload_dir / filename)
            saved_images.append(filename)

        if not saved_images:
            flash("يرجى اختيار صورة واحدة على الأقل", "error")
            return render_template("sell_account.html")

        db = get_db()

        cursor = db.execute("""
            INSERT INTO account_sales
            (user_id, title, description, price, images, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (
            session["user_id"],
            title,
            description,
            price,
            json.dumps(saved_images, ensure_ascii=False)
        ))

        account_id = cursor.lastrowid
        db.commit()
        db.close()

        # إرسال الحساب والصور إلى Telegram للمراجعة
        try:
            current_user = get_db().execute(
                "SELECT username FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()

            username = current_user["username"] if current_user else "غير معروف"

            image_paths = [
                str(upload_dir / filename)
                for filename in saved_images
            ]

            db_whatsapp = get_db()
            seller_row = db_whatsapp.execute(
                "SELECT whatsapp FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()
            db_whatsapp.close()

            whatsapp = seller_row["whatsapp"] if seller_row and seller_row["whatsapp"] else "غير مسجل"

            send_account_to_telegram(
                account_id,
                username,
                whatsapp,
                title,
                description,
                price,
                image_paths
            )

        except Exception as e:
            print("⚠️ تعذر إرسال الحساب إلى Telegram:", e)

        flash("تم إرسال حسابك للمراجعة بنجاح ✅", "success")
        return redirect(url_for("accounts"))

    return render_template("sell_account.html")


@app.route("/delete-account/<int:account_id>", methods=["POST"])
def delete_account(account_id):
    if "user_id" not in session:
        flash("يجب تسجيل الدخول أولًا")
        return redirect(url_for("login"))

    db = get_db()

    account = db.execute(
        "SELECT id, user_id FROM account_sales WHERE id = ?",
        (account_id,)
    ).fetchone()

    if not account:
        db.close()
        flash("الإعلان غير موجود")
        return redirect(url_for("accounts"))

    # صاحب الإعلان فقط يستطيع حذفه
    if account["user_id"] != session["user_id"]:
        db.close()
        flash("❌ لا يمكنك حذف إعلان ليس لك")
        return redirect(url_for("accounts"))

    db.execute(
        "DELETE FROM account_sales WHERE id = ?",
        (account_id,)
    )
    db.commit()
    db.close()

    flash("🗑️ تم حذف الإعلان من المتجر للجميع")
    return redirect(url_for("accounts"))


@app.route("/buy-account/<int:account_id>")
def buy_account(account_id):
    db = get_db()

    account = db.execute("""
        SELECT account_sales.title, users.whatsapp
        FROM account_sales
        JOIN users ON users.id = account_sales.user_id
        WHERE account_sales.id = ?
          AND account_sales.status = 'approved'
    """, (account_id,)).fetchone()

    db.close()

    if not account:
        flash("❌ الحساب غير موجود أو لم يعد متاحًا")
        return redirect(url_for("accounts"))

    whatsapp = (account["whatsapp"] or "").strip()
    number = "".join(ch for ch in whatsapp if ch.isdigit())

    if not number:
        flash("❌ صاحب الحساب لم يضف رقم واتساب صالحًا")
        return redirect(url_for("accounts"))

    message = quote(
        "مرحبًا، أريد شراء حساب Free Fire: " + account["title"]
    )

    return redirect(f"https://wa.me/{number}?text={message}")


@app.route("/accounts")
def accounts():
    db = get_db()

    accounts = db.execute("""
        SELECT
            account_sales.id,
            account_sales.title,
            account_sales.description,
            account_sales.price,
            account_sales.images,
            account_sales.created_at,
            account_sales.user_id,
            users.username,
            users.whatsapp
        FROM account_sales
        JOIN users
            ON users.id = account_sales.user_id
        WHERE account_sales.status = 'approved'
        ORDER BY account_sales.id DESC
    """).fetchall()

    db.close()

    return render_template(
        "accounts.html",
        accounts=accounts
    )

@app.route("/orders")
def orders():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    orders_list = db.execute("""
        SELECT
            orders.id,
            orders.player_id,
            orders.amount,
            orders.status,
            products.name AS product_name,
            products.description AS product_description
        FROM orders
        JOIN products
            ON products.id = orders.product_id
        WHERE orders.user_id = ?
        ORDER BY orders.id DESC
    """, (session["user_id"],)).fetchall()

    db.close()

    return render_template(
        "orders.html",
        orders=orders_list
    )


@app.route("/suggestion", methods=["GET", "POST"])
def suggestion():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        message = request.form.get("message", "").strip()

        if not message:
            flash("اكتب اقتراحك أولاً")
            return redirect(url_for("suggestion"))

        db = get_db()

        cursor = db.execute("""
            INSERT INTO suggestions (user_id, message, status)
            VALUES (?, ?, 'new')
        """, (
            session["user_id"],
            message
        ))

        suggestion_id = cursor.lastrowid

        user = db.execute("""
            SELECT username, email
            FROM users
            WHERE id = ?
        """, (session["user_id"],)).fetchone()

        db.commit()
        db.close()

        # إرسال الاقتراح إلى Telegram
        if BOT_TOKEN and ADMIN_CHAT_ID:
            text = (
                "💡 <b>اقتراح جديد</b>\n\n"
                f"🆔 رقم الاقتراح: <b>#{suggestion_id}</b>\n"
                f"👤 المستخدم: <b>{user['username']}</b>\n"
                f"📧 البريد: <b>{user['email']}</b>\n\n"
                f"📝 <b>الاقتراح:</b>\n{message}"
            )

            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ تمت المراجعة",
                            "callback_data": f"suggestion_done:{suggestion_id}"
                        }
                    ]
                ]
            }

            try:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_CHAT_ID,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard
                    },
                    timeout=15
                )
            except Exception as e:
                print("❌ خطأ إرسال الاقتراح:", e)

        flash("تم إرسال اقتراحك بنجاح 💡")
        return redirect(url_for("suggestion"))

    return render_template("suggestion.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
