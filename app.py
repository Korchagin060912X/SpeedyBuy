import hashlib
import os
import sqlite3

from flask import Flask, render_template, request, redirect, url_for, session, abort, flash

app = Flask(__name__)
app.config.update(
    SECRET_KEY='speedybuy-dev-key',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)
app.secret_key = 'speedybuy-dev-key'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'speedybuy.db')


def sanitize_text(value, max_len=255):
    if value is None:
        return ''
    value = str(value).strip()
    return value[:max_len]


def validate_order_payload(email, comment, rating):
    cleaned_email = sanitize_text(email, 254)
    cleaned_comment = sanitize_text(comment, 2000)
    local_part, separator, domain = cleaned_email.rpartition('@')
    if (
        cleaned_email.count('@') != 1
        or not separator
        or not local_part
        or '.' not in domain
        or any(character.isspace() for character in cleaned_email)
    ):
        return None
    domain_labels = domain.split('.')
    if any(not label or label.startswith('-') or label.endswith('-') for label in domain_labels):
        return None
    if not cleaned_comment:
        return None
    if rating in (None, ''):
        cleaned_rating = None
    else:
        try:
            cleaned_rating = int(rating)
        except (TypeError, ValueError):
            return None
        if not 1 <= cleaned_rating <= 5:
            return None
    return {'email': cleaned_email, 'comment': cleaned_comment, 'rating': cleaned_rating}


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT NOT NULL,
            app_type TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            is_popular INTEGER NOT NULL DEFAULT 0,
            is_new INTEGER NOT NULL DEFAULT 0,
            seller_comment TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            avatar_url TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            city TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS carts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cart_id) REFERENCES carts(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            customer_email TEXT DEFAULT '',
            customer_comment TEXT DEFAULT '',
            rating INTEGER,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'Ожидает оплаты',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            product_name TEXT NOT NULL,
            product_description TEXT DEFAULT '',
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            provider TEXT DEFAULT '',
            provider_payment_id TEXT DEFAULT '',
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            raw_payload TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS faq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS support_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            sender_name TEXT NOT NULL,
            message TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(thread_id) REFERENCES support_threads(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    product_columns = {row['name'] for row in conn.execute('PRAGMA table_info(products)').fetchall()}
    for field in ['app_type', 'image_url', 'is_active', 'is_popular', 'is_new', 'seller_comment']:
        if field not in product_columns:
            if field in ['is_active', 'is_popular', 'is_new']:
                default_sql = 'INTEGER NOT NULL DEFAULT 1'
            elif field == 'seller_comment':
                default_sql = 'TEXT NOT NULL DEFAULT ""'
            else:
                default_sql = 'TEXT DEFAULT ""'
            conn.execute(f'ALTER TABLE products ADD COLUMN {field} {default_sql}')
    if 'created_at' not in product_columns:
        conn.execute('ALTER TABLE products ADD COLUMN created_at TEXT')
        conn.execute('UPDATE products SET created_at = CURRENT_TIMESTAMP')

    order_columns = {row['name'] for row in conn.execute('PRAGMA table_info(orders)').fetchall()}
    for field, default_sql in {
        'user_id': 'INTEGER',
        'customer_email': 'TEXT DEFAULT ""',
        'customer_comment': 'TEXT DEFAULT ""',
        'rating': 'INTEGER',
        'status': 'TEXT DEFAULT "Ожидает оплаты"',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    }.items():
        if field not in order_columns:
            conn.execute(f'ALTER TABLE orders ADD COLUMN {field} {default_sql}')

    order_item_columns = {row['name'] for row in conn.execute('PRAGMA table_info(order_items)').fetchall()}
    for field, default_sql in {
        'product_name': 'TEXT DEFAULT ""',
        'product_description': 'TEXT DEFAULT ""',
    }.items():
        if field not in order_item_columns:
            conn.execute(f'ALTER TABLE order_items ADD COLUMN {field} {default_sql}')

    if not conn.execute('SELECT 1 FROM categories LIMIT 1').fetchone():
        categories = ['Подписки', 'Ключи', 'Игры']
        for category_name in categories:
            slug = category_name.lower().replace(' ', '-')
            conn.execute('INSERT OR IGNORE INTO categories (name, slug, description, is_active) VALUES (?, ?, ?, 1)', (category_name, slug, f'Категория: {category_name}'))

    product_count = conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    if product_count == 0:
        conn.executemany(
            'INSERT INTO products (name, category, price, description, app_type, image_url, is_active, is_popular, is_new) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                ('Steam Premium', 'Подписки', 399, 'Премиум-доступ к игровым бонусам и скидкам в Steam.', 'Steam', '', 1, 1, 1),
                ('Xbox Game Pass', 'Подписки', 599, 'Доступ к сотням игр и онлайн-сервисам Xbox.', 'Xbox', '', 1, 1, 0),
                ('Minecraft Java', 'Ключи', 1499, 'Оригинальный лицензионный ключ для Java-версии.', 'Minecraft', '', 1, 0, 1),
                ('CS2 Prime', 'Ключи', 899, 'Оригинальный ключ CS2 для активации Prime-статуса.', 'Counter-Strike 2', '', 1, 1, 0),
                ('Cyberpunk 2077', 'Игры', 1999, 'Полная версия культовой RPG в открытом мире.', 'CD Projekt Red', '', 1, 1, 0),
                ('EA SPORTS FC 25', 'Игры', 2599, 'Футбольный симулятор с актуальными клубами и составами.', 'EA Sports', '', 1, 0, 1),
                ('Spotify Family', 'Подписки', 449, 'Семейная подписка Spotify для нескольких пользователей.', 'Spotify', '', 1, 0, 1),
            ],
        )

    faq_count = conn.execute('SELECT COUNT(*) FROM faq').fetchone()[0]
    if faq_count == 0:
        conn.executemany(
            'INSERT INTO faq (question, answer, is_active, sort_order) VALUES (?, ?, ?, ?)',
            [
                ('Как быстро приходит ключ после оплаты?', 'Ключ отправляется автоматически сразу после подтверждения оплаты и обычно приходит в течение 1–5 минут.', 1, 1),
                ('Можно ли вернуть цифровой товар?', 'Возврат осуществляется только в случаях, когда товар не был активирован или подтверждено техническое несоответствие.', 1, 2),
                ('Поддерживаются ли подписки для нескольких пользователей?', 'Да, некоторые подписки поддерживают семейные и групповые тарифы, которые доступны в карточке товара.', 1, 3),
            ],
        )

    default_settings = {'telegram': 'https://t.me/speedybuy', 'tiktok': 'https://www.tiktok.com/@speedybuy'}
    for key, value in default_settings.items():
        conn.execute('INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)', (key, value))

    admin_exists = conn.execute('SELECT 1 FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin_exists:
        conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', ('admin', hash_password('admin123')))

    conn.commit()
    conn.close()


def get_db_row_to_dict(row):
    return dict(row) if row else None


def get_products(category='all', search='', sort='newest'):
    conn = get_db()
    query = 'SELECT * FROM products WHERE is_active = 1'
    params = []
    if category and category != 'all':
        query += ' AND category = ?'
        params.append(category)
    if search:
        query += ' AND name LIKE ?'
        params.append(f'%{search}%')
    if sort == 'price_asc':
        query += ' ORDER BY price ASC'
    elif sort == 'price_desc':
        query += ' ORDER BY price DESC'
    elif sort == 'newest':
        query += ' ORDER BY id DESC'
    else:
        query += ' ORDER BY id DESC'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return add_product_ratings([dict(row) for row in rows])


def get_categories():
    conn = get_db()
    rows = conn.execute('SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category ASC').fetchall()
    conn.close()
    return [row['category'] for row in rows]


def get_product_by_id(product_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    return get_db_row_to_dict(row)


def add_product_ratings(products):
    if not products:
        return products
    product_ids = [product['id'] for product in products]
    placeholders = ', '.join('?' for _ in product_ids)
    conn = get_db()
    rows = conn.execute(
        f'''
        SELECT product_id, ROUND(AVG(rating), 1) AS rating
        FROM (
            SELECT DISTINCT oi.product_id, oi.order_id, o.rating
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.product_id IN ({placeholders}) AND o.rating BETWEEN 1 AND 5
        )
        GROUP BY product_id
        ''',
        product_ids
    ).fetchall()
    conn.close()
    ratings = {row['product_id']: row['rating'] for row in rows}
    for product in products:
        product['rating'] = ratings.get(product['id'], 5.0)
    return products


def get_popular_products(limit=3):
    conn = get_db()
    rows = conn.execute(
        '''
        SELECT p.*, COUNT(DISTINCT oi.order_id) AS order_count
        FROM products p
        LEFT JOIN order_items oi ON oi.product_id = p.id
        WHERE p.is_active = 1
        GROUP BY p.id
        ORDER BY order_count DESC, p.created_at DESC, p.id DESC
        LIMIT ?
        ''',
        (limit,)
    ).fetchall()
    conn.close()
    return add_product_ratings([dict(row) for row in rows])


def get_new_products(limit=3):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM products WHERE is_active = 1 ORDER BY created_at DESC, id DESC LIMIT ?',
        (limit,)
    ).fetchall()
    conn.close()
    return add_product_ratings([dict(row) for row in rows])


def get_faq_items():
    conn = get_db()
    rows = conn.execute('SELECT * FROM faq WHERE is_active = 1 ORDER BY sort_order ASC, id ASC').fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_social_links():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM site_settings').fetchall()
    conn.close()
    data = {row['key']: row['value'] for row in rows}
    return {'telegram': data.get('telegram', 'https://t.me/speedybuy'), 'tiktok': data.get('tiktok', 'https://www.tiktok.com/@speedybuy')}


def get_or_create_cart(user_id=None):
    conn = get_db()
    if user_id is not None:
        row = conn.execute('SELECT * FROM carts WHERE user_id = ?', (user_id,)).fetchone()
        if row:
            conn.close(); return dict(row)
        cursor = conn.execute('INSERT INTO carts (user_id, created_at, updated_at) VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)', (user_id,))
        conn.commit(); conn.close(); return {'id': cursor.lastrowid, 'user_id': user_id}
    conn.close(); return None


def get_user_profile(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_review(product_id, user_id, rating, comment):
    if not product_id or not user_id or not 1 <= int(rating) <= 5:
        return False
    conn = get_db()
    conn.execute('INSERT INTO reviews (product_id, user_id, rating, comment) VALUES (?, ?, ?, ?)', (product_id, user_id, int(rating), sanitize_text(comment, 1000)))
    conn.commit(); conn.close(); return True


def get_reviews_for_product(product_id):
    conn = get_db()
    rows = conn.execute('SELECT r.*, u.username FROM reviews r JOIN users u ON u.id = r.user_id WHERE r.product_id = ? ORDER BY r.id DESC', (product_id,)).fetchall()
    conn.close(); return [dict(row) for row in rows]


def get_cart():
    return session.setdefault('cart', {})


def build_cart():
    cart = get_cart()
    items = []
    total = 0.0
    for product_id, quantity in cart.items():
        product = get_product_by_id(int(product_id))
        if product is None:
            continue
        qty = int(quantity)
        if qty <= 0:
            continue
        item_total = float(product['price']) * qty
        total += item_total
        items.append({'id': product['id'], 'name': product['name'], 'category': product['category'], 'app_type': product['app_type'], 'description': product['description'], 'seller_comment': product['seller_comment'], 'price': product['price'], 'quantity': qty, 'item_total': item_total})
    return items, total


def create_order_in_db(email, comment, rating, cart):
    cleaned = validate_order_payload(email, comment, rating)
    if not cleaned:
        return None
    items = []
    total = 0.0
    for product_id, quantity in cart.items():
        product = get_product_by_id(int(product_id))
        if not product:
            continue
        qty = int(quantity)
        item_total = float(product['price']) * qty
        total += item_total
        items.append({'id': product['id'], 'name': product['name'], 'price': product['price'], 'quantity': qty, 'item_total': item_total})
    if not items:
        return None
    conn = get_db()
    cursor = conn.execute(
        '''INSERT INTO orders (
            user_id, customer_name, phone, address, customer_email, customer_comment, rating, total_price, status
        ) VALUES (?, '', '', '', ?, ?, ?, ?, ?)''',
        (session.get('user_id'), cleaned['email'], cleaned['comment'], cleaned['rating'], total, 'Ожидает оплаты')
    )
    order_id = cursor.lastrowid
    for item in items:
        conn.execute(
            'INSERT INTO order_items (order_id, product_id, quantity, price, product_name, product_description) VALUES (?, ?, ?, ?, ?, ?)',
            (order_id, item['id'], item['quantity'], item['price'], item['name'], '')
        )
    conn.execute('INSERT INTO payments (order_id, provider, amount, status) VALUES (?, ?, ?, ?)', (order_id, 'manual', total, 'pending'))
    conn.commit(); conn.close()
    return {'id': order_id, **cleaned, 'items': items, 'total': total}


def create_product_in_db(name, category, price, description, app_type='', image_url='', seller_comment=''):
    name = sanitize_text(name, 120)
    category = sanitize_text(category, 80)
    description = sanitize_text(description, 1000)
    app_type = sanitize_text(app_type, 80)
    image_url = sanitize_text(image_url, 2048)
    seller_comment = sanitize_text(seller_comment, 1000)
    try:
        price_value = float(price)
    except (TypeError, ValueError):
        return False
    if not name or not category or price_value <= 0:
        return False
    conn = get_db()
    conn.execute(
        '''INSERT INTO products (
            name, category, price, description, app_type, image_url, seller_comment,
            is_active, is_popular, is_new, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
        (name, category, price_value, description, app_type, image_url, seller_comment, 1, 0, 0)
    )
    conn.commit(); conn.close()
    return True


def get_orders():
    conn = get_db()
    rows = conn.execute('SELECT * FROM orders ORDER BY id DESC').fetchall()
    orders = []
    for row in rows:
        order = dict(row)
        item_rows = conn.execute(
            '''SELECT oi.*, p.name AS product_name, p.category,
                      oi.quantity * oi.price AS item_total
               FROM order_items oi
               JOIN products p ON p.id = oi.product_id
               WHERE oi.order_id = ?''',
            (order['id'],)
        ).fetchall()
        order['items'] = [dict(item) for item in item_rows]
        orders.append(order)
    conn.close()
    return orders


def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def login_user(username, password):
    username = sanitize_text(username, 50)
    password = sanitize_text(password, 100)
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    if not user:
        return None
    if user['password_hash'] != hash_password(password):
        return None
    session['user_id'] = user['id']
    session['username'] = user['username']
    return user


def is_admin_user(user=None):
    current_user = user or get_current_user()
    if isinstance(current_user, sqlite3.Row):
        current_user = dict(current_user)
    return bool(current_user and current_user.get('username') == 'admin')


def register_user(username, password):
    username = sanitize_text(username, 50)
    password = sanitize_text(password, 100)
    if len(username) < 3 or len(password) < 6:
        return False
    conn = get_db()
    exists = conn.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone()
    if exists:
        conn.close(); return False
    conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, hash_password(password)))
    user_id = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()['id']
    conn.execute('INSERT OR IGNORE INTO user_profiles (user_id, avatar_url, bio, city, phone) VALUES (?, ?, ?, ?, ?)', (user_id, '', '', '', ''))
    conn.commit(); conn.close()
    return login_user(username, password)


def create_support_thread(user_id, subject, message):
    conn = get_db()
    thread_id = conn.execute('INSERT INTO support_threads (user_id, subject, status) VALUES (?, ?, ?)', (user_id, subject or 'Без темы', 'open')).lastrowid
    conn.execute('INSERT INTO support_messages (thread_id, sender_name, message, is_admin) VALUES (?, ?, ?, ?)', (thread_id, session.get('username', 'User'), message, 0))
    conn.commit(); conn.close()
    return thread_id


def get_support_threads_for_user(user_id):
    conn = get_db()
    rows = conn.execute('SELECT * FROM support_threads WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
    threads = []
    for row in rows:
        messages = conn.execute('SELECT * FROM support_messages WHERE thread_id = ? ORDER BY id ASC', (row['id'],)).fetchall()
        threads.append({'thread': dict(row), 'messages': [dict(m) for m in messages]})
    conn.close()
    return threads


@app.before_request
def enforce_security_checks():
    if request.method == 'POST' and request.path in ['/order', '/profile', '/support']:
        if request.form.get('csrf_token') is not None:
            return None


init_db()


@app.context_processor
def inject_globals():
    return {'social_links': get_social_links(), 'cart_count': sum(int(v) for v in get_cart().values())}


@app.route('/')
def index():
    social_links = get_social_links()
    popular_products = get_popular_products(3)
    new_products = get_new_products(3)
    categories = get_categories()
    return render_template('index.html', social_links=social_links, popular_products=popular_products, new_products=new_products, categories=categories)


@app.route('/marketplace')
def marketplace():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'newest')
    products = get_products(category, search, sort)
    categories = get_categories()
    return render_template('marketplace.html', products=products, categories=categories, active_category=category, search=search, sort=sort)


@app.route('/faq')
def faq_page():
    faq_items = get_faq_items()
    return render_template('faq.html', faq_items=faq_items)


@app.route('/support', methods=['GET', 'POST'])
def support_page():
    user = get_current_user()
    if not user:
        return render_template('support.html', user=None, threads=[])
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if message:
            create_support_thread(user['id'], subject, message)
        return redirect(url_for('support_page'))
    threads = get_support_threads_for_user(user['id'])
    return render_template('support.html', user=user, threads=threads)


@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    user = get_current_user()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            if register_user(username, password):
                flash('Регистрация успешна!')
                return redirect(url_for('profile_page'))
            flash('Ошибка регистрации или ник уже занят.')
            return redirect(url_for('profile_page'))
        if action == 'login':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            if login_user(username, password):
                flash('Вы вошли в систему.')
                return redirect(url_for('profile_page'))
            flash('Неверный никнейм или пароль.')
            return redirect(url_for('profile_page'))
    return render_template('profile.html', user=user)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if get_product_by_id(product_id) is None:
        abort(404)
    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session['cart'] = cart
    return redirect(url_for('marketplace'))


@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(str(product_id), None)
    session['cart'] = cart
    return redirect(url_for('cart_page'))


@app.route('/cart')
def cart_page():
    items, total = build_cart()
    item_count = sum(item['quantity'] for item in items)
    return render_template('cart.html', items=items, total=total, item_count=item_count)


@app.route('/checkout')
def checkout():
    items, total = build_cart()
    return render_template('checkout.html', items=items, total=total, error=None, form_data={})


@app.route('/order', methods=['POST'])
def create_order():
    email = request.form.get('email', '').strip()
    comment = request.form.get('comment', '').strip()
    rating = request.form.get('rating', '').strip()
    items, total = build_cart()
    if not items:
        return redirect(url_for('cart_page'))
    if validate_order_payload(email, comment, rating) is None:
        return render_template(
            'checkout.html',
            items=items,
            total=total,
            error='Укажите корректную почту и обязательный комментарий к заказу. Оценка должна быть от 1 до 5 звёзд.',
            form_data=request.form,
        ), 400
    order = create_order_in_db(
        email,
        comment,
        rating,
        {str(item['id']): item['quantity'] for item in items}
    )
    if order is None:
        flash('Не удалось оформить заказ. Проверьте товары в корзине.')
        return redirect(url_for('cart_page'))
    session['cart'] = {}
    return render_template('order_success.html', order=order)


@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    user = get_current_user()
    if user and is_admin_user(user):
        orders = get_orders()
        return render_template('admin_orders.html', orders=orders)
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        logged_user = login_user(username, password)
        if logged_user and is_admin_user(logged_user):
            flash('Админ-вход выполнен.')
            return redirect(url_for('admin_panel'))
        flash('Неверный логин или пароль администратора.')
        return redirect(url_for('admin_panel'))
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('admin_panel'))


@app.route('/admin/products')
def admin_products():
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))
    conn = get_db()
    products = [dict(row) for row in conn.execute(
        'SELECT * FROM products WHERE is_active = 1 ORDER BY id DESC'
    ).fetchall()]
    deleted_products = [dict(row) for row in conn.execute(
        'SELECT * FROM products WHERE is_active = 0 ORDER BY id DESC'
    ).fetchall()]
    conn.close()
    return render_template(
        'admin_products.html',
        products=products,
        deleted_products=deleted_products
    )


@app.route('/admin/products/<int:product_id>/edit', methods=['GET', 'POST'])
def admin_products_edit(product_id):
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))

    product = get_product_by_id(product_id)
    if product is None:
        abort(404)

    if request.method == 'POST':
        name = sanitize_text(request.form.get('name'), 120)
        image_url = sanitize_text(request.form.get('image_url'), 2048)
        seller_comment = sanitize_text(request.form.get('seller_comment'), 1000)
        if not name:
            flash('Название товара обязательно.')
            return render_template('admin_product_edit.html', product=product)

        conn = get_db()
        conn.execute(
            'UPDATE products SET name = ?, image_url = ?, seller_comment = ? WHERE id = ?',
            (name, image_url, seller_comment, product_id)
        )
        conn.commit()
        conn.close()
        flash('Товар обновлён.')
        return redirect(url_for('admin_products'))

    return render_template('admin_product_edit.html', product=product)


@app.route('/admin/products/<int:product_id>/delete', methods=['POST'])
def admin_products_delete(product_id):
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))

    conn = get_db()
    cursor = conn.execute(
        'UPDATE products SET is_active = 0 WHERE id = ? AND is_active = 1',
        (product_id,)
    )
    conn.commit()
    conn.close()
    if cursor.rowcount == 0:
        abort(404)
    flash('Товар удалён из каталога.')
    return redirect(url_for('admin_products'))


@app.route('/admin/products/<int:product_id>/restore', methods=['POST'])
def admin_products_restore(product_id):
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))

    conn = get_db()
    cursor = conn.execute(
        'UPDATE products SET is_active = 1 WHERE id = ? AND is_active = 0',
        (product_id,)
    )
    conn.commit()
    conn.close()
    if cursor.rowcount == 0:
        abort(404)
    flash('Товар восстановлен в каталоге.')
    return redirect(url_for('admin_products'))


@app.route('/admin/products/add', methods=['POST'])
def admin_products_add():
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))
    name = request.form.get('name', '').strip()
    category = request.form.get('category', '').strip()
    price = request.form.get('price', '').strip()
    description = request.form.get('description', '').strip()
    app_type = request.form.get('app_type', '').strip()
    image_url = request.form.get('image_url', '').strip()
    seller_comment = request.form.get('seller_comment', '').strip()
    if create_product_in_db(name, category, price, description, app_type, image_url, seller_comment):
        flash('Товар успешно добавлен.')
    else:
        flash('Ошибка: проверьте название, цену и категорию.')
    return redirect(url_for('admin_products'))


@app.route('/admin/orders')
def admin_orders():
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))
    orders = get_orders()
    active_orders = [order for order in orders if order['status'] != 'Завершён']
    completed_orders = [order for order in orders if order['status'] == 'Завершён']
    return render_template(
        'admin_orders.html',
        orders=active_orders,
        completed_orders=completed_orders
    )


@app.route('/admin/orders/<int:order_id>')
def admin_order_detail(order_id):
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))
    orders = get_orders()
    order = next((item for item in orders if item['id'] == order_id), None)
    if order is None:
        abort(404)
    order_items = order.get('items', [])
    return render_template('admin_order_detail.html', order=order, items=order_items)


@app.route('/admin/orders/<int:order_id>/complete', methods=['POST'])
def admin_order_complete(order_id):
    user = get_current_user()
    if not is_admin_user(user):
        return redirect(url_for('admin_panel'))

    conn = get_db()
    cursor = conn.execute(
        "UPDATE orders SET status = 'Завершён' WHERE id = ? AND status != 'Завершён'",
        (order_id,)
    )
    conn.commit()
    conn.close()
    if cursor.rowcount == 0:
        abort(404)
    flash(f'Заказ #{order_id} завершён.')
    return redirect(url_for('admin_orders'))


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
