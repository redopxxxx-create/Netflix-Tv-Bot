import os
import json
import re
import urllib.parse
import requests
import asyncio
import random
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait, MessageDeleteForbidden, UserNotParticipant, UsernameNotOccupied, ChatAdminRequired, UserIsBlocked, PeerIdInvalid, InputUserDeactivated
import logging
from config import API_ID, API_HASH, BOT_TOKEN, ADMINS, MAX_THREADS, MONGO_URI, DB_NAME, FORCE_SUB_CHANNEL, FORCE_SUB_TEXT, LOG_CHANNEL, PICS
import time
import traceback
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

# Fallback for translate_country_code if the custom module is missing
try:
    from code import translate_country_code
except ImportError:
    def translate_country_code(code):
        return code if code else "Unknown"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

class Database:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.users = self.db.users
        self.admin_cookies = self.db.admin_cookies
        self.stats = self.db.stats

    async def get_user_cookies(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("cookies", []) if user else []

    async def save_user_cookies(self, user_id, cookies):
        await self.users.update_one(
            {"_id": user_id},
            {"$set": {"cookies": cookies}},
            upsert=True
        )

    async def get_all_users(self):
        cursor = self.users.find({}, {"_id": 1})
        return [doc["_id"] async for doc in cursor]

    async def delete_user(self, user_id):
        await self.users.delete_one({"_id": user_id})

    async def get_admin_cookies(self):
        doc = await self.admin_cookies.find_one({"_id": "admin_cookies"})
        return doc.get("cookies", []) if doc else []

    async def save_admin_cookies(self, cookies):
        await self.admin_cookies.update_one(
            {"_id": "admin_cookies"},
            {"$set": {"cookies": cookies}},
            upsert=True
        )

    async def update_login_stats(self, successful=True):
        await self.stats.update_one(
            {"_id": "login_stats"},
            {
                "$inc": {
                    "total_attempts": 1,
                    "successful" if successful else "failed": 1
                }
            },
            upsert=True
        )

    async def get_login_stats(self):
        stats = await self.stats.find_one({"_id": "login_stats"})
        if stats:
            return {
                "successful": stats.get("successful", 0),
                "failed": stats.get("failed", 0),
                "total_attempts": stats.get("total_attempts", 0)
            }
        return {"successful": 0, "failed": 0, "total_attempts": 0}

    async def reset_login_stats(self):
        await self.stats.update_one(
            {"_id": "login_stats"},
            {"$set": {"successful": 0, "failed": 0, "total_attempts": 0}},
            upsert=True
        )

db = Database(MONGO_URI, DB_NAME)
app = Client("netflix_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# -------------------- Safe message helpers (with retry limit) --------------------
MAX_RETRIES = 5

async def safe_edit_message(message, text, reply_markup=None, parse_mode=None, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            if parse_mode is not None:
                return await message.edit_text(
                    text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs
                )
            else:
                return await message.edit_text(text, reply_markup=reply_markup, **kwargs)
        except FloodWait as e:
            logger.warning(f"Flood wait in edit_message: {e.value} seconds")
            await asyncio.sleep(e.value)
        except MessageNotModified:
            return message
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_send_message(client, chat_id, text, reply_markup=None, parse_mode=None, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            if parse_mode is not None:
                return await client.send_message(
                    chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs
                )
            else:
                return await client.send_message(chat_id, text, reply_markup=reply_markup, **kwargs)
        except FloodWait as e:
            logger.warning(f"Flood wait in send_message: {e.value} seconds")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_reply_message(message, text, reply_markup=None, parse_mode=None, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            if parse_mode is not None:
                return await message.reply_text(
                    text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs
                )
            else:
                return await message.reply_text(text, reply_markup=reply_markup, **kwargs)
        except FloodWait as e:
            logger.warning(f"Flood wait in reply_message: {e.value} seconds")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error replying to message: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_reply_photo(message, photo, caption=None, reply_markup=None, parse_mode=None, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            if parse_mode is not None:
                return await message.reply_photo(
                    photo=photo, caption=caption, parse_mode=parse_mode,
                    reply_markup=reply_markup, **kwargs
                )
            else:
                return await message.reply_photo(
                    photo=photo, caption=caption, reply_markup=reply_markup, **kwargs
                )
        except FloodWait as e:
            logger.warning(f"Flood wait in reply_photo: {e.value} seconds")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error replying with photo: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_delete_message(message):
    for attempt in range(MAX_RETRIES):
        try:
            return await message.delete()
        except FloodWait as e:
            logger.warning(f"Flood wait in delete_message: {e.value} seconds")
            await asyncio.sleep(e.value)
        except MessageDeleteForbidden:
            return None
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_edit_message_media(message, media, reply_markup=None, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await message.edit_media(media=media, reply_markup=reply_markup, **kwargs)
        except FloodWait as e:
            logger.warning(f"Flood wait in edit_message_media: {e.value} seconds")
            await asyncio.sleep(e.value)
        except MessageNotModified:
            return message
        except Exception as e:
            logger.error(f"Error editing message media: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

async def safe_answer_callback(callback_query, text=None, show_alert=False, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await callback_query.answer(text=text, show_alert=show_alert, **kwargs)
        except FloodWait as e:
            logger.warning(f"Flood wait in answer_callback: {e.value} seconds")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error answering callback: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(1)
    return None

# -------------------- Force Subscribe --------------------
class FSBConfig:
    def __init__(self):
        self.FSB = []
        self.load_fsb_vars()

    def load_fsb_vars(self):
        channel = FORCE_SUB_CHANNEL
        try:
            if "," in FORCE_SUB_CHANNEL:
                for channel_line in channel.split(","):
                    parts = channel_line.strip().split(":")
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        link_or_id = parts[1].strip()
                        if len(parts) >= 3:
                            custom_link = parts[2].strip()
                            self.FSB.append((name, link_or_id, custom_link))
                        else:
                            self.FSB.append((name, link_or_id))
            else:
                parts = channel.split(":")
                if len(parts) >= 2:
                    name = parts[0].strip()
                    link_or_id = parts[1].strip()
                    if len(parts) >= 3:
                        custom_link = parts[2].strip()
                        self.FSB.append((name, link_or_id, custom_link))
                    else:
                        self.FSB.append((name, link_or_id))
        except Exception as e:
            logger.error(f"FORCE_SUB_CHANNEL is not set correctly! Error: {e}")
            sys.exit(1)

app.fsb_config = FSBConfig()
app.user_data = {}
app.tv_login_data = {}
app.pending_cookies = {}
app.tv_accounts = {}
app.poor_user_data = {}
app.user_login_state = {}
app.message_ids = {}
app.admin_data = {}
app.pending_admin_cookies = {}

def split_list(lst):
    return [lst[i:i+2] for i in range(0, len(lst), 2)]

async def check_fsb(client, user_id):
    if not client.fsb_config.FSB:
        return [], []
    channel_button = []
    for idx, channel_info in enumerate(client.fsb_config.FSB):
        try:
            channel_name = channel_info[0]
            channel = channel_info[1]
            try:
                channel_id = int(channel)
            except:
                channel_id = channel
            await client.get_chat_member(channel_id, user_id)
        except UserNotParticipant:
            if len(channel_info) > 2:
                channel_link = channel_info[2]
            else:
                try:
                    if isinstance(channel_id, int):
                        chat = await client.get_chat(channel_id)
                        if chat.username:
                            channel_link = f"https://t.me/{chat.username}"
                        else:
                            channel_link = await client.export_chat_invite_link(channel_id)
                    else:
                        channel_link = f"https://t.me/{channel_id}"
                except Exception as e:
                    logger.error(f"Error creating invite link for {channel}: {e}")
                    channel_link = f"https://t.me/{channel_id}"
            channel_button.append(InlineKeyboardButton(channel_name, url=channel_link))
        except (UsernameNotOccupied, ChatAdminRequired) as e:
            await safe_send_message(client, LOG_CHANNEL, f"Channel issue: {channel} - {type(e).__name__}")
        except Exception as e:
            await safe_send_message(client, LOG_CHANNEL, f"Force Subscribe error: {e} at {channel}")
    return channel_button, []   # change_data never used

async def force_sub_check(client, message):
    user_id = message.from_user.id
    if user_id in ADMINS:
        return True
    channel_button, _ = await check_fsb(client, user_id)
    if not channel_button:
        return True
    channel_button = split_list(channel_button)
    channel_button.append([InlineKeyboardButton("🔄 REFRESH", callback_data="refresh")])
    photo = random.choice(PICS) if PICS else None
    await safe_reply_photo(
        message,
        photo=photo,
        caption=FORCE_SUB_TEXT,
        reply_markup=InlineKeyboardMarkup(channel_button),
        quote=True
    )
    return False

# -------------------- Cookie extraction helpers --------------------
def unescape_plan(text):
    try:
        if not isinstance(text, str):
            return str(text)
        replacements = {
            '\\x20': ' ', '\\x28': '(', '\\x29': ')', '\\u0020': ' ',
            '\\x2B': '+', '\\x40': '@', '\\x2F': '/', '\\x2D': '-'
        }
        for escaped, char in replacements.items():
            text = text.replace(escaped, char)
        return text
    except Exception as e:
        logger.error(f"Error in unescape_plan: {e}")
        return str(text)

def extract_netflix_id(content):
    # same as original, kept for brevity
    try:
        if not isinstance(content, str):
            content = str(content)
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for cookie in data:
                    if cookie.get("name") == "NetflixId" and cookie.get("name") != "SecureNetflixId":
                        return cookie.get("value")
            elif isinstance(data, dict):
                if "NetflixId" in data and "SecureNetflixId" not in data:
                    return data["NetflixId"]
                elif "cookies" in data:
                    for cookie in data["cookies"]:
                        if cookie.get("name") == "NetflixId" and cookie.get("name") != "SecureNetflixId":
                            return cookie.get("value")
        except:
            pass
        txt_format = re.findall(r'NetflixId=([^\s\n]+)', content)
        if txt_format:
            return txt_format[0] if txt_format else None
        new_format_match = re.search(r'Cookies\s*=\s*NetflixId=([^\s|]+)', content)
        if new_format_match:
            netflix_id = new_format_match.group(1)
            if '%' in netflix_id:
                try:
                    netflix_id = urllib.parse.unquote(netflix_id)
                except:
                    pass
            return netflix_id
        netflix_id_match = re.search(r'(?<!\wSecure)NetflixId=([^;,\s]+)', content)
        if netflix_id_match:
            netflix_id = netflix_id_match.group(1)
            if '%' in netflix_id:
                try:
                    netflix_id = urllib.parse.unquote(netflix_id)
                except:
                    pass
            return netflix_id
        netflix_id_alt_match = re.search(r'(?<!\bSecure)NetflixId=([^;,\s]+)', content)
        if netflix_id_alt_match:
            netflix_id = netflix_id_alt_match.group(1)
            if '%' in netflix_id:
                try:
                    netflix_id = urllib.parse.unquote(netflix_id)
                except:
                    pass
            return netflix_id
        netscape_match = re.search(r'\.netflix\.com\s+TRUE\s+/\s+TRUE\s+\d+\s+NetflixId\s+([^\s]+)', content)
        if netscape_match:
            netflix_id = netscape_match.group(1)
            if '%' in netflix_id:
                try:
                    netflix_id = urllib.parse.unquote(netflix_id)
                except:
                    pass
            return netflix_id
        plain_match = re.search(r'(?<!\bSecure)NetflixId[=:\s]+([^\s;,\n]+)', content, re.IGNORECASE)
        if plain_match:
            netflix_id = plain_match.group(1)
            if '%' in netflix_id:
                try:
                    netflix_id = urllib.parse.unquote(netflix_id)
                except:
                    pass
            return netflix_id
        return None
    except Exception as e:
        logger.error(f"Error in extract_netflix_id: {e}")
        return None

def extract_multiple_netflix_ids(content):
    # simplified version of the original
    try:
        if not isinstance(content, str):
            content = str(content)
        netflix_ids = []
        txt_matches = re.findall(r'NetflixId=([^\s\n]+)', content)
        for match in txt_matches:
            try:
                netflix_id = match
                if '%' in netflix_id:
                    netflix_id = urllib.parse.unquote(netflix_id)
                if netflix_id and netflix_id not in netflix_ids:
                    netflix_ids.append(netflix_id)
            except:
                continue
        if netflix_ids:
            return netflix_ids
        patterns = [
            r'Cookies\s*=\s*NetflixId=([^\s|]+)',
            r'(?<!\wSecure)NetflixId=([^;,\s\n]+)',
            r'\.netflix\.com\s+TRUE\s+/\s+TRUE\s+\d+\s+NetflixId\s+([^\s\n]+)',
            r'(?<!\bSecure)NetflixId[=:\s]+([^\s;,\n]+)'
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                netflix_id = match
                if '%' in netflix_id:
                    netflix_id = urllib.parse.unquote(netflix_id)
                if netflix_id and "SecureNetflixId" not in pattern and netflix_id not in netflix_ids:
                    netflix_ids.append(netflix_id)
        filtered = [nid for nid in netflix_ids if "SecureNetflixId" not in content]
        return filtered
    except Exception as e:
        logger.error(f"Error in extract_multiple_netflix_ids: {e}")
        return []

# Synchronous version (removed async)
def extract_profiles_from_manage_profiles(response_text):
    try:
        profiles = []
        try:
            profiles_match = re.search(r'"profiles"\s*:\s*({[^}]+})', response_text)
            if profiles_match:
                profiles_json_str = profiles_match.group(1)
                def unescape_hex(match):
                    try:
                        hex_code = match.group(1)
                        return chr(int(hex_code, 16))
                    except:
                        return match.group(0)
                cleaned_json = re.sub(r'\\x([0-9a-fA-F]{2})', unescape_hex, profiles_json_str)
                profiles_data = json.loads(f'{{{cleaned_json}}}')
                for profile_id, profile_data in profiles_data.items():
                    if isinstance(profile_data, dict):
                        summary = profile_data.get('summary', {})
                        if isinstance(summary, dict):
                            value = summary.get('value', {})
                            if isinstance(value, dict):
                                profile_name = value.get('profileName')
                                if profile_name:
                                    profiles.append(profile_name)
        except json.JSONDecodeError:
            profile_matches = re.findall(r'"profileName"\s*:\s*"([^"]+)"', response_text)
            for profile in profile_matches:
                profile = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), profile)
                profiles.append(profile)
        return profiles
    except Exception as e:
        logger.error(f"Error extracting profiles: {e}")
        return []

def check_cookie_sync(cookie_dict):
    # Synchronous cookie checker – used inside threads
    try:
        if not isinstance(cookie_dict, dict):
            return {'ok': False, 'err': 'Invalid cookie format', 'cookie': cookie_dict}
        session = requests.Session()
        session.cookies.update(cookie_dict)
        url = 'https://www.netflix.com/YourAccount'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0'}
        try:
            resp = session.get(url, headers=headers, timeout=25)
            txt = resp.text
        except requests.exceptions.Timeout:
            return {'ok': False, 'err': 'Request timeout', 'cookie': cookie_dict}
        except requests.exceptions.ConnectionError:
            return {'ok': False, 'err': 'Connection error', 'cookie': cookie_dict}
        except Exception as e:
            return {'ok': False, 'err': f'Request error: {str(e)}', 'cookie': cookie_dict}

        if '"mode":"login"' in txt:
            return {'ok': False, 'err': 'Invalid cookie (login page detected)', 'cookie': cookie_dict}
        if '"mode":"yourAccount"' not in txt:
            return {'ok': False, 'err': 'Invalid cookie (not logged in)', 'cookie': cookie_dict}

        def find(pattern):
            try:
                m = re.search(pattern, txt)
                return m.group(1) if m else None
            except:
                return None
        def find_list(pattern):
            try:
                return re.findall(pattern, txt)
            except:
                return []

        name = find(r'"userInfo":\{"data":\{"name":"([^"]+)"')
        if name:
            name = name.replace("\\x20", " ")
        else:
            name = "Unknown"
        country_code = find(r'"currentCountry":"([^"]+)"') or find(r'"countryCode":"([^"]+)"')
        country = translate_country_code(country_code) if country_code else "Unknown"
        plan = find(r'localizedPlanName.{1,50}?value":"([^"]+)"')
        if not plan:
            plan = find(r'"planName"\s*:\s*"([^"]+)"')
        if plan:
            plan = unescape_plan(plan)
        else:
            plan = "Unknown"
        plan_price = find(r'"planPrice":\{"fieldType":"String","value":"([^"]+)"')
        if plan_price:
            plan_price = unescape_plan(plan_price)
        else:
            plan_price = "Unknown"
        member_since = find(r'"memberSince":"([^"]+)"')
        if member_since:
            member_since = unescape_plan(member_since)
        else:
            member_since = "Unknown"
        next_billing_date = find(r'"nextBillingDate":\{"fieldType":"String","value":"([^"]+)"')
        if not next_billing_date:
            next_billing_date = "Unknown"
        payment_method = find(r'"paymentMethod":\{"fieldType":"String","value":"([^"]+)"')
        if not payment_method:
            payment_method = "Unknown"
        card_brand = find_list(r'"paymentOptionLogo":"([^"]+)"')
        if not card_brand:
            card_brand = ["Unknown"]
        last4_digits = find_list(r'"GrowthCardPaymentMethod","displayText":"([^"]+)"')
        if not last4_digits:
            last4_digits = ["Unknown"]
        phone_match = re.search(r'"growthLocalizablePhoneNumber":\{.*?"phoneNumberDigits":\{.*?"value":"([^"]+)"', txt, re.DOTALL)
        if phone_match:
            phone = phone_match.group(1).replace("\\x2B", "+")
        else:
            phone = find(r'"phoneNumberDigits":\{"__typename":"GrowthClearStringValue","value":"([^"]+)"')
            if phone:
                phone = phone.replace("\\x2B", "+")
            else:
                phone = "Unknown"
        phone_verified_match = re.search(r'"growthLocalizablePhoneNumber":\{.*?"isVerified":(true|false)', txt, re.DOTALL)
        if phone_verified_match:
            phone_verified = "Yes" if phone_verified_match.group(1) == "true" else "No"
        else:
            phone_verified_match = re.search(r'"growthPhoneNumber":\{"__typename":"GrowthPhoneNumber","isVerified":(true|false)', txt)
            if phone_verified_match:
                phone_verified = "Yes" if phone_verified_match.group(1) == "true" else "No"
            else:
                phone_verified = "Unknown"
        video_quality = find(r'"videoQuality":\{"fieldType":"String","value":"([^"]+)"')
        if not video_quality:
            video_quality = "Unknown"
        max_streams = find(r'"maxStreams":\{"fieldType":"Numeric","value":([0-9]+)')
        if not max_streams:
            max_streams = "Unknown"
        payment_hold = find(r'"growthHoldMetadata":\{"__typename":"GrowthHoldMetadata","isUserOnHold":(true|false)')
        if payment_hold:
            payment_hold = "Yes" if payment_hold == "true" else "No"
        else:
            payment_hold = "Unknown"
        extra_member = find(r'"showExtraMemberSection":\{"fieldType":"Boolean","value":(true|false)')
        if extra_member:
            extra_member = "Yes" if extra_member == "true" else "No"
        else:
            extra_member = "Unknown"
        extra_member_slot_status = "Unknown"
        add_on_slots_match = re.search(r'"addOnSlots":\s*\{[^}]*"value":\s*\[\s*\{\s*"fieldType":\s*"Group",\s*"fieldGroup":\s*"AddOnSlot",\s*"fields":\s*\{\s*"slotState":\s*\{\s*"fieldType":\s*"String",\s*"value":\s*"([^"]+)"', txt, re.DOTALL)
        if add_on_slots_match:
            extra_member_slot_status = add_on_slots_match.group(1)
        email_verified_match = re.search(r'"growthEmail":\{.*?"isVerified":(true|false)', txt, re.DOTALL)
        if email_verified_match:
            email_verified = "Yes" if email_verified_match.group(1) == "true" else "No"
        else:
            email_verified_match = re.search(r'"emailVerified"\s*:\s*(true|false)', txt)
            if email_verified_match:
                email_verified = "Yes" if email_verified_match.group(1) == "true" else "No"
            else:
                email_verified = "Unknown"
        membership_status = find(r'"membershipStatus":"([^"]+)"')
        if not membership_status:
            membership_status = "Unknown"
        email_match = re.search(r'"growthEmail":\{.*?"email":\{.*?"value":"([^"]+)"', txt, re.DOTALL)
        if email_match:
            email = email_match.group(1)
            try:
                email = urllib.parse.unquote(email)
            except:
                pass
            email = email.replace('\\x40', '@')
        else:
            email = find(r'"emailAddress"\s*:\s*"([^"]+)"') or "Unknown"
            try:
                email = urllib.parse.unquote(email)
            except:
                pass
            email = email.replace('\\x40', '@')

        profiles = []
        try:
            resp_profiles = session.get("https://www.netflix.com/ManageProfiles", timeout=15)
            # Now synchronous call
            profiles = extract_profiles_from_manage_profiles(resp_profiles.text)
        except Exception as e:
            logger.error(f"Error extracting profiles: {e}")

        profiles_str = ", ".join(profiles) if profiles else "Unknown"
        connected_profiles_count = len(profiles) if profiles else 0

        status = re.search(r'"membershipStatus":\s*"([^"]+)"', txt)
        is_premium = bool(status and status.group(1) == 'CURRENT_MEMBER')
        is_valid = bool(status)
        if not is_valid and "NetflixId" in cookie_dict and "SecureNetflixId" not in cookie_dict:
            is_valid = "Account & Billing" in txt or 'membershipStatus' in txt
            is_premium = is_valid

        netflix_id = cookie_dict.get('NetflixId', '')
        try:
            encoded_cookie = f"NetflixId={urllib.parse.quote(netflix_id, safe='')}"
        except:
            encoded_cookie = f"NetflixId={netflix_id}"

        return {
            'ok': is_valid,
            'premium': is_premium,
            'name': name,
            'country': country,
            'country_code': country_code or "Unknown",
            'plan': plan,
            'plan_price': plan_price,
            'member_since': member_since,
            'next_billing_date': next_billing_date,
            'payment_method': payment_method,
            'card_brand': card_brand,
            'last4_digits': last4_digits,
            'phone': phone,
            'phone_verified': phone_verified,
            'video_quality': video_quality,
            'max_streams': max_streams,
            'on_payment_hold': payment_hold,
            'extra_member': extra_member,
            'extra_member_slot_status': extra_member_slot_status,
            'email_verified': email_verified,
            'membership_status': membership_status,
            'connected_profiles': connected_profiles_count,
            'email': email,
            'profiles': profiles_str,
            'cookie': cookie_dict,
            'cookie_string': encoded_cookie
        }
    except Exception as e:
        logger.error(f"Unexpected error in check_cookie_sync: {e}")
        return {'ok': False, 'err': str(e), 'cookie': cookie_dict}

async def check_netflix_cookie(cookie_dict):
    return await asyncio.to_thread(check_cookie_sync, cookie_dict)

async def check_multiple_cookies(cookie_dicts):
    try:
        results = []
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            loop = asyncio.get_event_loop()
            futures = [loop.run_in_executor(executor, check_cookie_sync, cd) for cd in cookie_dicts]
            for future in asyncio.as_completed(futures):
                try:
                    result = await future
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error in thread: {e}")
                    results.append({'ok': False, 'err': str(e), 'cookie': {}})
        return results
    except Exception as e:
        logger.error(f"Error in check_multiple_cookies: {e}")
        return []

def create_button_layout(buttons):
    layout = []
    row = []
    for i, button in enumerate(buttons):
        row.append(button)
        if len(row) == 2:
            layout.append(row)
            row = []
    if row:
        layout.append(row)
    return layout

# -------------------- TV Login helpers (synchronous, called via to_thread) --------------------
def extract_auth_url_sync(session):
    try:
        resp = session.get("https://www.netflix.com/account", timeout=15)
        txt = resp.text
        auth_url_match = re.search(r'"authURL":"([^"]+)"', txt)
        if auth_url_match:
            auth_url = auth_url_match.group(1)
            return auth_url.replace('\\x2F', '/').replace('\\x3D', '=')
        return None
    except Exception as e:
        logger.error(f"Error extracting authURL: {e}")
        return None

def perform_tv_login_sync(session, auth_url, tv_code):
    try:
        url = "https://www.netflix.com/tv2"
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0"
        }
        data = {
            "flow": "websiteSignUp",
            "authURL": auth_url,
            "flowMode": "enterTvLoginRendezvousCode",
            "withFields": "tvLoginRendezvousCode,isTvUrl2",
            "code": tv_code,
            "tvLoginRendezvousCode": tv_code,
            "isTvUrl2": "true",
            "action": "nextAction"
        }
        response = session.post(url, headers=headers, data=data, allow_redirects=False)
        if response.status_code == 302 and response.headers.get('location') == 'https://www.netflix.com/tv/out/success':
            return {'success': True, 'message': 'TV login successful!'}
        else:
            if "That code wasn't right" in response.text:
                return {'success': False, 'message': 'Invalid TV code. Please check and try again.'}
            else:
                return {'success': False, 'message': 'TV login failed. Please try again.'}
    except requests.exceptions.Timeout:
        return {'success': False, 'message': 'Request timeout. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'message': 'Connection error. Please try again.'}
    except Exception as e:
        logger.error(f"Error during TV login: {e}")
        return {'success': False, 'message': f'Error: {str(e)}'}

# -------------------- Cleanup --------------------
async def cleanup_invalid_cookies(user_id=None):
    try:
        if user_id:
            cookies = await db.get_user_cookies(user_id)
            valid_cookies = []
            for cookie_data in cookies:
                check_result = await check_netflix_cookie(cookie_data['cookie'])
                if check_result.get('ok') and check_result.get('premium'):
                    valid_cookies.append(cookie_data)
            if len(valid_cookies) != len(cookies):
                await db.save_user_cookies(user_id, valid_cookies)
            return len(valid_cookies)
        else:
            users = await db.get_all_users()
            changed = False
            for uid in users:
                cookies = await db.get_user_cookies(uid)
                valid_cookies = []
                for cookie_data in cookies:
                    check_result = await check_netflix_cookie(cookie_data['cookie'])
                    if check_result.get('ok') and check_result.get('premium'):
                        valid_cookies.append(cookie_data)
                if len(valid_cookies) != len(cookies):
                    await db.save_user_cookies(uid, valid_cookies)
                    changed = True
            admin_cookies = await db.get_admin_cookies()
            valid_admin = []
            for cookie_data in admin_cookies:
                check_result = await check_netflix_cookie(cookie_data['cookie'])
                if check_result.get('ok') and check_result.get('premium'):
                    valid_admin.append(cookie_data)
            if len(valid_admin) != len(admin_cookies):
                await db.save_admin_cookies(valid_admin)
                changed = True
        return True
    except Exception as e:
        logger.error(f"Error in cleanup_invalid_cookies: {e}")
        return False

async def cancel_user_operation(user_id, message=None):
    try:
        cancelled = False
        for d in (app.user_data, app.tv_login_data, app.pending_cookies, app.tv_accounts,
                  app.poor_user_data, app.user_login_state, app.message_ids, app.admin_data,
                  app.pending_admin_cookies):
            if user_id in d:
                d.pop(user_id, None)
                cancelled = True
        if message:
            if cancelled:
                await safe_reply_message(message, "✅ Operation cancelled successfully!")
            else:
                await safe_reply_message(message, "ℹ️ No active operation to cancel.")
        return cancelled
    except Exception as e:
        logger.error(f"Error in cancel_user_operation: {e}")
        return False

# -------------------- Broadcast --------------------
async def broadcast_(client, message, pin=False):
    sts = await safe_reply_message(message, "<code>Processing...</code>")
    if message.reply_to_message:
        user_ids = await db.get_all_users()
        msg = message.reply_to_message
        total = len(user_ids)
        successful = 0
        blocked = 0
        deleted = 0
        unsuccessful = 0
        await safe_edit_message(sts, "<code>Broadcasting...</code>")
        for user_id in user_ids:
            try:
                docs = await msg.copy(int(user_id))
                if pin:
                    await docs.pin(both_sides=True)
                successful += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
                docs = await msg.copy(int(user_id))
                if pin:
                    await docs.pin(both_sides=True)
                successful += 1
            except (UserIsBlocked, UserNotParticipant):
                await db.delete_user(user_id)
                blocked += 1
            except PeerIdInvalid:
                await db.delete_user(user_id)
                unsuccessful += 1
            except InputUserDeactivated:
                await db.delete_user(user_id)
                deleted += 1
            except Exception as e:
                logger.error(f"Broadcast error for user {user_id}: {e}")
                unsuccessful += 1
        status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""
        await safe_edit_message(sts, status)
    else:
        await safe_edit_message(sts, "<code>Reply to a message to broadcast it.</code>")

# -------------------- Command Handlers --------------------
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    try:
        if not await force_sub_check(client, message):
            return
        welcome_text = """
🎬 **Netflix TV Login Bot** 🎬

Welcome! This bot helps you login to Netflix on your TV using cookies.

**Commands:**
/login - Add new cookies or select existing account for TV login
/myaccounts - View your saved accounts with detailed info
/delete - Delete your saved accounts
/poor - Use admin cookies (if you don't have premium)
/cancel - Cancel any ongoing operation
/stats - View bot statistics (Admin only)
/broadcast - Broadcast message to all users (Admin only)
/help - Show this help message

**How to use:**
1. Send /login to add new cookies or select existing account
2. Enter the 8-digit code from your TV
3. Done! Your TV will be logged in

**Note:** You can save up to 5 premium cookies per user

<blockquote><b>MadeBy:</b> <b><a href="https://t.me/still_alivenow">Ichigo Kurosaki</a></b></blockquote>
        """
        await safe_reply_message(
            message,
            welcome_text,
            disable_web_page_preview=True,
            quote=True
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        await safe_reply_message(message, "An error occurred. Please try again later.")

@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    await start_command(client, message)

@app.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    await cancel_user_operation(message.from_user.id, message)

@app.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    status_msg = await safe_reply_message(message, "📊 Gathering statistics...")
    users = await db.get_all_users()
    total_users = len(users)
    total_user_cookies = 0
    for uid in users:
        cookies = await db.get_user_cookies(uid)
        total_user_cookies += len(cookies)
    admin_cookies = await db.get_admin_cookies()
    total_admin_cookies = len(admin_cookies)
    login_stats = await db.get_login_stats()
    successful = login_stats.get("successful", 0)
    failed = login_stats.get("failed", 0)
    total_attempts = login_stats.get("total_attempts", 0)
    stats_text = f"""
📊 **Bot Statistics**

**Users:**
• Total Users: `{total_users}`
• Total User Cookies: `{total_user_cookies}`

**Admin:**
• Total Admin Cookies: `{total_admin_cookies}`

**Login Stats:**
• Successful Logins: `{successful}`
• Failed Logins: `{failed}`
• Total Attempts: `{total_attempts}`
• Success Rate: `{((successful/total_attempts)*100) if total_attempts > 0 else 0:.1f}%`

**System:**
• Max Threads: `{MAX_THREADS}`
• Uptime: Bot is running
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_stats_{message.from_user.id}")],
        [InlineKeyboardButton("❌ Close", callback_data=f"close_{message.from_user.id}")]
    ])
    await safe_edit_message(status_msg, stats_text, reply_markup=keyboard)

@app.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    await broadcast_(client, message)

@app.on_message(filters.command("login"))
async def login_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    await cancel_user_operation(user_id)
    cookies = await db.get_user_cookies(user_id)
    if cookies:
        await cleanup_invalid_cookies(user_id)
        cookies = await db.get_user_cookies(user_id)
        if cookies:
            app.user_login_state[user_id] = {'state': 'main_menu'}
            msg = await safe_reply_message(message, "📋 **Loading your accounts...**", quote=True)
            if msg:
                app.message_ids[user_id] = msg.id
                await show_login_main_menu(client, msg, user_id)
            return
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
    msg = await safe_reply_message(
        message,
        "📤 **You don't have any saved cookies.**\n\nPlease send your Netflix cookies:\n\n• NetflixId=value format\n• .txt file with multiple lines\n• Netscape format\n• JSON format\n\nOnly the first 5 **premium** cookies will be saved.",
        reply_markup=cancel_keyboard,
        quote=True
    )
    if msg:
        app.message_ids[user_id] = msg.id
        app.user_data[user_id] = {'state': 'awaiting_cookies'}

async def show_login_main_menu(client, message: Message, user_id):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Select Account for TV Login", callback_data=f"show_accounts_{user_id}")],
        [InlineKeyboardButton("📥 Add New Cookies", callback_data=f"add_cookies_{user_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]
    ])
    await safe_edit_message(message, "📋 **What would you like to do?**", reply_markup=keyboard)

@app.on_message(filters.command("myaccounts"))
async def myaccounts_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    await cleanup_invalid_cookies(user_id)
    cookies = await db.get_user_cookies(user_id)
    if not cookies:
        await safe_reply_message(message, "❌ You don't have any saved accounts yet.\nUse /login to add cookies.", quote=True)
        return
    text = f"📋 **Your Saved Accounts ({len(cookies)}/5):**\n\n"
    for i, acc in enumerate(cookies, 1):
        text += f"**{i}. {acc.get('name', 'Unknown')}**\n"
        text += f"📧 Email: {acc.get('email', 'Unknown')}\n"
        text += f"🌍 Country: {acc.get('country', 'Unknown')}\n"
        text += f"📺 Plan: {acc.get('plan', 'Unknown')}\n"
        text += f"🎬 Video Quality: {acc.get('video_quality', 'Unknown')}\n"
        text += f"👥 Max Streams: {acc.get('max_streams', 'Unknown')}\n"
        text += f"💳 Payment: {acc.get('payment_method', 'Unknown')}\n"
        text += f"📅 Member Since: {acc.get('member_since', 'Unknown')}\n"
        text += f"💰 Plan Price: {acc.get('plan_price', 'Unknown')}\n\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Delete Accounts", callback_data=f"delete_menu_{user_id}")],
        [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
    ])
    msg = await safe_reply_message(message, text, reply_markup=keyboard, quote=True)
    if msg:
        app.message_ids[user_id] = msg.id

@app.on_message(filters.command("delete"))
async def delete_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    await cleanup_invalid_cookies(user_id)
    cookies = await db.get_user_cookies(user_id)
    if not cookies:
        await safe_reply_message(message, "❌ You don't have any saved accounts to delete.", quote=True)
        return
    text = f"🗑 **Select accounts to delete:**\n\n"
    keyboard = []
    for i, acc in enumerate(cookies, 1):
        text += f"**{i}. {acc.get('name', 'Unknown')}**\n"
        text += f"📧 Email: {acc.get('email', 'Unknown')}\n"
        text += f"🌍 Country: {acc.get('country', 'Unknown')}\n"
        text += f"📺 Plan: {acc.get('plan', 'Unknown')}\n"
        text += f"🎬 Video Quality: {acc.get('video_quality', 'Unknown')}\n"
        text += f"👥 Max Streams: {acc.get('max_streams', 'Unknown')}\n"
        text += f"💳 Payment: {acc.get('payment_method', 'Unknown')}\n"
        text += f"📅 Member Since: {acc.get('member_since', 'Unknown')}\n"
        text += f"💰 Plan Price: {acc.get('plan_price', 'Unknown')}\n\n"
    text += f"\nYou have {len(cookies)}/5 accounts."
    delete_buttons = []
    for i, acc in enumerate(cookies, 1):
        name = acc.get('name', 'Unknown')[:15]
        delete_buttons.append(InlineKeyboardButton(f"🗑 Delete {i}. {name}", callback_data=f"delete_{user_id}_{i-1}"))
    layout = create_button_layout(delete_buttons)
    keyboard.extend(layout)
    keyboard.append([InlineKeyboardButton("🗑 Delete All Accounts", callback_data=f"deleteall_{user_id}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
    msg = await safe_reply_message(message, text, reply_markup=InlineKeyboardMarkup(keyboard), quote=True)
    if msg:
        app.message_ids[user_id] = msg.id

@app.on_message(filters.command("poor"))
async def poor_command(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    await cancel_user_operation(user_id)
    admin_cookies = await db.get_admin_cookies()
    if not admin_cookies:
        await safe_reply_message(message, "❌ No admin cookies available. Please contact an admin.", quote=True)
        return
    cookie_dicts = [cdata['cookie'] for cdata in admin_cookies if 'cookie' in cdata]
    if not cookie_dicts:
        await safe_reply_message(message, "❌ No valid admin cookies found.", quote=True)
        return
    check_results = await check_multiple_cookies(cookie_dicts)
    valid_cookies = [res for res in check_results if res.get('ok') and res.get('premium')]
    if not valid_cookies:
        await safe_reply_message(message, "❌ No valid admin cookies available. Please contact an admin.", quote=True)
        return
    app.poor_user_data[user_id] = {'cookies': valid_cookies}
    text = "🎬 **Select an account to login to TV:**\n\n"
    keyboard = []
    select_buttons = []
    for i, acc in enumerate(valid_cookies, 1):
        select_buttons.append(InlineKeyboardButton(f"Select {i}. {acc.get('name', 'Unknown')[:15]}", callback_data=f"poor_select_{user_id}_{i-1}"))
        text += f"{i}. **{acc.get('name', 'Unknown')}** - {acc.get('plan', 'Unknown')}\n"
        text += f"   Video: {acc.get('video_quality', 'Unknown')} | Streams: {acc.get('max_streams', 'Unknown')}\n"
        text += f"   📧 {acc.get('email', 'Unknown')}\n"
        text += f"   🌍 {acc.get('country', 'Unknown')}\n\n"
    layout = create_button_layout(select_buttons)
    keyboard.extend(layout)
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
    msg = await safe_reply_message(message, text, reply_markup=InlineKeyboardMarkup(keyboard), quote=True)
    if msg:
        app.message_ids[user_id] = msg.id

@app.on_message(filters.command("addadmincookies") & filters.user(ADMINS))
async def add_admin_cookies(client, message: Message):
    if not await force_sub_check(client, message):
        return
    admin_id = message.from_user.id
    await cancel_user_operation(admin_id)
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"admincancel_{admin_id}")]])
    msg = await safe_reply_message(
        message,
        "📤 **Send admin cookies**\n\nYou can send up to 20 premium cookies.\nOnly the first 20 premium cookies will be saved.\nThese will be used for /poor command.",
        reply_markup=cancel_keyboard,
        quote=True
    )
    if msg:
        app.message_ids[admin_id] = msg.id
        app.admin_data[admin_id] = {'state': 'awaiting_admin_cookies'}

@app.on_message(filters.command("viewadmincookies") & filters.user(ADMINS))
async def view_admin_cookies(client, message: Message):
    if not await force_sub_check(client, message):
        return
    admin_id = message.from_user.id
    admin_cookies = await db.get_admin_cookies()
    if not admin_cookies:
        await safe_reply_message(message, "No admin cookies found.", quote=True)
        return
    cookie_dicts = [cdata['cookie'] for cdata in admin_cookies if 'cookie' in cdata]
    if not cookie_dicts:
        await safe_reply_message(message, "No valid cookies to check.", quote=True)
        return
    check_results = await check_multiple_cookies(cookie_dicts)
    valid_cookies = [res for res in check_results if res.get('ok') and res.get('premium')]
    text = f"📋 **Admin Cookies ({len(valid_cookies)}/20):**\n\n"
    for i, acc in enumerate(valid_cookies, 1):
        text += f"{i}. **{acc.get('name', 'Unknown')}** - {acc.get('plan', 'Unknown')}\n"
        text += f"   📧 {acc.get('email', 'Unknown')}\n"
        text += f"   Video: {acc.get('video_quality', 'Unknown')} | Streams: {acc.get('max_streams', 'Unknown')}\n"
        text += f"   Status: ✅ Valid\n\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data=f"close_{admin_id}")]])
    msg = await safe_reply_message(message, text, reply_markup=keyboard, quote=True)
    if msg:
        app.message_ids[admin_id] = msg.id

@app.on_message(filters.command("clearadmincookies") & filters.user(ADMINS))
async def clear_admin_cookies(client, message: Message):
    if not await force_sub_check(client, message):
        return
    await db.save_admin_cookies([])
    await safe_reply_message(message, "✅ All admin cookies cleared.", quote=True)

# -------------------- Message Handlers for user input --------------------
@app.on_message(filters.text & filters.private)
async def handle_messages(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    if user_id in app.user_data and app.user_data[user_id].get('state') == 'awaiting_cookies':
        await process_cookie_input(client, message)
    elif user_id in app.admin_data and app.admin_data[user_id].get('state') == 'awaiting_admin_cookies':
        await process_admin_cookie_input(client, message)
    elif user_id in app.tv_login_data and app.tv_login_data[user_id].get('state') == 'awaiting_tv_code':
        await process_tv_code(client, message)

@app.on_message(filters.document & filters.private)
async def handle_documents(client, message: Message):
    if not await force_sub_check(client, message):
        return
    user_id = message.from_user.id
    if user_id in app.user_data and app.user_data[user_id].get('state') == 'awaiting_cookies':
        await process_document_cookie(client, message)
    elif user_id in app.admin_data and app.admin_data[user_id].get('state') == 'awaiting_admin_cookies':
        await process_admin_document_cookie(client, message)

async def process_document_cookie(client, message: Message):
    user_id = message.from_user.id
    status_msg = await safe_reply_message(message, "📥 Downloading file...", quote=True)
    try:
        file_path = await message.download()
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            await safe_edit_message(status_msg, f"❌ Error reading file: {str(e)}")
            return
        finally:
            try:
                os.remove(file_path)
            except:
                pass
        await safe_edit_message(status_msg, "🔄 Processing file...")
        await process_cookie_content(client, status_msg, content, user_id)
    except Exception as e:
        await safe_edit_message(status_msg, f"❌ Error processing file: {str(e)}")
        app.user_data.pop(user_id, None)

async def process_admin_document_cookie(client, message: Message):
    admin_id = message.from_user.id
    status_msg = await safe_reply_message(message, "📥 Downloading file...", quote=True)
    try:
        file_path = await message.download()
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            await safe_edit_message(status_msg, f"❌ Error reading file: {str(e)}")
            return
        finally:
            try:
                os.remove(file_path)
            except:
                pass
        await safe_edit_message(status_msg, "🔄 Processing file...")
        await process_admin_cookie_content(client, status_msg, content, admin_id)
    except Exception as e:
        await safe_edit_message(status_msg, f"❌ Error processing file: {str(e)}")
        app.admin_data.pop(admin_id, None)

async def process_cookie_input(client, message: Message):
    user_id = message.from_user.id
    content = message.text
    status_msg = await safe_reply_message(message, "🔄 Processing your cookies...", quote=True)
    await process_cookie_content(client, status_msg, content, user_id)

async def process_cookie_content(client, message: Message, content, user_id):
    netflix_ids = extract_multiple_netflix_ids(content)
    if not netflix_ids:
        netflix_id = extract_netflix_id(content)
        if netflix_id:
            netflix_ids = [netflix_id]
    if not netflix_ids:
        await safe_edit_message(message, "❌ No Netflix cookies found. Please check and try again.")
        app.user_data.pop(user_id, None)
        return
    await safe_edit_message(message, f"📊 Found {len(netflix_ids)} potential cookies. Checking validity with {MAX_THREADS} threads...")
    cookie_dicts = [{'NetflixId': nid} for nid in netflix_ids[:20]]
    check_results = await check_multiple_cookies(cookie_dicts)
    valid_cookies = [res for res in check_results if res.get('ok') and res.get('premium')]
    if not valid_cookies:
        await safe_edit_message(message, "❌ No valid premium cookies found.")
        app.user_data.pop(user_id, None)
        return
    existing_cookies = await db.get_user_cookies(user_id)
    await show_cookie_selection(client, message, user_id, valid_cookies, existing_cookies)

async def show_cookie_selection(client, message: Message, user_id, valid_cookies, existing_cookies):
    text = f"✅ Found {len(valid_cookies)} valid premium cookies!\n\n"
    text += f"You currently have {len(existing_cookies)}/5 saved cookies.\n\n"
    text += "**Select which cookies to save:**\n\n"
    keyboard = []
    save_buttons = []
    for i, cookie in enumerate(valid_cookies, 1):
        text += f"{i}. **{cookie.get('name', 'Unknown')}** - {cookie.get('plan', 'Unknown')}\n"
        text += f"   Video: {cookie.get('video_quality', 'Unknown')} | Streams: {cookie.get('max_streams', 'Unknown')}\n"
        text += f"   📧 {cookie.get('email', 'Unknown')}\n"
        text += f"   🌍 {cookie.get('country', 'Unknown')}\n\n"
        save_buttons.append(InlineKeyboardButton(f"💾 Save Account {i}", callback_data=f"save_{user_id}_{i-1}"))
    layout = create_button_layout(save_buttons)
    keyboard.extend(layout)
    keyboard.append([InlineKeyboardButton("💾 Save All Accounts", callback_data=f"saveall_{user_id}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
    app.pending_cookies[user_id] = {'valid_cookies': valid_cookies, 'existing_cookies': existing_cookies}
    await safe_edit_message(message, text, reply_markup=InlineKeyboardMarkup(keyboard))
    app.user_data.pop(user_id, None)

async def process_admin_cookie_input(client, message: Message):
    admin_id = message.from_user.id
    content = message.text
    status_msg = await safe_reply_message(message, "🔄 Processing admin cookies...", quote=True)
    await process_admin_cookie_content(client, status_msg, content, admin_id)

async def process_admin_cookie_content(client, message: Message, content, admin_id):
    netflix_ids = extract_multiple_netflix_ids(content)
    if not netflix_ids:
        netflix_id = extract_netflix_id(content)
        if netflix_id:
            netflix_ids = [netflix_id]
    if not netflix_ids:
        await safe_edit_message(message, "❌ No Netflix cookies found.")
        app.admin_data.pop(admin_id, None)
        return
    await safe_edit_message(message, f"📊 Found {len(netflix_ids)} potential cookies. Checking validity with {MAX_THREADS} threads...")
    cookie_dicts = [{'NetflixId': nid} for nid in netflix_ids[:20]]
    check_results = await check_multiple_cookies(cookie_dicts)
    valid_cookies = []
    for res in check_results:
        if res.get('ok') and res.get('premium'):
            valid_cookies.append({
                'name': res.get('name', 'Unknown'),
                'email': res.get('email', 'Unknown'),
                'plan': res.get('plan', 'Unknown'),
                'country': res.get('country', 'Unknown'),
                'video_quality': res.get('video_quality', 'Unknown'),
                'max_streams': res.get('max_streams', 'Unknown'),
                'cookie': res.get('cookie', {}),
                'added_at': datetime.now().isoformat()
            })
    if not valid_cookies:
        await safe_edit_message(message, "❌ No valid premium cookies found.")
        app.admin_data.pop(admin_id, None)
        return
    existing_cookies = await db.get_admin_cookies()
    await show_admin_cookie_selection(client, message, admin_id, valid_cookies, existing_cookies)

async def show_admin_cookie_selection(client, message: Message, admin_id, valid_cookies, existing_cookies):
    text = f"✅ Found {len(valid_cookies)} valid premium cookies for admin!\n\n"
    text += f"Current admin cookies: {len(existing_cookies)}/20\n\n"
    text += "**Select which cookies to save:**\n\n"
    keyboard = []
    save_buttons = []
    for i, cookie in enumerate(valid_cookies, 1):
        text += f"{i}. **{cookie.get('name', 'Unknown')}** - {cookie.get('plan', 'Unknown')}\n"
        text += f"   Video: {cookie.get('video_quality', 'Unknown')} | Streams: {cookie.get('max_streams', 'Unknown')}\n"
        text += f"   📧 {cookie.get('email', 'Unknown')}\n"
        text += f"   🌍 {cookie.get('country', 'Unknown')}\n\n"
        save_buttons.append(InlineKeyboardButton(f"💾 Save Account {i}", callback_data=f"adminsave_{admin_id}_{i-1}"))
    layout = create_button_layout(save_buttons)
    keyboard.extend(layout)
    keyboard.append([InlineKeyboardButton("💾 Save All Accounts", callback_data=f"adminsaveall_{admin_id}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"admincancel_{admin_id}")])
    app.pending_admin_cookies[admin_id] = {'valid_cookies': valid_cookies, 'existing_cookies': existing_cookies}
    await safe_edit_message(message, text, reply_markup=InlineKeyboardMarkup(keyboard))
    app.admin_data.pop(admin_id, None)

async def process_tv_code(client, message: Message):
    user_id = message.from_user.id
    tv_code = message.text.strip()
    if not re.match(r'^\d{8}$', tv_code):
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
        await safe_reply_message(message, "❌ Invalid code. Please enter an 8-digit code.", reply_markup=cancel_keyboard, quote=True)
        return
    if user_id not in app.tv_login_data:
        await safe_reply_message(message, "❌ Session expired. Please start over.", quote=True)
        return
    tv_data = app.tv_login_data[user_id]
    account_index = tv_data['account_index']
    if tv_data.get('is_poor'):
        if user_id not in app.poor_user_data:
            await safe_reply_message(message, "❌ Session expired. Please start over.", quote=True)
            return
        cookie_dict = app.poor_user_data[user_id]['cookies'][account_index]['cookie']
    else:
        if user_id not in app.tv_accounts:
            await safe_reply_message(message, "❌ Session expired. Please start over.", quote=True)
            return
        cookie_dict = app.tv_accounts[user_id][account_index]['cookie']

    status_msg = await safe_reply_message(message, "🔄 Logging into TV... Please wait.", quote=True)

    # Run the blocking network calls in a thread
    try:
        session = requests.Session()
        session.cookies.update(cookie_dict)
        auth_url = await asyncio.to_thread(extract_auth_url_sync, session)
        if not auth_url:
            await safe_edit_message(status_msg, "❌ Failed to get authURL. Cookie might be invalid.")
            app.tv_login_data.pop(user_id, None)
            return
        result = await asyncio.to_thread(perform_tv_login_sync, session, auth_url, tv_code)
        await db.update_login_stats(result['success'])
        if result['success']:
            await safe_edit_message(status_msg, "✅ **TV Login Successful!**\n\nYour TV should now be logged into Netflix.")
        else:
            retry_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"retry_{user_id}_{account_index}_{int(tv_data.get('is_poor', False))}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]
            ])
            await safe_edit_message(status_msg, f"❌ **Login Failed**\n\n{result['message']}", reply_markup=retry_keyboard)
    except Exception as e:
        logger.error(f"Error in TV login thread: {e}")
        await safe_edit_message(status_msg, "❌ An error occurred during TV login. Please try again.")
    finally:
        app.tv_login_data.pop(user_id, None)

# -------------------- Callback Handlers --------------------
@app.on_callback_query()
async def handle_callback(client, callback_query: CallbackQuery):
    try:
        data = callback_query.data
        user_id = callback_query.from_user.id
        await safe_answer_callback(callback_query)

        if data == "refresh":
            channel_button, _ = await check_fsb(client, user_id)
            if not channel_button:
                await safe_answer_callback(callback_query, "✅ Thanks for joining! You can now use the bot.")
                await safe_delete_message(callback_query.message)
                return
            channel_button = split_list(channel_button)
            channel_button.append([InlineKeyboardButton("🔄 REFRESH", callback_data="refresh")])
            if PICS:
                await safe_edit_message_media(
                    callback_query.message,
                    media=InputMediaPhoto(random.choice(PICS), caption=FORCE_SUB_TEXT),
                    reply_markup=InlineKeyboardMarkup(channel_button)
                )
            else:
                await safe_edit_message(callback_query.message, FORCE_SUB_TEXT, reply_markup=InlineKeyboardMarkup(channel_button))
            return

        # Handle close
        if data.startswith("close_"):
            parts = data.split("_")
            if len(parts) == 2 and int(parts[1]) == user_id:
                await safe_delete_message(callback_query.message)
                app.message_ids.pop(user_id, None)
        # Refresh stats
        elif data.startswith("refresh_stats_"):
            parts = data.split("_")
            if len(parts) == 3 and int(parts[2]) == user_id and user_id in ADMINS:
                users = await db.get_all_users()
                total_users = len(users)
                total_user_cookies = 0
                for uid in users:
                    cookies = await db.get_user_cookies(uid)
                    total_user_cookies += len(cookies)
                admin_cookies = await db.get_admin_cookies()
                total_admin_cookies = len(admin_cookies)
                login_stats = await db.get_login_stats()
                successful = login_stats.get("successful", 0)
                failed = login_stats.get("failed", 0)
                total_attempts = login_stats.get("total_attempts", 0)
                stats_text = f"""
📊 **Bot Statistics** (Refreshed)

**Users:**
• Total Users: `{total_users}`
• Total User Cookies: `{total_user_cookies}`

**Admin:**
• Total Admin Cookies: `{total_admin_cookies}`

**Login Stats:**
• Successful Logins: `{successful}`
• Failed Logins: `{failed}`
• Total Attempts: `{total_attempts}`
• Success Rate: `{((successful/total_attempts)*100) if total_attempts > 0 else 0:.1f}%`

**System:**
• Max Threads: `{MAX_THREADS}`
• Uptime: Bot is running
                """
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_stats_{user_id}")],
                    [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                ])
                await safe_edit_message(callback_query.message, stats_text, reply_markup=keyboard)
        # Delete menu
        elif data.startswith("delete_menu_"):
            parts = data.split("_")
            if len(parts) == 3 and int(parts[2]) == user_id:
                cookies = await db.get_user_cookies(user_id)
                if not cookies:
                    await safe_edit_message(callback_query.message, "❌ You don't have any saved accounts to delete.")
                    return
                text = f"🗑 **Select accounts to delete:**\n\n"
                keyboard = []
                for i, acc in enumerate(cookies, 1):
                    text += f"**{i}. {acc.get('name', 'Unknown')}**\n"
                    text += f"📧 Email: {acc.get('email', 'Unknown')}\n"
                    text += f"🌍 Country: {acc.get('country', 'Unknown')}\n"
                    text += f"📺 Plan: {acc.get('plan', 'Unknown')}\n"
                    text += f"🎬 Video Quality: {acc.get('video_quality', 'Unknown')}\n"
                    text += f"👥 Max Streams: {acc.get('max_streams', 'Unknown')}\n"
                    text += f"💳 Payment: {acc.get('payment_method', 'Unknown')}\n"
                    text += f"📅 Member Since: {acc.get('member_since', 'Unknown')}\n"
                    text += f"💰 Plan Price: {acc.get('plan_price', 'Unknown')}\n\n"
                text += f"\nYou have {len(cookies)}/5 accounts."
                delete_buttons = []
                for i, acc in enumerate(cookies, 1):
                    name = acc.get('name', 'Unknown')[:15]
                    delete_buttons.append(InlineKeyboardButton(f"🗑 Delete {i}. {name}", callback_data=f"delete_{user_id}_{i-1}"))
                layout = create_button_layout(delete_buttons)
                keyboard.extend(layout)
                keyboard.append([InlineKeyboardButton("🗑 Delete All Accounts", callback_data=f"deleteall_{user_id}")])
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
                await safe_edit_message(callback_query.message, text, reply_markup=InlineKeyboardMarkup(keyboard))
        # Delete single account
        elif data.startswith("delete_"):
            parts = data.split("_")
            if len(parts) == 3:
                cb_user_id = int(parts[1])
                account_index = int(parts[2])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                cookies = await db.get_user_cookies(user_id)
                if account_index < len(cookies):
                    deleted = cookies.pop(account_index)
                    await db.save_user_cookies(user_id, cookies)
                    await safe_edit_message(callback_query.message, f"✅ Deleted account: {deleted.get('name', 'Unknown')}")
                    if cookies:
                        text = f"📋 **Your Remaining Accounts ({len(cookies)}/5):**\n\n"
                        for i, acc in enumerate(cookies, 1):
                            text += f"**{i}. {acc.get('name', 'Unknown')}**\n"
                            text += f"📧 Email: {acc.get('email', 'Unknown')}\n"
                            text += f"🌍 Country: {acc.get('country', 'Unknown')}\n"
                            text += f"📺 Plan: {acc.get('plan', 'Unknown')}\n"
                            text += f"🎬 Video Quality: {acc.get('video_quality', 'Unknown')}\n"
                            text += f"👥 Max Streams: {acc.get('max_streams', 'Unknown')}\n"
                            text += f"💳 Payment: {acc.get('payment_method', 'Unknown')}\n"
                            text += f"📅 Member Since: {acc.get('member_since', 'Unknown')}\n"
                            text += f"💰 Plan Price: {acc.get('plan_price', 'Unknown')}\n\n"
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🗑 Delete More", callback_data=f"delete_menu_{user_id}")],
                            [InlineKeyboardButton("📋 Main Menu", callback_data=f"mainmenu_{user_id}")],
                            [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                        ])
                        await safe_reply_message(callback_query.message, text, reply_markup=keyboard)
                    else:
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📥 Add New Cookies", callback_data=f"add_cookies_{user_id}")],
                            [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                        ])
                        await safe_reply_message(callback_query.message, "✅ All accounts deleted. You have no saved accounts.\n\nUse /login to add new cookies.", reply_markup=keyboard)
                else:
                    await safe_edit_message(callback_query.message, "❌ Account not found.")
        # Delete all accounts
        elif data.startswith("deleteall_"):
            parts = data.split("_")
            if len(parts) == 2:
                cb_user_id = int(parts[1])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                cookies = await db.get_user_cookies(user_id)
                count = len(cookies)
                await db.save_user_cookies(user_id, [])
                await safe_edit_message(callback_query.message, f"✅ Deleted all {count} accounts.")
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Add New Cookies", callback_data=f"add_cookies_{user_id}")],
                    [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                ])
                await safe_reply_message(callback_query.message, "You have no saved accounts.\n\nUse /login to add new cookies.", reply_markup=keyboard)
        # Show myaccounts
        elif data.startswith("myaccounts_"):
            parts = data.split("_")
            if len(parts) == 2 and int(parts[1]) == user_id:
                cookies = await db.get_user_cookies(user_id)
                if not cookies:
                    await safe_edit_message(callback_query.message, "❌ You don't have any saved accounts yet.\nUse /login to add cookies.")
                    return
                text = f"📋 **Your Saved Accounts ({len(cookies)}/5):**\n\n"
                for i, acc in enumerate(cookies, 1):
                    text += f"**{i}. {acc.get('name', 'Unknown')}**\n"
                    text += f"📧 Email: {acc.get('email', 'Unknown')}\n"
                    text += f"🌍 Country: {acc.get('country', 'Unknown')}\n"
                    text += f"📺 Plan: {acc.get('plan', 'Unknown')}\n"
                    text += f"🎬 Video Quality: {acc.get('video_quality', 'Unknown')}\n"
                    text += f"👥 Max Streams: {acc.get('max_streams', 'Unknown')}\n"
                    text += f"💳 Payment: {acc.get('payment_method', 'Unknown')}\n"
                    text += f"📅 Member Since: {acc.get('member_since', 'Unknown')}\n"
                    text += f"💰 Plan Price: {acc.get('plan_price', 'Unknown')}\n\n"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Delete Accounts", callback_data=f"delete_menu_{user_id}")],
                    [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                ])
                await safe_edit_message(callback_query.message, text, reply_markup=keyboard)
        # Show accounts for TV login
        elif data.startswith("show_accounts_"):
            parts = data.split("_")
            if len(parts) == 3 and int(parts[2]) == user_id:
                cookies = await db.get_user_cookies(user_id)
                if not cookies:
                    await safe_edit_message(callback_query.message, "❌ No accounts found.")
                    return
                app.tv_accounts[user_id] = cookies
                text = "🎬 **Select an account to login to TV:**\n\n"
                keyboard = []
                select_buttons = []
                for i, acc in enumerate(cookies, 1):
                    text += f"{i}. **{acc.get('name', 'Unknown')}** - {acc.get('plan', 'Unknown')}\n"
                    text += f"   Video: {acc.get('video_quality', 'Unknown')} | Streams: {acc.get('max_streams', 'Unknown')}\n"
                    text += f"   📧 {acc.get('email', 'Unknown')}\n"
                    text += f"   🌍 {acc.get('country', 'Unknown')}\n\n"
                    select_buttons.append(InlineKeyboardButton(f"Select Account {i}", callback_data=f"select_{user_id}_{i-1}"))
                layout = create_button_layout(select_buttons)
                keyboard.extend(layout)
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
                await safe_edit_message(callback_query.message, text, reply_markup=InlineKeyboardMarkup(keyboard))
        # Add new cookies
        elif data.startswith("add_cookies_"):
            parts = data.split("_")
            if len(parts) == 3 and int(parts[2]) == user_id:
                cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
                await safe_edit_message(
                    callback_query.message,
                    "📤 **Please send your Netflix cookies**\n\n• NetflixId=value format\n• .txt file with multiple lines\n• Netscape format\n• JSON format\n\nOnly the first 5 **premium** cookies will be saved.",
                    reply_markup=cancel_keyboard
                )
                app.user_data[user_id] = {'state': 'awaiting_cookies'}
        # Retry TV login
        elif data.startswith("retry_"):
            parts = data.split("_")
            if len(parts) == 4:
                cb_user_id = int(parts[1])
                account_index = int(parts[2])
                is_poor = bool(int(parts[3]))
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                app.tv_login_data[user_id] = {'state': 'awaiting_tv_code', 'account_index': account_index, 'is_poor': is_poor}
                cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
                await safe_edit_message(callback_query.message, "📺 Please enter the **8-digit code** shown on your TV:", reply_markup=cancel_keyboard)
        # Save selected cookie (user)
        elif data.startswith("save_"):
            parts = data.split("_")
            if len(parts) == 3:
                cb_user_id = int(parts[1])
                cookie_index = int(parts[2])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                if user_id not in app.pending_cookies:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                pending = app.pending_cookies[user_id]
                valid_cookies = pending['valid_cookies']
                existing_cookies = pending['existing_cookies']
                if cookie_index >= len(valid_cookies):
                    await safe_edit_message(callback_query.message, "❌ Cookie not found.")
                    return
                cookie = valid_cookies[cookie_index]
                if any(c.get('cookie', {}).get('NetflixId') == cookie['cookie'].get('NetflixId') for c in existing_cookies):
                    await safe_edit_message(callback_query.message, "❌ This cookie is already saved.")
                    return
                if len(existing_cookies) >= 5:
                    await safe_edit_message(callback_query.message, "❌ You already have 5 premium cookies. Cannot save more.")
                    return
                existing_cookies.append({
                    'name': cookie.get('name', 'Unknown'),
                    'email': cookie.get('email', 'Unknown'),
                    'plan': cookie.get('plan', 'Unknown'),
                    'country': cookie.get('country', 'Unknown'),
                    'video_quality': cookie.get('video_quality', 'Unknown'),
                    'max_streams': cookie.get('max_streams', 'Unknown'),
                    'payment_method': cookie.get('payment_method', 'Unknown'),
                    'member_since': cookie.get('member_since', 'Unknown'),
                    'plan_price': cookie.get('plan_price', 'Unknown'),
                    'cookie': cookie.get('cookie', {}),
                    'added_at': datetime.now().isoformat()
                })
                await db.save_user_cookies(user_id, existing_cookies)
                app.pending_cookies.pop(user_id, None)
                await safe_edit_message(callback_query.message, f"✅ Saved account: {cookie.get('name', 'Unknown')}")
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎬 Login to TV Now", callback_data=f"loginnow_{user_id}_{len(existing_cookies)-1}")],
                    [InlineKeyboardButton("📋 Main Menu", callback_data=f"mainmenu_{user_id}")],
                    [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                ])
                await safe_reply_message(callback_query.message, "What would you like to do next?", reply_markup=keyboard)
        # Save all cookies (user)
        elif data.startswith("saveall_"):
            parts = data.split("_")
            if len(parts) == 2:
                cb_user_id = int(parts[1])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                if user_id not in app.pending_cookies:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                pending = app.pending_cookies[user_id]
                valid_cookies = pending['valid_cookies']
                existing_cookies = pending['existing_cookies']
                available_slots = 5 - len(existing_cookies)
                if available_slots <= 0:
                    await safe_edit_message(callback_query.message, "❌ You already have 5 premium cookies. Cannot save more.")
                    return
                saved_count = 0
                saved_names = []
                for cookie in valid_cookies:
                    if len(existing_cookies) >= 5:
                        break
                    if not any(c.get('cookie', {}).get('NetflixId') == cookie['cookie'].get('NetflixId') for c in existing_cookies):
                        existing_cookies.append({
                            'name': cookie.get('name', 'Unknown'),
                            'email': cookie.get('email', 'Unknown'),
                            'plan': cookie.get('plan', 'Unknown'),
                            'country': cookie.get('country', 'Unknown'),
                            'video_quality': cookie.get('video_quality', 'Unknown'),
                            'max_streams': cookie.get('max_streams', 'Unknown'),
                            'payment_method': cookie.get('payment_method', 'Unknown'),
                            'member_since': cookie.get('member_since', 'Unknown'),
                            'plan_price': cookie.get('plan_price', 'Unknown'),
                            'cookie': cookie.get('cookie', {}),
                            'added_at': datetime.now().isoformat()
                        })
                        saved_count += 1
                        saved_names.append(cookie.get('name', 'Unknown'))
                await db.save_user_cookies(user_id, existing_cookies)
                app.pending_cookies.pop(user_id, None)
                if saved_count == 0:
                    await safe_edit_message(callback_query.message, "❌ No new cookies were saved. They may already exist.")
                else:
                    await safe_edit_message(callback_query.message, f"✅ Saved {saved_count} new account(s): {', '.join(saved_names)}")
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎬 Login to TV Now", callback_data=f"loginselect_{user_id}")],
                        [InlineKeyboardButton("📋 Main Menu", callback_data=f"mainmenu_{user_id}")],
                        [InlineKeyboardButton("❌ Close", callback_data=f"close_{user_id}")]
                    ])
                    await safe_reply_message(callback_query.message, "What would you like to do next?", reply_markup=keyboard)
        # Cancel operation
        elif data.startswith("cancel_"):
            parts = data.split("_")
            if len(parts) == 2 and int(parts[1]) == user_id:
                await cancel_user_operation(user_id)
                await safe_delete_message(callback_query.message)
        # Main menu
        elif data.startswith("mainmenu_"):
            parts = data.split("_")
            if len(parts) == 2 and int(parts[1]) == user_id:
                await show_login_main_menu(client, callback_query.message, user_id)
        # Login now (after saving a single account)
        elif data.startswith("loginnow_"):
            parts = data.split("_")
            if len(parts) == 3:
                cb_user_id = int(parts[1])
                account_index = int(parts[2])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                cookies = await db.get_user_cookies(user_id)
                if account_index >= len(cookies):
                    await safe_edit_message(callback_query.message, "❌ Account not found.")
                    return
                account = cookies[account_index]
                app.tv_accounts[user_id] = cookies
                cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
                app.tv_login_data[user_id] = {'state': 'awaiting_tv_code', 'account_index': account_index, 'is_poor': False}
                await safe_edit_message(
                    callback_query.message,
                    f"📺 **Selected Account:**\n\n"
                    f"Name: {account.get('name', 'Unknown')}\n"
                    f"Plan: {account.get('plan', 'Unknown')}\n"
                    f"Video: {account.get('video_quality', 'Unknown')}\n"
                    f"Streams: {account.get('max_streams', 'Unknown')}\n"
                    f"Email: {account.get('email', 'Unknown')}\n\n"
                    f"Please enter the **8-digit code** shown on your TV:",
                    reply_markup=cancel_keyboard
                )
        # Login select (after saving multiple accounts)
        elif data.startswith("loginselect_"):
            parts = data.split("_")
            if len(parts) == 2:
                cb_user_id = int(parts[1])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                cookies = await db.get_user_cookies(user_id)
                if not cookies:
                    await safe_edit_message(callback_query.message, "❌ No accounts found.")
                    return
                app.tv_accounts[user_id] = cookies
                text = "🎬 **Select an account to login to TV:**\n\n"
                keyboard = []
                select_buttons = []
                for i, acc in enumerate(cookies, 1):
                    text += f"{i}. **{acc.get('name', 'Unknown')}** - {acc.get('plan', 'Unknown')}\n"
                    text += f"   Video: {acc.get('video_quality', 'Unknown')} | Streams: {acc.get('max_streams', 'Unknown')}\n"
                    text += f"   📧 {acc.get('email', 'Unknown')}\n"
                    text += f"   🌍 {acc.get('country', 'Unknown')}\n\n"
                    select_buttons.append(InlineKeyboardButton(f"Select Account {i}", callback_data=f"select_{user_id}_{i-1}"))
                layout = create_button_layout(select_buttons)
                keyboard.extend(layout)
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")])
                await safe_edit_message(callback_query.message, text, reply_markup=InlineKeyboardMarkup(keyboard))
        # Select account for TV login
        elif data.startswith("select_"):
            parts = data.split("_")
            if len(parts) == 3:
                cb_user_id = int(parts[1])
                account_index = int(parts[2])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This selection is not for you.")
                    return
                if user_id not in app.tv_accounts:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                accounts = app.tv_accounts[user_id]
                if account_index >= len(accounts):
                    await safe_edit_message(callback_query.message, "❌ Account not found.")
                    return
                account = accounts[account_index]
                cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
                app.tv_login_data[user_id] = {'state': 'awaiting_tv_code', 'account_index': account_index, 'is_poor': False}
                await safe_edit_message(
                    callback_query.message,
                    f"📺 **Selected Account:**\n\n"
                    f"Name: {account.get('name', 'Unknown')}\n"
                    f"Plan: {account.get('plan', 'Unknown')}\n"
                    f"Video: {account.get('video_quality', 'Unknown')}\n"
                    f"Streams: {account.get('max_streams', 'Unknown')}\n"
                    f"Email: {account.get('email', 'Unknown')}\n\n"
                    f"Please enter the **8-digit code** shown on your TV:",
                    reply_markup=cancel_keyboard
                )
        # Poor select (admin cookies)
        elif data.startswith("poor_select_"):
            parts = data.split("_")
            if len(parts) == 4:
                cb_user_id = int(parts[2])
                account_index = int(parts[3])
                if user_id != cb_user_id:
                    await safe_edit_message(callback_query.message, "❌ This selection is not for you.")
                    return
                if user_id not in app.poor_user_data:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                cookies = app.poor_user_data[user_id].get('cookies', [])
                if account_index >= len(cookies):
                    await safe_edit_message(callback_query.message, "❌ Account not found.")
                    return
                account = cookies[account_index]
                cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]])
                app.tv_login_data[user_id] = {'state': 'awaiting_tv_code', 'account_index': account_index, 'is_poor': True}
                await safe_edit_message(
                    callback_query.message,
                    f"📺 **Selected Admin Account:**\n\n"
                    f"Name: {account.get('name', 'Unknown')}\n"
                    f"Plan: {account.get('plan', 'Unknown')}\n"
                    f"Video: {account.get('video_quality', 'Unknown')}\n"
                    f"Streams: {account.get('max_streams', 'Unknown')}\n"
                    f"Email: {account.get('email', 'Unknown')}\n\n"
                    f"Please enter the **8-digit code** shown on your TV:",
                    reply_markup=cancel_keyboard
                )
        # Admin save single cookie
        elif data.startswith("adminsave_"):
            parts = data.split("_")
            if len(parts) == 3:
                cb_admin_id = int(parts[1])
                cookie_index = int(parts[2])
                if user_id != cb_admin_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                if user_id not in app.pending_admin_cookies:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                pending = app.pending_admin_cookies[user_id]
                valid_cookies = pending['valid_cookies']
                existing_cookies = pending['existing_cookies']
                if cookie_index >= len(valid_cookies):
                    await safe_edit_message(callback_query.message, "❌ Cookie not found.")
                    return
                cookie = valid_cookies[cookie_index]
                if any(c.get('cookie', {}).get('NetflixId') == cookie['cookie'].get('NetflixId') for c in existing_cookies):
                    await safe_edit_message(callback_query.message, "❌ This cookie is already saved.")
                    return
                if len(existing_cookies) >= 20:
                    await safe_edit_message(callback_query.message, "❌ Admin already has 20 premium cookies. Cannot save more.")
                    return
                existing_cookies.append(cookie)
                await db.save_admin_cookies(existing_cookies)
                app.pending_admin_cookies.pop(user_id, None)
                await safe_edit_message(callback_query.message, f"✅ Saved admin account: {cookie.get('name', 'Unknown')}")
        # Admin save all cookies
        elif data.startswith("adminsaveall_"):
            parts = data.split("_")
            if len(parts) == 2:
                cb_admin_id = int(parts[1])
                if user_id != cb_admin_id:
                    await safe_edit_message(callback_query.message, "❌ This action is not for you.")
                    return
                if user_id not in app.pending_admin_cookies:
                    await safe_edit_message(callback_query.message, "❌ Session expired. Please try again.")
                    return
                pending = app.pending_admin_cookies[user_id]
                valid_cookies = pending['valid_cookies']
                existing_cookies = pending['existing_cookies']
                available_slots = 20 - len(existing_cookies)
                if available_slots <= 0:
                    await safe_edit_message(callback_query.message, "❌ Admin already has 20 premium cookies. Cannot save more.")
                    return
                saved_count = 0
                for cookie in valid_cookies:
                    if len(existing_cookies) >= 20:
                        break
                    if not any(c.get('cookie', {}).get('NetflixId') == cookie['cookie'].get('NetflixId') for c in existing_cookies):
                        existing_cookies.append(cookie)
                        saved_count += 1
                await db.save_admin_cookies(existing_cookies)
                app.pending_admin_cookies.pop(user_id, None)
                await safe_edit_message(callback_query.message, f"✅ Saved {saved_count} new admin account(s).")
        # Admin cancel
        elif data.startswith("admincancel_"):
            parts = data.split("_")
            if len(parts) == 2 and int(parts[1]) == user_id:
                app.admin_data.pop(user_id, None)
                app.pending_admin_cookies.pop(user_id, None)
                await safe_edit_message(callback_query.message, "❌ Admin operation cancelled.")
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await safe_edit_message(callback_query.message, "❌ An error occurred. Please try again.")

# -------------------- Periodic cleanup --------------------
async def periodic_cleanup():
    while True:
        try:
            await cleanup_invalid_cookies()
            logger.info("Periodic cleanup completed")
        except Exception as e:
            logger.error(f"Error during periodic cleanup: {e}")
        await asyncio.sleep(3600)

def main():
    print("🤖 Netflix TV Login Bot is running...")
    print(f"Force Subscribe enabled: {FORCE_SUB_CHANNEL}")
    print(f"Log Channel: {LOG_CHANNEL}")
    loop = asyncio.get_event_loop()
    loop.create_task(periodic_cleanup())
    app.run()

if __name__ == "__main__":
    main()