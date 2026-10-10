# SpeedyBuy

Простой MVP интернет-магазина на Flask.

## Установка

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
python app.py
```

Откройте в браузере:

```text
http://127.0.0.1:5000/
```

## Что реализовано

- Каталог товаров с фильтрацией по категориям
- Добавление товара в корзину
- Просмотр корзины
- Оформление заказа с формой клиента
- Показ итоговой суммы

## Тесты

```bash
pytest -q
```
