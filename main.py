import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import json
import random
from playwright.sync_api import sync_playwright
import datetime
import re
import os
from time import sleep
import threading 
import logging
from decouple import config
import bs4

bot = telebot.TeleBot(config("BOT_TOKEN"))
ADMIN_ID = int(config("ADMIN_ID"))

month_replace = {
    "янв": "01", "фев": "02", "мар": "03", "апр": "04", "май": "05", "июн": "06",
    "июл": "07", "авг": "08", "сен": "09", "окт": "10", "ноя": "11", "дек": "12"
}

user_state = {}

# Настройка логирования
logging.basicConfig(filename="broadcast_errors.log", level=logging.ERROR, 
                    format="%(asctime)s - %(message)s")

# Глобальная переменная для хранения текста рассылки
broadcast_text = None

@bot.message_handler(commands=["broadcast"])
def broadcast_message(message):
    # Проверяем, что команду вызвал администратор
    if message.from_user.id == ADMIN_ID:
        bot.send_message(message.chat.id, "Введите сообщение для рассылки:")
        bot.register_next_step_handler(message, confirm_broadcast)
    else:
        bot.send_message(message.chat.id, "❌ У вас нет прав для выполнения этой команды.")

# Функция для подтверждения рассылки
def confirm_broadcast(message):
    global broadcast_text
    # Сохраняем текст сообщения для рассылки
    broadcast_text = message.text

    # Показываем сообщение администратору и запрашиваем подтверждение
    bot.send_message(message.chat.id, f"Вы хотите отправить это сообщение всем пользователям?\n\n{broadcast_text}", 
                     reply_markup=confirm_keyboard())

# Клавиатура для подтверждения
def confirm_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("✅ Да"), KeyboardButton("❌ Нет"))
    return markup

# Обработчик подтверждения
@bot.message_handler(func=lambda message: message.text in ["✅ Да", "❌ Нет"])
def handle_confirmation(message):
    global broadcast_text
    if message.text == "✅ Да":
        # Запускаем рассылку
        bot.send_message(message.chat.id, "Рассылка началась...", reply_markup=ReplyKeyboardRemove())
        send_broadcast(message, broadcast_text)
    else:
        bot.send_message(message.chat.id, "Рассылка отменена.", reply_markup=ReplyKeyboardRemove())
        broadcast_text = None  # Сбрасываем текст рассылки

# Функция для оформления сообщения
def format_broadcast_message(text):
    return (
        "📢 *Уведомление от разработчиков*\n\n"
        f"💬 {text}\n\n"
    )

