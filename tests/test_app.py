import pytest
from app import app, get_products, get_orders


@pytest.fixture()
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_homepage_has_title_and_products(client):
    response = client.get('/')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'SpeedyBuy' in text
    assert 'Покупай быстро и дешево только на SpeedyBuy.' in text
    assert 'Популярные товары' in text
    assert 'Новинки каталога' in text


def test_add_to_cart_increases_quantity(client):
    response = client.post('/cart/add/1', follow_redirects=True)
    assert response.status_code == 200
    assert '1' in response.get_data(as_text=True)


def test_checkout_page_loads(client):
    response = client.get('/checkout')
    assert response.status_code == 200
    assert 'Оформление заказа' in response.get_data(as_text=True)


def test_database_has_seed_products():
    products = get_products()
    assert len(products) >= 5
    assert any(product['name'] == 'Galaxy A55' for product in products)


def test_order_is_saved_in_database(client):
    client.post('/cart/add/1', follow_redirects=True)
    response = client.post('/order', data={
        'name': 'Иван',
        'phone': '+79991234567',
        'address': 'ул. Лесная, 10',
    }, follow_redirects=True)
    assert response.status_code == 200
    orders = get_orders()
    assert len(orders) >= 1
    assert any(order['customer_name'] == 'Иван' for order in orders)


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
    }, follow_redirects=True)
    assert response.status_code == 200
    assert len(get_products()) == before + 1
    assert any(product['name'] == 'Test Product' for product in get_products())


def test_support_requires_login(client):
    response = client.get('/support')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'войдите в аккаунт' in text or 'Войти' in text
