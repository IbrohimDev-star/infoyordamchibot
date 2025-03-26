import os
import json
import logging
import telebot
import requests
from telebot import types
from datetime import datetime, timedelta
import time
import random
import wikipedia
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request

# Flask serverini sozlash (webhook uchun)
server = Flask(__name__)

# Logging sozlamalari
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables’dan maxfiy ma’lumotlarni olish
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')
FIREBASE_CRED = os.environ.get('FIREBASE_CRED')

# Botni sozlash
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ADMINS = [1058402071]

# Firebase sozlamalari
cred = credentials.Certificate(json.loads(FIREBASE_CRED))
firebase_admin.initialize_app(cred)
db = firestore.client()

# Emoji sozlamalari
weather_emojis = {
    "clear sky": "☀️ Quyoshli",
    "few clouds": "⛅ Qisman bulutli",
    "scattered clouds": "☁️ Bulutli",
    "broken clouds": "☁️ Qisman bulutli",
    "overcast clouds": "☁️ To‘liq bulutli",
    "shower rain": "🌧️ Yengil yomg‘ir",
    "rain": "🌧️ Yomg‘ir",
    "light rain": "🌧️ Yengil yomg‘ir",
    "moderate rain": "🌧️ O‘rtacha yomg‘ir",
    "heavy intensity rain": "🌧️ Kuchli yomg‘ir",
    "thunderstorm": "⛈️ Momaqaldiroq",
    "snow": "❄️ Qor",
    "light snow": "❄️ Yengil qor",
    "heavy snow": "❄️ Kuchli qor",
    "mist": "🌫️ Tuman",
    "fog": "🌫️ Tuman",
    "haze": "🌫️ Yengil tuman",
}

prayer_emojis = {
    "Fajr": "🌅 Bomdod",
    "Sunrise": "🌞 Quyosh chiqishi",
    "Dhuhr": "🕛 Peshin",
    "Asr": "🌤️ Asr",
    "Maghrib": "🌇 Shom",
    "Isha": "🌙 Xufton",
}

currency_emojis = {
    "USD": "🇺🇸 USD",
    "EUR": "🇪🇺 EUR",
    "RUB": "🇷🇺 RUB",
    "GBP": "🇬🇧 GBP",
    "JPY": "🇯🇵 JPY",
    "KZT": "🇰🇿 KZT",
    "CNY": "🇨🇳 CNY",
    "UZS": "🇺🇿 UZS",
}

city_translations = {
    "toshkent": "Tashkent",
    "samarqand": "Samarkand",
    "buxoro": "Bukhara",
    "andijon": "Andijan",
    "farg‘ona": "Fergana",
    "namangan": "Namangan",
    "qarshi": "Karshi",
    "nukus": "Nukus",
    "urgench": "Urgench",
    "jizzax": "Jizzakh",
    "termiz": "Termez",
    "navoiy": "Navoi",
    "guliston": "Gulistan",
    "xiva": "Khiva",
}

# Firebase’dan foydalanuvchilarni olish va saqlash
def get_users():
    users_ref = db.collection("users")
    users = users_ref.get()
    return [user.to_dict() for user in users]

def save_user(user_id, username):
    users_ref = db.collection("users")
    user_ref = users_ref.document(str(user_id))
    user_ref.set({
        "user_id": user_id,
        "username": username,
        "banned": False
    })

def ban_user(user_id):
    users_ref = db.collection("users")
    user_ref = users_ref.document(str(user_id))
    user_ref.update({"banned": True})

def unban_user(user_id):
    users_ref = db.collection("users")
    user_ref = users_ref.document(str(user_id))
    user_ref.update({"banned": False})

def get_banned_users():
    users = get_users()
    return {user["user_id"] for user in users if user.get("banned", False)}

# Firebase’dan valyuta keshini olish va saqlash
def get_currency_cache():
    cache_ref = db.collection("currency_cache").document("rates")
    cache = cache_ref.get()
    if cache.exists:
        return cache.to_dict()
    return {"timestamp": 0, "rates": {}}

def save_currency_cache(rates):
    cache_ref = db.collection("currency_cache").document("rates")
    cache_ref.set({
        "timestamp": int(time.time()),
        "rates": rates
    })

