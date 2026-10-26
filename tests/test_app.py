import sqlite3

import pytest
import app as app_module
from app import app, get_new_products, get_orders, get_popular_products, get_products


@pytest.fixture()
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def isolate_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'test.db'))
    app_module.init_db()


def test_homepage_has_title_and_products(client):
    response = client.get('/')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'SpeedyBuy' in text
    assert 'Покупай быстро и дешево только на SpeedyBuy.' in text
    assert 'Популярные товары' in text
    assert 'Новинки каталога' in text
    assert '<a href="/marketplace" class="primary-btn">Перейти в маркетплейс</a>' in text
    assert text.count('<a href="/marketplace">Смотреть всё</a>') == 2
    assert '<a href="/support" class="primary-btn">Связаться с поддержкой</a>' in text
    assert '<a class="menu-toggle" href="/" aria-label="SpeedyBuy — главная">SC</a>' in text
    assert 'class="background-markings" aria-hidden="true"' in text
    assert 'Все товары' not in text
    assert 'category=all' not in text


def test_add_to_cart_increases_quantity(client):
    response = client.post('/cart/add/1', follow_redirects=True)
    assert response.status_code == 200
    assert '1' in response.get_data(as_text=True)


def test_checkout_page_loads(client):
    client.post('/cart/add/1')
    response = client.get('/checkout')
    assert response.status_code == 200
    assert 'Оформление заказа' in response.get_data(as_text=True)
    text = response.get_data(as_text=True)
    assert 'Ваша почта' in text
    assert 'Комментарий к заказу' in text
    assert 'data-rating-value="5"' in text


def test_database_has_seed_products():
    products = get_products()
    assert len(products) >= 5
    assert any(product['name'] == 'Steam Premium' for product in products)


def test_new_products_are_ordered_by_creation_date(tmp_path, monkeypatch):
    database_path = tmp_path / 'catalog.db'
    monkeypatch.setattr(app_module, 'DB_PATH', str(database_path))
    connection = sqlite3.connect(database_path)
    connection.execute(
        'CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER, is_new INTEGER, created_at TEXT)'
    )
    connection.execute('CREATE TABLE orders (id INTEGER PRIMARY KEY, rating INTEGER)')
    connection.execute('CREATE TABLE order_items (order_id INTEGER, product_id INTEGER)')
    connection.executemany(
        'INSERT INTO products (id, name, is_active, is_new, created_at) VALUES (?, ?, 1, 0, ?)',
        [(1, 'Older product', '2026-01-01 10:00:00'), (2, 'Newer product', '2026-02-01 10:00:00')]
    )
    connection.commit()
    connection.close()

    assert [product['name'] for product in get_new_products()] == ['Newer product', 'Older product']


def test_popular_products_are_ranked_by_number_of_orders(tmp_path, monkeypatch):
    database_path = tmp_path / 'catalog.db'
    monkeypatch.setattr(app_module, 'DB_PATH', str(database_path))
    connection = sqlite3.connect(database_path)
    connection.execute(
        'CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER, created_at TEXT)'
    )
    connection.execute(
        'CREATE TABLE order_items (order_id INTEGER, product_id INTEGER, quantity INTEGER)'
    )
    connection.execute('CREATE TABLE orders (id INTEGER PRIMARY KEY, rating INTEGER)')
    connection.executemany(
        'INSERT INTO products (id, name, is_active, created_at) VALUES (?, ?, 1, ?)',
        [(1, 'One large order', '2026-01-01 10:00:00'), (2, 'Repeated orders', '2026-01-02 10:00:00')]
    )
    connection.executemany(
        'INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)',
        [(1, 1, 10), (2, 2, 1), (3, 2, 1)]
    )
    connection.commit()
    connection.close()

    assert [product['name'] for product in get_popular_products()] == ['Repeated orders', 'One large order']


def test_popular_products_show_catalog_items_and_include_new_orders(tmp_path, monkeypatch):
    database_path = tmp_path / 'catalog.db'
    monkeypatch.setattr(app_module, 'DB_PATH', str(database_path))
    app_module.init_db()

    products = get_products()
    initial_popular_ids = [product['id'] for product in get_popular_products()]
    assert len(initial_popular_ids) == 3

    product = products[-1]
    assert product['id'] not in initial_popular_ids
    with app.test_client() as test_client:
        test_client.post(f"/cart/add/{product['id']}")
        response = test_client.post('/order', data={
            'email': 'buyer@example.com',
            'comment': 'Комментарий к заказу',
        })

    assert response.status_code == 200
    assert product['id'] == get_popular_products()[0]['id']


