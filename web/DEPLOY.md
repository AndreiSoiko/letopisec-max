# Деплой веб-сайта Летописец

## 1. Подготовка окружения на сервере

```bash
# Создать директорию и скопировать файлы
mkdir -p /home/letopisec-max/web
cd /home/letopisec-max/web
# Скопируйте содержимое папки web/ сюда через scp/git

# Создать виртуальное окружение
python3 -m venv /home/letopisec-max/web-venv
/home/letopisec-max/web-venv/bin/pip install -r requirements-web.txt

# Создать .env из примера
cp .env.example .env
nano .env  # заполнить все переменные

# Создать директорию логов
sudo mkdir -p /var/log/letopisec-web
sudo chown letopisec-max:letopisec-max /var/log/letopisec-web
```

## 2. Регистрация VK OAuth приложения

1. Зайдите на https://dev.vk.com/
2. «Мои приложения» → «Создать приложение»
3. Тип: **Веб-сайт**
4. Базовый домен: `yourdomain.ru`
5. Доверенный redirect URI: `https://yourdomain.ru/accounts/vk/callback/`
6. Скопируйте **ID приложения** → `VK_APP_ID` в .env
7. Скопируйте **Защищённый ключ** → `VK_APP_SECRET` в .env

## 3. Регистрация Yandex OAuth приложения

1. Зайдите на https://oauth.yandex.ru/
2. «Зарегистрировать новое приложение»
3. Название: Летописец
4. Права доступа: **Яндекс Паспорт → Доступ к адресу электронной почты**, **Доступ к имени пользователя, фото и логину**
5. Callback URI: `https://yourdomain.ru/accounts/yandex/callback/`
6. Скопируйте **ClientID** → `YANDEX_CLIENT_ID` в .env
7. Скопируйте **Client secret** → `YANDEX_CLIENT_SECRET` в .env

## 4. Первоначальная миграция базы данных

```bash
cd /home/letopisec-max/web
/home/letopisec-max/web-venv/bin/python manage.py migrate
/home/letopisec-max/web-venv/bin/python manage.py collectstatic --noinput
/home/letopisec-max/web-venv/bin/python manage.py createsuperuser
```

> Примечание: таблицы `users`, `api_keys`, `api_jobs` уже созданы ботом — Django их не трогает (managed=False).
> Django создаст только `web_accounts_webuser`, `web_tinkoff_orders` и стандартные таблицы auth.

## 5. Настройка systemd

```bash
sudo cp deploy/letopisec-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable letopisec-web
sudo systemctl start letopisec-web
sudo systemctl status letopisec-web
```

## 6. Настройка Nginx

```bash
# Установить Nginx если не установлен
sudo apt install -y nginx

# Скопировать конфиг, заменив yourdomain.ru на реальный домен
sudo cp deploy/nginx.conf /etc/nginx/sites-available/letopisec
sudo sed -i 's/yourdomain.ru/РЕАЛЬНЫЙ_ДОМЕН/g' /etc/nginx/sites-available/letopisec
sudo ln -s /etc/nginx/sites-available/letopisec /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. SSL через Let's Encrypt (рекомендуется)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.ru -d www.yourdomain.ru
# После получения сертификата раскомментировать HTTPS блок в nginx.conf
```

## 8. Обновление T-Bank webhook URL

В настройках T-Bank терминала укажите два URL нотификаций:
- Бот (уже настроен): `https://yourdomain.ru/tinkoff/notify`
- Веб: `https://yourdomain.ru/billing/tinkoff-notify/`

Или укажите в переменной `TINKOFF_WEB_NOTIFICATION_URL` в `.env` веба.

## 9. Настройка привязки MAX-аккаунта

Для работы команды `/link` в боте:
- Бот должен иметь доступ к таблице `web_accounts_webuser` (это та же БД)
- Никакой дополнительной настройки не нужно — бот читает/пишет напрямую в эту таблицу

## Структура проекта

```
web/
├── manage.py
├── requirements-web.txt
├── .env.example
├── letopisec_web/       # Основные настройки Django
├── accounts/            # Авторизация (email + VK + Yandex), привязка MAX
├── billing/             # Баланс, пополнение через T-Bank
├── api_keys/            # Управление API-ключами
├── jobs/                # История заданий API
├── dashboard/           # Главная страница
├── templates/           # HTML шаблоны
└── deploy/              # Файлы деплоя (nginx, systemd)
```