def is_admin(user_id):
    return user_id in ADMINS

def retry_on_failure(func, max_retries=3, delay=5):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            logger.error(f"Qayta urinish {attempt + 1}/{max_retries}: Xatolik - {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e

def get_wikipedia_info(query):
    try:
        wikipedia.set_lang("uz")
        summary = wikipedia.summary(query, sentences=3)
        return summary
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Bu so‘z bir nechta ma’noga ega bo‘lishi mumkin: {e.options}"
    except wikipedia.exceptions.PageError:
        return "Bu mavzu bo‘yicha ma’lumot topilmadi"
    except Exception as e:
        return f"Xatolik yuz berdi: {str(e)}"

def get_weather_advice(temp, desc, wind_speed, precipitation):
    advice = []
    if temp < 0:
        advice.append("❄️ Juda sovuq! Issiq kiyimlar kiying va ehtiyot bo‘ling.")
    elif 0 <= temp <= 10:
        advice.append("🧥 Sovuq. Issiq kiyining va sharf oling.")
    elif 10 < temp <= 20:
        advice.append("🧥 Salqin. Yengil kurtka kiyishni tavsiya qilamiz.")
    elif 20 < temp <= 30:
        advice.append("👕 Qulay harorat. Yengil kiyimlar kiying.")
    else:
        advice.append("🔥 Juda issiq! Yengil kiyimlar kiying va ko‘p suv iching.")
    if "rain" in desc.lower() or "shower" in desc.lower():
        advice.append("🌧️ Yomg‘ir yog‘adi. Soyabon oling va suv o‘tkazmaydigan kiyim kiying.")
    elif "thunderstorm" in desc.lower():
        advice.append("⛈️ Momaqaldiroq bo‘ladi. Ochiq joylardan uzoq turing va ehtiyot bo‘ling.")
    elif "snow" in desc.lower():
        advice.append("❄️ Qor yog‘adi. Issiq kiyimlar va sirpanmaydigan poyabzal kiying.")
    elif "mist" in desc.lower() or "fog" in desc.lower() or "haze" in desc.lower():
        advice.append("🌫️ Tumanli. Yo‘l ko‘rinishi yomon bo‘lishi mumkin, ehtiyot bo‘ling.")
    if wind_speed > 10:
        advice.append("💨 Shamol kuchli. Shamolga qarshi ehtiyot bo‘ling va ochiq joylardan uzoq turing.")
    if precipitation > 0:
        advice.append("☔ Yog‘ingarchilik kutilmoqda. Soyabon yoki yomg‘ir kiyimi oling.")
    return "\n".join(advice) if advice else "🌟 Maxsus maslahat yo‘q. Ob-havoga qarab ehtiyot bo‘ling!"

def get_current_weather_by_city(city):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=uz"
        response = requests.get(url, timeout=10).json()
        if response.get("cod") != 200:
            return "❌ Shahar topilmadi! Iltimos, to‘g‘ri nom kiriting.", None, None, None
        return process_weather_response(response)
    except requests.RequestException as e:
        logger.error(f"Ob-havo ma’lumotlarini olishda xatolik: {e}")
        return "⚠️ Ob-havo ma’lumotlarini olishda xatolik yuz berdi.", None, None, None

def get_current_weather_by_coords(lat, lon):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=uz"
        response = requests.get(url, timeout=10).json()
        if response.get("cod") != 200:
            return "❌ Joylashuv bo‘yicha ma’lumot topilmadi.", None, None, None
        return process_weather_response(response)
    except requests.RequestException as e:
        logger.error(f"Ob-havo ma’lumotlarini olishda xatolik: {e}")
        return "⚠️ Ob-havo ma’lumotlarini olishda xatolik yuz berdi.", None, None, None

def process_weather_response(response):
    temp = response["main"]["temp"]
    desc = response["weather"][0]["description"]
    weather_condition = weather_emojis.get(desc, f"☁️ {desc.capitalize()} (tarjima topilmadi)")
    humidity = response["main"]["humidity"]
    wind_speed = response["wind"]["speed"]
    sunrise = datetime.fromtimestamp(response["sys"]["sunrise"]).strftime("%H:%M")
    sunset = datetime.fromtimestamp(response["sys"]["sunset"]).strftime("%H:%M")
    precipitation = response.get("rain", {}).get("1h", 0) or response.get("snow", {}).get("1h", 0)
    city = response["name"]
    advice = get_weather_advice(temp, desc, wind_speed, precipitation)
    weather_info = (
        f"🏙️ **{city}dagi joriy ob-havo:**\n"
        f"🌡️ Harorat: {temp}°C\n"
        f"⛅ Ob-havo holati: {weather_condition}\n"
        f"💧 Yog‘ingarchilik (so‘nggi 1 soat): {precipitation} mm\n"
        f"💨 Shamol tezligi: {wind_speed} m/s\n"
        f"🌫️ Namlik: {humidity}%\n"
        f"🌅 Quyosh chiqishi: {sunrise}\n"
        f"🌇 Quyosh botishi: {sunset}\n\n"
        f"📌 **Maslahatlar:**\n{advice}"
    )
    return weather_info, response["coord"]["lat"], response["coord"]["lon"], city

def get_forecast_weather(lat, lon):
    try:
        url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=uz"
        response = requests.get(url, timeout=10).json()
        if response.get("cod") != "200":
            return None
        forecast_data = {}
        for entry in response["list"]:
            date = datetime.fromtimestamp(entry["dt"]).strftime("%Y-%m-%d")
            if date not in forecast_data:
                forecast_data[date] = {
                    "temp": entry["main"]["temp"],
                    "desc": entry["weather"][0]["description"],
                    "humidity": entry["main"]["humidity"],
                    "wind": entry["wind"]["speed"],
                    "precipitation": entry.get("rain", {}).get("3h", 0) or entry.get("snow", {}).get("3h", 0)
                }
        return forecast_data
    except requests.RequestException as e:
        logger.error(f"Ob-havo prognozini olishda xatolik: {e}")
        return None

def translate_city_name(city):
    city = city.lower().replace("‘", "'")
    return city_translations.get(city, city.capitalize())

def get_prayer_times_by_city(city):
    try:
        city = translate_city_name(city)
        current_date = datetime.now().strftime("%d-%m-%Y")
        url = f"http://api.aladhan.com/v1/timingsByCity?city={city}&country=Uzbekistan&method=2"
        response = requests.get(url, timeout=10).json()
        if response["code"] != 200:
            return "❌ Shahar topilmadi! Iltimos, to‘g‘ri nom kiriting yoki joylashuvingizni yuboring."
        timings = response["data"]["timings"]
        prayer_info = (
            f"🕌 **{city}dagi bugungi namoz vaqtlari ({current_date}):**\n"
            f"{prayer_emojis['Fajr']}: {timings['Fajr']}\n"
            f"{prayer_emojis['Sunrise']}: {timings['Sunrise']}\n"
            f"{prayer_emojis['Dhuhr']}: {timings['Dhuhr']}\n"
            f"{prayer_emojis['Asr']}: {timings['Asr']}\n"
            f"{prayer_emojis['Maghrib']}: {timings['Maghrib']}\n"
            f"{prayer_emojis['Isha']}: {timings['Isha']}"
        )
        return prayer_info
    except requests.RequestException as e:
        logger.error(f"Namoz vaqtlarini olishda xatolik: {e}")
        return "⚠️ Namoz vaqtlarini olishda xatolik yuz berdi."

def get_prayer_times_by_coords(lat, lon):
    try:
        _, _, _, city = get_current_weather_by_coords(lat, lon)
        if not city:
            city = "Joylashuvingiz"
        current_date = datetime.now().strftime("%d-%m-%Y")
        url = f"http://api.aladhan.com/v1/timings?latitude={lat}&longitude={lon}&method=2"
        response = requests.get(url, timeout=10).json()
        if response["code"] != 200:
            return "❌ Joylashuv bo‘yicha ma’lumot topilmadi."
        timings = response["data"]["timings"]
        prayer_info = (
            f"🕌 **{city}dagi bugungi namoz vaqtlari ({current_date}):**\n"
            f"{prayer_emojis['Fajr']}: {timings['Fajr']}\n"
            f"{prayer_emojis['Sunrise']}: {timings['Sunrise']}\n"
            f"{prayer_emojis['Dhuhr']}: {timings['Dhuhr']}\n"
            f"{prayer_emojis['Asr']}: {timings['Asr']}\n"
            f"{prayer_emojis['Maghrib']}: {timings['Maghrib']}\n"
            f"{prayer_emojis['Isha']}: {timings['Isha']}"
        )
        return prayer_info
    except requests.RequestException as e:
        logger.error(f"Namoz vaqtlarini olishda xatolik: {e}")
        return "⚠️ Namoz vaqtlarini olishda xatolik yuz berdi."

def get_currency_rates():
    try:
        cache = get_currency_cache()
        current_time = int(time.time())
        if current_time - cache["timestamp"] < 3600:  # 1 soat kesh
            return cache["rates"]
        url = "https://api.exchangerate-api.com/v4/latest/UZS"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        rates = response.json()["rates"]
        save_currency_cache(rates)
        return rates
    except requests.RequestException as e:
        logger.error(f"Valyuta kursini olishda xato: {e}")
        return None

def generate_random_number(start, end):
    return random.randint(start, end)

def random_number_menu():
    return types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton("⬅️ Orqaga"))

