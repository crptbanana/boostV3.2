import os
import sys
import csv
import asyncio
import time
import logging
from datetime import datetime
import aiohttp
import ssl
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputPeerUser, InputPeerChannel, InputUser, InputFolderPeer, InputPeerChat
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
from telethon.tl.functions.messages import GetDialogFiltersRequest, UpdateDialogFilterRequest
from telethon.tl.types import DialogFilter, InputPeerUser, DialogFilterDefault
import random
from comment_generator import generate_comment
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import InputStickerSetShortName
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon.tl.functions.messages import SaveGifRequest

# Глобальные переменные для отслеживания последних постов (больше не используются)
# last_post_ids = {}  # {channel_link: last_post_id}


class Config:
    def __init__(self, config_file='config.txt'):
        self.config_file = config_file
        self.settings = {}
        self.forward_config = {}
        self.reactions_config = {}
        self.favorites_config = {}
        self.load_config()
    
    def load_config(self):
        """Загружает настройки из файла конфигурации"""
        try:
            if not os.path.exists(self.config_file):
                print(f"❌ Файл конфигурации {self.config_file} не найден!")
                return
            
            current_section = None
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if line.startswith('[') and line.endswith(']'):
                            current_section = line[1:-1]
                        elif '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            if current_section == 'forward':
                                self.forward_config[key] = value
                            elif current_section == 'reactions':
                                self.reactions_config[key] = value
                            elif current_section == 'favorites':
                                self.favorites_config[key] = value
                            else:
                                self.settings[key] = value
            
            print(f"✅ Загружено {len(self.settings)} настроек из {self.config_file}")
            
        except Exception as e:
            print(f"❌ Ошибка при загрузке конфигурации: {str(e)}")
    
    def get(self, key, default=None):
        """Получает значение настройки"""
        return self.settings.get(key, default)
    
    def get_int(self, key, default=0):
        """Получает целое число"""
        try:
            return int(self.get(key, default))
        except:
            return default
    
    def get_float(self, key, default=0.0):
        """Получает число с плавающей точкой"""
        try:
            return float(self.get(key, default))
        except:
            return default
    
    def get_bool(self, key, default=False):
        """Получает булево значение"""
        value = self.get(key, str(default)).lower()
        return value in ('y', 'yes', 'true', '1', 'on')
    
    def get_range(self, key, default_min=0, default_max=0):
        """Получает диапазон значений (минимум-максимум)"""
        value = self.get(key, f"{default_min}-{default_max}")
        try:
            if '-' in value:
                min_val, max_val = value.split('-', 1)
                return int(min_val.strip()), int(max_val.strip())
            else:
                return int(value), int(value)
        except:
            return default_min, default_max
    
    def get_list(self, key, default=None):
        """Получает список значений, разделенных запятыми"""
        value = self.get(key, '')
        if not value:
            return default or []
        return [item.strip() for item in value.split(',') if item.strip()]
    
    def get_forward_config(self):
        """Получает конфигурацию пересылки"""
        from_channels = self.get_list('FORWARD_FROM_CHANNELS', [])
        to_channel = self.get('FORWARD_TO_CHANNEL', '')
        to_channel_2 = self.get('FORWARD_TO_CHANNEL_2', '')
        
        # Добавляем логирование для отладки
        logging.info(f"🔍 Отладка get_forward_config:")
        logging.info(f"  from_channels: {from_channels}")
        logging.info(f"  to_channel: {to_channel}")
        logging.info(f"  to_channel_2: {to_channel_2}")
        
        return {
            'from_channels': from_channels,
            'to_channel': to_channel,
            'to_channel_2': to_channel_2
        }
    
    def get_reactions_config(self):
        """Получает конфигурацию реакций"""
        reactions = {}
        for key, value in self.settings.items():
            if key.startswith('REACTIONS_CHANNELS'):
                if ':' in value:
                    # Ищем последнее вхождение ':' чтобы правильно разделить ссылку и эмодзи
                    last_colon_index = value.rfind(':')
                    if last_colon_index != -1:
                        channel_link = value[:last_colon_index].strip()
                        emojis = value[last_colon_index + 1:].strip()
                        emoji_list = [emoji.strip() for emoji in emojis.split(',') if emoji.strip()]
                        reactions[channel_link] = emoji_list
        return reactions
    
    def get_favorites_config(self):
        """Получает конфигурацию избранного"""
        return self.get_list('FAVORITES_CHANNELS', [])
    
    def get_main_account_index(self):
        """Получает индекс главного аккаунта из конфигурации"""
        try:
            return int(self.get('MAIN_ACCOUNT', '1')) - 1  # Нумерация с 1, но индекс с 0
        except (ValueError, TypeError):
            return 0  # По умолчанию первый аккаунт

    def get_reactions_selected_accounts(self):
        """Получает номера аккаунтов для реакций"""
        accounts_str = self.get('REACTIONS_SELECTED_ACCOUNTS', '0')
        if accounts_str == '0':
            return []  # Пустой список означает "использовать все"
        try:
            return [int(x.strip()) - 1 for x in accounts_str.split(",")]  # Вычитаем 1 для индексации с 0
        except ValueError:
            logging.warning("⚠️ Некорректная настройка REACTIONS_SELECTED_ACCOUNTS")
            return []
    
    def get_favorites_selected_accounts(self):
        """Получает номера аккаунтов для избранного"""
        accounts_str = self.get('FAVORITES_SELECTED_ACCOUNTS', '0')
        if accounts_str == '0':
            return []  # Пустой список означает "использовать все"
        try:
            return [int(x.strip()) - 1 for x in accounts_str.split(",")]  # Вычитаем 1 для индексации с 0
        except ValueError:
            logging.warning("⚠️ Некорректная настройка FAVORITES_SELECTED_ACCOUNTS")
            return []
    
    def get_reactions_account_delay(self):
        """Получает задержку между аккаунтами для реакций"""
        delay_str = self.get('REACTIONS_ACCOUNT_DELAY', '2-5')
        try:
            min_delay, max_delay = map(float, delay_str.split('-'))
            return min_delay, max_delay
        except (ValueError, AttributeError):
            logging.warning("⚠️ Некорректная настройка REACTIONS_ACCOUNT_DELAY, используем 2-5")
            return 2.0, 5.0
    
    def get_favorites_account_delay(self):
        """Получает задержку между аккаунтами для избранного"""
        delay_str = self.get('FAVORITES_ACCOUNT_DELAY', '2-5')
        try:
            min_delay, max_delay = map(float, delay_str.split('-'))
            return min_delay, max_delay
        except (ValueError, AttributeError):
            logging.warning("⚠️ Некорректная настройка FAVORITES_ACCOUNT_DELAY, используем 2-5")
            return 2.0, 5.0

class TelegramAccount:
    def __init__(self, phone, api_id, api_hash, password, session, proxy):
        self.phone = phone
        self.api_id = api_id
        self.api_hash = api_hash
        self.password = password
        self.session = session
        self.proxy_config = None
        
        # Настраиваем прокси если строка не пустая
        if proxy and proxy.strip():
            try:
                proxy_parts = proxy.strip().split(':')
                if len(proxy_parts) != 4:
                    print(f"❌ Ошибка: неверный формат прокси для {phone}")
                    return
                    
                host, port, username, password = proxy_parts
                
                if not port.isdigit():
                    print(f"❌ Ошибка: порт прокси должен быть числом для {phone}")
                    return
                    
                # Новый формат прокси для Telethon 1.28+
                # Формат: (type, addr, port, rdns, username, password)
                self.proxy_config = ('socks5', host, int(port), True, username, password)
                print(f"✅ Прокси настроен для аккаунта {phone}: {host}:{port}")
            except Exception as e:
                print(f"❌ Ошибка при настройке прокси для {phone}: {str(e)}")
                self.proxy_config = None
        
        # Создаем клиент с прокси если он настроен
        try:
            # ВАЖНО: Создаем StringSession, который НЕ сохраняет DC адреса
            # Это заставляет Telethon каждый раз проходить через прокси
            if session:
                # Используем существующую сессию, но с флагом автопересоздания DC
                session_instance = StringSession(session)
            else:
                session_instance = StringSession()
            
            # DEBUG: выводим информацию о прокси
            if self.proxy_config:
                print(f"🔍 DEBUG: Создаем клиента с прокси {self.proxy_config[1]}:{self.proxy_config[2]}")
            else:
                print(f"⚠️ DEBUG: Создаем клиента БЕЗ прокси!")
            
            self.client = TelegramClient(
                session_instance,
                int(api_id),
                api_hash,
                proxy=self.proxy_config,
                connection_retries=3,
                retry_delay=1,
                use_ipv6=False,  # Форсируем IPv4 через прокси
                auto_reconnect=True,  # Автопереподключение
                flood_sleep_threshold=0  # Не спать при flood wait
            )
        except Exception as e:
            print(f"❌ Ошибка при создании клиента для {phone}: {str(e)}")
            raise

def setup_logging(config):
    """Настраивает логирование"""
    if config.get_bool('SAVE_LOGS'):
        # Создаем директорию для логов
        if not os.path.exists('logs'):
            os.makedirs('logs')
        
        # Настраиваем логирование
        log_level = logging.DEBUG if config.get_bool('VERBOSE_LOGGING') else logging.INFO
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        
        # Лог файл с датой
        log_filename = f'logs/server_bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        
        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler()  # Вывод в консоль тоже
            ]
        )
        
        print(f"✅ Логирование настроено: {log_filename}")
    else:
        # Только консоль
        log_level = logging.DEBUG if config.get_bool('VERBOSE_LOGGING') else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