def send_broadcast(message, text):
    try:
        # Читаем файл с пользователями
        with open("groups.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_users = 0
        success_count = 0
        failed_count = 0

        # Форматируем сообщение
        formatted_message = format_broadcast_message(text)

        # Отправляем сообщение каждому пользователю
        for line in lines:
            # Убираем лишние пробелы и проверяем, что строка не пустая
            line = line.strip()
            if not line:
                logging.warning("Пустая строка в groups.txt")
                continue  # Пропускаем пустые строки

            # Разделяем строку на user_id и group
            parts = line.split(": ")
            if len(parts) == 0:
                logging.warning(f"Некорректная строка в groups.txt: {line}")
                continue  # Пропускаем строки без user_id

            # Извлекаем user_id (группа может быть пустой)
            user_id = parts[0]

            try:
                # Отправляем сообщение
                sent_message = bot.send_message(user_id, formatted_message, parse_mode="Markdown")
                
                # Сохраняем ID сообщения
                save_last_broadcast(user_id, sent_message.message_id)
                
                success_count += 1
            except Exception as e:
                failed_count += 1
                logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

            total_users += 1

        # Отправляем отчет администратору
        report = (
            f"✅ Рассылка завершена.\n"
            f"Всего пользователей: {total_users}\n"
            f"Успешно отправлено: {success_count}\n"
            f"Не удалось отправить: {failed_count}"
        )
        bot.send_message(message.chat.id, report, reply_markup=main_menu())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при рассылке: {e}")
    finally:
        global broadcast_text
        broadcast_text = None  # Сбрасываем текст рассылки после завершения

# Функция для удаления последнего сообщения с статистикой
def delete_last_broadcast():
    try:
        with open("last_broadcast.json", "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0, 0  # Если файл пуст или отсутствует

    total_users = len(data)
    success_count = 0
    failed_count = 0

    for user_id, message_id in data.items():
        try:
            bot.delete_message(user_id, message_id)
            success_count += 1
        except Exception as e:
            failed_count += 1
            logging.error(f"Не удалось удалить сообщение у пользователя {user_id}: {e}")

    # Очищаем файл после удаления
    with open("last_broadcast.json", "w") as f:
        json.dump({}, f, indent=4)

    return success_count, failed_count

# Команда для удаления последнего сообщения с отчетом
@bot.message_handler(commands=["delete_last_broadcast"])
def handle_delete_last_broadcast(message):
    if message.from_user.id == ADMIN_ID:
        # Удаляем последнее сообщение и получаем статистику
        success_count, failed_count = delete_last_broadcast()

        # Отправляем отчет администратору
        report = (
            f"✅ Удаление последнего сообщения рассылки завершено.\n"
            f"Всего пользователей: {success_count + failed_count}\n"
            f"Успешно удалено: {success_count}\n"
            f"Не удалось удалить: {failed_count}"
        )
        bot.send_message(message.chat.id, report, reply_markup=main_menu())
    else:
        bot.send_message(message.chat.id, "❌ У вас нет прав для выполнения этой команды.")

def animate_loading(message, stop_event):
    loading_text = "Загрузка расписания"
    msg = bot.send_message(message.chat.id, loading_text)  # Отправляем начальное сообщение
    msg_id = msg.message_id  # Сохраняем ID сообщения

    progress = 0  # Начальное значение прогресса
    max_progress = 35  # Максимальное значение прогресса
    steps = 9  # Количество шагов за 4 секунды
    step_size = max_progress / steps  # Базовый размер шага

    for _ in range(steps):
        if stop_event.is_set():
            break

        # Увеличиваем прогресс на базовый шаг + случайное значение
        progress = min(progress + step_size + random.uniform(-1, 1), max_progress)
        
        # Создаем прогресс-бар
        progress_bar = "[" + "-" * int(progress) + ">" + " " * (max_progress - int(progress)) + "]"
        
        # Обновляем сообщение с прогресс-баром
        bot.edit_message_text(f"{loading_text}\n{progress_bar}", message.chat.id, msg_id)
        
        sleep(0.3)  # Пауза 0.3 секунды

    # Удаляем сообщение с анимацией после завершения
    bot.delete_message(message.chat.id, msg_id)

# Функция для сохранения ID последнего сообщения
def save_last_broadcast(user_id, message_id):
    try:
        with open("last_broadcast.json", "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    data[user_id] = message_id

    with open("last_broadcast.json", "w") as f:
        json.dump(data, f, indent=4)

# Функция для проверки наличия расписания в JSON
def schedule_exists(user_group, formatted_date):
    try:
        with open("schedule_cache.json", "r", encoding="utf-8") as file:
            data = json.load(file)
            return user_group in data and formatted_date in data[user_group]
    except (FileNotFoundError, json.JSONDecodeError):
        return False

# Функция для отправки расписания с анимацией (если данных нет в JSON)
def send_schedule_with_animation(message, user_group, user_date=None):
    if not user_date:
        user_date = message.text.strip().lower()
    
    match = re.match(r"(\d{1,2})[ .]?([а-яА-Я]+|\d{2})?", user_date)
    if not match:
        bot.send_message(message.chat.id, "❌ Неверный формат даты. Пример: 06.03 или 06 Мар.", reply_markup=main_menu())
        return

    day, month_input = match.groups()
    
    # Добавляем ведущий ноль, если день состоит из одной цифры
    day = day.zfill(2)
    
    month = month_replace.get(month_input[:3], month_input) if month_input else None
    if not month:
        bot.send_message(message.chat.id, "❌ Неверный формат месяца. Пример: 06 Мар, 06 марта.", reply_markup=main_menu())
        return

    formatted_date = f"{datetime.datetime.now().year}-{month}-{day}"
    
    # Проверяем, есть ли расписание в JSON
    if schedule_exists(user_group, formatted_date):
        # Если данные есть, просто отправляем их
        schedule = get_schedule(user_group, formatted_date)
        bot.send_message(message.chat.id, schedule, reply_markup=main_menu())  # Возвращаем главное меню
        return
    
    # Если данных нет, запускаем анимацию
    stop_event = threading.Event()
    threading.Thread(target=animate_loading, args=(message, stop_event)).start()
    
    # Получаем расписание через Playwright
    schedule = fetch_schedule_via_playwright(user_group, formatted_date)
    
    # Останавливаем анимацию
    stop_event.set()
    
    # Сохраняем расписание в JSON
    cache = load_schedule_cache()
    if user_group not in cache:
        cache[user_group] = {}
    cache[user_group][formatted_date] = schedule
    save_schedule_cache(cache)
    
    # Отправляем расписание и возвращаем главное меню
    bot.send_message(message.chat.id, schedule, reply_markup=main_menu())

def clean_old_cache():
    cache = load_schedule_cache()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    for group in cache:
        cache[group] = {date: schedule for date, schedule in cache[group].items() if date >= today}
    save_schedule_cache(cache)

def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_group(user_id):
    try:
        with open("groups.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                if not line:  # Пропускаем пустые строки
                    continue
                try:
                    saved_user_id, group = line.split(": ")
                    if saved_user_id == str(user_id):
                        return group
                except ValueError:
                    # Пропускаем строки с некорректным форматом
                    logging.warning(f"Некорректная строка в groups.txt: {line}")
                    continue
    except FileNotFoundError:
        return None
    return None

# Главное меню
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("📅 Расписание"))
    markup.add(KeyboardButton("❓ Задать вопрос"))
    markup.add(KeyboardButton("⚙️ Настройки"))
    return markup

@bot.message_handler(commands=["start"])
def start(message):
    user_id = str(message.from_user.id)
    
    # Проверяем, есть ли пользователь в groups.txt
    try:
        with open("groups.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    user_exists = False
    for line in lines:
        if line.startswith(f"{user_id}:"):
            user_exists = True
            break

    # Если пользователя нет, добавляем его с пустой группой
    if not user_exists:
        # Проверяем и исправляем формат файла
        try:
            with open("groups.txt", "r", encoding="utf-8") as f:
                content = f.read()
                if not content.endswith("\n"):
                    # Если файл не заканчивается на новую строку, добавляем её
                    with open("groups.txt", "a", encoding="utf-8") as f:
                        f.write("\n")
        except FileNotFoundError:
            pass  # Файл не существует, создадим его позже

        # Добавляем нового пользователя
        with open("groups.txt", "a", encoding="utf-8") as f:
            f.write(f"{user_id}: \n")  # Пустая группа и символ новой строки

    # Приветствуем пользователя
    bot.send_message(message.chat.id, "Добро пожаловать! Выберите действие:", reply_markup=main_menu())

STATE_WAITING_FOR_DATE = "waiting_for_date"

@bot.message_handler(func=lambda message: message.text == "📅 Расписание")
def schedule_handler(message):
    user_group = get_group(message.from_user.id)
    
    if not user_group:
        bot.send_message(message.chat.id, "❌ Группа не найдена. Укажите свою группу через ⚙️ Настройки.", reply_markup=main_menu())
        return

    # Создаем клавиатуру с кнопками "Сегодня", "Завтра" и "Указать дату"
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("Сегодня"))
    markup.add(KeyboardButton("Завтра"))
    markup.add(KeyboardButton("Указать дату"))
    markup.add(KeyboardButton("⬅️ Назад"))

    bot.send_message(message.chat.id, "Выберите день или укажите дату вручную:", reply_markup=markup)
    bot.register_next_step_handler(message, lambda msg: handle_day_selection(msg, user_group))

def handle_day_selection(message, user_group):
    if message.text == "Сегодня":
        date = datetime.datetime.now().strftime("%d.%m")
        send_schedule_with_animation(message, user_group, date)
    elif message.text == "Завтра":
        date = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%d.%m")
        send_schedule_with_animation(message, user_group, date)
    elif message.text == "Указать дату":
        # Устанавливаем состояние "ожидание ввода даты"
        user_state[message.chat.id] = STATE_WAITING_FOR_DATE
        bot.send_message(message.chat.id, "📅 Введите дату в формате ДД.ММ (например, 06.03 или 06 Мар):")
        bot.register_next_step_handler(message, lambda msg: handle_custom_date(msg, user_group))
    elif message.text == "⬅️ Назад":
        bot.send_message(message.chat.id, "Возврат в главное меню.", reply_markup=main_menu())
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор. Попробуйте снова.", reply_markup=main_menu())

def handle_custom_date(message, user_group):
    # Проверяем, находится ли пользователь в состоянии ожидания ввода даты
    if user_state.get(message.chat.id) == STATE_WAITING_FOR_DATE:
        # Обрабатываем введенную пользователем дату
        user_date = message.text.strip().lower()
        send_schedule_with_animation(message, user_group, user_date)
        # Сбрасываем состояние пользователя
        user_state[message.chat.id] = None
    else:
        bot.send_message(message.chat.id, "❌ Неверный ввод. Попробуйте снова.", reply_markup=main_menu())

@bot.message_handler(func=lambda message: message.text == "❓ Задать вопрос")
def ask_question_handler(message):
    categories = load_questions()  # Загружаем категории из JSON
    markup = ReplyKeyboardMarkup(resize_keyboard=True)

    for category in categories.keys():
        markup.add(KeyboardButton(category))  # Создаем кнопки для каждой категории

    markup.add(KeyboardButton("Связь с разработчиком"))  # Добавляем кнопку "Связь с разработчиком"
    markup.add(KeyboardButton("⬅️ Назад"))
    bot.send_message(message.chat.id, "Выберите категорию:", reply_markup=markup)

    # Устанавливаем состояние пользователя — он в главном меню
    user_state[message.chat.id] = 'main_menu'

# Хэндлер для кнопок категорий
@bot.message_handler(func=lambda message: message.text in load_questions().keys())
def category_handler(message):
    categories = load_questions()  # Загружаем категории из JSON
    category = message.text
    markup = ReplyKeyboardMarkup(resize_keyboard=True)

    for question in categories[category].keys():
        markup.add(KeyboardButton(question))  # Создаем кнопки для вопросов категории

    markup.add(KeyboardButton("⬅️ Назад"))
    bot.send_message(message.chat.id, f"Выберите вопрос из {category}:", reply_markup=markup)

    # Устанавливаем состояние пользователя — он в категории
    user_state[message.chat.id] = category

# Хэндлер для кнопок вопросов
@bot.message_handler(func=lambda message: any(message.text in q for q in load_questions().values()))
def answer_question_handler(message):
    categories = load_questions()  # Загружаем категории из JSON

    for category, questions in categories.items():
        if message.text in questions:
            bot.send_message(message.chat.id, questions[message.text])  # Отправляем ответ на выбранный вопрос
            break

@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def settings_handler(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("📌 Указать группу"))
    markup.add(KeyboardButton("⬅️ Назад"))
    bot.send_message(message.chat.id, "Выберите настройку:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "📌 Указать группу")
def set_group_handler(message):
    bot.send_message(message.chat.id, "📝 Введите название вашей группы:")
    bot.register_next_step_handler(message, save_group)

def save_group(message):
    user_id = str(message.from_user.id)
    group_name = message.text.strip()

    if not group_name:
        bot.send_message(message.chat.id, "❌ Название группы не может быть пустым.")
        return

    update_user_group(user_id, group_name)
    bot.send_message(message.chat.id, f"Ваша группа {group_name} сохранена.", reply_markup=main_menu())

def send_schedule(message, user_group):
    user_date = message.text.strip().lower()
    match = re.match(r"(\d{1,2})[ .]?([а-яА-Я]+|\d{2})?", user_date)
    if not match:
        bot.send_message(message.chat.id, "❌ Неверный формат даты. Пример: 06.03 или 06 Мар.")
        return

    day, month_input = match.groups()
    
    # Добавляем ведущий ноль, если день состоит из одной цифры
    day = day.zfill(2)
    
    month = month_replace.get(month_input[:3], month_input) if month_input else None
    if not month:
        bot.send_message(message.chat.id, "❌ Неверный формат месяца. Пример: 06 Мар, 06 марта.")
        return

    formatted_date = f"{datetime.datetime.now().year}-{month}-{day}"
    
    # Получаем расписание из кэша или через Playwright
    schedule = get_schedule(user_group, formatted_date)
    
    # Отправляем расписание пользователю
    bot.send_message(message.chat.id, schedule)

# Хэндлер для кнопки "⬅️ Назад"
@bot.message_handler(func=lambda message: message.text == "⬅️ Назад")
def back_handler(message):
    current_state = user_state.get(message.chat.id, 'main_menu')

    if current_state == 'main_menu':
        # Возвращаем в главное меню
        sent_message = bot.send_message(message.chat.id, "✅", reply_markup=main_menu())
        sleep(1)
        bot.delete_message(message.chat.id, message.message_id)
        bot.delete_message(message.chat.id, sent_message.message_id)
        user_state[message.chat.id] = 'main_menu'
    elif current_state in load_questions().keys():
        categories = load_questions() 
        markup = ReplyKeyboardMarkup(resize_keyboard=True)

        for category in categories.keys():
            markup.add(KeyboardButton(category))

        markup.add(KeyboardButton("⬅️ Назад"))
        bot.send_message(message.chat.id, "Выберите категорию:", reply_markup=markup)

        user_state[message.chat.id] = 'main_menu'

def load_schedule_cache():
    if not os.path.exists("schedule_cache.json"):
        return {}
    try:
        with open("schedule_cache.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Функция для сохранения данных в JSON-файл
def save_schedule_cache(cache):
    with open("schedule_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)

def get_schedule(group, date):
    """
    Получает расписание из кэша или через Playwright.
    Если расписание содержит ошибку, оно не сохраняется в кэш.
    """
    cache = load_schedule_cache()

    # Проверяем, есть ли расписание в кэше
    if group in cache and date in cache[group]:
        return cache[group][date]

    # Если данных нет, запрашиваем через Playwright
    schedule = fetch_schedule_via_playwright(group, date)

    # Проверяем, содержит ли расписание ошибку или сообщение о выходном дне
    if "❌ Ошибка загрузки" in schedule or "❌ Нет занятий" in schedule or "❌ Выходной или нет занятий" in schedule:
        return schedule  # Не сохраняем ошибки или сообщения о выходных в кэш

    # Сохраняем данные в кэш
    if group not in cache:
        cache[group] = {}
    cache[group][date] = schedule
    save_schedule_cache(cache)

    return schedule

def fetch_schedule_via_playwright(group, date):
    """
    Получает расписание через Playwright.
    Возвращает строку с расписанием или сообщение об ошибке.
    """
    url = f"https://rgsu.net/for-students/timetable/timetable/?group={group}&date={date}&week=9"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # Добавляем заголовки, чтобы имитировать обычный браузер
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            })

            # Переходим на страницу с таймаутом 10 секунд
            page.goto(url, timeout=4000, wait_until="domcontentloaded")

            # Проверяем наличие контейнера с сообщением "По группе {group} нет данных."
            no_data_container = page.query_selector(".n-timetable-draw#mainDrawContainer")
            if no_data_container:
                no_data_text = no_data_container.inner_text()
                if f"По группе {group} нет данных." in no_data_text:
                    return f"📅 Расписание на {date}:\n❌ Выходной или нет занятий."

            # Ждем появления элементов расписания
            page.wait_for_selector(".n-timetable-day__item", timeout=10000)

            # Пытаемся найти расписание
            schedule_items = page.query_selector_all(".n-timetable-day__item")
            if not schedule_items:
                return f"📅 Расписание на {date}:\n❌ Нет занятий."

            # Формируем текст расписания
            schedule_text = f"📅 Расписание на {date}:\n\n"

            for item in schedule_items:
                time_from = item.query_selector(".n-timetable-day__from")
                time_to = item.query_selector(".n-timetable-day__to")
                subject = item.query_selector(".n-timetable-card__title")
                subject_type = item.query_selector(".n-timetable-card__category")
                location = item.query_selector(".n-timetable-card__auditorium")
                teacher = item.query_selector(".n-timetable-card__affiliation")
                address = item.query_selector(".n-timetable-card__address")

                time_from_text = time_from.inner_text() if time_from else "Не указано"
                time_to_text = time_to.inner_text() if time_to else "Не указано"
                subject_text = subject.inner_text() if subject else "Неизвестный предмет"
                subject_type_text = subject_type.inner_text().capitalize() if subject_type else "Неизвестная категория"
                location_text = location.inner_text() if location else "Неизвестное место"
                teacher_text = teacher.inner_text() if teacher else "Преподаватель не указан"
                address_text = address.inner_text() if address else ""

                # Исключаем адрес "ул. Лосиноостровская, 40"
                if address_text == "ул. Лосиноостровская, 40":
                    address_text = ""

                lesson_info = [
                    f"⏰ {time_from_text} - {time_to_text}",
                    f"📖 {subject_text}",
                    f"{subject_type_text}",
                    f"📍 {location_text}",
                    f"👨‍🏫 {teacher_text}",
                ]

                # Добавляем адрес, если он не "ул. Лосиноостровская, 40"
                if address_text:
                    lesson_info.append(f"🏫 {address_text}")

                schedule_text += "\n".join(lesson_info) + "\n\n"

            return schedule_text

        except Exception as e:
            # Логируем ошибку
            logging.error(f"Ошибка при парсинге расписания на {date}: {e}")
            return f"📅 Расписание на {date}:\n❌ Ошибка загрузки."
        finally:
            # Закрываем браузер
            browser.close()

def read_groups_file():
    """
    Читает файл groups.txt и возвращает список строк.
    Если файл не существует, возвращает пустой список.
    Поддерживает несколько кодировок: utf-8, cp1251, ISO-8859-1.
    """
    encodings = ['utf-8', 'cp1251', 'ISO-8859-1']  # Список поддерживаемых кодировок
    for encoding in encodings:
        try:
            with open("groups.txt", "r", encoding=encoding) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue  # Пробуем следующую кодировку
        except FileNotFoundError:
            return []  # Файл не существует
    raise UnicodeDecodeError("Не удалось декодировать файл groups.txt с использованием поддерживаемых кодировок.")

def write_groups_file(lines):
    """
    Записывает список строк в файл groups.txt в кодировке utf-8.
    """
    with open("groups.txt", "w", encoding="utf-8") as f:
        f.writelines(lines)

def update_user_group(user_id, group_name):
    """
    Обновляет группу пользователя в файле groups.txt.
    Если пользователь не существует, добавляет его.
    """
    lines = read_groups_file()
    found = False
    updated_lines = []

    for line in lines:
        if line.strip():  # Пропускаем пустые строки
            try:
                saved_user_id, saved_group = line.strip().split(": ")
                if saved_user_id == user_id:
                    updated_lines.append(f"{user_id}: {group_name}\n")
                    found = True
                else:
                    updated_lines.append(line + "\n")
            except ValueError:
                # Пропускаем строки с некорректным форматом
                logging.warning(f"Некорректная строка в groups.txt: {line}")
                continue

    if not found:
        updated_lines.append(f"{user_id}: {group_name}\n")

    write_groups_file(updated_lines)

@bot.message_handler(func=lambda message: message.text == "Связь с разработчиком")
def contact_developer_handler(message):
    # Запрашиваем у пользователя сообщение
    bot.send_message(message.chat.id, "📝 Напишите ваше сообщение разработчику:")
    bot.register_next_step_handler(message, forward_message_to_admin)

def forward_message_to_admin(message):
    # Пересылаем сообщение администратору
    user_id = message.from_user.id
    user_first_name = message.from_user.first_name
    user_username = f"@{message.from_user.username}" if message.from_user.username else "отсутствует"
    user_message = message.text

    # Сохраняем user_id для ответа
    user_state[user_id] = {"waiting_for_admin_reply": True}

    # Формируем сообщение для администратора
    admin_message = (
        f"📩 Новое сообщение от пользователя:\n\n"
        f"🆔 ID: {user_id}\n"
        f"👤 Имя: {user_first_name}\n"
        f"📛 Юзернейм: {user_username}\n\n"
        f"💬 Сообщение:\n{user_message}"
    )

    # Отправляем сообщение администратору
    bot.send_message(ADMIN_ID, admin_message)
    bot.send_message(message.chat.id, "✅ Ваше сообщение отправлено разработчику. Ожидайте ответа.", reply_markup=main_menu())

@bot.message_handler(func=lambda message: message.reply_to_message and message.from_user.id == ADMIN_ID)
def handle_admin_reply(message):
    # Получаем текст ответа администратора
    admin_reply = message.text

    # Получаем оригинальное сообщение
    original_message = message.reply_to_message.text

    # Проверяем, что сообщение содержит ожидаемый формат
    if "🆔 ID:" not in original_message or "💬 Сообщение:" not in original_message:
        bot.send_message(ADMIN_ID, "❌ Не удалось определить пользователя. Сообщение имеет неверный формат.")
        return

    try:
        # Извлекаем user_id из оригинального сообщения
        user_id_part = original_message.split("🆔 ID: ")[1]
        user_id = int(user_id_part.split("\n")[0])
    except (IndexError, ValueError) as e:
        # Если не удалось извлечь user_id, уведомляем администратора
        bot.send_message(ADMIN_ID, f"❌ Не удалось определить ID пользователя. Ошибка: {e}")
        return

    try:
        # Отправляем ответ пользователю
        sent_message = bot.send_message(user_id, f"📨 Ответ от разработчика:\n\n{admin_reply}")

        # Проверяем, что sent_message является объектом сообщения
        if hasattr(sent_message, 'message_id'):
            bot.send_message(ADMIN_ID, f"✅ Ответ пользователю {user_id} успешно доставлен.")
        else:
            # Если sent_message не является объектом сообщения, уведомляем администратора
            bot.send_message(ADMIN_ID, f"❌ Не удалось доставить ответ пользователю {user_id}. Ошибка: {sent_message}")
    except Exception as e:
        # Если произошла ошибка при отправке, уведомляем администратора
        bot.send_message(ADMIN_ID, f"❌ Не удалось доставить ответ пользователю {user_id}. Ошибка: {e}")

    # Сбрасываем состояние пользователя
    if user_id in user_state:
        user_state[user_id]["waiting_for_admin_reply"] = False

bot.infinity_polling()