def currency_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for currency in currency_emojis.keys():
        if currency != "UZS":
            markup.add(types.KeyboardButton(f"{currency_emojis[currency]}"))
    markup.add(types.KeyboardButton("📜 Barcha valyutalar"), types.KeyboardButton("💱 Valyuta konvertori"))
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    return markup

def currency_selection_menu(exclude_currency=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for currency in currency_emojis.keys():
        if currency != exclude_currency:
            markup.add(types.KeyboardButton(f"{currency_emojis[currency]}"))
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    return markup

def amount_input_menu():
    return types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton("⬅️ Orqaga"))

def forecast_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    today = datetime.now()
    for i in range(5):
        day = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        markup.add(types.KeyboardButton(f"📅 {day}"))
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    return markup

def weather_request_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📍 Joylashuvni yuborish", request_location=True), types.KeyboardButton("⬅️ Orqaga"))
    return markup

def prayer_request_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📍 Joylashuvni yuborish", request_location=True), types.KeyboardButton("⬅️ Orqaga"))
    return markup

def main_menu(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("⛅ Ob-havo"), types.KeyboardButton("🕌 Namoz vaqtlari"))
    markup.add(types.KeyboardButton("💱 Valyuta kursi"), types.KeyboardButton("🎲 Tasodifiy son"))
    markup.add(types.KeyboardButton("📚 Vikipediya"), types.KeyboardButton("📝 Shikoyat va Takliflar"))
    if user_id and is_admin(user_id):
        markup.add(types.KeyboardButton("👨‍💼 Admin paneli"))
    return markup