def load_accounts():
    """Загружает аккаунты из CSV файла"""
    accounts = []
    try:
        if not os.path.exists('accounts.csv'):
            logging.error("❌ Файл accounts.csv не найден!")
            return accounts
            
        with open('accounts.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not {'phone', 'api_id', 'api_hash', 'password', 'session', 'proxy'}.issubset(set(reader.fieldnames)):
                logging.error("❌ В файле accounts.csv отсутствуют необходимые колонки!")
                return accounts
                
            for row in reader:
                try:
                    account = TelegramAccount(
                        phone=row['phone'].strip(),
                        api_id=row['api_id'].strip(),
                        api_hash=row['api_hash'].strip(),
                        password=row.get('password', '').strip() or None,
                        session=row['session'].strip(),
                        proxy=row['proxy'].strip()
                    )
                    accounts.append(account)
                except Exception as e:
                    logging.error(f"❌ Ошибка при загрузке аккаунта {row.get('phone', 'неизвестный')}: {str(e)}")
                    continue
                    
        if not accounts:
            logging.error("❌ Не удалось загрузить ни одного аккаунта из accounts.csv")
        else:
            logging.info(f"✅ Успешно загружено аккаунтов: {len(accounts)}")
            
    except Exception as e:
        logging.error(f"❌ Ошибка при чтении accounts.csv: {str(e)}")
        
    return accounts

def save_session(account, force=False):
    """
    Сохраняет строку сессии в CSV файл
    
    Args:
        account: Аккаунт для сохранения
        force: Принудительное сохранение (по умолчанию False)
    
    Сессия сохраняется только если:
    - force=True (принудительно)
    - Или изменился DC (Data Center)
    - Или изменился Auth Key
    - Или прошло значительное время с последнего сохранения
    
    Sequence numbers и server salt НЕ требуют сохранения на диск -
    они автоматически обновляются при переподключении.
    """
    try:
        # Получаем текущую сессию
        current_session = account.client.session.save()
        
        with open('accounts.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames

        # Обновляем сессию для нужного аккаунта
        session_updated = False
        for row in rows:
            if row['phone'] == account.phone:
                old_session = row['session']
                
                # Проверяем, изменилась ли сессия ЗНАЧИТЕЛЬНО
                # (не просто sequence numbers, а DC/auth_key)
                if force or old_session != current_session:
                    # Простая проверка: если первые 100 символов изменились = смена DC/ключей
                    if force or old_session[:100] != current_session[:100]:
                        row['session'] = current_session
                        session_updated = True
                        logging.info(f"💾 Критическое изменение сессии для {account.phone} - сохраняем")
                    else:
                        # Только sequence numbers изменились - не сохраняем
                        logging.debug(f"🔍 Незначительное изменение сессии {account.phone} - пропускаем")
                break

        # Сохраняем только если были значительные изменения
        if session_updated:
            with open('accounts.csv', 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            logging.info(f"✅ Сессия сохранена для {account.phone}")
            
    except Exception as e:
        logging.error(f"❌ Ошибка при сохранении сессии для {account.phone}: {str(e)}")

async def ensure_connection(account):
    """Проверяет соединение и переподключается при необходимости"""
    try:
        reconnected = False
        
        # Проверяем, подключен ли клиент
        if not account.client.is_connected():
            logging.warning(f"⚠️ Клиент {account.phone} отключен, переподключаемся...")
            await account.client.connect()
            reconnected = True
            
        # Проверяем авторизацию
        if not await account.client.is_user_authorized():
            logging.error(f"❌ Аккаунт {account.phone} не авторизован!")
            return False
        
        # ВАЖНО: Сохраняем сессию после переподключения
        # Потому что мог измениться DC или auth_key
        if reconnected:
            save_session(account, force=True)
            logging.info(f"💾 Сессия сохранена после переподключения {account.phone}")
            
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка проверки соединения для {account.phone}: {e}")
        try:
            # Пытаемся переподключиться
            await account.client.disconnect()
            await asyncio.sleep(2)
            await account.client.connect()
            
            if await account.client.is_user_authorized():
                # Сохраняем сессию после восстановления соединения
                save_session(account, force=True)
                logging.info(f"💾 Сессия сохранена после восстановления {account.phone}")
                return True
            return False
        except:
            return False

async def connect_account(account):
    """Подключает аккаунт к Telegram"""
    try:
        logging.info(f"Подключение аккаунта {account.phone}...")
        
        # Добавляем таймаут для подключения
        try:
            await asyncio.wait_for(account.client.connect(), timeout=30.0)
        except asyncio.TimeoutError:
            logging.error(f"❌ Таймаут подключения для {account.phone} (30 сек)")
            return False
        
        if not await account.client.is_user_authorized():
            logging.warning(f"⚠️ Требуется авторизация для {account.phone}")
            logging.warning(f"⚠️ Аккаунт {account.phone} требует SMS код - АВТОМАТИЧЕСКИ ПРОПУСКАЕМ")
            await account.client.disconnect()
            return False
                
        logging.info(f"Аккаунт {account.phone} успешно подключен!")
        
        # Сохраняем сессию после успешного подключения
        save_session(account)
        
        return True
        
    except Exception as e:
        logging.error(f"Ошибка при подключении аккаунта {account.phone}: {str(e)}")
        return False

async def load_channels():
    """Загружает список каналов из файла"""
    if not os.path.exists('channels.txt'):
        logging.error("❌ Файл channels.txt не найден!")
        return []
        
    with open('channels.txt', 'r', encoding='utf-8') as f:
        channels = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    if not channels:
        logging.error("❌ Нет каналов в channels.txt")
        return []
        
    logging.info(f"✅ Загружено каналов: {len(channels)}")
    return channels

def read_sticker_packs(filename='stickers.txt'):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        logging.error(f'Не удалось прочитать {filename}: {e}')
        return []

async def get_stickers_from_pack(client, pack_url):
    if '/addstickers/' not in pack_url:
        return []
    short_name = pack_url.split('/addstickers/')[-1]
    try:
        res = await client(GetStickerSetRequest(stickerset=InputStickerSetShortName(short_name=short_name), hash=0))
        return [doc for doc in res.documents]
    except Exception as e:
        logging.error(f'Ошибка при получении стикеров из пака {pack_url}: {e}')
        return []

async def get_folder_id(client, folder_name):
    try:
        result = await client(GetDialogFiltersRequest())
        
        for folder in result.filters:
            if isinstance(folder, DialogFilterDefault):
                continue
                
            if isinstance(folder, DialogFilter):
                logging.debug(f"Найдена папка: {folder.title}")
                if folder.title == folder_name:
                    return folder
        
        logging.warning(f"Папка {folder_name} не найдена в списке папок.")
        return None
    except Exception as e:
        logging.error(f"Ошибка при получении папки: {str(e)}")
        return None

async def add_user_to_folder(client, user, folder_name):
    try:
        folder = await get_folder_id(client, folder_name)
        if not folder:
            logging.warning(f"Папка {folder_name} не найдена")
            return False

        peer = await client.get_input_entity(user)
        
        if not folder.include_peers:
            folder.include_peers = []
            
        def get_peer_id(peer):
            if isinstance(peer, InputPeerUser):
                return ('user', peer.user_id)
            elif isinstance(peer, InputPeerChannel):
                return ('channel', peer.channel_id)
            elif isinstance(peer, InputPeerChat):
                return ('chat', peer.chat_id)
            return (None, None)
            
        current_peer_type, current_peer_id = get_peer_id(peer)
        
        for existing_peer in folder.include_peers:
            existing_type, existing_id = get_peer_id(existing_peer)
            if current_peer_type == existing_type and current_peer_id == existing_id:
                logging.debug(f"{current_peer_type.capitalize()} уже в папке {folder_name}")
                return True
        
        folder.include_peers.append(peer)
        
        await client(UpdateDialogFilterRequest(
            id=folder.id,
            filter=folder
        ))
        
        logging.info(f"{current_peer_type.capitalize()} добавлен в папку {folder_name}")
        return True
            
    except Exception as e:
        logging.error(f"Ошибка при добавлении в папку: {str(e)}")
        return False

def log_message(username, log_file):
    """Логирует username в указанный файл"""
    try:
        username = username.lstrip('@')
        log_entry = f"@{username}\n"
        
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        with open(f'logs/{log_file}', 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
    except Exception as e:
        logging.error(f"Ошибка при логировании: {str(e)}")

def log_comment(channel, comment, log_file):
    """Логирует комментарий в указанный файл"""
    try:
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        with open(f'logs/{log_file}', 'a', encoding='utf-8') as f:
            f.write(f"Channel: {channel}\nComment: {comment}\n---\n")
            
    except Exception as e:
        logging.error(f"Ошибка при логировании комментария: {str(e)}")

async def check_spam_status(client, phone):
    """Проверяет статус спама через @SpamBot"""
    try:
        spam_bot = await client.get_entity('SpamBot')
        
        logging.info(f"📱 Аккаунт {phone}: Отправляем первую команду /start в @SpamBot")
        await client.send_message(spam_bot, '/start')
        
        first_wait = random.randint(60, 180)
        logging.info(f"Ожидаем {first_wait//60} минут {first_wait%60} секунд перед проверкой первого ответа...")
        await asyncio.sleep(first_wait)
        
        response1 = await client.get_messages(spam_bot, limit=1)
        if response1:
            message1 = response1[0].message
            logging.info(f"Первый ответ @SpamBot: {message1}")
        
        logging.info(f"📱 Аккаунт {phone}: Отправляем вторую команду /start в @SpamBot")
        await client.send_message(spam_bot, '/start')
        
        second_wait = random.randint(180, 420)
        logging.info(f"Ожидаем {second_wait//60} минут {second_wait%60} секунд перед проверкой второго ответа...")
        await asyncio.sleep(second_wait)
        
        response2 = await client.get_messages(spam_bot, limit=1)
        if not response2:
            logging.error(f"❌ Не получен ответ от @SpamBot для аккаунта {phone}")
            return None
            
        message2 = response2[0].message
        logging.info(f"Второй ответ @SpamBot: {message2}")
        
        if "К сожалению, кто-то из пользователей" in message2:
            while True:
                try:
                    wait_time = int(input(f"\nАккаунт {phone} ограничен. Введите время ожидания в секундах: "))
                    if wait_time < 0:
                        print("Время ожидания не может быть отрицательным!")
                        continue
                    return wait_time
                except ValueError:
                    print("❌ Пожалуйста, введите целое число!")
        
        return 0
        
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке спам статуса для {phone}: {str(e)}")
        return None

# === NEW: Функции для работы с last_commented.txt (post_id и count) ===
LAST_COMMENTED_FILE = 'last_commented.txt'

# === NEW: Функции для работы с last_reacted.txt (post_id и account_phone) ===
LAST_REACTED_FILE = 'last_reacted.txt'

def read_last_commented(filename=LAST_COMMENTED_FILE):
    """Читает last_commented.txt и возвращает словарь {(phone, channel): (post_id, count)}"""
    data = {}
    if not os.path.exists(filename):
        return data
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 4:
                phone, channel, post_id, count = parts
                data[(phone, channel)] = (int(post_id), int(count))
            elif len(parts) == 3:
                # Для обратной совместимости
                phone, channel, post_id = parts
                data[(phone, channel)] = (int(post_id), 1)
    return data

def write_last_commented(data, filename=LAST_COMMENTED_FILE):
    """Записывает словарь {(phone, channel): (post_id, count)} в last_commented.txt"""
    with open(filename, 'w', encoding='utf-8') as f:
        for (phone, channel), (post_id, count) in data.items():
            f.write(f"{phone} {channel} {post_id} {count}\n")

def read_last_reacted(filename=LAST_REACTED_FILE):
    """Читает last_reacted.txt и возвращает словарь {(phone, channel): post_id}"""
    data = {}
    if not os.path.exists(filename):
        return data
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 3:
                phone, channel, post_id = parts
                data[(phone, channel)] = int(post_id)
    return data

def write_last_reacted(data, filename=LAST_REACTED_FILE):
    """Записывает словарь {(phone, channel): post_id} в last_reacted.txt"""
    with open(filename, 'w', encoding='utf-8') as f:
        for (phone, channel), post_id in data.items():
            f.write(f"{phone} {channel} {post_id}\n")

# === NEW: Функции для работы с last_favorited.txt (post_id и account_phone) ===
LAST_FAVORITED_FILE = 'last_favorited.txt'

# === NEW: Функции для работы с last_forwarded.txt (post_id, channel и account_phone) ===
LAST_FORWARDED_FILE = 'last_forwarded.txt'

def read_last_favorited(filename=LAST_FAVORITED_FILE):
    """Читает last_favorited.txt и возвращает словарь {(phone, channel): post_id}"""
    data = {}
    if not os.path.exists(filename):
        return data
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Пропускаем комментарии и пустые строки
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) == 3:
                phone, channel, post_id = parts
                try:
                    data[(phone, channel)] = int(post_id)
                except ValueError:
                    logging.warning(f"⚠️ Некорректный post_id в строке: {line}")
                    continue
    return data

def write_last_favorited(data, filename=LAST_FAVORITED_FILE):
    """Записывает словарь {(phone, channel): post_id} в last_favorited.txt"""
    with open(filename, 'w', encoding='utf-8') as f:
        # Записываем заголовок
        f.write("# Файл для отслеживания последних добавлений в избранное\n")
        f.write("# Формат: phone channel post_id\n")
        f.write("# Пример: +79952423572 https://t.me/crptA92 12345\n\n")
        # Записываем данные
        for (phone, channel), post_id in data.items():
            f.write(f"{phone} {channel} {post_id}\n")

def read_last_forwarded(filename=LAST_FORWARDED_FILE):
    """Читает last_forwarded.txt и возвращает словарь {(phone, channel, channel_type): post_id}"""
    last_forwarded = {}
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    try:
                        parts = line.split(' ')
                        if len(parts) >= 4:
                            phone = parts[0].strip()
                            channel = parts[1].strip()
                            channel_type = parts[2].strip()
                            post_id = int(parts[3].strip())
                            last_forwarded[(phone, channel, channel_type)] = post_id
                        elif len(parts) >= 3:
                            # Поддержка старого формата для обратной совместимости
                            phone = parts[0].strip()
                            channel = parts[1].strip()
                            post_id = int(parts[2].strip())
                            # Мигрируем в новый формат, считая что это основной канал
                            last_forwarded[(phone, channel, 'основной')] = post_id
                    except ValueError:
                        logging.warning(f"⚠️ Пропускаем некорректную строку в {filename}: {line}")
                        continue
            logging.info(f"📖 Загружено {len(last_forwarded)} записей из {filename}")
        else:
            logging.info(f"📄 Файл {filename} не найден, создаем новый")
    except Exception as e:
        logging.error(f"❌ Ошибка при чтении {filename}: {e}")
    return last_forwarded

def write_last_forwarded(data, filename=LAST_FORWARDED_FILE):
    """Записывает словарь {(phone, channel, channel_type): post_id} в last_forwarded.txt"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Файл для отслеживания последних пересылок\n")
            f.write("# Формат: phone channel channel_type post_id\n")
            f.write("# Пример: +79952423572 https://t.me/crptA92 основной 12345\n\n")
            for (phone, channel, channel_type), post_id in data.items():
                f.write(f"{phone} {channel} {channel_type} {post_id}\n")
        logging.info(f"✅ Данные записаны в {filename}")
    except Exception as e:
        logging.error(f"❌ Ошибка при записи {filename}: {e}")

def is_error_comment(comment: str) -> bool:
    """
    Проверяет, является ли комментарий сообщением об ошибке.
    
    Args:
        comment (str): Текст комментария
        
    Returns:
        bool: True если это ошибка, False если нормальный комментарий
    """
    if not comment:
        return True
    
    error_keywords = [
        'ошибка',
        'error',
        'не удалось',
        'failed',
        'нет доступных',
        'ошибка генерации',
        'ошибка: не удалось'
    ]
    
    comment_lower = comment.lower()
    for keyword in error_keywords:
        if keyword in comment_lower:
            return True
    
    return False

async def delete_error_comments(client, entity, discussion_id, account_phone=None, max_check=50):
    """
    Удаляет комментарии с ошибками из обсуждения поста.
    Удаляет только комментарии от текущего аккаунта (если указан account_phone).
    
    Args:
        client: Telethon клиент
        entity: Entity канала
        discussion_id: ID поста с обсуждением
        account_phone: Номер телефона аккаунта (для проверки авторства)
        max_check: Максимальное количество комментариев для проверки
    """
    try:
        # Получаем информацию о текущем пользователе
        me = await client.get_me()
        current_user_id = me.id if me else None
        
        # Получаем комментарии из обсуждения
        messages = await client.get_messages(entity, reply_to=discussion_id, limit=max_check)
        
        deleted_count = 0
        for msg in messages:
            # Проверяем, что это комментарий с ошибкой
            if not msg.text or not is_error_comment(msg.text):
                continue
            
            # Проверяем авторство - удаляем только свои комментарии
            if current_user_id and hasattr(msg, 'from_id') and msg.from_id:
                # Проверяем, что это сообщение от текущего пользователя
                if hasattr(msg.from_id, 'user_id'):
                    if msg.from_id.user_id != current_user_id:
                        continue  # Пропускаем чужие сообщения
                elif hasattr(msg.from_id, 'channel_id'):
                    continue  # Пропускаем сообщения от каналов
            
            # Удаляем комментарий с ошибкой
            try:
                await client.delete_messages(entity, [msg.id])
                logging.info(f"🗑️ Удален комментарий с ошибкой: {msg.text[:50]}...")
                deleted_count += 1
                await asyncio.sleep(0.5)  # Небольшая задержка между удалениями
            except Exception as e:
                logging.warning(f"⚠️ Не удалось удалить сообщение {msg.id}: {e}")
        
        if deleted_count > 0:
            logging.info(f"✅ Удалено {deleted_count} комментариев с ошибками")
        
    except Exception as e:
        logging.debug(f"Не удалось проверить комментарии на ошибки: {e}")

async def comment_on_channels(account, channels, min_delay, max_delay, min_comments, max_comments, general_reply_prob=50, sticker_prob=10, personality_mode="auto"):
    # Проверяем соединение перед началом работы
    if not await ensure_connection(account):
        logging.error(f"❌ Не удалось установить соединение для {account.phone}")
        return
    
    client = account.client
    log_file = 'channel_comments.txt'
    num_comments = random.randint(int(min_comments), int(max_comments))
    logging.info(f"[{account.phone}] Будет оставлено {num_comments} комментариев")

    sticker_packs = read_sticker_packs()
    all_stickers = []
    for pack_url in sticker_packs:
        stickers = await get_stickers_from_pack(client, pack_url)
        if stickers:
            all_stickers.extend(stickers)
    
    last_commented = read_last_commented()
    comments_made = 0
    while comments_made < num_comments:
        any_action = False
        for channel in channels:
            if comments_made >= num_comments:
                break
            try:
                entity = await client.get_entity(channel)
                # Получаем только последний пост
                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=1,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))
                if not history.messages:
                    logging.warning(f"❌ Нет сообщений в канале {channel}")
                    continue
                post = history.messages[0]
                post_id = getattr(post, 'id', None)
                post_text = post.message or ''
                key = (account.phone, channel)
                prev_post_id, prev_count = last_commented.get(key, (None, 0))
                # Если пост сменился — сбрасываем счётчик
                if prev_post_id != post_id:
                    prev_count = 0
                # Сколько ещё можно дописать
                to_write = num_comments - prev_count
                if to_write <= 0:
                    logging.info(f"⏩ [{account.phone}] Уже оставил {prev_count} комментариев под постом {post_id} в {channel}, пропускаем")
                    continue
                for _ in range(to_write):
                    if comments_made >= num_comments:
                        break
                    use_sticker = all_stickers and (random.randint(1, 100) <= sticker_prob)
                    if use_sticker:
                        sticker = random.choice(all_stickers)
                        if hasattr(post, 'replies') and post.replies and getattr(post.replies, 'comments', False):
                            discussion_id = getattr(post, 'id', None)
                            if discussion_id is None:
                                logging.error(f"❌ Не удалось получить discussion_id для поста в {channel}")
                                continue
                            try:
                                await client.send_file(entity, sticker, comment_to=discussion_id)
                                logging.info(f"✅ [{account.phone}] Отправлен стикер в {channel} (post {post_id})")
                                log_comment(channel, '[sticker]', log_file)
                                comments_made += 1
                                prev_count += 1
                                last_commented[key] = (post_id, prev_count)
                                write_last_commented(last_commented)
                                save_session(account)  # Сохраняем сессию после успешного действия
                                any_action = True
                            except FloodWaitError as e:
                                logging.warning(f"⚠️ FloodWait: ждем {e.seconds} сек...")
                                await asyncio.sleep(e.seconds)
                                continue
                            except Exception as e:
                                logging.error(f"❌ Ошибка при отправке стикера в {channel}: {e}")
                        else:
                            logging.warning(f"⚠️ В канале {channel} комментарии отключены или не поддерживаются")
                    else:
                        # Генерируем комментарий с проверкой на ошибки
                        max_comment_attempts = 5  # Максимум попыток генерации нормального комментария
                        comment = None
                        for attempt in range(max_comment_attempts):
                            generated = generate_comment(post_text, general_reply_prob=general_reply_prob, personality_mode=personality_mode)
                            
                            # Проверяем, не является ли комментарий ошибкой
                            if not is_error_comment(generated):
                                comment = generated
                                break
                            else:
                                logging.warning(f"⚠️ Сгенерирован комментарий с ошибкой (попытка {attempt + 1}/{max_comment_attempts}): {generated}")
                                if attempt < max_comment_attempts - 1:
                                    await asyncio.sleep(0.5)  # Небольшая задержка перед повторной попыткой
                        
                        # Если после всех попыток получили ошибку - пропускаем этот комментарий
                        if not comment or is_error_comment(comment):
                            logging.warning(f"⚠️ Не удалось сгенерировать нормальный комментарий после {max_comment_attempts} попыток, пропускаем")
                            continue
                        
                        if hasattr(post, 'replies') and post.replies and getattr(post.replies, 'comments', False):
                            discussion_id = getattr(post, 'id', None)
                            if discussion_id is None:
                                logging.error(f"❌ Не удалось получить discussion_id для поста в {channel}")
                                continue
                            
                            # Удаляем старые комментарии с ошибками перед отправкой нового
                            try:
                                await delete_error_comments(client, entity, discussion_id, account.phone)
                            except Exception as e:
                                logging.debug(f"Не удалось проверить старые комментарии: {e}")
                            
                            try:
                                await client.send_message(entity, comment, comment_to=discussion_id)
                                logging.info(f"✅ [{account.phone}] Оставлен комментарий в {channel} (post {post_id}): {comment}")
                                log_comment(channel, comment, log_file)
                                comments_made += 1
                                prev_count += 1
                                last_commented[key] = (post_id, prev_count)
                                write_last_commented(last_commented)
                                save_session(account)  # Сохраняем сессию после успешного действия
                                any_action = True
                            except FloodWaitError as e:
                                logging.warning(f"⚠️ FloodWait: ждем {e.seconds} сек...")
                                await asyncio.sleep(e.seconds)
                                continue
                            except Exception as e:
                                logging.error(f"❌ Ошибка при комментировании {channel}: {e}")
                        else:
                            logging.warning(f"⚠️ В канале {channel} комментарии отключены или не поддерживаются")
                    if comments_made < num_comments and any_action:
                        delay = random.uniform(min_delay, max_delay)
                        logging.info(f"⏳ Задержка {delay:.1f} сек...")
                        await asyncio.sleep(delay)
            except Exception as e:
                logging.error(f"❌ Ошибка обработки канала {channel}: {e}")
                continue
        if not any_action:
            break  # Все каналы/посты пропущены, выходим из while

async def resolve_channel_link(client, channel_link):
    """Преобразует ссылку на канал в entity"""
    try:
        # Убираем лишние пробелы
        channel_link = channel_link.strip()
        
        # Если это уже ID канала (начинается с -100)
        if channel_link.startswith('-100'):
            return await client.get_entity(int(channel_link))
        
        # Если это ссылка на канал
        if channel_link.startswith('https://t.me/'):
            # Извлекаем username из ссылки
            username = channel_link.replace('https://t.me/', '').split('/')[0]
            if username.startswith('+'):
                username = username[1:]  # Убираем + если есть
            return await client.get_entity(f"@{username}")
        
        # Если это username без @
        if not channel_link.startswith('@'):
            return await client.get_entity(f"@{channel_link}")
        
        # Если это username с @
        return await client.get_entity(channel_link)
        
    except Exception as e:
        logging.error(f"❌ Ошибка преобразования ссылки {channel_link}: {e}")
        return None

async def forward_posts_from_channels(main_account, forward_config):
    """Пересылает последний пост из указанных каналов в каналы назначения"""
    logging.info(f"🔍 Отладка пересылки: from_channels={forward_config['from_channels']}, to_channel={forward_config['to_channel']}, to_channel_2={forward_config['to_channel_2']}")
    
    if not forward_config['from_channels']:
        logging.info("⚠️ Не указаны каналы-источники для пересылки")
        return
    
    # Загружаем данные о последних пересланных постах
    last_forwarded = read_last_forwarded()
    logging.info(f"📖 Загружено {len(last_forwarded)} записей о пересланных постах")
    
    client = main_account.client
    from_channels = forward_config['from_channels']
    to_channel = forward_config['to_channel']
    to_channel_2 = forward_config['to_channel_2']
    
    # Формируем список каналов назначения (только непустые)
    to_channels = []
    if to_channel:
        to_channels.append(('основной', to_channel))
        logging.info(f"✅ Добавлен основной канал назначения: {to_channel}")
    else:
        logging.warning("⚠️ Основной канал назначения не указан")
        
    if to_channel_2:
        to_channels.append(('второй', to_channel_2))
        logging.info(f"✅ Добавлен второй канал назначения: {to_channel_2}")
    else:
        logging.warning("⚠️ Второй канал назначения не указан")
    
    if not to_channels:
        logging.info("⚠️ Не указаны каналы назначения для пересылки")
        return
    
    logging.info(f"🔄 Начинаем пересылку постов из {len(from_channels)} каналов в {len(to_channels)} каналов назначения")
    for i, (channel_type, channel_link) in enumerate(to_channels):
        logging.info(f"  {i+1}. {channel_type}: {channel_link}")
    
    try:
        # Получаем все каналы назначения
        to_entities = {}
        for channel_type, channel_link in to_channels:
            entity = await resolve_channel_link(client, channel_link)
            if not entity:
                logging.error(f"❌ Не удалось получить {channel_type} канал назначения: {channel_link}")
                continue
            to_entities[channel_type] = entity
            logging.info(f"✅ {channel_type.capitalize()} канал назначения найден: {getattr(entity, 'title', 'N/A')}")
        
        if not to_entities:
            logging.error("❌ Не удалось получить ни одного канала назначения")
            return
        
        for from_channel in from_channels:
            try:
                # Получаем канал-источник
                from_entity = await resolve_channel_link(client, from_channel)
                if not from_entity:
                    logging.error(f"❌ Не удалось получить канал-источник: {from_channel}")
                    continue
                logging.info(f"✅ Канал-источник найден: {getattr(from_entity, 'title', 'N/A')}")
                
                # Получаем только последний пост (как в реакциях и избранном)
                messages = await client(GetHistoryRequest(
                    peer=from_entity,
                    limit=1,  # Только последний пост
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))
                
                if not messages.messages:
                    logging.info(f"📭 Нет сообщений в канале {from_channel}")
                    continue
                
                # Берем только последний пост
                latest_message = messages.messages[0]
                logging.info(f"🔍 Найден последний пост {latest_message.id} в канале {from_channel}")
                
                # Пересылаем пост во все каналы назначения
                for channel_type, to_entity in to_entities.items():
                    try:
                        # Проверяем, был ли уже переслан этот пост в данный канал назначения
                        key = (main_account.phone, from_channel, channel_type)
                        current_post_id = latest_message.id
                        
                        if key in last_forwarded and last_forwarded[key] == current_post_id:
                            logging.info(f"🔄 Аккаунт {main_account.phone} уже переслал пост {current_post_id} из {from_channel} в {channel_type} канал - ПРОПУСКАЕМ")
                            continue
                        
                        # Пересылаем пост
                        await client(ForwardMessagesRequest(
                            from_peer=from_entity,
                            id=[latest_message.id],
                            to_peer=to_entity
                        ))
                        
                        # Запоминаем, что пост переслан в данный канал назначения
                        last_forwarded[key] = current_post_id
                        write_last_forwarded(last_forwarded)
                        
                        logging.info(f"✅ Переслан последний пост {latest_message.id} из {from_channel} в {channel_type} канал")
                            
                    except FloodWaitError as e:
                        logging.warning(f"⚠️ FloodWait при пересылке в {channel_type} канал: ждем {e.seconds} сек...")
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        logging.error(f"❌ Ошибка при пересылке поста {latest_message.id} в {channel_type} канал: {e}")
                
                # Небольшая задержка между каналами-источниками
                if from_channel != from_channels[-1]:
                    await asyncio.sleep(random.uniform(2, 5))
                
            except Exception as e:
                logging.error(f"❌ Ошибка обработки канала {from_channel}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"❌ Ошибка в функции пересылки: {e}")

async def forward_posts_from_channels_via_bot(forward_config, config, source_accounts):
    """
    Пересылает последний пост из указанных каналов в каналы назначения через Telegram Bot API
    
    ЛОГИКА:
    1. Аккаунты (с резервированием) получают последний пост и chat_id канала через Telethon
    2. Если первый аккаунт не работает - автоматически берется следующий
    3. Бот пересылает пост используя полученные данные через Bot API
    
    ВАЖНО: Бот должен быть админом в канале назначения
    """
    logging.info(f"🤖 Пересылка через Telegram Bot API (резервирование: {len(source_accounts)} аккаунтов)")
    
    if not forward_config['from_channels']:
        logging.info("⚠️ Не указаны каналы-источники для пересылки")
        return
    
    # Загружаем данные о последних пересланных постах
    last_forwarded = read_last_forwarded()
    logging.info(f"📖 Загружено {len(last_forwarded)} записей о пересланных постах")
    
    # Получаем токен бота
    bot_token = config.get('BOT_TOKEN', '')
    if not bot_token:
        logging.error("❌ Не указан BOT_TOKEN в конфигурации")
        return
    
    from_channels = forward_config['from_channels']
    to_channel = forward_config['to_channel']
    to_channel_2 = forward_config['to_channel_2']
    
    # Формируем список каналов назначения (только непустые)
    to_channels = []
    if to_channel:
        to_channels.append(('основной', to_channel))
        logging.info(f"✅ Добавлен основной канал назначения: {to_channel}")
    else:
        logging.warning("⚠️ Основной канал назначения не указан")
        
    if to_channel_2:
        to_channels.append(('второй', to_channel_2))
        logging.info(f"✅ Добавлен второй канал назначения: {to_channel_2}")
    else:
        logging.warning("⚠️ Второй канал назначения не указан")
    
    if not to_channels:
        logging.info("⚠️ Не указаны каналы назначения для пересылки")
        return
    
    logging.info(f"🔄 Начинаем пересылку постов из {len(from_channels)} каналов в {len(to_channels)} каналов назначения")
    for i, (channel_type, channel_link) in enumerate(to_channels):
        logging.info(f"  {i+1}. {channel_type}: {channel_link}")
    
    try:
        # Преобразуем ссылки в @username для Bot API
        # Можно просто менять здесь SOURCE_CHANNEL и TARGET_CHANNEL:
        
        to_channel_usernames = {}
        for channel_type, channel_link in to_channels:
            # Извлекаем username из ссылки (формат: https://t.me/channel_name)
            if '/' in channel_link:
                channel_username = channel_link.split('/')[-1]
                to_channel_usernames[channel_type] = f"@{channel_username}"  # TARGET_CHANNEL
            elif channel_link.startswith('@'):
                to_channel_usernames[channel_type] = channel_link
            else:
                to_channel_usernames[channel_type] = f"@{channel_link}"
            
            logging.info(f"✅ Целевой канал для бота: {to_channel_usernames[channel_type]}")
        
        # Обрабатываем каждый канал-источник
        for from_channel_link in from_channels:
            try:
                # Извлекаем @username из ссылки канала-источника
                if '/' in from_channel_link:
                    from_username = from_channel_link.split('/')[-1]
                    from_channel_username = f"@{from_username}"  # SOURCE_CHANNEL
                elif from_channel_link.startswith('@'):
                    from_channel_username = from_channel_link
                elif from_channel_link.startswith('-'):
                    # Числовой ID
                    from_channel_username = from_channel_link
                else:
                    from_channel_username = f"@{from_channel_link}"
                
                # ПОЛУЧАЕМ ПОСТ ЧЕРЕЗ АККАУНТЫ (с резервированием)
                latest_message_id = None
                source_chat_id = None
                successful_account = None
                
                # Перебираем аккаунты, пока не найдем рабочий
                for account_index, source_account in enumerate(source_accounts):
                    try:
                        # Проверяем соединение аккаунта
                        if not await ensure_connection(source_account):
                            logging.warning(f"⚠️ Аккаунт {source_account.phone} недоступен, пробуем следующий...")
                            continue
                        
                        logging.info(f"🔍 Попытка #{account_index + 1}/{len(source_accounts)}: получаем пост из {from_channel_username} через {source_account.phone}")
                        
                        client = source_account.client
                        from telethon.tl.functions.channels import JoinChannelRequest
                        
                        # Извлекаем username без @ 
                        username = from_channel_username.lstrip('@')
                        
                        # Получаем entity канала
                        from_entity = await client.get_entity(username)
                        logging.info(f"✅ Канал найден: {getattr(from_entity, 'title', username)}")
                        
                        # Получаем chat_id для Bot API (формат: -100 + channel_id)
                        if hasattr(from_entity, 'id'):
                            source_chat_id = f"-100{from_entity.id}"
                            logging.info(f"📋 Chat ID: {source_chat_id}")
                        
                        # Пытаемся подписаться на канал
                        try:
                            result = await client(JoinChannelRequest(from_entity))
                            logging.info(f"✅ Аккаунт подписался на канал")
                        except Exception as join_err:
                            logging.debug(f"   Уже подписан: {join_err}")
                        
                        # Получаем последний пост
                        messages = await client(GetHistoryRequest(
                            peer=from_entity, 
                            limit=1, 
                            offset_date=None, 
                            offset_id=0, 
                            max_id=0, 
                            min_id=0, 
                            add_offset=0, 
                            hash=0
                        ))
                        
                        if messages.messages:
                            latest_message_id = messages.messages[0].id
                            successful_account = source_account.phone
                            logging.info(f"✅ Последний пост: #{latest_message_id}")
                            logging.info(f"🎯 Успешно получено через аккаунт {successful_account}")
                            save_session(source_account)  # Сохраняем сессию после успешного получения поста
                            break  # Нашли рабочий аккаунт, выходим из цикла
                        else:
                            logging.warning(f"⚠️ В канале нет сообщений (попытка {account_index + 1})")
                            
                    except Exception as telethon_err:
                        logging.error(f"❌ Ошибка с аккаунтом {source_account.phone}: {telethon_err}")
                        if account_index < len(source_accounts) - 1:
                            logging.info(f"🔄 Пробуем следующий аккаунт...")
                        continue
                
                # Если ни один аккаунт не смог получить пост
                if not latest_message_id or not source_chat_id:
                    logging.error(f"❌ НИ ОДИН аккаунт не смог получить данные из {from_channel_username}")
                    logging.error(f"   Проверено аккаунтов: {len(source_accounts)}")
                    continue
                
                # ПЕРЕСЫЛАЕМ ПОСТ ЧЕРЕЗ БОТА (Bot API)
                # Создаем SSL контекст для Bot API
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                async with aiohttp.ClientSession(connector=connector) as session:
                    # Пересылаем пост во все каналы назначения
                    for channel_type, to_username in to_channel_usernames.items():
                        try:
                            # Проверяем дубликаты
                            key = (f"bot_{bot_token[:10]}", from_channel_link, channel_type)
                            
                            if key in last_forwarded and last_forwarded[key] == latest_message_id:
                                logging.info(f"🔄 Бот уже переслал пост #{latest_message_id} - ПРОПУСКАЕМ")
                                continue
                            
                            # ПЕРЕСЫЛАЕМ через Bot API forwardMessage
                            forward_url = f"https://api.telegram.org/bot{bot_token}/forwardMessage"
                            forward_payload = {
                                'chat_id': to_username,
                                'from_chat_id': source_chat_id,  # Используем chat_id от аккаунта
                                'message_id': latest_message_id
                            }
                            
                            logging.info(f"🤖 ПЕРЕСЫЛКА: {source_chat_id} → {to_username}, пост #{latest_message_id}")
                            logging.info(f"   📱 Источник данных: аккаунт {successful_account}")
                            
                            async with session.post(forward_url, json=forward_payload) as forward_response:
                                forward_result = await forward_response.json()
                                
                                if forward_result.get('ok'):
                                    last_forwarded[key] = latest_message_id
                                    write_last_forwarded(last_forwarded)
                                    
                                    new_msg_id = forward_result.get('result', {}).get('message_id', 'N/A')
                                    logging.info(f"✅ УСПЕШНО ПЕРЕСЛАН пост #{latest_message_id} → #{new_msg_id} (через {successful_account})")
                                else:
                                    error_desc = forward_result.get('description', 'Unknown')
                                    logging.error(f"❌ Bot API ошибка: {error_desc}")
                                    logging.error(f"   Бот админ в {to_username}? Права Post Messages?")
                            
                        except Exception as e:
                            logging.error(f"❌ Ошибка пересылки в {channel_type} канал: {e}")
                    
                    # Задержка между каналами
                    if from_channel_link != from_channels[-1]:
                        await asyncio.sleep(random.uniform(2, 5))
                
            except Exception as e:
                logging.error(f"❌ Ошибка обработки канала {from_channel_link}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"❌ Ошибка в функции пересылки через бота: {e}")

async def run_forwarding_cycle(account, forward_config, config):
    """Бесконечный цикл пересылки постов"""
    logging.info(f"🔄 Запуск цикла пересылки для аккаунта {account.phone}")
    
    while True:
        try:
            await forward_posts_from_channels(account, forward_config)
            
            # Получаем интервал из конфигурации
            interval_minutes = config.get('FORWARDING_INTERVAL_MINUTES', 10)
            logging.info(f"⏳ Ожидание {interval_minutes} минут до следующего цикла пересылки...")
            await asyncio.sleep(interval_minutes * 60)
            
        except Exception as e:
            logging.error(f"❌ Ошибка в цикле пересылки: {e}")
            await asyncio.sleep(60)  # Ждем 1 минуту при ошибке

async def run_fast_forwarding_cycle(config):
    """Быстрый цикл пересылки постов с настраиваемым интервалом (в минутах)"""
    if not config.get_bool('ENABLE_FORWARDING', False):
        return
    
    # Получаем интервал проверки из конфигурации (по умолчанию 1 минута)
    forwarding_interval_minutes = config.get_int('FORWARDING_CHECK_INTERVAL_MINUTES', 1)
    forwarding_interval = forwarding_interval_minutes * 60  # Конвертируем минуты в секунды
    logging.info(f"⚡ Запуск быстрого цикла пересылки (проверка каждые {forwarding_interval_minutes} минут)")
    
    # Загружаем аккаунты один раз при старте
    all_accounts = load_accounts()
    if not all_accounts:
        logging.error("❌ Нет аккаунтов для быстрой пересылки")
        return
    
    # Подключаем аккаунты один раз и переиспользуем
    forwarding_account_num = config.get('FORWARDING_ACCOUNT', '0')
    connected_accounts = []
    main_account = None
    
    if forwarding_account_num.lower() == 'bot':
        # Для бота подключаем все аккаунты
        for account in all_accounts:
            if await connect_account(account):
                connected_accounts.append(account)
        if not connected_accounts:
            logging.error("❌ Не удалось подключить аккаунты для быстрой пересылки")
            return
    else:
        # Для обычной пересылки подключаем один аккаунт
        if forwarding_account_num == '0':
            main_account = all_accounts[0] if all_accounts else None
        else:
            try:
                account_index = int(forwarding_account_num) - 1
                main_account = all_accounts[account_index] if 0 <= account_index < len(all_accounts) else None
            except:
                main_account = None
        
        if main_account and await connect_account(main_account):
            logging.info(f"✅ Аккаунт {main_account.phone} подключен для быстрой пересылки")
        else:
            logging.error("❌ Не удалось подключить аккаунт для быстрой пересылки")
            return
    
    forward_config = config.get_forward_config()
    
    while True:
        try:
            if forwarding_account_num.lower() == 'bot':
                # Проверяем соединение для всех аккаунтов
                active_accounts = []
                for account in connected_accounts:
                    if await ensure_connection(account):
                        active_accounts.append(account)
                
                if active_accounts:
                    await forward_posts_from_channels_via_bot(forward_config, config, active_accounts)
            else:
                # Проверяем соединение для основного аккаунта
                if await ensure_connection(main_account):
                    await forward_posts_from_channels(main_account, forward_config)
            
            # Интервал проверки из конфигурации
            await asyncio.sleep(forwarding_interval)
            
        except Exception as e:
            logging.error(f"❌ Ошибка в быстром цикле пересылки: {e}")
            await asyncio.sleep(forwarding_interval)  # Ждем интервал при ошибке

async def check_reaction_exists(client, channel_entity, message_id, account_phone):
    """Проверяет, проставлена ли уже реакция на пост данным аккаунтом"""
    try:
        # Получаем информацию о сообщении с реакциями
        message = await client.get_messages(channel_entity, ids=message_id)
        if not message:
            logging.warning(f"⚠️ Не удалось получить сообщение {message_id}")
            return False
        
        # Получаем текущий ID пользователя
        me = await client.get_me()
        current_user_id = str(me.id)
        account_id = str(account_phone).replace('+', '')
        
        logging.debug(f"🔍 Проверяем реакцию: текущий_пользователь={current_user_id}, аккаунт_телефон={account_id}")
        
        # Проверяем, есть ли реакция от текущего аккаунта
        if hasattr(message, 'reactions') and message.reactions:
            logging.debug(f"🔍 Проверяем {len(message.reactions.results)} реакций на посте {message_id}")
            
            for reaction in message.reactions.results:
                if hasattr(reaction, 'reaction') and hasattr(reaction.reaction, 'emoticon'):
                    # Проверяем, что это реакция от текущего аккаунта
                    if hasattr(reaction, 'peer_id') and reaction.peer_id:
                        # Сравниваем ID аккаунта (приводим к строкам для корректного сравнения)
                        reaction_user_id = str(reaction.peer_id.user_id)
                        emoji = reaction.reaction.emoticon
                        
                        logging.debug(f"🔍 Найдена реакция: user_id='{reaction_user_id}', emoji='{emoji}'")
                        logging.debug(f"🔍 Сравниваем: reaction_user_id='{reaction_user_id}' vs current_user_id='{current_user_id}'")
                        
                        if reaction_user_id == current_user_id:
                            logging.info(f"🔍 Найдена реакция от аккаунта {account_phone} на пост {message_id} с эмодзи {emoji}")
                            return True
        
        if not hasattr(message, 'reactions') or not message.reactions:
            logging.debug(f"🔍 На посте {message_id} нет реакций")
        else:
            logging.debug(f"🔍 На посте {message_id} есть {len(message.reactions.results)} реакций, но не от аккаунта {account_phone}")
            
            # Логируем все найденные реакции для отладки
            for i, reaction in enumerate(message.reactions.results):
                if hasattr(reaction, 'reaction') and hasattr(reaction.reaction, 'emoticon'):
                    if hasattr(reaction, 'peer_id') and reaction.peer_id:
                        reaction_user_id = str(reaction.peer_id.user_id)
                        emoji = reaction.reaction.emoticon
                        logging.debug(f"🔍 Реакция {i+1}: user_id='{reaction_user_id}', emoji='{emoji}'")
        
        logging.info(f"🔍 Реакция от аккаунта {account_phone} на пост {message_id} не найдена")
        
        return False
    except Exception as e:
        logging.warning(f"⚠️ Не удалось проверить реакцию на пост {message_id}: {e}")
        return False



async def add_reactions_to_posts(main_account, reactions_config, config):
    """Добавляет одну случайную реакцию к постам в указанных каналах"""
    if not reactions_config:
        logging.info("⚠️ Конфигурация реакций не настроена")
        return
    
    # Проверяем соединение перед началом работы
    if not await ensure_connection(main_account):
        logging.error(f"❌ Не удалось установить соединение для {main_account.phone}")
        return
    
    client = main_account.client
    
    logging.info(f"😊 Начинаем проставление реакций в {len(reactions_config)} каналах")
    
    for channel_link, emojis in reactions_config.items():
        try:
            # Получаем канал
            channel_entity = await resolve_channel_link(client, channel_link)
            if not channel_entity:
                logging.error(f"❌ Не удалось получить канал: {channel_link}")
                continue
            logging.info(f"✅ Канал найден: {getattr(channel_entity, 'title', 'N/A')}")
            
            # Получаем только последний пост
            messages = await client(GetHistoryRequest(
                peer=channel_entity,
                limit=1,  # Только последний пост
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            if not messages.messages:
                logging.info(f"📭 Нет сообщений в канале {channel_link}")
                continue
            
            # Берем только последний пост
            latest_message = messages.messages[0]
            current_post_id = latest_message.id
            
            # Загружаем информацию о последних реакциях
            last_reacted = read_last_reacted()
            
            # Проверяем, уже ли этот аккаунт поставил реакцию на этот пост
            key = (main_account.phone, channel_link)
            if key in last_reacted and last_reacted[key] == current_post_id:
                logging.info(f"😊 Аккаунт {main_account.phone} уже поставил реакцию на пост {current_post_id} в {channel_link} - ПРОПУСКАЕМ")
                continue
            
            logging.info(f"📝 НОВЫЙ пост {current_post_id} в канале {channel_link} - ставим реакцию")
            
            # Каждый аккаунт ставит реакцию по порядку из списка эмодзи
            if emojis and isinstance(emojis, list) and len(emojis) > 0:
                # Выбираем случайный эмодзи для каждого аккаунта
                selected_emoji = random.choice(emojis)
                
                logging.info(f"🎲 Аккаунт {main_account.phone} случайно выбрал эмодзи: {selected_emoji}")
                
                try:
                    # Отправляем реакцию
                    emoji_string = str(selected_emoji)
                    logging.info(f"🔍 Отправляем эмодзи '{emoji_string}'")
                    
                    reaction_obj = ReactionEmoji(emoticon=emoji_string)
                    
                    await client(SendReactionRequest(
                        peer=channel_entity,
                        msg_id=current_post_id,
                        reaction=[reaction_obj],
                        big=False
                    ))
                    
                    logging.info(f"✅ Реакция {selected_emoji} успешно поставлена на пост {current_post_id}")
                    
                    # Запоминаем, что этот аккаунт поставил реакцию на этот пост
                    last_reacted[key] = current_post_id
                    write_last_reacted(last_reacted)
                    save_session(main_account)  # Сохраняем сессию после успешного действия
                    logging.info(f"💾 Запомнили: аккаунт {main_account.phone} поставил реакцию на пост {current_post_id} в {channel_link}")
                    
                except FloodWaitError as e:
                    logging.warning(f"⚠️ FloodWait при проставлении реакции: ждем {e.seconds} сек...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logging.error(f"❌ Ошибка при проставлении реакции на пост {current_post_id}: {e}")
                    continue
            else:
                logging.error(f"❌ Некорректные эмодзи для канала {channel_link}: {emojis} (тип: {type(emojis)})")
                continue
                    
        except Exception as e:
            logging.error(f"❌ Ошибка обработки канала {channel_link}: {e}")
            continue

async def add_posts_to_favorites(main_account, favorites_config, config):
    """Добавляет посты из указанных каналов в избранное"""
    if not favorites_config:
        logging.info("⚠️ Конфигурация избранного не настроена")
        return
    
    # Проверяем соединение перед началом работы
    if not await ensure_connection(main_account):
        logging.error(f"❌ Не удалось установить соединение для {main_account.phone}")
        return
    
    client = main_account.client
    
    logging.info(f"⭐ Начинаем добавление постов в избранное из {len(favorites_config)} каналов")
    
    # Загружаем информацию о последних добавлениях в избранное
    last_favorited = read_last_favorited()
    
    for channel_link in favorites_config:
        try:
            # Получаем канал
            channel_entity = await resolve_channel_link(client, channel_link)
            if not channel_entity:
                logging.error(f"❌ Не удалось получить канал: {channel_link}")
                continue
            logging.info(f"✅ Канал найден: {getattr(channel_entity, 'title', 'N/A')}")
            
            # Получаем только последний пост
            messages = await client(GetHistoryRequest(
                peer=channel_entity,
                limit=1,  # Только последний пост
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            if not messages.messages:
                logging.info(f"📭 Нет сообщений в канале {channel_link}")
                continue
            
            # Берем только последний пост
            latest_message = messages.messages[0]
            current_post_id = latest_message.id
            
            # Проверяем, уже ли этот аккаунт добавил этот пост в избранное
            key = (main_account.phone, channel_link)
            if key in last_favorited and last_favorited[key] == current_post_id:
                logging.info(f"⭐ Аккаунт {main_account.phone} уже добавил пост {current_post_id} в избранное из {channel_link} - ПРОПУСКАЕМ")
                continue
            
            logging.info(f"⭐ НОВЫЙ пост {current_post_id} в канале {channel_link} - добавляем в избранное")
            
            try:
                # Всегда пересылаем весь пост (текст + медиа) в избранное
                await client(ForwardMessagesRequest(
                    from_peer=channel_entity,
                    id=[latest_message.id],
                    to_peer='me'  # Saved Messages
                ))
                logging.info(f"⭐ Сохранен пост {current_post_id} в избранное")
                
                # Запоминаем, что этот аккаунт добавил этот пост в избранное
                last_favorited[key] = current_post_id
                write_last_favorited(last_favorited)
                save_session(main_account)  # Сохраняем сессию после успешного действия
                logging.info(f"💾 Запомнили: аккаунт {main_account.phone} добавил пост {current_post_id} в избранное из {channel_link}")
                
            except FloodWaitError as e:
                logging.warning(f"⚠️ FloodWait при сохранении в избранное: ждем {e.seconds} сек...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logging.error(f"❌ Ошибка при сохранении поста {current_post_id} в избранное: {e}")
                continue
                    
        except Exception as e:
            logging.error(f"❌ Ошибка обработки канала {channel_link}: {e}")
            continue

async def run_bot_cycle(config):
    """Выполняет один цикл работы бота"""
    logging.info("=== НАЧАЛО РАБОТЫ БОТА: ПЕРВЫЙ ЦИКЛ (РЕАКЦИИ + ИЗБРАННОЕ) + ВТОРОЙ ЦИКЛ (КОММЕНТИРОВАНИЕ) ===")
    
    try:
        # Загружаем ВСЕ аккаунты из accounts.csv
        all_accounts = load_accounts()
        if not all_accounts:
            logging.error("❌ Не найдено ни одного аккаунта в accounts.csv")
            return False
            
        logging.info(f"📱 Загружено {len(all_accounts)} аккаунтов из accounts.csv")
        for i, account in enumerate(all_accounts, 1):
            logging.info(f"  {i}. {account.phone}")
        
        # ПОДКЛЮЧАЕМ ВСЕ АККАУНТЫ СРАЗУ
        logging.info("🔌 Подключение всех аккаунтов...")
        connected_accounts = []
        
        for i, account in enumerate(all_accounts, 1):
            try:
                logging.info(f"🔌 Подключение аккаунта {i} ({account.phone})...")
                if await connect_account(account):
                    connected_accounts.append(account)
                    logging.info(f"✅ Аккаунт {i} ({account.phone}) успешно подключен")
                else:
                    logging.warning(f"⚠️ Аккаунт {i} ({account.phone}) не удалось подключить")
            except Exception as e:
                logging.error(f"❌ Ошибка подключения аккаунта {i} ({account.phone}): {str(e)}")
                continue
        
        if not connected_accounts:
            logging.error("❌ Не удалось подключить ни одного аккаунта!")
            return False
        
        logging.info(f"✅ Успешно подключено {len(connected_accounts)} из {len(all_accounts)} аккаунтов")
        
        # Загружаем и выбираем каналы
        all_channels = await load_channels()
        if not all_channels:
            return False
            
        logging.info(f"📺 Доступные каналы:")
        for i, channel in enumerate(all_channels, 1):
            logging.info(f"  {i}. {channel}")
            
        # Выбираем каналы из конфигурации
        selected_channels_str = config.get('SELECTED_CHANNELS', '0')
        if selected_channels_str == '0':
            selected_channels = all_channels
        else:
            try:
                selected_indices = [int(x.strip()) - 1 for x in selected_channels_str.split(",")]
                if any(i < 0 or i >= len(all_channels) for i in selected_indices):
                    logging.error(f"❌ Номера каналов должны быть от 1 до {len(all_channels)}")
                    return False
                selected_channels = [all_channels[i] for i in selected_indices]
            except ValueError:
                logging.error("❌ Ошибка в настройке SELECTED_CHANNELS")
                return False
                
        logging.info(f"✅ Выбрано каналов: {len(selected_channels)}")
        
        # Получаем настройки из конфигурации
        min_delay, max_delay = config.get_range('COMMENT_DELAY', 15, 30)
        min_account_delay, max_account_delay = config.get_range('ACCOUNT_DELAY', 60, 120)
        min_comments, max_comments = config.get_range('COMMENTS_COUNT', 1, 5)
        general_reply_prob = config.get_int('GENERAL_REPLY_PROBABILITY', 50)
        sticker_prob = config.get_int('STICKER_PROBABILITY', 10)
        personality_mode = "auto" if config.get_int('PERSONALITY_MODE', 1) == 1 else "random"
        check_spam = config.get_bool('CHECK_SPAM_STATUS', True)
        
        logging.info("⚙️ Настройки из конфигурации:")
        logging.info(f"  - Задержка между комментариями: {min_delay}-{max_delay} сек")
        logging.info(f"  - Задержка между аккаунтами: {min_account_delay}-{max_account_delay} сек")
        logging.info(f"  - Количество комментариев: {min_comments}-{max_comments}")
        logging.info(f"  - Вероятность обобщённых слов: {general_reply_prob}%")
        logging.info(f"  - Вероятность стикеров: {sticker_prob}%")
        logging.info(f"  - Режим психотипа: {personality_mode}")
        logging.info(f"  - Проверка спама: {'Да' if check_spam else 'Нет'}")
        
        # Логируем статус новых функций
        enable_forwarding = config.get_bool('ENABLE_FORWARDING', False)
        enable_reactions = config.get_bool('ENABLE_REACTIONS', False)
        enable_favorites = config.get_bool('ENABLE_FAVORITES', False)
        
        logging.info("🚀 Статус новых функций:")
        logging.info(f"  - Пересылка постов: {'Включена' if enable_forwarding else 'Отключена'}")
        logging.info(f"  - Проставление реакций: {'Включена' if enable_reactions else 'Отключена'}")
        logging.info(f"  - Добавление в избранное: {'Включено' if enable_favorites else 'Отключено'}")
        
        if enable_forwarding:
            forward_config = config.get_forward_config()
            logging.info(f"  Пересылка: {len(forward_config['from_channels'])} источников → {forward_config['to_channel']}")
        
        if enable_reactions:
            reactions_config = config.get_reactions_config()
            logging.info(f"  Реакции: {len(reactions_config)} каналов с эмодзи")
        
        if enable_favorites:
            favorites_config = config.get_favorites_config()
            logging.info(f"  Избранное: {len(favorites_config)} каналов")
        
        # ПЕРВЫЙ ЦИКЛ: Пересылка, Реакции и Избранное
        logging.info("=== ПЕРВЫЙ ЦИКЛ: Пересылка + Реакции + Избранное ===")
        
        # Пересылка постов (если включена)
        if config.get_bool('ENABLE_FORWARDING', False):
            logging.info("=== Пересылка постов ===")
            forward_config = config.get_forward_config()
            
            # Получаем номер аккаунта для пересылки
            forwarding_account_num = config.get('FORWARDING_ACCOUNT', '0')
            if forwarding_account_num.lower() == 'bot':
                # Используем бота для пересылки (аккаунты для получения постов с резервированием)
                if connected_accounts:
                    logging.info(f"🤖 Пересылка через бота с резервированием ({len(connected_accounts)} аккаунтов доступно)")
                    await forward_posts_from_channels_via_bot(forward_config, config, connected_accounts)
                else:
                    logging.error("❌ Нет подключенных аккаунтов для получения постов")
            elif forwarding_account_num == '0':
                # Используем первый подключенный аккаунт
                forwarding_accounts = [connected_accounts[0]] if connected_accounts else []
                logging.info(f"🔄 Пересылка с первого подключенного аккаунта {connected_accounts[0].phone if connected_accounts else 'N/A'}")
            else:
                # Используем конкретный аккаунт из подключенных
                try:
                    account_index = int(forwarding_account_num) - 1  # Вычитаем 1, так как пользователи указывают с 1
                    if 0 <= account_index < len(connected_accounts):
                        forwarding_accounts = [connected_accounts[account_index]]
                        logging.info(f"🔄 Пересылка с выбранного аккаунта {connected_accounts[account_index].phone} (номер {forwarding_account_num})")
                    else:
                        logging.error(f"❌ Номер аккаунта {forwarding_account_num} не найден в подключенных. Доступно: 1-{len(connected_accounts)}")
                        forwarding_accounts = []
                except ValueError:
                    logging.error(f"❌ Некорректный номер аккаунта для пересылки: {forwarding_account_num}")
                    forwarding_accounts = []
            
            # Проверяем, не был ли уже выполнен пересылка через бота
            if forwarding_account_num.lower() != 'bot':
                if forwarding_accounts:
                    for account in forwarding_accounts:
                        logging.info(f"🔄 Пересылка с аккаунта {account.phone}")
                        logging.info(f"🔍 Отладка: аккаунт подключен: {account.client.is_connected()}")
                        await forward_posts_from_channels(account, forward_config)
                        # Небольшая задержка между аккаунтами
                        if account != forwarding_accounts[-1]:
                            await asyncio.sleep(random.uniform(2, 5))
                else:
                    logging.warning("⚠️ Нет доступных аккаунтов для пересылки")
        else:
            logging.info("⚠️ Пересылка отключена в конфигурации (ENABLE_FORWARDING=False)")
        
        # Проставление реакций (ВТОРАЯ функция)
        if config.get_bool('ENABLE_REACTIONS', False):
            logging.info("=== ПЕРВЫЙ ЦИКЛ: Проставление реакций ===")
            reactions_config = config.get_reactions_config()
            logging.info(f"🔍 Отладка: reactions_config = {reactions_config}")
            
            # ВЫБИРАЕМ АККАУНТЫ ДЛЯ РЕАКЦИЙ ИЗ ПОДКЛЮЧЕННЫХ
            reactions_account_indices = config.get_reactions_selected_accounts()
            if reactions_account_indices:
                # Используем выбранные аккаунты для реакций (индексы из accounts.csv)
                reactions_accounts = []
                for i in reactions_account_indices:
                    if 0 <= i < len(connected_accounts):
                        reactions_accounts.append(connected_accounts[i])
                    else:
                        logging.warning(f"⚠️ Аккаунт с индексом {i+1} не найден в подключенных")
                
                logging.info(f"😊 Проставление реакций с {len(reactions_accounts)} выбранных аккаунтов")
            else:
                # Используем все подключенные аккаунты
                reactions_accounts = connected_accounts
                logging.info(f"😊 Проставление реакций с {len(reactions_accounts)} всех подключенных аккаунтов")
            
            if reactions_accounts:
                # Показываем план реакций для каждого аккаунта
                emojis = list(reactions_config.values())[0] if reactions_config else []
                if emojis:
                    logging.info("📋 План реакций по аккаунтам:")
                    for i, account in enumerate(reactions_accounts):
                        emoji = emojis[i % len(emojis)]
                        logging.info(f"  Аккаунт {i+1} ({account.phone}): {emoji}")
                
                # Получаем задержку между аккаунтами для реакций
                min_delay, max_delay = config.get_reactions_account_delay()
                logging.info(f"⏱️ Задержка между аккаунтами для реакций: {min_delay}-{max_delay} сек")
                
                for account in reactions_accounts:
                    logging.info(f"😊 Проставление реакций с аккаунта {account.phone}")
                    await add_reactions_to_posts(account, reactions_config, config)
                    # Задержка между аккаунтами из конфига
                    if account != reactions_accounts[-1]:
                        delay = random.uniform(min_delay, max_delay)
                        logging.info(f"⏱️ Ожидание {delay:.1f} сек перед следующим аккаунтом")
                        await asyncio.sleep(delay)
            else:
                logging.warning("⚠️ Нет доступных аккаунтов для реакций")
        else:
            logging.warning("⚠️ Реакции отключены в конфигурации (ENABLE_REACTIONS=False)")
        
        # Добавление в избранное (ВТОРАЯ функция)
        if config.get_bool('ENABLE_FAVORITES', False):
            logging.info("=== ПЕРВЫЙ ЦИКЛ: Добавление в избранное ===")
            favorites_config = config.get_favorites_config()
            logging.info(f"🔍 Отладка: favorites_config = {favorites_config}")
            
            # ВЫБИРАЕМ АККАУНТЫ ДЛЯ ИЗБРАННОГО ИЗ ПОДКЛЮЧЕННЫХ
            favorites_account_indices = config.get_favorites_selected_accounts()
            if favorites_account_indices:
                # Используем выбранные аккаунты для избранного (индексы из accounts.csv)
                favorites_accounts = []
                for i in favorites_account_indices:
                    if 0 <= i < len(connected_accounts):
                        favorites_accounts.append(connected_accounts[i])
                    else:
                        logging.warning(f"⚠️ Аккаунт с индексом {i+1} не найден в подключенных")
                
                logging.info(f"⭐ Добавление в избранное с {len(favorites_accounts)} выбранных аккаунтов")
            else:
                # Используем все подключенные аккаунты
                favorites_accounts = connected_accounts
                logging.info(f"⭐ Добавление в избранное с {len(favorites_accounts)} всех подключенных аккаунтов")
            
            if favorites_accounts:
                # Получаем задержку между аккаунтами для избранного
                min_delay, max_delay = config.get_favorites_account_delay()
                logging.info(f"⏱️ Задержка между аккаунтами для избранного: {min_delay}-{max_delay} сек")
                
                for account in favorites_accounts:
                    logging.info(f"⭐ Добавление в избранное с аккаунта {account.phone}")
                    await add_posts_to_favorites(account, favorites_config, config)
                    # Задержка между аккаунтами из конфига
                    if account != favorites_accounts[-1]:
                        delay = random.uniform(min_delay, max_delay)
                        logging.info(f"⏱️ Ожидание {delay:.1f} сек перед следующим аккаунтом")
                        await asyncio.sleep(delay)
            else:
                logging.warning("⚠️ Нет доступных аккаунтов для избранного")
        else:
            logging.warning("⚠️ Избранное отключено в конфигурации (ENABLE_FAVORITES=False)")
        
        # ВТОРОЙ ЦИКЛ: Комментирование постов в каналах
        logging.info("=== ВТОРОЙ ЦИКЛ: Комментирование постов в каналах ===")
        
        # ВЫБИРАЕМ АККАУНТЫ ДЛЯ КОММЕНТИРОВАНИЯ ИЗ ПОДКЛЮЧЕННЫХ
        selected_accounts_str = config.get('SELECTED_ACCOUNTS', '0')
        if selected_accounts_str == '0':
            # Используем все подключенные аккаунты
            commenting_accounts = connected_accounts
            logging.info(f"💬 Комментирование с {len(commenting_accounts)} всех подключенных аккаунтов")
        else:
            try:
                # Выбираем конкретные аккаунты (индексы из accounts.csv)
                selected_indices = [int(x.strip()) - 1 for x in selected_accounts_str.split(",")]
                commenting_accounts = []
                for i in selected_indices:
                    if 0 <= i < len(connected_accounts):
                        commenting_accounts.append(connected_accounts[i])
                    else:
                        logging.warning(f"⚠️ Аккаунт с индексом {i+1} не найден в подключенных")
                
                logging.info(f"💬 Комментирование с {len(commenting_accounts)} выбранных аккаунтов")
            except ValueError:
                logging.error("❌ Ошибка в настройке SELECTED_ACCOUNTS")
                commenting_accounts = connected_accounts
        
        if commenting_accounts:
            for i, account in enumerate(commenting_accounts):
                logging.info(f"[{account.phone}] Заходим и комментируем...")
                await comment_on_channels(
                    account, selected_channels, min_delay, max_delay, 
                    min_comments, max_comments, general_reply_prob, sticker_prob, personality_mode
                )
                
                # Задержка между аккаунтами (кроме последнего)
                if i < len(commenting_accounts) - 1:
                    account_delay = random.uniform(min_account_delay, max_account_delay)
                    logging.info(f"⏳ Задержка между аккаунтами: {account_delay:.1f} секунд...")
                    await asyncio.sleep(account_delay)
        else:
            logging.warning("⚠️ Нет доступных аккаунтов для комментирования")
        
        logging.info("=== ВТОРОЙ ЦИКЛ РАБОТЫ БОТА (КОММЕНТИРОВАНИЕ) ЗАВЕРШЕН ===")
        logging.info("=== ПОЛНЫЙ ЦИКЛ РАБОТЫ БОТА ЗАВЕРШЕН: Реакции + Избранное + Комментирование ===")
        return True
        
    except Exception as e:
        logging.error(f"Произошла ошибка в цикле: {str(e)}")
        return False
    finally:
        # Отключаем все аккаунты
        for account in connected_accounts:
            try:
                await account.client.disconnect()
            except:
                pass








async def main():
    """Главная функция"""
    print("🚀 Запуск серверной версии Telegram бота...")
    
    # Загружаем конфигурацию
    config = Config()
    
    # Настраиваем логирование
    setup_logging(config)
    
    logging.info("=== СЕРВЕРНАЯ ВЕРСИЯ TELEGRAM БОТА ===")
    logging.info(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Проверяем серверные настройки
    run_infinite = config.get_bool('RUN_INFINITE_LOOP', True)
    cycle_interval = config.get_int('CYCLE_INTERVAL_MINUTES', 60)
    max_cycles = config.get_int('MAX_CYCLES', 0)
    
    logging.info(f"Режим работы: {'Бесконечный цикл' if run_infinite else 'Один цикл'}")
    if run_infinite:
        logging.info(f"Интервал между циклами: {cycle_interval} минут")
        if max_cycles > 0:
            logging.info(f"Максимальное количество циклов: {max_cycles}")
        else:
            logging.info("Максимальное количество циклов: неограниченно")
    
    try:
        # Запускаем быстрый цикл пересылки параллельно (если включена пересылка)
        forwarding_task = None
        if config.get_bool('ENABLE_FORWARDING', False):
            forwarding_task = asyncio.create_task(run_fast_forwarding_cycle(config))
            logging.info("⚡ Быстрый цикл пересылки запущен параллельно")
        
        if run_infinite:
            cycle_count = 0
            
            while True:
                cycle_count += 1
                current_time = time.time()
                logging.info(f"\n=== ЦИКЛ #{cycle_count} ===")
                
                # Выполняем основной цикл
                success = await run_bot_cycle(config)
                
                if not success:
                    logging.error("❌ Основной цикл завершился с ошибкой")
                
                # Проверяем лимит циклов
                if max_cycles > 0 and cycle_count >= max_cycles:
                    logging.info(f"✅ Достигнут лимит циклов ({max_cycles}). Завершение работы.")
                    break
                
                # Ждем перед следующим циклом
                logging.info(f"⏳ Ожидание {cycle_interval} минут перед следующим циклом...")
                await asyncio.sleep(cycle_interval * 60)
        else:
            # Один цикл
            success = await run_bot_cycle(config)
            if success:
                logging.info("✅ Работа завершена успешно")
            else:
                logging.error("❌ Работа завершена с ошибкой")
        
        # Отменяем задачу пересылки при завершении
        if forwarding_task:
            forwarding_task.cancel()
            try:
                await forwarding_task
            except asyncio.CancelledError:
                pass
                
    except KeyboardInterrupt:
        logging.info("⚠️ Получен сигнал прерывания. Завершение работы...")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {str(e)}")
    finally:
        logging.info("=== ЗАВЕРШЕНИЕ РАБОТЫ БОТА ===")

if __name__ == '__main__':
    asyncio.run(main()) 