def test_cart_item_can_be_removed(client):
    client.post('/cart/add/1')

    response = client.get('/cart')
    text = response.get_data(as_text=True)
    assert 'Убрать из корзины' in text
    assert 'action="/cart/remove/1"' in text

    response = client.post('/cart/remove/1', follow_redirects=True)
    assert response.status_code == 200
    assert 'Корзина пуста' in response.get_data(as_text=True)


def test_order_is_saved_in_database(client):
    client.post('/cart/add/1')
    response = client.post('/order', data={
        'email': 'buyer@example.com',
        'comment': 'Нужна доставка после 18:00',
    }, follow_redirects=True)
    assert response.status_code == 200
    orders = get_orders()
    assert len(orders) >= 1
    order = orders[0]
    assert order['customer_email'] == 'buyer@example.com'
    assert order['customer_comment'] == 'Нужна доставка после 18:00'
    assert order['rating'] is None


def test_admin_can_complete_order_without_deleting_it_or_its_rating(client):
    client.post('/cart/add/1')
    client.post('/order', data={
        'email': 'buyer@example.com',
        'comment': 'Order comment',
        'rating': '4',
    })
    order_id = get_orders()[0]['id']
    client.post('/admin', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    details = client.get(f'/admin/orders/{order_id}')
    assert 'Завершить заказ' in details.get_data(as_text=True)
    assert f'action="/admin/orders/{order_id}/complete"' in details.get_data(as_text=True)

    response = client.post(f'/admin/orders/{order_id}/complete', follow_redirects=True)

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Активных заказов нет.' in text
    assert f'#{order_id} — buyer@example.com' in text
    assert 'Завершён' in text
    orders = get_orders()
    assert len(orders) == 1
    assert orders[0]['status'] == 'Завершён'
    assert orders[0]['rating'] == 4
    assert len(orders[0]['items']) == 1
    assert next(product for product in get_products() if product['id'] == 1)['rating'] == 4.0
    assert 'Завершить заказ' not in client.get(f'/admin/orders/{order_id}').get_data(as_text=True)


def test_order_requires_valid_email_and_comment(client):
    client.post('/cart/add/1')

    response = client.post('/order', data={'email': 'not-an-email', 'comment': ''})

    assert response.status_code == 400
    assert 'Укажите корректную почту' in response.get_data(as_text=True)
    assert get_orders() == []


def test_order_ratings_are_averaged_per_product_and_remembered(client):
    for rating in ('5', '2'):
        client.post('/cart/add/1')
        response = client.post('/order', data={
            'email': 'buyer@example.com',
            'comment': f'Оценка {rating}',
            'rating': rating,
        })
        assert response.status_code == 200

    product = next(product for product in get_products() if product['id'] == 1)
    assert product['rating'] == 3.5
    assert len(get_orders()) == 2
    assert [order['rating'] for order in get_orders()] == [2, 5]
    marketplace = client.get('/marketplace').get_data(as_text=True)
    assert '3.5' in marketplace
    assert '--rating: 70.0%' in marketplace


def test_admin_seller_comment_is_saved_and_shown_in_catalog(client):
    assert app_module.create_product_in_db(
        'Product with seller note',
        'Игры',
        '500',
        'Product description',
        seller_comment='Код придёт на почту после обработки заказа.',
    )
    product = next(product for product in get_products() if product['name'] == 'Product with seller note')
    client.post('/admin', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    client.post(f"/cart/add/{product['id']}")
    checkout = client.get('/checkout').get_data(as_text=True)
    assert 'Код придёт на почту после обработки заказа.' in checkout

    response = client.get('/marketplace')
    assert 'Код придёт на почту после обработки заказа.' in response.get_data(as_text=True)

    response = client.post(
        f"/admin/products/{product['id']}/edit",
        data={
            'name': product['name'],
            'image_url': '',
            'seller_comment': 'Изменённый комментарий продавца.',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert app_module.get_product_by_id(product['id'])['seller_comment'] == 'Изменённый комментарий продавца.'


def test_homepage_has_footer_links(client):
    response = client.get('/')
    text = response.get_data(as_text=True)
    assert 'Маркетплейс' in text
    assert 'FAQ' in text
    assert 'Telegram' in text
    assert 'TikTok' in text


def test_marketplace_page_has_categories_and_search(client):
    response = client.get('/marketplace')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Подписки' in text
    assert 'Ключи' in text
    assert 'Игры' in text
    assert 'Поиск' in text
    assert 'tabs-row' not in text
    assert text.count('>Подписки</a>') == 1
    assert text.count('>Ключи</a>') == 1
    assert text.count('>Игры</a>') == 1
    assert 'onchange="this.form.submit()"' in text


def test_marketplace_sort_form_preserves_selected_category(client):
    response = client.get('/marketplace?category=Игры&sort=price_asc')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<input type="hidden" name="category" value="Игры">' in text
    assert '<option value="price_asc" selected>Цена: низкая → высокая</option>' in text


def test_marketplace_renders_product_image_at_card_size(client):
    assert app_module.create_product_in_db(
        'Product with image',
        'Игры',
        '999',
        'Product description',
        'Steam',
        'https://example.com/product.jpg',
    )

    response = client.get('/marketplace')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert '<img class="product-image" src="https://example.com/product.jpg" alt="Product with image" loading="lazy">' in text


def test_faq_page_loads(client):
    response = client.get('/faq')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Часто задаваемые вопросы' in text


def test_admin_page_requires_login(client):
    response = client.get('/admin')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Админ-панель' in text or 'admin' in text.lower()


def test_admin_can_add_product(client):
    client.post('/admin', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    before = len(get_products())
    response = client.post('/admin/products/add', data={
        'name': 'Test Product',
        'category': 'Игры',
        'price': '999',
        'description': 'Тестовый товар для админки',
        'app_type': 'Steam',
        'image_url': 'https://example.com/test-product.jpg',
        'seller_comment': 'Комментарий от магазина.',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert len(get_products()) == before + 1
    product = max(
        (product for product in get_products() if product['name'] == 'Test Product'),
        key=lambda product: product['id']
    )
    assert product['image_url'] == 'https://example.com/test-product.jpg'
    assert product['seller_comment'] == 'Комментарий от магазина.'


def test_admin_can_edit_product_name_and_image(client):
    assert app_module.create_product_in_db('Editable product', 'Игры', '500', 'Description')
    product = next(product for product in get_products() if product['name'] == 'Editable product')
    client.post('/admin', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    response = client.post(
        f"/admin/products/{product['id']}/edit",
        data={'name': 'Updated product', 'image_url': 'https://example.com/updated.jpg'},
        follow_redirects=True
    )

    assert response.status_code == 200
    updated = app_module.get_product_by_id(product['id'])
    assert updated['name'] == 'Updated product'
    assert updated['image_url'] == 'https://example.com/updated.jpg'


def test_admin_can_delete_and_restore_product(client):
    assert app_module.create_product_in_db('Removable product', 'Игры', '500', 'Description')
    product = next(product for product in get_products() if product['name'] == 'Removable product')
    client.post('/admin', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    response = client.post(
        f"/admin/products/{product['id']}/delete",
        follow_redirects=True
    )

    assert response.status_code == 200
    assert app_module.get_product_by_id(product['id'])['is_active'] == 0
    assert all(item['id'] != product['id'] for item in get_products())
    deleted_products_page = client.get('/admin/products')
    deleted_text = deleted_products_page.get_data(as_text=True)
    assert deleted_text.index('Управление товарами') < deleted_text.index('Удалённые товары')
    assert 'Removable product' in deleted_text
    assert f'/admin/products/{product["id"]}/restore' in deleted_text

    response = client.post(
        f"/admin/products/{product['id']}/restore",
        follow_redirects=True
    )

    assert response.status_code == 200
    assert app_module.get_product_by_id(product['id'])['is_active'] == 1


def test_support_requires_login(client):
    response = client.get('/support')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'войдите в аккаунт' in text or 'Войти' in text