def admin_panel_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📢 Barchaga xabar yuborish"), types.KeyboardButton("🚫 Foydalanuvchini bloklash"))
    markup.add(types.KeyboardButton("✅ Blokdan chiqarish"), types.KeyboardButton("👥 Foydalanuvchilar ro‘yxati"))
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or "Noma'lum"
        banned_users = get_banned_users()
        if user_id not in banned_users:
            users = get_users()
            if not any(user["user_id"] == user_id for user in users):
                save_user(user_id, username)
            bot.reply_to(message, "👋 Assalomu alaykum! Foydali va qiziqarli yordamchi botimizga xush kelibsiz.\n"
                                  "📋 Ushbu bot yordamida ob-havo, namoz vaqtlari, valyuta kurslari, tasodifiy son generatori va Vikipediya xizmatlaridan foydalanishingiz mumkin.\n"
                                  "🔽 Quyidagi tugmalardan birini tanlang!", reply_markup=main_menu(user_id))
        else:
            bot.reply_to(message, "🚫 Siz botdan foydalana olmaysiz, chunki bloklangansiz!")
    except Exception as e:
        logger.error(f"Start buyrug‘ida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Sizda admin huquqlari yo‘q!", reply_markup=main_menu(message.from_user.id))
        return
    try:
        bot.reply_to(message, "👨‍💼 Admin paneliga xush kelibsiz! Quyidagi opsiyalardan birini tanlang:", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except Exception as e:
        logger.error(f"Admin panelida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Admin panelida xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_admin_panel(message):
    try:
        text = message.text.strip()
        if text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
        elif text == "📢 Barchaga xabar yuborish":
            bot.reply_to(message, "📢 Barchaga yuboriladigan xabarni kiriting:")
            bot.register_next_step_handler(message, broadcast_message)
        elif text == "🚫 Foydalanuvchini bloklash":
            bot.reply_to(message, "🚫 Bloklash uchun foydalanuvchi ID’sini kiriting:")
            bot.register_next_step_handler(message, ban_user_handler)
        elif text == "✅ Blokdan chiqarish":
            bot.reply_to(message, "✅ Blokdan chiqarish uchun foydalanuvchi ID’sini kiriting:")
            bot.register_next_step_handler(message, unban_user_handler)
        elif text == "👥 Foydalanuvchilar ro‘yxati":
            users = get_users()
            if not users:
                bot.reply_to(message, "👥 Foydalanuvchilar ro‘yxati bo‘sh!", reply_markup=admin_panel_menu())
            else:
                user_list = "\n".join([f"ID: {user['user_id']}, Username: {user['username']}, Banned: {user['banned']}" for user in users])
                bot.reply_to(message, f"👥 Foydalanuvchilar ro‘yxati:\n{user_list}", reply_markup=admin_panel_menu())
                bot.register_next_step_handler(message, process_admin_panel)
    except Exception as e:
        logger.error(f"Admin panelida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Admin panelida xatolik yuz berdi: {str(e)}", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)

def broadcast_message(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "👨‍💼 Admin paneliga qaytdik!", reply_markup=admin_panel_menu())
            bot.register_next_step_handler(message, process_admin_panel)
            return
        users = get_users()
        banned_users = get_banned_users()
        for user in users:
            user_id = user["user_id"]
            if user_id not in banned_users:
                try:
                    bot.send_message(user_id, f"📢 Admin xabari:\n{message.text}")
                except Exception as e:
                    logger.error(f"Foydalanuvchi {user_id} ga xabar yuborishda xato: {e}")
        bot.reply_to(message, "✅ Xabar barcha foydalanuvchilarga yuborildi!", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except Exception as e:
        logger.error(f"Xabar yuborishda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xabar yuborishda xatolik yuz berdi: {str(e)}", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)

def ban_user_handler(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "👨‍💼 Admin paneliga qaytdik!", reply_markup=admin_panel_menu())
            bot.register_next_step_handler(message, process_admin_panel)
            return
        user_id = int(message.text)
        ban_user(user_id)
        bot.reply_to(message, f"🚫 Foydalanuvchi {user_id} bloklandi!", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except ValueError:
        bot.reply_to(message, "❌ Iltimos, to‘g‘ri foydalanuvchi ID’sini kiriting (raqam bo‘lishi kerak)!", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except Exception as e:
        logger.error(f"Bloklashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Bloklashda xatolik yuz berdi: {str(e)}", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)

def unban_user_handler(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "👨‍💼 Admin paneliga qaytdik!", reply_markup=admin_panel_menu())
            bot.register_next_step_handler(message, process_admin_panel)
            return
        user_id = int(message.text)
        unban_user(user_id)
        bot.reply_to(message, f"✅ Foydalanuvchi {user_id} blokdan chiqarildi!", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except ValueError:
        bot.reply_to(message, "❌ Iltimos, to‘g‘ri foydalanuvchi ID’sini kiriting (raqam bo‘lishi kerak)!", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)
    except Exception as e:
        logger.error(f"Blokdan chiqarishda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Blokdan chiqarishda xatolik yuz berdi: {str(e)}", reply_markup=admin_panel_menu())
        bot.register_next_step_handler(message, process_admin_panel)

@bot.message_handler(func=lambda message: message.text == "⛅ Ob-havo")
def weather_request(message):
    try:
        bot.reply_to(message, "📍 Iltimos, shahar nomini kiriting yoki joylashuvingizni yuboring:", reply_markup=weather_request_menu())
        bot.register_next_step_handler(message, process_weather_request)
    except Exception as e:
        logger.error(f"Ob-havo so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_weather_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        if message.location:
            lat = message.location.latitude
            lon = message.location.longitude
            weather_info, lat, lon, city = get_current_weather_by_coords(lat, lon)
            if lat and lon:
                forecast_data = get_forecast_weather(lat, lon)
                if forecast_data:
                    bot.reply_to(message, weather_info, reply_markup=forecast_menu())
                    bot.register_next_step_handler(message, lambda m: process_forecast(m, forecast_data))
                else:
                    bot.reply_to(message, weather_info, reply_markup=main_menu(message.from_user.id))
            else:
                bot.reply_to(message, weather_info, reply_markup=main_menu(message.from_user.id))
        else:
            city = message.text.strip()
            weather_info, lat, lon, city = get_current_weather_by_city(city)
            if lat and lon:
                forecast_data = get_forecast_weather(lat, lon)
                if forecast_data:
                    bot.reply_to(message, weather_info, reply_markup=forecast_menu())
                    bot.register_next_step_handler(message, lambda m: process_forecast(m, forecast_data))
                else:
                    bot.reply_to(message, weather_info, reply_markup=main_menu(message.from_user.id))
            else:
                bot.reply_to(message, weather_info, reply_markup=main_menu(message.from_user.id))
    except Exception as e:
        logger.error(f"Ob-havo so‘rovini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_forecast(message, forecast_data):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        date = message.text.replace("📅 ", "")
        if date in forecast_data:
            data = forecast_data[date]
            temp = data["temp"]
            desc = data["desc"]
            weather_condition = weather_emojis.get(desc, f"☁️ {desc.capitalize()} (tarjima topilmadi)")
            humidity = data["humidity"]
            wind_speed = data["wind"]
            precipitation = data["precipitation"]
            advice = get_weather_advice(temp, desc, wind_speed, precipitation)
            forecast_info = (
                f"📅 **{date} uchun ob-havo prognozi:**\n"
                f"🌡️ Harorat: {temp}°C\n"
                f"⛅ Ob-havo holati: {weather_condition}\n"
                f"💧 Yog‘ingarchilik (3 soatlik): {precipitation} mm\n"
                f"💨 Shamol tezligi: {wind_speed} m/s\n"
                f"🌫️ Namlik: {humidity}%\n\n"
                f"📌 **Maslahatlar:**\n{advice}"
            )
            bot.reply_to(message, forecast_info, reply_markup=forecast_menu())
            bot.register_next_step_handler(message, lambda m: process_forecast(m, forecast_data))
        else:
            bot.reply_to(message, "❌ Iltimos, ro‘yxatdan kunni tanlang!", reply_markup=forecast_menu())
            bot.register_next_step_handler(message, lambda m: process_forecast(m, forecast_data))
    except Exception as e:
        logger.error(f"Ob-havo prognozini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "🕌 Namoz vaqtlari")
def prayer_request(message):
    try:
        bot.reply_to(message, "📍 Iltimos, shahar nomini kiriting yoki joylashuvingizni yuboring:", reply_markup=prayer_request_menu())
        bot.register_next_step_handler(message, process_prayer_request)
    except Exception as e:
        logger.error(f"Namoz vaqtlari so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_prayer_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        if message.location:
            lat = message.location.latitude
            lon = message.location.longitude
            prayer_info = get_prayer_times_by_coords(lat, lon)
            bot.reply_to(message, prayer_info, reply_markup=main_menu(message.from_user.id))
        else:
            city = message.text.strip()
            prayer_info = get_prayer_times_by_city(city)
            bot.reply_to(message, prayer_info, reply_markup=main_menu(message.from_user.id))
    except Exception as e:
        logger.error(f"Namoz vaqtlari so‘rovini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "💱 Valyuta kursi")
def currency_request(message):
    try:
        bot.reply_to(message, "💱 Valyuta kursini ko‘rish uchun valyutani tanlang:", reply_markup=currency_menu())
        bot.register_next_step_handler(message, process_currency_request)
    except Exception as e:
        logger.error(f"Valyuta kursi so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_currency_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        if message.text == "📜 Barcha valyutalar":
            rates = get_currency_rates()
            if not rates:
                bot.reply_to(message, "⚠️ Valyuta kurslarini olishda xatolik yuz berdi!", reply_markup=currency_menu())
                bot.register_next_step_handler(message, process_currency_request)
                return
            currency_info = "📜 **Joriy valyuta kurslari (UZS asosida):**\n"
            for currency, emoji in currency_emojis.items():
                if currency != "UZS" and currency in rates:
                    rate = rates[currency]
                    currency_info += f"{emoji}: {1/rate:.2f} UZS\n"
            bot.reply_to(message, currency_info, reply_markup=currency_menu())
            bot.register_next_step_handler(message, process_currency_request)
        elif message.text == "💱 Valyuta konvertori":
            bot.reply_to(message, "💱 Qaysi valyutadan konvert qilmoqchisiz?", reply_markup=currency_selection_menu())
            bot.register_next_step_handler(message, process_currency_conversion_from)
        else:
            selected_currency = message.text.split()[1] if " " in message.text else message.text
            rates = get_currency_rates()
            if not rates or selected_currency not in rates:
                bot.reply_to(message, "⚠️ Valyuta kurslarini olishda xatolik yuz berdi!", reply_markup=currency_menu())
                bot.register_next_step_handler(message, process_currency_request)
                return
            rate = rates[selected_currency]
            currency_info = f"💱 **{selected_currency} kursi (UZS asosida):**\n1 {selected_currency} = {1/rate:.2f} UZS"
            bot.reply_to(message, currency_info, reply_markup=currency_menu())
            bot.register_next_step_handler(message, process_currency_request)
    except Exception as e:
        logger.error(f"Valyuta kursi so‘rovini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_currency_conversion_from(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "💱 Valyuta kursi menyusiga qaytdik!", reply_markup=currency_menu())
            bot.register_next_step_handler(message, process_currency_request)
            return
        from_currency = message.text.split()[1] if " " in message.text else message.text
        bot.reply_to(message, f"💱 {from_currency} dan qaysi valyutaga konvert qilmoqchisiz?", reply_markup=currency_selection_menu(from_currency))
        bot.register_next_step_handler(message, lambda m: process_currency_conversion_to(m, from_currency))
    except Exception as e:
        logger.error(f"Valyuta konvertatsiyasida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_currency_conversion_to(message, from_currency):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "💱 Qaysi valyutadan konvert qilmoqchisiz?", reply_markup=currency_selection_menu())
            bot.register_next_step_handler(message, process_currency_conversion_from)
            return
        to_currency = message.text.split()[1] if " " in message.text else message.text
        bot.reply_to(message, f"💱 {from_currency} dan {to_currency} ga konvert qilish uchun miqdorni kiriting:", reply_markup=amount_input_menu())
        bot.register_next_step_handler(message, lambda m: process_currency_conversion_amount(m, from_currency, to_currency))
    except Exception as e:
        logger.error(f"Valyuta konvertatsiyasida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_currency_conversion_amount(message, from_currency, to_currency):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, f"💱 {from_currency} dan qaysi valyutaga konvert qilmoqchisiz?", reply_markup=currency_selection_menu(from_currency))
            bot.register_next_step_handler(message, lambda m: process_currency_conversion_to(m, from_currency))
            return
        amount = float(message.text)
        rates = get_currency_rates()
        if not rates or from_currency not in rates or to_currency not in rates:
            bot.reply_to(message, "⚠️ Valyuta kurslarini olishda xatolik yuz berdi!", reply_markup=currency_menu())
            bot.register_next_step_handler(message, process_currency_request)
            return
        from_rate = rates[from_currency]
        to_rate = rates[to_currency]
        amount_in_uzs = amount / from_rate
        converted_amount = amount_in_uzs * to_rate
        bot.reply_to(message, f"💱 {amount} {from_currency} = {converted_amount:.2f} {to_currency}", reply_markup=currency_menu())
        bot.register_next_step_handler(message, process_currency_request)
    except ValueError:
        bot.reply_to(message, "❌ Iltimos, to‘g‘ri miqdorni kiriting (raqam bo‘lishi kerak)!", reply_markup=amount_input_menu())
        bot.register_next_step_handler(message, lambda m: process_currency_conversion_amount(m, from_currency, to_currency))
    except Exception as e:
        logger.error(f"Valyuta konvertatsiyasida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "🎲 Tasodifiy son")
def random_number_request(message):
    try:
        bot.reply_to(message, "🎲 Iltimos, diapazonni kiriting (masalan, 1-100):")
        bot.register_next_step_handler(message, process_random_number_request)
    except Exception as e:
        logger.error(f"Tasodifiy son so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_random_number_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        start, end = map(int, message.text.split("-"))
        if start >= end:
            bot.reply_to(message, "❌ Boshlang‘ich son oxirgi sondan kichik bo‘lishi kerak!", reply_markup=random_number_menu())
            bot.register_next_step_handler(message, process_random_number_request)
            return
        random_num = generate_random_number(start, end)
        bot.reply_to(message, f"🎲 Tasodifiy son: {random_num}\nYana bir son generatsiya qilish uchun yangi diapazon kiriting yoki orqaga qayting:", reply_markup=random_number_menu())
        bot.register_next_step_handler(message, process_random_number_request)
    except ValueError:
        bot.reply_to(message, "❌ Iltimos, to‘g‘ri diapazon kiriting (masalan, 1-100)!", reply_markup=random_number_menu())
        bot.register_next_step_handler(message, process_random_number_request)
    except Exception as e:
        logger.error(f"Tasodifiy son generatsiyasida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "📚 Vikipediya")
def wikipedia_request(message):
    try:
        bot.reply_to(message, "📚 Qidiruv so‘zini kiriting (masalan, O‘zbekiston):")
        bot.register_next_step_handler(message, process_wikipedia_request)
    except Exception as e:
        logger.error(f"Vikipediya so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_wikipedia_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        query = message.text.strip()
        info = get_wikipedia_info(query)
        bot.reply_to(message, info, reply_markup=main_menu(message.from_user.id))
    except Exception as e:
        logger.error(f"Vikipediya so‘rovini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "📝 Shikoyat va Takliflar")
def feedback_request(message):
    try:
        bot.reply_to(message, "📝 Iltimos, shikoyat yoki taklifingizni yozing:")
        bot.register_next_step_handler(message, process_feedback_request)
    except Exception as e:
        logger.error(f"Shikoyat va takliflar so‘rovida xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

def process_feedback_request(message):
    try:
        if message.text == "⬅️ Orqaga":
            bot.reply_to(message, "🏠 Asosiy menyuga qaytdik!", reply_markup=main_menu(message.from_user.id))
            return
        feedback = message.text.strip()
        user_id = message.from_user.id
        username = message.from_user.username or "Noma'lum"
        for admin_id in ADMINS:
            try:
                bot.send_message(admin_id, f"📝 Yangi shikoyat/taklif:\nFoydalanuvchi: {username} (ID: {user_id})\nXabar: {feedback}")
            except Exception as e:
                logger.error(f"Admin {admin_id} ga xabar yuborishda xato: {e}")
        bot.reply_to(message, "✅ Shikoyat yoki taklifingiz qabul qilindi! Tez orada ko‘rib chiqamiz.", reply_markup=main_menu(message.from_user.id))
    except Exception as e:
        logger.error(f"Shikoyat va takliflar so‘rovini qayta ishlashda xatolik: {e}")
        bot.reply_to(message, f"⚠️ Xatolik yuz berdi: {str(e)}", reply_markup=main_menu(message.from_user.id))

# Webhook uchun Flask routelari
@server.route('/bot', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'OK', 200

@server.route('/')
def index():
    return 'Bot is running!'

# Webhook sozlash va serverni ishga tushirish
if __name__ == "__main__":
    # Webhook sozlash
    bot.remove_webhook()
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/bot"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    # Flask serverini ishga tushirish
server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))            
