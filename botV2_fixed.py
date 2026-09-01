import asyncio
import io
import json
import os
import sqlite3
import random
import html
import aiohttp
import re
import time

from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, events, Button, errors
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl import types
from telethon.tl.types import ReactionEmoji
from telethon.tl.types import (
    ChatBannedRights,
    UserStatusOnline,
    ChannelParticipantsAdmins
)
from telethon.tl.functions.channels import EditBannedRequest, InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest


# =========================================================
# CONFIG
# =========================================================

API_ID = 30501720

API_HASH = "93930be9066c9edcb0189e1557d32289"

BOT_TOKEN = "8679754306:AAGqyMGbHMlyyO8qUT3WQkfMmqYOXWMsMFA"


# =========================================================
# ADMIN / OWNER IDS
# =========================================================

OWNER_IDS = [6974549243, 7173443148]

ADMIN_ID = OWNER_IDS[0]
OWNER_ID = OWNER_IDS[0] if OWNER_IDS else 0

# =========================================================
# ADMIN MODERATION STORAGE
# =========================================================

warnings = {}
muted_users = {}

# =========================================================
# ALL / CALL RUNNING CHATS
# =========================================================

running_chats = set()

EMOJIS = [
    "🔍", "🚴🏾‍♂", "🫸🏿", "💁🏿",
    "🧑🏿‍⚕️", "😯", "🧒", "🔥",
    "👀", "🤖", "🎯", "💀", "👻",
    "⚡", "🌚", "🐍", "🧃", "🫆",
    "🧌", "🥷", "🫪", "👾"
]

# =========================================================
# BOT CONFIG
# =========================================================

SESSION = "daily_add_bot"

# =========================================================
# PRIVATE WRITABLE DATA DIRECTORY
# =========================================================
# Android external storage (/storage/emulated/0) can cause
# SQLite sessions to become readonly. Keep Telethon SQLite
# session files inside Termux's private HOME directory.
DATA_DIR = os.path.join(
    os.path.expanduser("~"),
    "testbot_data"
)
os.makedirs(DATA_DIR, exist_ok=True)

BOOTSTRAP_SESSION_PATH = os.path.join(
    DATA_DIR,
    "cloud_bootstrap"
)

START_BOT_SESSION_FILE = os.path.join(
    DATA_DIR,
    "start_bot_session.session"
)

USERS_FILE = "users.json"
GROUPS_FILE = "group_list.json"

# ================= LEARNING DATABASE =================
REPLY_FILE = "reply_db.json"
REPLY_MEDIA_DIR = "reply_media"

# =========================================================
# TELEGRAM FILE CLOUD SOURCE
# =========================================================
# daily_add_bot ကို မပြောင်းပါ။ ၎င်းသည် local session အဖြစ်ပဲ ဆက်သုံးမည်။
#
# start_bot_session.session နှင့် bot_data.db ကို Telegram Channel
# ထဲမှာ file အဖြစ်တင်ပြီး message URL များကို ဒီနေရာမှာထည့်ပါ။
# DB_FILE is configured above for Telegram cloud loading.
START_BOT_SESSION_URL = "https://t.me/c/4433605081/10"
DB_URL = "https://t.me/c/4433605081/7"

# =========================================================
# TELEGRAM JSON CLOUD SOURCE (TEST)
# =========================================================
# Channel ထဲမှာ JSON file ၃ ခုကို သီးခြား message အနေနဲ့တင်ပြီး
# အဲ့ဒီ message URL ၃ ခုကို ဒီနေရာမှာ ထည့်ပါ။
# Bot က Channel JSON တွေကို DOWNLOAD ပဲလုပ်မယ်။
# Channel ထဲကို automatic upload/update မလုပ်ပါ။

USERS_JSON_URL = "https://t.me/c/4433605081/5"
GROUPS_JSON_URL = "https://t.me/c/4433605081/6"
REPLY_JSON_URL = "https://t.me/c/4433605081/4"

CLOUD_JSON_FILES = {
    "users.json": USERS_JSON_URL,
    "group_list.json": GROUPS_JSON_URL,
    "reply_db.json": REPLY_JSON_URL,
}

REQUIRED_CHANNEL = "thagyitharboruto_official"
REQUIRED_GROUP = "shinobi_universe"

STICKER_ID = "BAADBQADWRsAAurp8Fa6zKIkGoUR7AI"

BOT_USERNAME = "ThaGyiTharBorutoBot"

# =========================================================
# SETADD MEMBER LIST STORAGE
# =========================================================
DB_FILE = os.path.join(DATA_DIR, "bot_data.db")
# ==========================
# CONFIG
# ==========================
CHUNK_SIZE = 20  # status ကို update လုပ်မည့် member အရေအတွက်
POWER_ANIM = ["⚡️", "⚡️⚡️", "⚡️⚡️⚡️", "⚡️⚡️⚡️⚡️", "⚡️⚡️⚡️⚡️⚡️"]

# ==========================
# DATABASE SETUP
# ==========================

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# Setadd groups table: store group_id (text), title, members_json, count, saved_at
cursor.execute("""
CREATE TABLE IF NOT EXISTS setadd_groups (
    group_key TEXT PRIMARY KEY,
    title TEXT,
    members_json TEXT,
    count INTEGER,
    saved_at INTEGER
)
""")
conn.commit()

# ==========================
# OWNER CHECK
# ==========================

def is_owner(user_id):
    return user_id == OWNER_ID

# ==========================
# HELPER FUNCTIONS
# ==========================

def normalize_key(entity):
    """Return a stable key for a chat/entity: prefer id if available, else username."""
    try:
        return str(entity.id)
    except Exception:
        try:
            return str(entity.username)
        except Exception:
            return str(entity)

async def fetch_and_save_members(source_entity):
    """Fetch participants from source_entity and return list of dicts (id, username, name)."""
    members = []
    async for user in client.iter_participants(source_entity):
        if getattr(user, "bot", False):
            continue
        members.append({
            "id": user.id, 
            "username": getattr(user, "username", None), 
            "name": (user.first_name or "")
        })
    return members

# =========================================================
# CLIENT
# =========================================================

# =========================================================
# CLOUD FILE BOOTSTRAP
# =========================================================
# daily_add_bot ကို မူလအတိုင်းပဲ အသုံးပြုပါတယ်။
# Channel ထဲက start_bot_session.session / bot_data.db ကို
# အရင် download လုပ်ပြီးမှ main client ကို စတင်ပါတယ်။

# =========================================================
# MAIN CLIENT
# =========================================================

print(f"📁 Telethon session directory: {DATA_DIR}")
print(f"📁 Main session: {START_BOT_SESSION_FILE}")
print(f"📁 Database: {DB_FILE}")
bot = TelegramClient(
    START_BOT_SESSION_FILE,
    API_ID,
    API_HASH
).start(
    bot_token=BOT_TOKEN
)

# Existing code uses both `bot` and `client`.
# Keep both names pointing to the same Telethon client.
client = bot

# =========================================================
# FORCE CHANNEL + GROUP JOIN CHECK FOR EVERY COMMAND
# =========================================================
# /start ကိုတော့ မူလ /start flow အတိုင်း အလုပ်လုပ်ခွင့်ပေးထားပါတယ်။
# တခြား command အားလုံးကို command handler မစခင် Join စစ်ပါတယ်။

async def require_join_for_command(event):
    try:
        # Command မဟုတ်ရင် မစစ်
        text = (event.raw_text or "").strip()
        if not text.startswith("/"):
            return False

        # /start ကို မူလ start handler အတိုင်းထား
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command == "/start":
            return False

        # Bot owner တွေကို မူလ /start owner behavior နဲ့အညီ bypass
        if event.sender_id in OWNER_IDS:
            return False

        user_id = event.sender_id
        if not user_id:
            return False

        joined = await is_joined(user_id)
        if joined:
            return False

        mention = f"<a href='tg://user?id={user_id}'>User</a>"
        try:
            sender = await event.get_sender()
            first_name = getattr(sender, "first_name", None) or "User"
            mention = (
                f"<a href='tg://user?id={user_id}'>"
                f"{html.escape(first_name)}"
                f"</a>"
            )
        except Exception:
            pass

        text = (
            f"<blockquote>"
            f"⚠️ Hello {mention}!\n\n"
            f"Bot Command တွေကို အသုံးပြုရန်\n"
            f"📢 Channel နဲ့ 👥 Group နှစ်ခုလုံးကို Join လုပ်ထားရပါမယ်။"
            f"</blockquote>"
        )

        buttons = [
            [
                Button.url(
                    "📢 Join Channel",
                    f"https://t.me/{REQUIRED_CHANNEL}"
                )
            ],
            [
                Button.url(
                    "👥 Join Group",
                    f"https://t.me/{REQUIRED_GROUP}"
                )
            ],
            [
                Button.inline(
                    "✅ Verify",
                    b"verify_join"
                )
            ]
        ]

        # Private / Group နှစ်မျိုးလုံးမှာ command message ကို reply ပြန်မယ်။
        await event.reply(
            text,
            buttons=buttons,
            parse_mode="html"
        )

        return True

    except Exception as e:
        print("Command Join Check Error:", e)
        return False


# ဒီ handler ကို command handlers အားလုံးမတိုင်ခင် register လုပ်ထားရပါတယ်။
@bot.on(events.NewMessage(incoming=True))
async def global_command_join_gate(event):
    try:
        if not (event.raw_text or "").strip().startswith("/"):
            return

        blocked = await require_join_for_command(event)
        if blocked:
            raise events.StopPropagation

    except events.StopPropagation:
        raise
    except Exception as e:
        print("Global Command Join Gate Error:", e)

# =========================================================
# CREATE MEDIA DIRECTORY
# =========================================================

os.makedirs(
    REPLY_MEDIA_DIR,
    exist_ok=True
)


# =========================================================
# JSON LOCK
# =========================================================

json_lock = asyncio.Lock()


# =========================================================
# JSON DATABASE HELPERS
# =========================================================

def load_json(filename, default=None):

    if default is None:
        default = {}

    try:

        if not os.path.exists(filename):
            return default

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return data

    except Exception as e:

        print(
            f"JSON Load Error [{filename}]:",
            e
        )

        return default


def save_json(filename, data):

    temp_file = filename + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

        os.replace(
            temp_file,
            filename
        )

    except Exception as e:

        print(
            f"JSON Save Error [{filename}]:",
            e
        )

        try:

            if os.path.exists(temp_file):
                os.remove(temp_file)

        except Exception:
            pass


# =========================================================
# TELEGRAM JSON CLOUD HELPERS
# =========================================================

async def download_telegram_file_from_url(url, filename, expected_name=None):
    """Download a Telegram file from a message URL."""
    if not url or "PASTE_" in url or "your_channel" in url:
        raise ValueError(f"URL မထည့်ရသေးပါ: {filename}")

    chat, message_id = parse_telegram_message_url(url)
    message = await client.get_messages(chat, ids=message_id)

    if not message:
        raise ValueError(f"Message မတွေ့ပါ: {url}")
    if not message.file:
        raise ValueError(f"Message မှာ file မပါပါ: {url}")

    cloud_name = getattr(message.file, "name", None) or ""
    if expected_name and cloud_name and cloud_name != expected_name:
        raise ValueError(
            f"File name မကိုက်ပါ: {cloud_name} (expected: {expected_name})"
        )

    temp_file = filename + ".cloud.tmp"
    try:
        await client.download_media(message, file=temp_file)

        if not os.path.exists(temp_file):
            raise ValueError(f"{filename} download မအောင်မြင်ပါ")

        os.replace(temp_file, filename)

        # Telethon's SQLite session must be writable.
        try:
            os.chmod(filename, 0o600)
        except Exception:
            pass

        return True
    finally:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass


async def load_cloud_session_and_db():
    """Load start_bot_session.session and bot_data.db from Telegram."""
    results = []

    for url, filename in (
        (START_BOT_SESSION_URL, START_BOT_SESSION_FILE),
        (DB_URL, DB_FILE),
    ):
        try:
            await download_telegram_file_from_url(
                url,
                filename,
                expected_name=filename
            )
            results.append(f"✅ {filename}: Loaded")
        except Exception as e:
            results.append(f"❌ {filename}: {e}")
            print(f"Cloud File Load Error [{filename}]: {e}")

    return results


def parse_telegram_message_url(url):
    """Return (chat, message_id) from common Telegram message URLs."""
    if not url or "your_channel" in url:
        raise ValueError("JSON URL မထည့်ရသေးပါ")

    url = url.strip().rstrip("/")
    m = re.match(r"^https?://t\.me/(?:s/)?([^/]+)/([0-9]+)$", url)
    if m:
        chat = m.group(1)
        return chat, int(m.group(2))

    # Private/supergroup/channel message links: https://t.me/c/1234567890/123
    m = re.match(r"^https?://t\.me/c/([0-9]+)/([0-9]+)$", url)
    if m:
        internal_id = int(m.group(1))
        chat = int(f"-100{internal_id}")
        return chat, int(m.group(2))

    raise ValueError("Telegram message URL ပုံစံမမှန်ပါ")


async def download_json_from_telegram(url, filename):
    """Download one JSON document from a Telegram message."""
    chat, message_id = parse_telegram_message_url(url)
    message = await client.get_messages(chat, ids=message_id)

    if not message:
        raise ValueError(f"Message မတွေ့ပါ: {url}")

    if not message.file:
        raise ValueError(f"Message မှာ file မပါပါ: {url}")

    file_name = getattr(message.file, "name", None) or ""
    if file_name and not file_name.lower().endswith(".json"):
        raise ValueError(f"JSON file မဟုတ်ပါ: {file_name}")

    # Download to a temporary file first so an interrupted download
    # never destroys the existing local database.
    temp_file = filename + ".cloud.tmp"
    try:
        await client.download_media(message, file=temp_file)
        if not os.path.exists(temp_file):
            raise ValueError("JSON file download မအောင်မြင်ပါ")

        with open(temp_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate the JSON before replacing the local file.
        save_json(filename, data)
        return True, data
    finally:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass


async def load_cloud_jsons(show_result=False):
    """Load all three JSON databases from their Telegram message URLs."""
    results = []

    for filename, url in CLOUD_JSON_FILES.items():
        if not url or "your_channel" in url:
            results.append(f"⚠️ {filename}: URL မထည့်ရသေးပါ")
            continue

        try:
            await download_json_from_telegram(url, filename)
            results.append(f"✅ {filename}: Loaded")
        except Exception as e:
            # Keep the existing local file if cloud loading fails.
            results.append(f"❌ {filename}: {e}")
            print(f"Cloud JSON Load Error [{filename}]: {e}")

    if show_result:
        return "\n".join(results)
    return results


# Bot start မလုပ်ခင် Channel JSON ၃ ခုကို local JSON အဖြစ် load လုပ်ပါ။
# Download မအောင်မြင်ရင် ရှိပြီးသား local JSON ကို မဖျက်ဘဲ ဆက် run ပါမယ်။
try:
    bot.loop.run_until_complete(load_cloud_jsons())
except Exception as e:
    print("Cloud JSON Startup Error:", e)



# =========================================================
# CLOSE LOCAL DB BEFORE CLOUD RESTORE
# =========================================================
# The cloud DB will replace the SQLite file. Close the old connection
# first so the cursor does not keep pointing at the old inode.
try:
    conn.close()
except Exception:
    pass

# =========================================================
# CLOUD SESSION + DB BOOTSTRAP
# =========================================================

bootstrap_client = TelegramClient(
    BOOTSTRAP_SESSION_PATH,
    API_ID,
    API_HASH
).start(
    bot_token=BOT_TOKEN
)

client = bootstrap_client

try:
    bootstrap_client.loop.run_until_complete(
        load_cloud_session_and_db()
    )
finally:
    try:
        bootstrap_client.disconnect()
    except Exception:
        pass

# =========================================================
# REOPEN DATABASE AFTER CLOUD RESTORE
# =========================================================
conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS setadd_groups (
    group_key TEXT PRIMARY KEY,
    title TEXT,
    members_json TEXT,
    count INTEGER,
    saved_at INTEGER
)
""")
conn.commit()

# =========================================================
# CREATE JSON FILES
# =========================================================

if not os.path.exists(USERS_FILE):

    save_json(
        USERS_FILE,
        {}
    )


if not os.path.exists(GROUPS_FILE):

    save_json(
        GROUPS_FILE,
        {}
    )


if not os.path.exists(REPLY_FILE):

    save_json(
        REPLY_FILE,
        {
            "__offrp__": []
        }
    )


# =========================================================
# LEARNING CACHE
# =========================================================

reply_db = load_json(
    REPLY_FILE,
    {
        "__offrp__": []
    }
)

if "__offrp__" not in reply_db:

    reply_db["__offrp__"] = []

    save_json(
        REPLY_FILE,
        reply_db
    )


# =========================================================
# REPLY CACHE
# =========================================================

shuffle_cache = {}

last_sent = {}


# =========================================================
# REPLY DATABASE SAVE
# =========================================================

def save_reply_db():

    save_json(
        REPLY_FILE,
        reply_db
    )


# =========================================================
# NORMALIZE LEARNING KEY
# =========================================================

def normalize_reply_key(text):

    if not text:
        return ""

    return (
        text
        .lower()
        .strip()
    )


# =========================================================
# CHECK ADMIN / OWNER
# =========================================================

async def is_admin_or_owner(event):

    try:

        sender = await event.get_sender()

        if not sender:
            return False

        # OWNER
        if sender.id in OWNER_IDS:
            return True

        # ADMIN
        if event.is_group:

            try:

                perms = await bot.get_permissions(
                    event.chat_id,
                    sender.id
                )

                if (
                    perms.is_admin
                    or perms.is_creator
                ):

                    return True

            except Exception:
                pass

    except Exception:
        pass

    return False

# =========================================================
# MODERATION RIGHTS
# =========================================================

def mute_rights(until_date=None):
    return ChatBannedRights(
        until_date=until_date,
        send_messages=True
    )


def unmute_rights():
    return ChatBannedRights(
        until_date=None,
        send_messages=False,
        view_messages=False
    )


def ban_rights():
    return ChatBannedRights(
        until_date=None,
        view_messages=True
    )


# =========================================================
# GET MODERATION TARGET
# =========================================================

async def get_moderation_target(event):

    # =====================================================
    # REPLY
    # =====================================================

    if event.is_reply:

        try:

            reply = await event.get_reply_message()

            if reply and reply.sender_id:

                user = await reply.get_sender()

                return reply.sender_id, user

        except Exception:

            pass


    # =====================================================
    # USERNAME / USER ID
    # =====================================================

    args = event.raw_text.split()

    if len(args) < 2:
        return None


    target = None

    for arg in args[1:]:

        # Skip duration
        if (
            arg.endswith("m")
            or arg.endswith("h")
            or arg.endswith("d")
        ):
            continue

        # Skip number
        if arg.isdigit():
            continue

        target = arg
        break


    if not target:
        return None


    try:

        if target.startswith("@"):

            target = target[1:]


        if target.isdigit():

            entity = await bot.get_entity(
                int(target)
            )

        else:

            entity = await bot.get_entity(
                target
            )


        return entity.id, entity


    except Exception:

        return None


# =========================================================
# USER DISPLAY NAME
# =========================================================

def moderation_user_name(user):

    if not user:
        return "User"


    first = getattr(
        user,
        "first_name",
        None
    ) or ""


    last = getattr(
        user,
        "last_name",
        None
    ) or ""


    name = (
        f"{first} {last}"
        .strip()
    )


    return name or "User"


# =========================================================
# OWNER PROTECTION HELPERS
# =========================================================

async def notify_owner(owner_id, chat_id, action):
    """Notify an owner when Owner Protection restores their permissions."""
    try:
        chat = await bot.get_entity(chat_id)
        group_link = await get_group_link(chat)

        if action == "unban":
            text = f"""
<blockquote expandable>
🚨 <b>Owner Protection</b>

မင်းကို Group တစ်ခုမှာ
<b>Ban</b> လုပ်ထားတာ တွေ့လို့
Bot က အလိုအလျောက် <b>Unban</b> လုပ်ပေးလိုက်ပြီ။

🔗 <b>Group Link :</b>
{html.escape(group_link)}
</blockquote>
"""
        elif action == "unmute":
            text = f"""
<blockquote expandable>
🚨 <b>Owner Protection</b>

မင်းကို Group တစ်ခုမှာ
<b>Mute</b> လုပ်ထားတာ တွေ့လို့
Bot က အလိုအလျောက် <b>Unmute</b> လုပ်ပေးလိုက်ပြီ။

🔗 <b>Group Link :</b>
{html.escape(group_link)}
</blockquote>
"""
        else:
            text = f"""
<blockquote expandable>
🚨 <b>Owner Protection</b>

Owner Protection က
မင်းရဲ့ Permission ကို ပြန်ပြင်ပေးလိုက်ပြီ။

🔗 <b>Group Link :</b>
{html.escape(group_link)}
</blockquote>
"""

        await bot.send_message(
            owner_id,
            text,
            parse_mode="html"
        )

    except Exception as e:
        print("Owner Notification Error:", e)


async def check_owner_mute_status(chat_id, notify=True):
    """
    /mute command အသုံးပြုပီးနောက် ခေါ်သုံးသည်။
    OWNER_IDS ထဲက Owner တွေ ဒီ Group ထဲမှာ ရှိမရှိစစ်ပြီး
    ရှိနေရင် Member လား Admin လား စစ်မယ်။
    Owner က Member ဖြစ်ပြီး Permission မှာ
    စာပို့ခွင့် (send_messages) ပိတ်ခံထားရရင်
    (Mute ခံထားရရင်) Bot က Auto Unmute လုပ်ပေးမယ်။
    (Ban ဖြစ်မဖြစ်ကို ဒီနေရာမှာ မစစ်ပါ)
    """
    changed = False

    for owner_id in OWNER_IDS:
        try:
            perms = await bot.get_permissions(
                chat_id,
                owner_id
            )
        except Exception:
            # Owner ဟာ ဒီ Group ထဲမှာ မရှိပါ
            continue

        is_admin_or_creator = bool(
            getattr(perms, "is_admin", False)
            or getattr(perms, "is_creator", False)
        )

        # Owner က Admin/Creator ဖြစ်နေရင် Mute Permission
        # စစ်ရန်မလိုပါ (Member ဖြစ်မှသာ စစ်မည်)
        if is_admin_or_creator:
            continue

        is_muted = (
            hasattr(perms, "send_messages")
            and perms.send_messages is False
        )

        if is_muted:
            try:
                await bot(
                    EditBannedRequest(
                        chat_id,
                        owner_id,
                        unmute_rights()
                    )
                )

                changed = True

                if notify:
                    await notify_owner(
                        owner_id,
                        chat_id,
                        "unmute"
                    )

            except Exception as e:
                print("Owner Unmute Error:", e)

    return changed


async def check_owner_ban_status(chat_id, notify=True):
    """
    /ban command အသုံးပြုပီးနောက် ခေါ်သုံးသည်။
    OWNER_IDS ထဲက Owner တွေ ဒီ Group ရဲ့ Banned List ထဲမှာ
    ရှိနေရင် Bot က Auto Unban လုပ်ပြီး
    Group Link ကို Owner ရဲ့ DM ထဲကို ပို့ပေးမယ်။
    (Mute ဖြစ်မဖြစ်ကို ဒီနေရာမှာ မစစ်ပါ)
    """
    changed = False

    for owner_id in OWNER_IDS:
        try:
            perms = await bot.get_permissions(
                chat_id,
                owner_id
            )
        except Exception:
            continue

        is_banned = bool(
            getattr(perms, "is_banned", False)
        )

        if is_banned:
            try:
                await bot(
                    EditBannedRequest(
                        chat_id,
                        owner_id,
                        unmute_rights()
                    )
                )

                changed = True

                if notify:
                    await notify_owner(
                        owner_id,
                        chat_id,
                        "unban"
                    )

            except Exception as e:
                print("Owner Unban Error:", e)

    return changed


async def delayed_owner_mute_protection(chat_id):
    """/mute ပြီး 5 seconds နောက် Owner Mute Status ပြန်စစ်ပေးတယ်."""
    try:
        await asyncio.sleep(5)
        await check_owner_mute_status(
            chat_id,
            notify=True
        )
    except Exception as e:
        print("Delayed Owner Mute Protection Error:", e)


async def delayed_owner_ban_protection(chat_id):
    """/ban ပြီး 5 seconds နောက် Owner Ban Status ပြန်စစ်ပေးတယ်."""
    try:
        await asyncio.sleep(5)
        await check_owner_ban_status(
            chat_id,
            notify=True
        )
    except Exception as e:
        print("Delayed Owner Ban Protection Error:", e)


# =========================================================
# OWNER PROTECT
# =========================================================

@bot.on(events.ChatAction())
async def owner_protect(event):

    try:

        if not event.is_group:
            return


        if not event.user_id:
            return


        # =================================================
        # OWNER ONLY
        # =================================================

        if event.user_id not in OWNER_IDS:
            return


        # =================================================
        # OWNER KICK / BAN ဖြစ်ရင် ပြန် UNBAN
        # =================================================

        if (
            event.user_kicked
            or event.user_banned
        ):

            try:

                await bot(
                    EditBannedRequest(
                        event.chat_id,
                        event.user_id,
                        unmute_rights()
                    )
                )

            except Exception as e:

                print(
                    "Owner Unban Error:",
                    e
                )


        # =================================================
        # OWNER MUTE ဖြစ်နေရင် UNMUTE
        # =================================================

        try:

            perms = await bot.get_permissions(
                event.chat_id,
                event.user_id
            )


            if hasattr(
                perms,
                "send_messages"
            ):

                if perms.send_messages is False:

                    await bot(
                        EditBannedRequest(
                            event.chat_id,
                            event.user_id,
                            unmute_rights()
                        )
                    )

        except Exception:

            pass


    except Exception as e:

        print(
            "Owner Protect Error:",
            e
        )


# =========================================================
# /WARN
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/warn(?:@\w+)?(?:\s+(\d+))?(?:\s+(.+))?$"
    )
)
async def warn_user(event):

    try:

        if not event.is_group:
            return


        if not await is_admin_or_owner(event):

            return await event.reply(
                "<blockquote>"
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
                "</blockquote>",
                parse_mode="html"
            )


        target_data = (
            await get_moderation_target(event)
        )


        if not target_data:

            return await event.reply(
                "<blockquote>"
                "⚠️ Reply သို့မဟုတ် "
                "/warn @user"
                "</blockquote>",
                parse_mode="html"
            )


        user_id, user_obj = target_data


        # =================================================
        # OWNER PROTECT
        # =================================================

        if user_id in OWNER_IDS:

            return await event.reply(
                "<blockquote>"
                "👑 The Last Shinobi ကို Warn လုပ်လို့မရဘူး"
                "</blockquote>",
                parse_mode="html"
            )


        user_name = moderation_user_name(
            user_obj
        )


        amount = (
            event.pattern_match.group(1)
        )


        change = (
            int(amount)
            if amount
            else 1
        )


        # =================================================
        # GROUP + USER ID နဲ့ WARN သိမ်း
        # =================================================

        warning_key = (
            event.chat_id,
            user_id
        )


        current = warnings.get(
            warning_key,
            0
        )


        new = max(
            0,
            current + change
        )


        warnings[
            warning_key
        ] = new


        # =================================================
        # AUTO MUTE
        # =================================================

        if new >= 3:

            try:

                until = (
                    datetime.now(
                        timezone.utc
                    )
                    + timedelta(
                        hours=1
                    )
                )


                await bot(
                    EditBannedRequest(
                        event.chat_id,
                        user_id,
                        mute_rights(until)
                    )
                )


                muted_users[
                    warning_key
                ] = until


                warnings[
                    warning_key
                ] = 0


                text = (
                    "<blockquote expandable>\n"
                    f"🔇 {html.escape(user_name)}\n\n"
                    "Warn 3 ကြိမ် ပြည့်သွားလို့\n"
                    "1 နာရီ Mute လုပ်လိုက်ပြီ\n"
                    "</blockquote>"
                )


            except Exception as e:

                text = (
                    "<blockquote expandable>\n"
                    "❌ Failed\n\n"
                    f"<code>{html.escape(str(e))}</code>\n"
                    "</blockquote>"
                )


        else:

            text = (
                "<blockquote expandable>\n"
                f"⚠️ {html.escape(user_name)}\n\n"
                "Warning ပါ 3 ကြိမ်ပြည့်ရင်\n"
                "1 နာရီ Auto Mute ပါတယ်\n\n"
                f"Current Warn :\n"
                f"{new}/3\n"
                "</blockquote>"
            )


        await event.reply(
            text,
            parse_mode="html"
        )


    except Exception as e:

        print(
            "Warn Error:",
            e
        )


# =========================================================
# /BAN
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/ban(?:@\w+)?(?:\s+(.+))?$"
    )
)
async def ban_user(event):

    try:

        if not event.is_group:
            return


        if not await is_admin_or_owner(event):

            return await event.reply(
                "<blockquote>"
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
                "</blockquote>",
                parse_mode="html"
            )


        target_data = (
            await get_moderation_target(event)
        )


        if not target_data:

            return await event.reply(
                "<blockquote>"
                "⚠️ Reply သို့မဟုတ် "
                "/ban @user"
                "</blockquote>",
                parse_mode="html"
            )


        user_id, user_obj = target_data


        if user_id in OWNER_IDS:

            return await event.reply(
                "<blockquote>"
                "👑 The Last Shinobi ကို Ban လုပ်လို့မရဘူး"
                "</blockquote>",
                parse_mode="html"
            )


        user_name = moderation_user_name(
            user_obj
        )


        await bot(
            EditBannedRequest(
                event.chat_id,
                user_id,
                ban_rights()
            )
        )

        # 5 seconds later, verify that no OWNER was banned.
        asyncio.create_task(
            delayed_owner_ban_protection(
                event.chat_id
            )
        )


        await event.reply(
            "<blockquote expandable>\n"
            f"🚫 {html.escape(user_name)}\n\n"
            "Ban လိုက်ပြီ\n"
            "</blockquote>",
            parse_mode="html"
        )


    except Exception as e:

        await event.reply(
            "<blockquote expandable>\n"
            "❌ Failed\n\n"
            f"<code>{html.escape(str(e))}</code>\n"
            "</blockquote>",
            parse_mode="html"
        )


# =========================================================
# /UNBAN
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/unban(?:@\w+)?(?:\s+(.+))?$"
    )
)
async def unban_user(event):

    try:

        if not event.is_group:
            return


        if not await is_admin_or_owner(event):

            return await event.reply(
                "<blockquote>"
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
                "</blockquote>",
                parse_mode="html"
            )


        target_data = (
            await get_moderation_target(event)
        )


        if not target_data:

            return await event.reply(
                "<blockquote>"
                "⚠️ Reply သို့မဟုတ် "
                "/unban @user"
                "</blockquote>",
                parse_mode="html"
            )


        user_id, user_obj = target_data


        user_name = moderation_user_name(
            user_obj
        )


        await bot(
            EditBannedRequest(
                event.chat_id,
                user_id,
                unmute_rights()
            )
        )


        warnings.pop(
            (
                event.chat_id,
                user_id
            ),
            None
        )


        muted_users.pop(
            (
                event.chat_id,
                user_id
            ),
            None
        )


        await event.reply(
            "<blockquote expandable>\n"
            f"✅ {html.escape(user_name)}\n\n"
            "Ban ဖြည်လိုက်ပါပြီ\n"
            "</blockquote>",
            parse_mode="html"
        )


    except Exception as e:

        await event.reply(
            "<blockquote expandable>\n"
            "❌ Failed\n\n"
            f"<code>{html.escape(str(e))}</code>\n"
            "</blockquote>",
            parse_mode="html"
        )


# =========================================================
# /MUTE
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/mute(?:@\w+)?(?:\s+(.+))?$"
    )
)
async def mute_user(event):

    try:

        if not event.is_group:
            return


        if not await is_admin_or_owner(event):

            return await event.reply(
                "<blockquote>"
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
                "</blockquote>",
                parse_mode="html"
            )


        target_data = (
            await get_moderation_target(event)
        )


        if not target_data:

            return await event.reply(
                "<blockquote>"
                "⚠️ Reply သို့မဟုတ် "
                "/mute @user"
                "</blockquote>",
                parse_mode="html"
            )


        user_id, user_obj = target_data


        if user_id in OWNER_IDS:

            return await event.reply(
                "<blockquote>"
                "👑 The Last Shinobi ကို Mute လုပ်လို့မရဘူး"
                "</blockquote>",
                parse_mode="html"
            )


        user_name = moderation_user_name(
            user_obj
        )


        # =================================================
        # DURATION
        # =================================================

        args = event.raw_text.split()

        until = None

        mute_text = (
            "ပြန်မဖွင့်မချင်း"
        )


        for arg in args:

            try:

                if arg.endswith("m"):

                    amount = int(
                        arg[:-1]
                    )

                    if amount <= 0:
                        continue


                    until = (
                        datetime.now(
                            timezone.utc
                        )
                        + timedelta(
                            minutes=amount
                        )
                    )


                    mute_text = (
                        f"{amount} မိနစ်"
                    )


                elif arg.endswith("h"):

                    amount = int(
                        arg[:-1]
                    )

                    if amount <= 0:
                        continue


                    until = (
                        datetime.now(
                            timezone.utc
                        )
                        + timedelta(
                            hours=amount
                        )
                    )


                    mute_text = (
                        f"{amount} နာရီ"
                    )


                elif arg.endswith("d"):

                    amount = int(
                        arg[:-1]
                    )

                    if amount <= 0:
                        continue


                    until = (
                        datetime.now(
                            timezone.utc
                        )
                        + timedelta(
                            days=amount
                        )
                    )


                    mute_text = (
                        f"{amount} ရက်"
                    )


            except Exception:

                pass


        await bot(
            EditBannedRequest(
                event.chat_id,
                user_id,
                mute_rights(until)
            )
        )

        # 5 seconds later, verify that no OWNER was muted.
        asyncio.create_task(
            delayed_owner_mute_protection(
                event.chat_id
            )
        )


        warning_key = (
            event.chat_id,
            user_id
        )


        muted_users[
            warning_key
        ] = until


        await event.reply(
            "<blockquote expandable>\n"
            f"🔇 {html.escape(user_name)}\n\n"
            "ရှူးးး မင်းကို စကားပြောခွင့် "
            "ပိတ်လိုက်ပြီ :\n"
            f"{mute_text}\n"
            "</blockquote>",
            parse_mode="html"
        )


    except Exception as e:

        await event.reply(
            "<blockquote expandable>\n"
            "❌ Failed\n\n"
            f"<code>{html.escape(str(e))}</code>\n"
            "</blockquote>",
            parse_mode="html"
        )


# =========================================================
# /UNMUTE
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/unmute(?:@\w+)?(?:\s+(.+))?$"
    )
)
async def unmute_user(event):

    try:

        if not event.is_group:
            return


        if not await is_admin_or_owner(event):

            return await event.reply(
                "<blockquote>"
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
                "</blockquote>",
                parse_mode="html"
            )


        target_data = (
            await get_moderation_target(event)
        )


        if not target_data:

            return await event.reply(
                "<blockquote>"
                "⚠️ Reply သို့မဟုတ် "
                "/unmute @user"
                "</blockquote>",
                parse_mode="html"
            )


        user_id, user_obj = target_data


        user_name = moderation_user_name(
            user_obj
        )


        await bot(
            EditBannedRequest(
                event.chat_id,
                user_id,
                unmute_rights()
            )
        )


        warning_key = (
            event.chat_id,
            user_id
        )


        muted_users.pop(
            warning_key,
            None
        )


        await event.reply(
            "<blockquote expandable>\n"
            f"🔊 {html.escape(user_name)}\n\n"
            "စကားပြောလို့ရပီ\n"
            "</blockquote>",
            parse_mode="html"
        )


    except Exception as e:

        await event.reply(
            "<blockquote expandable>\n"
            "❌ Failed\n\n"
            f"<code>{html.escape(str(e))}</code>\n"
            "</blockquote>",
            parse_mode="html"
        )

# =========================================================
# LEARNING SYSTEM
# =========================================================
#
# User:
#   နေကောင်းလား
#
# User Reply:
#   ကောင်းပါတယ်
#
# Bot learns:
#
# {
#   "နေကောင်းလား": [
#       {
#           "type": "text",
#           "content": "ကောင်းပါတယ်"
#       }
#   ]
# }
#
# =========================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def learn_reply(event):

    try:

        # =====================================================
        # GROUP / PRIVATE ONLY
        # =====================================================

        if not (
            event.is_group
            or event.is_private
        ):

            return


        # =====================================================
        # SENDER
        # =====================================================

        sender = await event.get_sender()

        if not sender:
            return


        # =====================================================
        # IGNORE BOT
        # =====================================================

        if getattr(
            sender,
            "bot",
            False
        ):

            return


        # =====================================================
        # IGNORE OUR OWN MESSAGE
        # =====================================================

        me = await bot.get_me()

        if event.sender_id == me.id:
            return


        # =====================================================
        # MUST BE REPLY
        # =====================================================

        if not event.is_reply:
            return


        # =====================================================
        # GET ORIGINAL MESSAGE
        # =====================================================

        original_msg = (
            await event.get_reply_message()
        )

        if not original_msg:
            return


        # =====================================================
        # ORIGINAL MUST BE TEXT
        # =====================================================

        original_text = (
            original_msg.raw_text
            or ""
        )

        if not original_text.strip():
            return


        # =====================================================
        # NORMALIZE ORIGINAL
        # =====================================================

        original = normalize_reply_key(
            original_text
        )

        if not original:
            return


        # =====================================================
        # IGNORE COMMAND
        # =====================================================

        if original.startswith("/"):
            return


        # =====================================================
        # OFF RP DOES NOT MEAN STOP LEARNING
        #
        # Learning ဆက်လုပ်မယ်။
        # Auto Reply ပဲ OFF ဖြစ်မယ်။
        # =====================================================


        # =====================================================
        # CREATE KEY
        # =====================================================

        if original not in reply_db:

            reply_db[original] = []


        # =====================================================
        # SAVE TEXT REPLY
        # =====================================================

        if event.raw_text:

            reply_text = (
                event.raw_text.strip()
            )

            if not reply_text:
                return


            # Ignore commands
            if reply_text.startswith("/"):
                return


            # Same text skip
            if (
                reply_text.lower()
                == original
            ):

                return


            # Duplicate check
            exists = any(

                r.get("type") == "text"

                and

                r.get("content")
                == reply_text

                for r in reply_db[original]

            )


            if not exists:

                reply_db[original].append({

                    "type": "text",

                    "content": reply_text

                })

                save_reply_db()

                # Reset shuffle
                shuffle_cache.pop(
                    original,
                    None
                )

                print(
                    "✅ Learned Text:",
                    original,
                    "->",
                    reply_text
                )

            return


        # =====================================================
        # SAVE STICKER
        # =====================================================

        if event.sticker:

            try:

                filename = (
                    f"sticker_"
                    f"{event.id}_"
                    f"{timestamp()}.webp"
                )

                filepath = os.path.join(
                    REPLY_MEDIA_DIR,
                    filename
                )

                await event.download_media(
                    file=filepath
                )

                if not os.path.exists(
                    filepath
                ):

                    return


                exists = any(

                    r.get("type")
                    == "sticker"

                    and

                    r.get("content")
                    == filepath

                    for r in reply_db[original]

                )


                if not exists:

                    reply_db[original].append({

                        "type": "sticker",

                        "content": filepath

                    })

                    save_reply_db()

                    shuffle_cache.pop(
                        original,
                        None
                    )

                    print(
                        "✅ Learned Sticker:",
                        original
                    )

            except Exception as e:

                print(
                    "Sticker Learning Error:",
                    e
                )

            return


        # =====================================================
        # SAVE VOICE
        # =====================================================

        if event.voice:

            try:

                filename = (
                    f"voice_"
                    f"{event.id}_"
                    f"{timestamp()}.ogg"
                )

                filepath = os.path.join(
                    REPLY_MEDIA_DIR,
                    filename
                )

                await event.download_media(
                    file=filepath
                )

                if not os.path.exists(
                    filepath
                ):

                    return


                exists = any(

                    r.get("type")
                    == "voice"

                    and

                    r.get("content")
                    == filepath

                    for r in reply_db[original]

                )


                if not exists:

                    reply_db[original].append({

                        "type": "voice",

                        "content": filepath

                    })

                    save_reply_db()

                    shuffle_cache.pop(
                        original,
                        None
                    )

                    print(
                        "✅ Learned Voice:",
                        original
                    )

            except Exception as e:

                print(
                    "Voice Learning Error:",
                    e
                )

            return


    except Exception as e:

        print(
            "Learning System Error:",
            e
        )


# =========================================================
# AUTO REPLY SYSTEM
# =========================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def auto_reply(event):

    try:

        # =====================================================
        # GROUP / PRIVATE
        # =====================================================

        if not (
            event.is_group
            or event.is_private
        ):

            return


        # =====================================================
        # SENDER
        # =====================================================

        sender = await event.get_sender()

        if not sender:
            return


        # =====================================================
        # IGNORE BOT
        # =====================================================

        if getattr(
            sender,
            "bot",
            False
        ):

            return


        # =====================================================
        # IGNORE OUR OWN MESSAGE
        # =====================================================

        me = await bot.get_me()

        if event.sender_id == me.id:
            return


        # =====================================================
        # TEXT ONLY FOR KEY
        # =====================================================

        if not event.raw_text:
            return


        # =====================================================
        # NORMALIZE
        # =====================================================

        key = normalize_reply_key(
            event.raw_text
        )

        if not key:
            return


        # =====================================================
        # IGNORE COMMANDS
        # =====================================================

        if key.startswith("/"):
            return


        # =====================================================
        # GROUP OFF RP CHECK
        # =====================================================

        if event.is_group:

            chat_id = str(
                event.chat_id
            )

            off_list = reply_db.get(
                "__offrp__",
                []
            )

            if chat_id in off_list:

                return


        # =====================================================
        # KEY CHECK
        # =====================================================

        if key not in reply_db:
            return


        replies = reply_db.get(
            key,
            []
        )

        if not replies:
            return


        # =====================================================
        # REMOVE INVALID MEDIA
        # =====================================================

        valid_replies = []

        for reply in replies:

            if not isinstance(
                reply,
                dict
            ):
                continue

            reply_type = reply.get(
                "type"
            )

            content = reply.get(
                "content"
            )

            if not content:
                continue

            if reply_type == "text":

                valid_replies.append(
                    reply
                )

            elif reply_type in (
                "sticker",
                "voice"
            ):

                if os.path.exists(
                    content
                ):

                    valid_replies.append(
                        reply
                    )


        if not valid_replies:
            return


        # =====================================================
        # SHUFFLE
        # =====================================================

        if (
            key not in shuffle_cache
            or not shuffle_cache[key]
        ):

            shuffle_cache[key] = (
                valid_replies[:]
            )

            random.shuffle(
                shuffle_cache[key]
            )


        chosen = (
            shuffle_cache[key].pop()
        )


        # =====================================================
        # PREVENT SAME REPLY
        # =====================================================

        previous = last_sent.get(
            key
        )

        if previous:

            previous_type = previous.get(
                "type"
            )

            previous_content = previous.get(
                "content"
            )

            if (

                chosen.get("type")
                == previous_type

                and

                chosen.get("content")
                == previous_content

            ):

                alternatives = [

                    r

                    for r in valid_replies

                    if not (

                        r.get("type")
                        == previous_type

                        and

                        r.get("content")
                        == previous_content

                    )

                ]

                if alternatives:

                    chosen = random.choice(
                        alternatives
                    )


        last_sent[key] = chosen


        # =====================================================
        # TEXT REPLY
        # =====================================================

        if chosen.get(
            "type"
        ) == "text":

            text = (
                chosen.get(
                    "content",
                    ""
                )
                .strip()
            )

            if not text:
                return


            # Don't reply same sentence
            if (
                text.lower()
                == key
            ):

                return


            # Escape HTML
            safe_text = html.escape(
                text
            )


            # =================================================
            # QUOTE STYLE
            # =================================================

            await event.reply(

                f"<blockquote><b>{safe_text}</b></blockquote>",

                parse_mode="html"

            )

            return


        # =====================================================
        # STICKER REPLY
        # =====================================================

        if chosen.get(
            "type"
        ) == "sticker":

            filepath = chosen.get(
                "content"
            )

            if (
                filepath
                and os.path.exists(
                    filepath
                )
            ):

                await event.reply(
                    file=filepath
                )

            return


        # =====================================================
        # VOICE REPLY
        # =====================================================

        if chosen.get(
            "type"
        ) == "voice":

            filepath = chosen.get(
                "content"
            )

            if (
                filepath
                and os.path.exists(
                    filepath
                )
            ):

                await event.reply(
                    file=filepath
                )

            return


    except Exception as e:

        print(
            "Auto Reply Error:",
            e
        )


# =========================================================
# /OFFRP
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/offrp$"
    )
)
async def off_reply(event):

    try:

        if not event.is_group:

            await event.reply(
                "❌ ဒီ Command ကို Group ထဲမှာပဲ သုံးနိုင်ပါတယ်။"
            )

            return


        if not await is_admin_or_owner(
            event
        ):

            await event.reply(
                "❌ Admin Only"
            )

            return


        chat_id = str(
            event.chat_id
        )


        if "__offrp__" not in reply_db:

            reply_db[
                "__offrp__"
            ] = []


        if chat_id in reply_db[
            "__offrp__"
        ]:

            await event.reply(
                "⚠️ Reply System already OFF"
            )

            return


        reply_db[
            "__offrp__"
        ].append(
            chat_id
        )

        save_reply_db()


        await event.reply(
            "<blockquote>"
            "🔕 <b>Reply System OFF</b>\n\n"
            "ဒီ Group မှာ Auto Reply မပြန်တော့ပါဘူး။"
            "</blockquote>",
            parse_mode="html"
        )

    except Exception as e:

        print(
            "OFFRP Error:",
            e
        )


# =========================================================
# /ONRP
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/onrp$"
    )
)
async def on_reply(event):

    try:

        if not event.is_group:

            await event.reply(
                "❌ ဒီ Command ကို Group ထဲမှာပဲ သုံးနိုင်ပါတယ်။"
            )

            return


        if not await is_admin_or_owner(
            event
        ):

            await event.reply(
                "❌ Admin Only"
            )

            return


        chat_id = str(
            event.chat_id
        )


        if "__offrp__" not in reply_db:

            reply_db[
                "__offrp__"
            ] = []


        if chat_id not in reply_db[
            "__offrp__"
        ]:

            await event.reply(
                "⚠️ Reply System already ON"
            )

            return


        reply_db[
            "__offrp__"
        ].remove(
            chat_id
        )

        save_reply_db()


        await event.reply(
            "<blockquote>"
            "🔔 <b>Reply System ON</b>\n\n"
            "ဒီ Group မှာ Auto Reply ပြန်ပါမယ်။"
            "</blockquote>",
            parse_mode="html"
        )

    except Exception as e:

        print(
            "ONRP Error:",
            e
        )


# =========================================================
# TRANSLATION SYSTEM
# =========================================================

LANGUAGES = {

    "Afrikaans": "af",
    "Albanian": "sq",
    "Amharic": "am",
    "Arabic": "ar",
    "Armenian": "hy",
    "Azerbaijani": "az",
    "Basque": "eu",
    "Belarusian": "be",
    "Bengali": "bn",
    "Bosnian": "bs",
    "Bulgarian": "bg",
    "Catalan": "ca",
    "Cebuano": "ceb",
    "Chinese (Simplified)": "zh-cn",
    "Chinese (Traditional)": "zh-tw",
    "Corsican": "co",
    "Croatian": "hr",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Esperanto": "eo",
    "Estonian": "et",
    "Finnish": "fi",
    "French": "fr",
    "Frisian": "fy",
    "Galician": "gl",
    "Georgian": "ka",
    "German": "de",
    "Greek": "el",
    "Gujarati": "gu",
    "Haitian Creole": "ht",
    "Hausa": "ha",
    "Hawaiian": "haw",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hmong": "hmn",
    "Hungarian": "hu",
    "Icelandic": "is",
    "Igbo": "ig",
    "Indonesian": "id",
    "Irish": "ga",
    "Italian": "it",
    "Japanese": "ja",
    "Javanese": "jw",
    "Kannada": "kn",
    "Kazakh": "kk",
    "Khmer": "km",
    "Korean": "ko",
    "Kurdish (Kurmanji)": "ku",
    "Kyrgyz": "ky",
    "Lao": "lo",
    "Latin": "la",
    "Latvian": "lv",
    "Lithuanian": "lt",
    "Luxembourgish": "lb",
    "Macedonian": "mk",
    "Malagasy": "mg",
    "Malay": "ms",
    "Malayalam": "ml",
    "Maltese": "mt",
    "Maori": "mi",
    "Marathi": "mr",
    "Myanmar": "my",
    "Nepali": "ne",
    "Norwegian": "no",
    "Nyanja (Chichewa)": "ny",
    "Odia (Oriya)": "or",
    "Pashto": "ps",
    "Persian": "fa",
    "Polish": "pl",
    "Portuguese": "pt",
    "Punjabi": "pa",
    "Romanian": "ro",
    "Russian": "ru",
    "Samoan": "sm",
    "Scots Gaelic": "gd",
    "Serbian": "sr",
    "Sesotho": "st",
    "Shona": "sn",
    "Sindhi": "sd",
    "Sinhala (Sinhalese)": "si",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Somali": "so",
    "Spanish": "es",
    "Sundanese": "su",
    "Swahili": "sw",
    "Swedish": "sv",
    "Tagalog (Filipino)": "tl",
    "Tajik": "tg",
    "Tamil": "ta",
    "Tatar": "tt",
    "Telugu": "te",
    "Thai": "th",
    "Turkish": "tr",
    "Turkmen": "tk",
    "Ukrainian": "uk",
    "Urdu": "ur",
    "Uyghur": "ug",
    "Uzbek": "uz",
    "Vietnamese": "vi",
    "Welsh": "cy",
    "Xhosa": "xh",
    "Yiddish": "yi",
    "Yoruba": "yo",
    "Zulu": "zu"

}


# =========================================================
# LANGUAGE ALIASES
# =========================================================

LANG_ALIASES = {

    "myanmar (burmese)": "my",
    "burmese": "my",
    "မြန်မာ": "my",

    "english": "en",
    "အင်္ဂလိပ်": "en",

    "japanese": "ja",
    "ဂျပန်": "ja",

    "korean": "ko",
    "ကိုရီးယား": "ko",

    "chinese": "zh-cn",
    "တရုတ်": "zh-cn",

    "thai": "th",
    "ထိုင်း": "th",

    "french": "fr",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "russian": "ru",
    "arabic": "ar",
    "hindi": "hi",
    "portuguese": "pt",
    "vietnamese": "vi",
    "indonesian": "id",
    "malay": "ms",
    "turkish": "tr",
    "persian": "fa",
    "urdu": "ur"

}


# =========================================================
# LANGUAGE CODE → NAME
# =========================================================

LANGUAGE_NAMES = {
    code: name
    for name, code in LANGUAGES.items()
}

LANGUAGE_NAMES["my"] = "Myanmar"
LANGUAGE_NAMES["zh-cn"] = "Chinese (Simplified)"
LANGUAGE_NAMES["zh-tw"] = "Chinese (Traditional)"


# =========================================================
# GOOGLE TRANSLATE URL
# =========================================================

GOOGLE_TRANSLATE_URL = (
    "https://translate.googleapis.com/translate_a/single"
)


# =========================================================
# GOOGLE TRANSLATE
# =========================================================

async def google_translate(
    text,
    target_language
):

    params = {

        "client": "gtx",
        "sl": "auto",
        "tl": target_language,
        "dt": "t",
        "q": text

    }

    timeout = aiohttp.ClientTimeout(
        total=20
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.get(
            GOOGLE_TRANSLATE_URL,
            params=params
        ) as response:

            if response.status != 200:

                raise Exception(
                    f"HTTP {response.status}"
                )

            data = await response.json(
                content_type=None
            )


    if not data or not data[0]:

        raise Exception(
            "Translation result မရပါ"
        )


    translated_parts = []

    for item in data[0]:

        if item and item[0]:

            translated_parts.append(
                item[0]
            )


    translated = "".join(
        translated_parts
    ).strip()


    if not translated:

        raise Exception(
            "Translation result ဗလာဖြစ်နေပါတယ်"
        )


    return translated


# =========================================================
# GET LANGUAGE CODE
# =========================================================

def get_language_code(value):

    value = value.strip()

    value_lower = value.lower()


    if value_lower in LANGUAGE_NAMES:

        return value_lower


    if value_lower in LANG_ALIASES:

        return LANG_ALIASES[
            value_lower
        ]


    for name, code in LANGUAGES.items():

        if value_lower == name.lower():

            return code


    return None


# =========================================================
# /TR
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/tr(?:@\w+)?(?:\s+(.+))?$",
        incoming=True
    )
)
async def translate_command(event):

    processing = None

    try:

        if not event.is_reply:

            await event.reply(
                "❌ ဘာသာပြန်ချင်တဲ့ Message ကို "
                "Reply လုပ်ပြီး `/tr en` လို့ပေးပါ။",
                parse_mode="markdown"
            )

            return


        reply_msg = (
            await event.get_reply_message()
        )

        if not reply_msg:

            await event.reply(
                "❌ Reply Message မတွေ့ပါ။"
            )

            return


        original_text = (
            reply_msg.text
            or ""
        )


        if not original_text.strip():

            await event.reply(
                "❌ Reply ထားတဲ့ Message မှာ "
                "ဘာသာပြန်စရာ Text မရှိပါ။"
            )

            return


        target = (
            event.pattern_match.group(1)
        )


        if not target:

            await event.reply(

                "🌐 <b>Translation Language</b>\n\n"

                "အသုံးပြုပုံ:\n\n"

                "• `/tr en` → English\n"
                "• `/tr my` → Myanmar\n"
                "• `/tr ja` → Japanese\n"
                "• `/tr ko` → Korean\n"
                "• `/tr zh-cn` → Chinese\n"
                "• `/tr th` → Thai\n\n"

                "Language Name နဲ့လည်းရပါတယ်။",

                parse_mode="html"
            )

            return


        lang_code = get_language_code(
            target
        )


        if not lang_code:

            await event.reply(

                "❌ <b>Language မတွေ့ပါဘူး။</b>\n\n"

                "ဥပမာ:\n"
                "`/tr en`\n"
                "`/tr my`\n"
                "`/tr ja`\n"
                "`/tr ko`",

                parse_mode="html"
            )

            return


        language_name = (
            LANGUAGE_NAMES.get(
                lang_code,
                lang_code
            )
        )


        processing = await event.reply(
            "🌐 ဘာသာပြန်နေပါတယ်..."
        )


        translated = await google_translate(
            original_text,
            lang_code
        )


        original_html = html.escape(
            original_text
        )

        translated_html = html.escape(
            translated
        )


        result = (

            f"🌐 <b>Translation</b>\n\n"

            f"<blockquote>"
            f"<b>Original:</b>\n"
            f"{original_html}"
            f"</blockquote>\n\n"

            f"<blockquote>"
            f"<b>{html.escape(language_name)}:</b>\n"
            f"{translated_html}"
            f"</blockquote>"

        )


        await processing.edit(
            result,
            parse_mode="html"
        )


    except Exception as e:

        print(
            "Translation Error:",
            e
        )

        try:

            if processing:

                await processing.edit(

                    "❌ <b>Translation Error</b>\n\n"
                    f"<code>{html.escape(str(e))}</code>",

                    parse_mode="html"
                )

            else:

                await event.reply(
                    "❌ ဘာသာပြန်ရာမှာ Error ဖြစ်သွားပါတယ်။"
                )

        except Exception:
            pass


# =========================================================
# DATE / TIME
# =========================================================

def today():

    return datetime.now().strftime(
        "%Y-%m-%d"
    )


def now_datetime():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def timestamp():

    return int(
        datetime.now().timestamp()
    )


# =========================================================
# USER NAME
# =========================================================

def get_full_name(user):

    first = user.first_name or ""
    last = user.last_name or ""

    name = (
        f"{first} {last}"
        .strip()
    )

    if not name:
        name = "Unknown"

    return name


def get_username(user):

    if user.username:

        return f"@{user.username}"

    return "No Username"


# =========================================================
# PREMIUM
# =========================================================

def premium_status(user):

    if getattr(
        user,
        "premium",
        False
    ):

        return "⭐ Premium User"

    return "👤 Normal User"


# =========================================================
# SAVE /START USER
# =========================================================

async def save_start_user(user):

    if not user:
        return False

    user_id = str(
        user.id
    )

    async with json_lock:

        users = load_json(
            USERS_FILE,
            {}
        )

        is_new = (
            user_id not in users
        )

        old_data = users.get(
            user_id,
            {}
        )

        users[user_id] = {

            "id": user.id,

            "username": (
                f"@{user.username}"
                if user.username
                else None
            ),

            "first_name": (
                user.first_name or ""
            ),

            "last_name": (
                user.last_name or ""
            ),

            "premium": bool(
                getattr(
                    user,
                    "premium",
                    False
                )
            ),

            "first_start": (
                old_data.get(
                    "first_start"
                )
                or now_datetime()
            ),

            "last_start": now_datetime()

        }

        save_json(
            USERS_FILE,
            users
        )

    return is_new


# =========================================================
# NEW USER NOTIFICATION
# =========================================================

async def send_new_user_notification(user):

    try:

        user_id = user.id

        if user.username:

            username = (
                f"@{user.username}"
            )

        else:

            first_name = (
                user.first_name
                or "User"
            )

            username = (
                f"<a href='tg://user?id={user_id}'>"
                f"{first_name}"
                f"</a>"
            )


        if getattr(
            user,
            "premium",
            False
        ):

            status = "⭐ Premium"

        else:

            status = "👤 Normal User"


        text = (

            "🆕 <b>New User Is Started</b>\n"
            "=================\n"

            f"👤 <b>User ID</b> - "
            f"<code>{user_id}</code>\n"

            f"📛 <b>User Name</b> - "
            f"{username}\n"

            f"🕐 <b>Date</b> - "
            f"<code>{now_datetime()}</code>\n"

            f"💎 <b>User Status</b> - "
            f"{status}"

        )


        await bot.send_message(
            ADMIN_ID,
            text,
            parse_mode="html"
        )


    except Exception as e:

        print(
            "New User Notification Error:",
            e
        )


# =========================================================
# PRIVATE MESSAGE FORWARD
# =========================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def forward_private_messages(event):

    try:

        if not event.is_private:
            return


        user = await event.get_sender()

        if not user:
            return


        user_id = user.id


        if user_id in OWNER_IDS:
            return


        if getattr(
            user,
            "bot",
            False
        ):

            return


        text = (
            event.raw_text
            or ""
        )


        if text.strip().startswith("/"):
            return


        await bot.forward_messages(
            ADMIN_ID,
            event.message
        )


    except Exception as e:

        print(
            "Private Message Forward Error:",
            e
        )


# =========================================================
# CHECK CHANNEL + GROUP
# =========================================================

async def is_joined(user_id):

    try:

        await bot.get_permissions(
            REQUIRED_CHANNEL,
            user_id
        )

    except Exception:

        return False


    try:

        await bot.get_permissions(
            REQUIRED_GROUP,
            user_id
        )

    except Exception:

        return False


    return True


# =========================================================
# /START
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/start(?:\s.*)?$"
    )
)
async def start_cmd(event):

    user = await event.get_sender()

    if not user:
        return


    if event.is_private:

        is_new_user = await save_start_user(
            user
        )

        if is_new_user:

            await send_new_user_notification(
                user
            )


    user_id = user.id

    chat_id = event.chat_id

    first_name = (
        user.first_name
        or "User"
    )

    mention = (
        f"<a href='tg://user?id={user_id}'>"
        f"{first_name}"
        f"</a>"
    )


    # =====================================================
    # REACTION
    # =====================================================

    try:

        emoji = random.choice([
            "❤️‍🔥",
            "🔥",
            "✨",
            "😍",
            "👾",
            "⚡"
        ])

        await bot(
            SendReactionRequest(
                peer=chat_id,
                msg_id=event.id,
                reaction=[
                    ReactionEmoji(
                        emoticon=emoji
                    )
                ],
                big=True
            )
        )

    except Exception as e:

        print(
            "Reaction Error:",
            e
        )


    # =====================================================
    # TYPING
    # =====================================================

    async with bot.action(
        chat_id,
        "typing"
    ):

        animation = [

            "𝒲",
            "𝒲𝑒",
            "𝒲𝑒𝓁",
            "𝒲𝑒𝓁𝒸",
            "𝒲𝑒𝓁𝒸𝑜",
            "𝒲𝑒𝓁𝒸𝑜𝓂",
            "𝒲𝑒𝓁𝒸𝑜𝓂𝑒",
            "𝒲𝑒𝓁𝒸𝑜𝓂𝑒.",
            "𝒲𝑒𝓁𝒸𝑜𝓂𝑒..",
            "𝒲𝑒𝓁𝒸𝑜𝓂𝑒..."

        ]


        msg = await event.reply(
            animation[0]
        )


        for frame in animation[1:]:

            await asyncio.sleep(
                0.3
            )

            try:

                await msg.edit(
                    frame
                )

            except Exception:

                break


        await asyncio.sleep(
            0.3
        )


        try:

            await msg.delete()

        except Exception:

            pass


    # =====================================================
    # STICKER
    # =====================================================

    try:

        sticker_msg = await event.respond(
            file=STICKER_ID,
            reply_to=event.id
        )

        await asyncio.sleep(
            5
        )

        try:

            await sticker_msg.delete()

        except Exception:

            pass

    except Exception as e:

        print(
            "Sticker Error:",
            e
        )


    # =====================================================
    # PROFILE PHOTO
    # =====================================================

    file = None

    try:

        photos = await bot.get_profile_photos(
            user_id,
            limit=1
        )

        if photos.total > 0:

            file = io.BytesIO()

            await bot.download_media(
                photos[0],
                file
            )

            file.name = "profile.jpg"

            file.seek(0)

    except Exception as e:

        print(
            "Profile Photo Error:",
            e
        )


    # =====================================================
    # OWNER
    # =====================================================

    if user_id in OWNER_IDS:

        text = (

            f"<blockquote expandable>"
            f"👑 𝐇𝐞𝐥𝐥𝐨 {mention}!\n\n"

            f"𝐘𝐨𝐮 𝐚𝐫𝐞 𝐭𝐡𝐞 𝐁𝐨𝐭 𝐎𝐰𝐧𝐞𝐫.\n\n"

            f"မင်းက The Last Shinobi ဖြစ်တဲ့အတွက် "
            f"Bot ကို တိုက်ရိုက်အသုံးပြုနိုင်ပါတယ်။"

            f"</blockquote>"

        )


        buttons = [

            [

                Button.url(
                    "➕ Add to Group",
                    (
                        f"https://t.me/"
                        f"{BOT_USERNAME}"
                        f"?startgroup=true"
                    )
                )

            ]

        ]


    else:

        joined = await is_joined(
            user_id
        )


        if not joined:

            text = (

                f"<blockquote>"
                f"⚠️ Hello {mention}!\n\n"

                f"Bot ကိုအသုံးပြုရန် "
                f"Channel & Group ကို Join လုပ်ပါ။"

                f"</blockquote>"

            )


            buttons = [

                [

                    Button.url(
                        "📢 Join Channel",
                        (
                            f"https://t.me/"
                            f"{REQUIRED_CHANNEL}"
                        )
                    )

                ],

                [

                    Button.url(
                        "👥 Join Group",
                        (
                            f"https://t.me/"
                            f"{REQUIRED_GROUP}"
                        )
                    )

                ],

                [

                    Button.inline(
                        "✅ Verify",
                        b"verify_join"
                    )

                ]

            ]


        else:

            text = (

                f"<blockquote expandable>"
                f"💖 𝐇𝐞𝐥𝐥𝐨 {mention}!\n\n"

                f"ကျနော် Tha Gyi Thar Boruto က "
                f"𝐆𝐫𝐨𝐮𝐩 𝐎𝐧𝐥𝐲 မှာ "
                f"𝐎𝐧𝐥𝐢𝐧𝐞 𝐌𝐞𝐦𝐛𝐞𝐫 တွေနဲ့အတူ "
                f"𝐑𝐞𝐩𝐥𝐲 ပြန်ပြီး စကားပြောသော "
                f"ချစ်စက်ရုပ်လေးတစ်ကောင်ပါ။"

                f"</blockquote>"

            )


            buttons = [

                [

                    Button.url(
                        "➕ Add to Group",
                        (
                            f"https://t.me/"
                            f"{BOT_USERNAME}"
                            f"?startgroup=true"
                        )
                    )

                ]

            ]


    # =====================================================
    # SEND
    # =====================================================

    try:

        if file:

            await bot.send_file(
                chat_id,
                file,
                caption=text,
                buttons=buttons,
                parse_mode="html"
            )

        else:

            await event.respond(
                text,
                buttons=buttons,
                parse_mode="html"
            )

    except Exception as e:

        print(
            "Final Message Error:",
            e
        )


# =========================================================
# VERIFY
# =========================================================

@bot.on(
    events.CallbackQuery(
        data=b"verify_join"
    )
)
async def verify_callback(event):

    user_id = event.sender_id

    joined = await is_joined(
        user_id
    )


    if joined:

        await event.answer(
            "✅ Verification Successful!"
        )


        await event.edit(

            "<blockquote>"
            "✅ Verification Successful!\n\n"
            "Channel & Group Join လုပ်ထားတာ "
            "အတည်ပြုပြီးပါပြီ။"
            "</blockquote>",

            buttons=[

                [

                    Button.url(
                        "➕ Add to Group",
                        (
                            f"https://t.me/"
                            f"{BOT_USERNAME}"
                            f"?startgroup=true"
                        )
                    )

                ]

            ],

            parse_mode="html"
        )


    else:

        await event.answer(
            "❌ Join Channel & Group first!",
            alert=True
        )


# =========================================================
# SAVE GROUP
# =========================================================

async def save_group(
    event,
    actor=None
):

    try:

        chat = await event.get_chat()

        if not chat:
            return


        chat_id = event.chat_id

        group_id = str(
            chat_id
        )


        group_title = (
            getattr(
                chat,
                "title",
                None
            )
            or "Unknown Group"
        )


        username = getattr(
            chat,
            "username",
            None
        )


        if username:

            group_link = (
                f"https://t.me/{username}"
            )

        else:

            group_link = (
                "🔒 Private Group"
            )


        actor_data = None


        if actor:

            actor_data = {

                "id": actor.id,

                "username": (
                    f"@{actor.username}"
                    if actor.username
                    else None
                ),

                "name": get_full_name(
                    actor
                )

            }


        async with json_lock:

            groups = load_json(
                GROUPS_FILE,
                {}
            )


            if group_id not in groups:

                groups[group_id] = {

                    "chat_id": chat_id,

                    "title": group_title,

                    "username": username,

                    "link": group_link,

                    "added_date": (
                        now_datetime()
                    ),

                    "added_by": actor_data,

                    "members": []

                }

            else:

                groups[group_id][
                    "title"
                ] = group_title

                groups[group_id][
                    "username"
                ] = username

                groups[group_id][
                    "link"
                ] = group_link


            save_json(
                GROUPS_FILE,
                groups
            )


    except Exception as e:

        print(
            "Save Group Error:",
            e
        )


# =========================================================
# REMOVE GROUP
# =========================================================

async def remove_group(
    chat_id
):

    try:

        group_id = str(
            chat_id
        )


        async with json_lock:

            groups = load_json(
                GROUPS_FILE,
                {}
            )


            if group_id in groups:

                del groups[group_id]

                save_json(
                    GROUPS_FILE,
                    groups
                )

                print(
                    "🗑️ Group removed:",
                    chat_id
                )


    except Exception as e:

        print(
            "Remove Group Error:",
            e
        )


# =========================================================
# SAVE ADDED MEMBER
# =========================================================

async def save_added_member(
    chat_id,
    adder,
    member
):

    try:

        if not isinstance(
            member,
            types.User
        ):

            return


        if member.bot:
            return


        group_id = str(
            chat_id
        )


        async with json_lock:

            groups = load_json(
                GROUPS_FILE,
                {}
            )


            if group_id not in groups:
                return


            members = groups[
                group_id
            ].setdefault(
                "members",
                []
            )


            member_id = member.id

            date = today()


            # =================================================
            # DUPLICATE
            # =================================================

            for old in members:

                if (

                    old.get(
                        "adder_id"
                    )
                    == adder.id

                    and

                    old.get(
                        "member_id"
                    )
                    == member_id

                    and

                    old.get(
                        "date"
                    )
                    == date

                ):

                    return


            # =================================================
            # SAVE
            # =================================================

            members.append({

                "adder_id": adder.id,

                "adder_username": (
                    f"@{adder.username}"
                    if adder.username
                    else None
                ),

                "member_id": member.id,

                "member_username": (
                    f"@{member.username}"
                    if member.username
                    else None
                ),

                "member_name": (
                    get_full_name(
                        member
                    )
                ),

                "member_premium": bool(
                    getattr(
                        member,
                        "premium",
                        False
                    )
                ),

                "date": date,

                "timestamp": timestamp()

            })


            save_json(
                GROUPS_FILE,
                groups
            )


    except Exception as e:

        print(
            "Save Added Member Error:",
            e
        )


# =========================================================
# MEMBER ADD EVENT
# =========================================================

@bot.on(
    events.ChatAction()
)
async def member_added(event):

    try:

        if not event.user_added:
            return


        if not event.is_group:
            return


        adder = await event.get_user()

        if not adder:
            return


        if getattr(
            adder,
            "bot",
            False
        ):

            return


        users = []


        if event.users:

            users = event.users

        elif event.user:

            users = [
                event.user
            ]


        for member in users:

            await save_added_member(
                event.chat_id,
                adder,
                member
            )


    except Exception as e:

        print(
            "Member Add Error:",
            e
        )


# =========================================================
# FIND USER
# =========================================================

async def find_user_from_show(
    event,
    target=None
):

    if event.is_reply and not target:

        try:

            reply = (
                await event.get_reply_message()
            )


            if reply and reply.sender_id:

                return await reply.get_sender()


        except Exception:

            pass


    if target:

        target = target.strip()


        if target.startswith("@"):

            target = target[1:]


        if target.isdigit():

            try:

                return await bot.get_entity(
                    int(target)
                )

            except Exception:

                return None


        try:

            return await bot.get_entity(
                target
            )

        except Exception:

            return None


    return None


# =========================================================
# /SHOW
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/show(?:@\w+)?(?:\s+(.+))?$"
    )
)
async def show_stats(event):

    try:

        if not event.is_group:

            await event.reply(
                "❌ ဒီ Command ကို Group ထဲမှာပဲ အသုံးပြုနိုင်ပါတယ်။"
            )

            return


        target = (
            event.pattern_match.group(1)
        )


        user = await find_user_from_show(
            event,
            target
        )


        if not user:

            await event.reply(

                "❌ User ကိုရှာမတွေ့ပါဘူး။\n\n"

                "အသုံးပြုပုံ:\n\n"

                "• User ရဲ့စာကို Reply လုပ်ပြီး `/show`\n"
                "• `/show @username`\n"
                "• `/show UserID`"

            )

            return


        group_id = str(
            event.chat_id
        )


        groups = load_json(
            GROUPS_FILE,
            {}
        )


        group = groups.get(
            group_id
        )


        if not group:

            await event.reply(
                "❌ ဒီ Group ကို Bot ရဲ့ "
                "Group Database ထဲမှာ မတွေ့ပါဘူး။"
            )

            return


        members = group.get(
            "members",
            []
        )


        date = today()


        today_members = [

            member

            for member in members

            if (

                member.get(
                    "adder_id"
                )
                == user.id

                and

                member.get(
                    "date"
                )
                == date

            )

        ]


        total = len(
            today_members
        )


        username = (
            f"@{user.username}"
            if user.username
            else "No Username"
        )


        name = get_full_name(
            user
        )


        premium = premium_status(
            user
        )


        if today_members:

            member_lines = []


            for index, member in enumerate(
                today_members,
                start=1
            ):

                member_username = (
                    member.get(
                        "member_username"
                    )
                )


                member_name = (
                    member.get(
                        "member_name",
                        "Unknown"
                    )
                )


                if member_username:

                    display = (
                        member_username
                    )

                else:

                    display = (
                        member_name
                    )


                member_lines.append(
                    f"{index:02d} │ {display}"
                )


            member_text = (
                "\n".join(
                    member_lines
                )
            )


        else:

            member_text = (
                "— No Members Added Today —"
            )


        group_title = (
            group.get(
                "title",
                "Unknown Group"
            )
        )


        text = f"""
**👥 𝗗𝗔𝗜𝗟𝗬 𝗔𝗗𝗗 𝗦𝗧𝗔𝗧𝗦**

**👥 𝗚𝗥𝗢𝗨𝗣**
├ **𝗡𝗮𝗺𝗲:** {group_title}
└ **𝗜𝗗:** `{event.chat_id}`

━━━━━━━━━━━━━━━━━━

**👤 𝗨𝗦𝗘𝗥 𝗜𝗡𝗙𝗢**

├ **𝗨𝘀𝗲𝗿 𝗜𝗗:**
│ `{user.id}`

├ **𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲:**
│ {username}

├ **𝗡𝗮𝗺𝗲:**
│ {name}

└ **𝗔𝗰𝗰𝗼𝘂𝗻𝘁:**
   {premium}

━━━━━━━━━━━━━━━━━━

📅 **𝗗𝗮𝘁𝗲:**
`{date}`

👥 **𝗔𝗱𝗱𝗲𝗱 𝗧𝗼𝗱𝗮𝘆:**
**{total} 𝗠𝗲𝗺𝗯𝗲𝗿𝘀**

━━━━━━━━━━━━━━━━━━

👥 **𝗔𝗗𝗗𝗘𝗗 𝗠𝗘𝗠𝗕𝗘𝗥𝗦**

{member_text}

━━━━━━━━━━━━━━━━━━

🔭 **𝗦𝗧𝗔𝗧𝗨𝗦:**
**𝗧𝗼𝗱𝗮𝘆'𝘀 𝗔𝗱𝗱 𝗖𝗼𝘂𝗻𝘁: {total}**

🛡️ **𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬 𝗠𝗢𝗡𝗜𝗧𝗢𝗥**
"""


        await event.reply(
            text
        )


    except Exception as e:

        print(
            "Show Command Error:",
            e
        )

        await event.reply(
            "❌ `/show` command မှာ Error ဖြစ်သွားပါတယ်။"
        )


# =========================================================
# GET ACTION ACTOR
# =========================================================

async def get_action_actor(
    event,
    bot_id
):

    actor = None


    try:

        action_message = getattr(
            event,
            "action_message",
            None
        )


        if action_message:

            try:

                sender = (
                    await action_message.get_sender()
                )


                if (
                    sender
                    and sender.id != bot_id
                ):

                    actor = sender


            except Exception:

                pass


        if not actor:

            try:

                sender = (
                    await event.get_sender()
                )


                if (
                    sender
                    and sender.id != bot_id
                ):

                    actor = sender


            except Exception:

                pass


    except Exception as e:

        print(
            "Get Action Actor Error:",
            e
        )


    return actor


# =========================================================
# GROUP LINK
# =========================================================

async def get_group_link(chat):

    try:

        username = getattr(
            chat,
            "username",
            None
        )


        if username:

            return (
                f"https://t.me/{username}"
            )


        try:

            from telethon.tl.functions.messages import (
                ExportChatInviteRequest
            )


            result = await bot(
                ExportChatInviteRequest(
                    peer=chat
                )
            )


            return result.link


        except Exception:

            return "🔒 Private Group"


    except Exception:

        return "❌ Link မရနိုင်ပါ"


# =========================================================
# BOT ADMIN STATUS
# =========================================================

async def get_bot_admin_status(
    chat_id
):

    try:

        me = await bot.get_me()


        permissions = (
            await bot.get_permissions(
                chat_id,
                me.id
            )
        )


        if permissions.is_admin:

            return "👑 Admin"


        return "👤 Member"


    except Exception as e:

        print(
            "Bot Admin Check Error:",
            e
        )

        return "❓ Unknown"


# =========================================================
# GROUP STATUS NOTIFICATION
# =========================================================

async def send_group_status_notification(
    event,
    action
):

    try:

        if not event.is_group:
            return


        me = await bot.get_me()

        bot_id = me.id


        actor = await get_action_actor(
            event,
            bot_id
        )


        if actor:

            actor_id = actor.id

            actor_name = (
                get_full_name(
                    actor
                )
            )


            if actor.username:

                actor_username = (
                    f"@{actor.username}"
                )

            else:

                actor_username = (
                    "No Username"
                )


        else:

            actor_id = "Unknown"

            actor_name = (
                "Unknown / Telegram did not provide"
            )

            actor_username = (
                "Unknown"
            )


        chat = await event.get_chat()

        if not chat:
            return


        group_name = (
            getattr(
                chat,
                "title",
                None
            )
            or "Unknown Group"
        )


        group_id = event.chat_id


        group_link = (
            await get_group_link(
                chat
            )
        )


        bot_status = (
            await get_bot_admin_status(
                group_id
            )
        )


        date_time = now_datetime()


        if action == "added":

            title = (
                "🟢 <b>BOT ADDED TO GROUP</b>"
            )

            action_text = (
                "Bot ကို Group ထဲသို့ "
                "Add လုပ်လိုက်ပါပြီ။"
            )

        else:

            title = (
                "🔴 <b>BOT REMOVED FROM GROUP</b>"
            )

            action_text = (
                "Bot ကို Group ထဲမှ "
                "Remove / Kick လုပ်လိုက်ပါပြီ။"
            )


        text = f"""
{title}

━━━━━━━━━━━━━━━━━━

👥 <b>GROUP INFO</b>

├ 👥 <b>Name:</b> {html.escape(group_name)}
├ 🆔 <b>Group ID:</b> <code>{group_id}</code>
└ 🔗 <b>Group Link:</b> {group_link}

━━━━━━━━━━━━━━━━━━

👤 <b>ACTION BY</b>

├ 👤 <b>Name:</b> {html.escape(actor_name)}
├ 🔗 <b>Username:</b> {html.escape(str(actor_username))}
└ 🆔 <b>User ID:</b> <code>{actor_id}</code>

━━━━━━━━━━━━━━━━━━

🤖 <b>BOT STATUS</b>

├ 🤖 <b>Bot Name:</b> {html.escape(me.first_name or "Bot")}
├ 🔗 <b>Bot Username:</b> @{me.username or "No Username"}
├ 🆔 <b>Bot ID:</b> <code>{me.id}</code>
└ 🛡️ <b>Group Permission:</b> {bot_status}

━━━━━━━━━━━━━━━━━━

📌 <b>ACTION:</b>

{action_text}

🕐 <b>Date:</b>
<code>{date_time}</code>

━━━━━━━━━━━━━━━━━━
"""


        for owner_id in OWNER_IDS:

            try:

                await bot.send_message(
                    owner_id,
                    text,
                    parse_mode="html"
                )

            except Exception as e:

                print(
                    f"Notification Error {owner_id}:",
                    e
                )


    except Exception as e:

        print(
            "Group Notification Error:",
            e
        )


# =========================================================
# BOT GROUP STATUS
# =========================================================

@bot.on(
    events.ChatAction()
)
async def bot_group_status(event):

    try:

        if not event.is_group:
            return


        me = await bot.get_me()

        bot_id = me.id


        target_id = getattr(
            event,
            "user_id",
            None
        )


        if target_id != bot_id:
            return


        # =================================================
        # ADDED
        # =================================================

        if event.user_added:

            actor = await get_action_actor(
                event,
                bot_id
            )


            await save_group(
                event,
                actor
            )


            await send_group_status_notification(
                event,
                "added"
            )


            return


        # =================================================
        # KICKED
        # =================================================

        if event.user_kicked:

            await send_group_status_notification(
                event,
                "removed"
            )


            await remove_group(
                event.chat_id
            )


            return


        # =================================================
        # LEFT
        # =================================================

        if event.user_left:

            await send_group_status_notification(
                event,
                "removed"
            )


            await remove_group(
                event.chat_id
            )


            return


    except Exception as e:

        print(
            "Bot Group Status Error:",
            e
        )

# =========================================================
# WELCOME / GOODBYE SYSTEM
# =========================================================

@bot.on(
    events.ChatAction()
)
async def welcome_goodbye(event):

    try:

        # =====================================================
        # GROUP ONLY
        # =====================================================

        if not event.is_group:
            return


        # =====================================================
        # GET USER
        # =====================================================

        user = await event.get_user()

        if not user:
            return


        # =====================================================
        # IGNORE BOT
        # =====================================================

        if getattr(
            user,
            "bot",
            False
        ):
            return


        # =====================================================
        # USER INFO
        # =====================================================

        name = (
            user.first_name
            or "User"
        )

        user_id = user.id

        chat = await event.get_chat()

        group_name = (
            getattr(
                chat,
                "title",
                None
            )
            or "Group"
        )


        # =====================================================
        # SAFE HTML
        # =====================================================

        safe_name = html.escape(
            name
        )

        safe_group_name = html.escape(
            group_name
        )


        # =====================================================
        # WELCOME
        # =====================================================

        if (
            event.user_joined
            or event.user_added
        ):

            text = (

                f"<blockquote>"
                f"🎉 မင်္ဂလာပါ {safe_name} ရေ"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"{safe_group_name} ကနေ "
                f"လှိုက်လှဲစွာ ကြိုဆိုပါတယ်နော် 🎉"
                f"</blockquote>\n\n"

                f"<blockquote expandable>"
                f"👤 Name: "
                f"<tg-spoiler>{safe_name}</tg-spoiler>\n"
                f"🆔 ID: "
                f"<tg-spoiler>{user_id}</tg-spoiler>"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"စကားဝင်ပြောနော် 💬"
                f"</blockquote>\n"

                f"<blockquote>"
                f"လိုအပ်တာရှိရင် "
                f'<a href="tg://user?id=6974549243">'
                f"The Last Shinobi"
                f"</a>"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"🤗 ပျော်ရွှင်စွာ စကားပြောနိုင်ပါစေဗျာ။ 🤗"
                f"</blockquote>"

            )


            try:

                msg = await event.reply(
                    text,
                    parse_mode="html",
                )

            except Exception as e:

                print(
                    "Welcome Send Error:",
                    e
                )

                return


            # =================================================
            # AUTO DELETE - 15 SECONDS
            # =================================================

            await asyncio.sleep(
                15
            )


            try:

                await msg.delete()

            except Exception:
                pass


            try:

                await event.delete()

            except Exception:
                pass


            return


        # =====================================================
        # GOODBYE
        # =====================================================

        if (
            event.user_left
            or event.user_kicked
        ):

            text = (

                f"<blockquote>"
                f"ဟော {safe_name} က "
                f"{safe_group_name} ကနေ "
                f"ထွက်သွားပါပြီ 😔"
                f"</blockquote>\n\n"

                f"<blockquote expandable>"
                f"👤 Name: "
                f"<tg-spoiler>{safe_name}</tg-spoiler>\n"
                f"🆔 ID: "
                f"<tg-spoiler>{user_id}</tg-spoiler>"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"အတူတူရှိခဲ့တဲ့ အမှတ်တရတွေအတွက် "
                f"ကျေးဇူးတင်ပါတယ်။ 🤍"
                f"</blockquote>\n"

                f"<blockquote>"
                f"အချိန်မရွေး ပြန်လာနိုင်ပါတယ် "
                f"အမြဲတမ်း ကြိုဆိုလျက်ပါ"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"လိုအပ်တာရှိရင် "
                f'<a href="tg://user?id=6974549243">'
                f"The Last Shinobi"
                f"</a>"
                f"</blockquote>\n\n"

                f"<blockquote>"
                f"👋 Bye Bye {safe_name}"
                f"</blockquote>"

            )


            try:

                msg = await event.reply(
                    text,
                    parse_mode="html",
                )

            except Exception as e:

                print(
                    "Goodbye Send Error:",
                    e
                )

                return


            # =================================================
            # AUTO DELETE - 15 SECONDS
            # =================================================

            await asyncio.sleep(
                15
            )


            try:

                await msg.delete()

            except Exception:
                pass


            try:

                await event.delete()

            except Exception:
                pass


            return


    except Exception as e:

        print(
            "Welcome / Goodbye Error:",
            e
        )
        
# =========================================================
# /ALL / /CALL / /ADM / /STOP SYSTEM
# =========================================================


# =========================================================
# /ALL
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/all(?:@\w+)?(?:\s+(.*))?$"
    )
)
async def all_handler(event):

    try:

        # =====================================================
        # GROUP ONLY
        # =====================================================

        if not event.is_group:
            return


        # =====================================================
        # ADMIN / OWNER ONLY
        # =====================================================

        if not await is_admin_or_owner(event):

            await event.reply(
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
            )

            return


        chat_id = event.chat_id


        # =====================================================
        # ALREADY RUNNING
        # =====================================================

        if chat_id in running_chats:

            await event.reply(
                "⚠️ ခေါ်ဆောင်လျက်ရှိသည်"
            )

            return


        running_chats.add(chat_id)


        try:

            # =================================================
            # CUSTOM MESSAGE
            # =================================================

            msg = event.pattern_match.group(1)

            text = (
                msg.strip()
                if msg and msg.strip()
                else "📢 ရှိသမျှ Member တွေကို ခေါ်ဆောင်နေပါသည်"
            )


            # =================================================
            # GET GROUP
            # =================================================

            chat = await event.get_input_chat()


            users = []


            # =================================================
            # GET ALL MEMBERS
            # =================================================

            async for user in bot.iter_participants(chat):

                if getattr(
                    user,
                    "bot",
                    False
                ):

                    continue


                users.append(user)


            # =================================================
            # NO USERS
            # =================================================

            if not users:

                await event.reply(
                    "❌ No users found."
                )

                return


            # =================================================
            # SHUFFLE
            # =================================================

            random.shuffle(users)


            # =================================================
            # SEND 5 USERS PER MESSAGE
            # =================================================

            for i in range(
                0,
                len(users),
                5
            ):

                # Stop command နဲ့ ရပ်ထားရင်
                if chat_id not in running_chats:

                    return


                batch = users[
                    i:i + 5
                ]


                message = (
                    f"{html.escape(text)}\n\n"
                )


                for user in batch:

                    emoji = random.choice(
                        EMOJIS
                    )


                    message += (
                        f'<a href="tg://user?id={user.id}">'
                        f'{emoji}'
                        f'</a> '
                    )


                await bot.send_message(

                    chat_id,

                    message,

                    parse_mode="html",

                    reply_to=event.id

                )


                await asyncio.sleep(2)


            # =================================================
            # FINISHED
            # =================================================

            if chat_id in running_chats:

                await bot.send_message(

                    chat_id,

                    "✅ All Member ခေါ်ဆောင်ခြင်းပြီးဆုံးပါပီ",

                    reply_to=event.id

                )


        finally:

            running_chats.discard(
                chat_id
            )


    except Exception as e:

        running_chats.discard(
            event.chat_id
        )


        print(
            "ALL Command Error:",
            e
        )


# =========================================================
# /CALL
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/call(?:@\w+)?(?:\s+(.*))?$"
    )
)
async def call_handler(event):

    try:

        # =====================================================
        # GROUP ONLY
        # =====================================================

        if not event.is_group:
            return


        # =====================================================
        # ADMIN / OWNER ONLY
        # =====================================================

        if not await is_admin_or_owner(event):

            await event.reply(
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
            )

            return


        chat_id = event.chat_id


        # =====================================================
        # ALREADY RUNNING
        # =====================================================

        if chat_id in running_chats:

            await event.reply(
                "⚠️ ခေါ်ဆောင်လျက် ရှိသည်"
            )

            return


        running_chats.add(
            chat_id
        )


        try:

            # =================================================
            # CUSTOM MESSAGE
            # =================================================

            msg = event.pattern_match.group(1)

            text = (
                msg.strip()
                if msg and msg.strip()
                else "📢 Online ဖြစ်တဲ့ User တွေကို ခေါ်နေပါတယ်"
            )


            # =================================================
            # GET GROUP
            # =================================================

            chat = await event.get_input_chat()


            users = []


            # =================================================
            # GET ONLINE USERS
            # =================================================

            async for user in bot.iter_participants(chat):

                if getattr(
                    user,
                    "bot",
                    False
                ):

                    continue


                if isinstance(
                    user.status,
                    UserStatusOnline
                ):

                    users.append(
                        user
                    )


            # =================================================
            # NO ONLINE USERS
            # =================================================

            if not users:

                await event.reply(
                    "❌ Online ဖြစ်နေတဲ့ User တွေကို မတွေ့ပါဘူး"
                )

                return


            # =================================================
            # SHUFFLE
            # =================================================

            random.shuffle(
                users
            )


            # =================================================
            # SEND 5 USERS PER MESSAGE
            # =================================================

            for i in range(
                0,
                len(users),
                5
            ):

                if chat_id not in running_chats:

                    return


                batch = users[
                    i:i + 5
                ]


                message = (
                    f"{html.escape(text)}\n\n"
                )


                for user in batch:

                    emoji = random.choice(
                        EMOJIS
                    )


                    message += (
                        f'<a href="tg://user?id={user.id}">'
                        f'{emoji}'
                        f'</a> '
                    )


                await bot.send_message(

                    chat_id,

                    message,

                    parse_mode="html",

                    reply_to=event.id

                )


                await asyncio.sleep(2)


            # =================================================
            # FINISHED
            # =================================================

            if chat_id in running_chats:

                await bot.send_message(

                    chat_id,

                    "✅ Online User ခေါ်ဆောင်ခြင်းပြီးဆုံးပါပီ",

                    reply_to=event.id

                )


        finally:

            running_chats.discard(
                chat_id
            )


    except Exception as e:

        running_chats.discard(
            event.chat_id
        )


        print(
            "CALL Command Error:",
            e
        )


# =========================================================
# /ADM
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/adm(?:@\w+)?(?:\s+(.*))?$"
    )
)
async def adm_handler(event):

    try:

        # =====================================================
        # GROUP ONLY
        # =====================================================

        if not event.is_group:
            return


        # =====================================================
        # ADMIN / OWNER ONLY
        # =====================================================

        if not await is_admin_or_owner(event):

            await event.reply(
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
            )

            return


        # =====================================================
        # SENDER
        # =====================================================

        sender = await event.get_sender()

        if not sender:
            return


        sender_name = (
            sender.first_name
            or "User"
        )


        sender_name = html.escape(
            sender_name
        )


        sender_mention = (
            f'<a href="tg://user?id={sender.id}">'
            f'{sender_name}'
            f'</a>'
        )


        if sender.username:

            uname = (
                f"@{html.escape(sender.username)}"
            )

        else:

            uname = sender_name


        # =====================================================
        # EXTRA MESSAGE
        # =====================================================

        extra_text = (
            event.pattern_match.group(1)
        )


        if extra_text:

            extra_text = html.escape(
                extra_text.strip()
            )


            header = (

                f"{sender_mention} "
                f"({uname}) က Admin တွေကို "
                f"ပြောနေတယ်\n\n"

                f"💬 {extra_text}\n\n"

            )

        else:

            header = (

                f"{sender_mention} "
                f"({uname}) က Admin တွေကို "
                f"ခေါ်နေတယ်\n\n"

            )


        # =====================================================
        # GET ADMINS
        # =====================================================

        admins = []


        async for user in bot.iter_participants(

            event.chat_id,

            filter=ChannelParticipantsAdmins

        ):

            if getattr(
                user,
                "bot",
                False
            ):

                continue


            admins.append(
                user
            )


        # =====================================================
        # NO ADMINS
        # =====================================================

        if not admins:

            await event.reply(
                "❌ No admins found."
            )

            return


        # =====================================================
        # BUILD MESSAGE
        # =====================================================

        message = header


        for admin in admins:

            emoji = random.choice(
                EMOJIS
            )


            message += (
                f'<a href="tg://user?id={admin.id}">'
                f'{emoji}'
                f'</a> '
            )


        # =====================================================
        # SEND
        # =====================================================

        await bot.send_message(

            event.chat_id,

            message,

            parse_mode="html",

            reply_to=event.id

        )


    except Exception as e:

        print(
            "ADM Command Error:",
            e
        )


# =========================================================
# /STOP
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/stop(?:@\w+)?$"
    )
)
async def stop_handler(event):

    try:

        # =====================================================
        # ADMIN / OWNER ONLY
        # =====================================================

        if not await is_admin_or_owner(event):

            await event.reply(
                "❌ Nah Nah Admin တွေဘဲ သုံးခွင့်ရှိသည်"
            )

            return


        chat_id = event.chat_id


        # =====================================================
        # STOP
        # =====================================================

        if chat_id in running_chats:

            running_chats.discard(
                chat_id
            )


            await event.reply(
                "🛑 ခေါ်ဆောင်ခြင်း ရပ်တန့်လိုက်ပါပြီ"
            )


        else:

            await event.reply(
                "❌ ဘာကိုမှ မခေါ်ဆောင်နေပါဘူး"
            )


    except Exception as e:

        print(
            "STOP Command Error:",
            e
        )

# =========================================================
# GROUP PROTECTION SYSTEM
# Bio + Link + Forward + Bad Words
# NO MENTION CHECK
# =========================================================

import re
import time
import asyncio
from telethon import events
from telethon.tl.types import ChatBannedRights
from telethon.tl.functions.channels import EditBannedRequest


# =========================================================
# PROTECTION CONFIG
# =========================================================

PROTECTION_MAX_WARN = 3

# 5 Minutes
PROTECTION_MUTE_TIME = 5 * 60

# Warning message auto delete
PROTECTION_DELETE_TIME = 300


# =========================================================
# BAD WORDS
# =========================================================

PROTECTION_BAD_WORDS = [
    "fuck",
    "shit",

    "လီး",
    "လိး",
    "စပ",
    "သပ",
    "သပ့",
    "စပစား",
    "သပ့စား",
    "တောသား",
    "မင်းမေစပ",
    "ကိုမေကိုလိုး",
    "မအေလိုး",
    "မင်းမေလိုး",
    "မအေးလိုး",
    "မင်းမေလိုးလိုက်",
    "ငါလိုးမသား",
    "ဖင်ခံ",
    "စောက်တောသား",
    "ခွေးမ",

    "kmkl",
    "lee",
    "mmsp"
]


# =========================================================
# BIO DETECTOR
# =========================================================

PROTECTION_BIO_PATTERN = re.compile(
    r"""
    # English
    b[\s\W_]*i[\s\W_]*o |
    b1o |
    bi0 |
    b!o |

    # Fancy fonts
    ʙ[\s\W_]*ɪ[\s\W_]*ᴏ |
    𝙗[\s\W_]*𝙞[\s\W_]*𝙤 |
    𝗯[\s\W_]*𝗶[\s\W_]*𝗼 |
    𝕓[\s\W_]*𝕚[\s\W_]*𝕠 |
    𝓫[\s\W_]*𝓲[\s\W_]*𝓸 |
    𝒃[\s\W_]*𝒊[\s\W_]*𝒐 |
    𝐛[\s\W_]*𝐢[\s\W_]*𝐨 |

    # Fullwidth
    ｂ[\s\W_]*ｉ[\s\W_]*ｏ |
    🅱[\s\W_]*🅸[\s\W_]*🅾 |

    # Myanmar
    ဘိုင် |
    ဘိုင်[\s-]*အို |
    ဘီအိုင်အို |
    ဘိုင်အို |
    ဘိုင်အိုး |
    ဘိုင်လား |
    ဘိုင်လာ |
    ဘို |
    ဘိုင်ဘို |

    # Mixed
    b[\s]*အိုင်[\s]*o |
    b[\s]*a[\s]*i[\s]*o |
    bio[\s]*link |
    bio[\s]*chat |
    bio[\s]*tg |
    bio[\s]*pm |

    # Hidden / spaced
    b[\s\.\/_-]*i[\s\.\/_-]*o |
    b[\s]*i[\s]*o |
    b[\.\-_\s]*i[\.\-_\s]*o
    """,
    re.IGNORECASE | re.VERBOSE
)


# =========================================================
# PROTECTION WARNING DATABASE
# =========================================================

protection_warns = {}


# =========================================================
# AUTO DELETE WARNING MESSAGE
# =========================================================

async def protection_auto_delete(message, delay=PROTECTION_DELETE_TIME):

    try:
        await asyncio.sleep(delay)
        await message.delete()

    except Exception:
        pass


# =========================================================
# PROTECTION MUTE
# =========================================================

async def protection_mute(chat_id, user_id, seconds):

    try:

        until_date = int(time.time()) + seconds

        rights = ChatBannedRights(
            until_date=until_date,
            send_messages=True
        )

        await bot(
            EditBannedRequest(
                chat_id,
                user_id,
                rights
            )
        )

        return True

    except Exception as e:

        print(
            "Protection Mute Error:",
            e
        )

        return False


# =========================================================
# PROTECTION MESSAGE HANDLER
# =========================================================

@bot.on(
    events.NewMessage(
        incoming=True
    )
)
async def group_protection(event):

    try:

        # =====================================================
        # GROUP ONLY
        # =====================================================

        if not event.is_group:
            return


        # =====================================================
        # GET SENDER
        # =====================================================

        sender = await event.get_sender()

        if not sender:
            return


        sender_id = sender.id
        chat_id = event.chat_id


        # =====================================================
        # IGNORE BOT
        # =====================================================

        if getattr(
            sender,
            "bot",
            False
        ):
            return


        # =====================================================
        # IGNORE OUR BOT
        # =====================================================

        me = await bot.get_me()

        if sender_id == me.id:
            return


        # =====================================================
        # OWNER BYPASS
        # =====================================================

        if sender_id in OWNER_IDS:
            return


        # =====================================================
        # ADMIN BYPASS
        # =====================================================

        try:

            perms = await bot.get_permissions(
                chat_id,
                sender_id
            )

            if (
                perms.is_admin
                or perms.is_creator
            ):
                return

        except Exception:

            # Permission မစစ်နိုင်ရင်
            # protection ဆက်လုပ်မယ်
            pass


        # =====================================================
        # MESSAGE
        # =====================================================

        msg = event.message

        if not msg:
            return


        text = (
            msg.raw_text
            or ""
        )


        # =====================================================
        # CHECK REASON
        #
        # ❗ Mention Check မပါ
        # =====================================================

        reason = None


        # =====================================================
        # LINK CHECK
        # =====================================================

        if re.search(
            r"""
            (?:
                https?://
                |
                www\.
                |
                t\.me/
                |
                telegram\.me/
                |
                telegram\.dog/
            )
            """,
            text,
            re.IGNORECASE | re.VERBOSE
        ):

            reason = (
                "🔗 Group ထဲမှာ Link "
                "ပို့ခွင့်မပေးပါ။"
            )


        # =====================================================
        # FORWARD CHECK
        #
        # ဘယ် Channel က Forward ဖြစ်ဖြစ်
        # ဘယ် User က Forward ဖြစ်ဖြစ်
        # ဘယ် Group က Forward ဖြစ်ဖြစ်
        # Forward ဖြစ်တာနဲ့ Delete
        # =====================================================

        elif getattr(
            msg,
            "fwd_from",
            None
        ) is not None:

            reason = (
                "🔄 Forward Message "
                "ပို့ခွင့်မပေးပါ။"
            )


        # =====================================================
        # BIO CHECK
        # =====================================================

        elif PROTECTION_BIO_PATTERN.search(
            text
        ):

            reason = (
                "🧬 Bio Link / Bio စာသားမျိုး "
                "ပို့ခွင့်မပေးပါ။"
            )


        # =====================================================
        # BAD WORD CHECK
        # =====================================================

        else:

            normalized_text = (
                text
                .lower()
                .replace("\u200b", "")
                .replace("\u200c", "")
                .replace("\u200d", "")
            )

            for word in PROTECTION_BAD_WORDS:

                if word.lower() in normalized_text:

                    reason = (
                        "🤬 မသင့်တော်တဲ့ စကားလုံး "
                        "အသုံးပြုထားပါတယ်။"
                    )

                    break


        # =====================================================
        # NOTHING FOUND
        # =====================================================

        if not reason:
            return


        # =====================================================
        # DELETE ORIGINAL MESSAGE
        # =====================================================

        try:

            await msg.delete()

        except Exception as e:

            print(
                "Protection Delete Error:",
                e
            )


        # =====================================================
        # WARN KEY
        #
        # Group တစ်ခုချင်း + User တစ်ယောက်ချင်း
        # Warn သီးသန့်တွက်မယ်
        # =====================================================

        warn_key = (
            chat_id,
            sender_id
        )


        protection_warns[warn_key] = (
            protection_warns.get(
                warn_key,
                0
            ) + 1
        )


        warn_count = protection_warns[
            warn_key
        ]


        # =====================================================
        # USER NAME
        # =====================================================

        first_name = (
            sender.first_name
            or "User"
        )

        safe_name = (
            first_name
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        mention = (
            f'<a href="tg://user?id={sender_id}">'
            f'{safe_name}'
            f'</a>'
        )


        # =====================================================
        # AUTO MUTE
        # =====================================================

        if warn_count >= PROTECTION_MAX_WARN:

            muted = await protection_mute(
                chat_id,
                sender_id,
                PROTECTION_MUTE_TIME
            )

            if muted:

                protection_warns[
                    warn_key
                ] = 0

                warn_message = await event.respond(
                    f"""
<blockquote expandable>
🔇 {mention}

🚫 Rule ချိုးဖောက်မှု 3 ကြိမ်
ပြည့်သွားပါပြီ။

📌 နောက်ဆုံးအကြောင်းပြချက်
{reason}

⏱️ Auto Mute
5 Minutes

⚠️ Warning Reset
0/3
</blockquote>
""",
                    parse_mode="html"
                )

            else:

                warn_message = await event.respond(
                    f"""
<blockquote expandable>
⚠️ {mention}

{reason}

❌ Auto Mute လုပ်ရာမှာ
Error ဖြစ်သွားပါတယ်။

Warning : {warn_count}/3
</blockquote>
""",
                    parse_mode="html"
                )


            asyncio.create_task(
                protection_auto_delete(
                    warn_message
                )
            )

            return


        # =====================================================
        # NORMAL WARNING
        # =====================================================

        remaining = (
            PROTECTION_MAX_WARN
            - warn_count
        )

        warn_message = await event.respond(
            f"""
<blockquote expandable>
🚫 {mention}

{reason}

⚠️ Warning : {warn_count}/3

🔇 {remaining} ကြိမ်ကျန်ပါသေးတယ်။
3 ကြိမ်ပြည့်ရင် 5 Minutes Auto Mute ပါ။
</blockquote>
""",
            parse_mode="html"
        )


        asyncio.create_task(
            protection_auto_delete(
                warn_message
            )
        )


    except Exception as e:

        print(
            "Group Protection Error:",
            e
        )



# BROADCAST SYSTEM
# =========================================================

async def copy_broadcast_message(message, chat_id):
    """
    Telegram Bot API copyMessage ကို အသုံးပြုပြီး
    source message ကို Forward Header မပါဘဲ Copy ပို့ပေးတယ်။
    """

    if not message:
        return False

    url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    )

    payload = {
        "chat_id": str(chat_id),
        "from_chat_id": str(message.chat_id),
        "message_id": int(message.id),
    }

    try:

        async with aiohttp.ClientSession() as session:

            async with session.post(
                url,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                data = await response.json()

                if data.get("ok"):
                    return True

                # Telegram API FloodWait
                if response.status == 429:

                    retry_after = (
                        data.get("parameters", {})
                        .get("retry_after", 1)
                    )

                    await asyncio.sleep(
                        int(retry_after)
                    )

                    async with session.post(
                        url,
                        data=payload,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as retry_response:

                        retry_data = (
                            await retry_response.json()
                        )

                        if retry_data.get("ok"):
                            return True

                raise RuntimeError(
                    data.get(
                        "description",
                        "copyMessage failed"
                    )
                )

    except Exception:
        raise


# =========================================================
# BROADCAST COMMAND
# =========================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/broadcast(?:@\w+)?$"
    )
)
async def broadcast_msg(event):

    try:

        # -----------------------------------------------------
        # OWNER ONLY
        # -----------------------------------------------------

        sender = await event.get_sender()

        if not sender or sender.id not in OWNER_IDS:
            return


        # -----------------------------------------------------
        # REPLY MESSAGE REQUIRED
        # -----------------------------------------------------

        if not event.is_reply:

            return await event.reply(
                "❌ Broadcast လုပ်မယ့်စာကို Reply ထောက်ပြီး "
                "`/broadcast` လို့ ရိုက်ပါ။"
            )


        msg = await event.get_reply_message()

        if not msg:

            return await event.reply(
                "❌ Broadcast လုပ်မယ့် message ကို "
                "မတွေ့ပါဘူး။"
            )


        # -----------------------------------------------------
        # STATUS MESSAGE
        # -----------------------------------------------------

        status_msg = await event.reply(
            "🚀 <b>Broadcast စတင်နေပါပြီ...</b>\n\n"
            "အလုပ်မလုပ်တော့တဲ့ User / Group ID တွေကို "
            "လည်း သန့်ရှင်းပေးနေပါတယ်။",
            parse_mode="html"
        )


        # =====================================================
        # USER DATABASE
        # =====================================================

        u_count = 0
        u_failed = 0

        async with json_lock:

            users = load_json(
                USERS_FILE,
                {}
            )

            user_items = list(
                users.items()
            )


        for user_key, user_data in user_items:

            try:

                # user_data က dict ဖြစ်ရင် id ယူမယ်
                if isinstance(user_data, dict):

                    user_id = int(
                        user_data.get(
                            "id",
                            user_key
                        )
                    )

                else:

                    user_id = int(
                        user_data
                    )


                # ကိုယ့်ကိုယ်ကို Broadcast ပြန်မပို့
                if user_id == sender.id:
                    continue


                await copy_broadcast_message(
                    msg,
                    user_id
                )

                u_count += 1

                await asyncio.sleep(
                    0.3
                )


            except FloodWaitError as e:

                await asyncio.sleep(
                    e.seconds
                )

                try:

                    await copy_broadcast_message(
                        msg,
                        user_id
                    )

                    u_count += 1

                except Exception:

                    u_failed += 1

                    async with json_lock:

                        users = load_json(
                            USERS_FILE,
                            {}
                        )

                        users.pop(
                            str(user_id),
                            None
                        )

                        save_json(
                            USERS_FILE,
                            users
                        )


            except Exception:

                # Block / Delete account / Invalid ID
                # ဖြစ်ရင် Database ကနေဖယ်
                u_failed += 1

                try:

                    async with json_lock:

                        users = load_json(
                            USERS_FILE,
                            {}
                        )

                        users.pop(
                            str(user_id),
                            None
                        )

                        save_json(
                            USERS_FILE,
                            users
                        )

                except Exception:
                    pass


        # =====================================================
        # GROUP DATABASE
        # =====================================================

        g_count = 0
        g_failed = 0

        async with json_lock:

            groups = load_json(
                GROUPS_FILE,
                []
            )

            # -------------------------------------------------
            # LIST FORMAT
            # -------------------------------------------------
            #
            # [
            #     -1001234567890,
            #     -1009876543210
            # ]
            #

            if isinstance(groups, list):

                group_ids = []

                for group_id in groups:

                    try:

                        group_ids.append(
                            int(group_id)
                        )

                    except (
                        TypeError,
                        ValueError
                    ):
                        continue


            # -------------------------------------------------
            # DICT FORMAT
            # -------------------------------------------------
            #
            # {
            #     "-1001234567890": {},
            #     "-1009876543210": {}
            # }
            #

            elif isinstance(groups, dict):

                group_ids = []

                for group_key, group_data in groups.items():

                    try:

                        if isinstance(
                            group_data,
                            dict
                        ):

                            group_id = (
                                group_data.get(
                                    "chat_id",
                                    group_key
                                )
                            )

                        else:

                            group_id = group_key


                        group_ids.append(
                            int(group_id)
                        )

                    except (
                        TypeError,
                        ValueError
                    ):
                        continue


            # -------------------------------------------------
            # INVALID JSON STRUCTURE
            # -------------------------------------------------

            else:

                group_ids = []


        # =====================================================
        # SEND TO GROUPS
        # =====================================================

        for group_id in group_ids:

            try:

                await copy_broadcast_message(
                    msg,
                    group_id
                )

                g_count += 1

                await asyncio.sleep(
                    0.3
                )


            # -------------------------------------------------
            # FLOOD WAIT
            # -------------------------------------------------

            except FloodWaitError as e:

                await asyncio.sleep(
                    e.seconds
                )

                try:

                    await copy_broadcast_message(
                        msg,
                        group_id
                    )

                    g_count += 1

                except Exception:

                    g_failed += 1

                    async with json_lock:

                        groups = load_json(
                            GROUPS_FILE,
                            []
                        )

                        # List database
                        if isinstance(
                            groups,
                            list
                        ):

                            groups = [
                                x
                                for x in groups
                                if str(x)
                                != str(group_id)
                            ]

                        # Dict database
                        elif isinstance(
                            groups,
                            dict
                        ):

                            groups.pop(
                                str(group_id),
                                None
                            )

                        save_json(
                            GROUPS_FILE,
                            groups
                        )


            # -------------------------------------------------
            # OTHER ERRORS
            # -------------------------------------------------

            except Exception:

                # Bot မရှိတော့တဲ့ Group /
                # Left / Kicked / Invalid ID
                # ဖြစ်ရင် Database ကနေဖယ်
                g_failed += 1

                try:

                    async with json_lock:

                        groups = load_json(
                            GROUPS_FILE,
                            []
                        )

                        # -------------------------------------
                        # LIST DATABASE
                        # -------------------------------------

                        if isinstance(
                            groups,
                            list
                        ):

                            groups = [
                                x
                                for x in groups
                                if str(x)
                                != str(group_id)
                            ]


                        # -------------------------------------
                        # DICT DATABASE
                        # -------------------------------------

                        elif isinstance(
                            groups,
                            dict
                        ):

                            groups.pop(
                                str(group_id),
                                None
                            )


                        save_json(
                            GROUPS_FILE,
                            groups
                        )

                except Exception:
                    pass


        # =====================================================
        # REPORT
        # =====================================================

        report = (
            "✅ <b>Broadcast လုပ်ဆောင်ချက် "
            "ပြီးဆုံးပါပြီ!</b>\n\n"

            "👤 <b>Users:</b>\n"
            f"   • အောင်မြင်: "
            f"<code>{u_count}</code>\n"

            f"   • ဖယ်ရှားခဲ့သည် "
            f"(Failed/Blocked): "
            f"<code>{u_failed}</code>\n\n"

            "👥 <b>Groups:</b>\n"
            f"   • အောင်မြင်: "
            f"<code>{g_count}</code>\n"

            f"   • ဖယ်ရှားခဲ့သည် "
            f"(Left/Kicked): "
            f"<code>{g_failed}</code>"
        )


        await status_msg.edit(
            report,
            parse_mode="html"
        )


    # =====================================================
    # GLOBAL ERROR
    # =====================================================

    except Exception as e:

        print(
            "Broadcast Error:",
            e
        )

        try:

            await event.reply(
                "❌ <b>Broadcast Failed</b>\n\n"
                f"<code>"
                f"{html.escape(str(e))}"
                f"</code>",
                parse_mode="html"
            )

        except Exception:
            pass



# =========================================================
# /HELP MENU
# =========================================================

MENU_TEXT = """<blockquote expandable>
🤖 <b>Bot Command List</b>

Bot ရဲ့ Command အားလုံးကို ကြည့်ရန်
အောက်က <b>Open</b> Button ကိုနှိပ်ပါ။

<b>Owner :</b> @ThaGyiTharBoruto
<b>Channel :</b> @thagyitharboruto_official
</blockquote>"""

GROUP_CMDS = """<blockquote expandable>
╔════════ <b>Bot Command List</b> ════════╗

🚀 <b>/start</b>
→ Bot စတင်ပြီး user data သိမ်းခြင်း၊ welcome/reaction/sticker စနစ်

⚠️ <b>/warn</b>
→ User ကို warning ပေးခြင်း၊ 3 ကြိမ်ပြည့်ရင် 1 နာရီ mute

⛔ <b>/ban</b>
→ User ကို group မှ ban လုပ်ခြင်း

✅ <b>/unban</b>
→ User ရဲ့ ban ကို ဖြည်ခြင်း

🔇 <b>/mute</b>
→ User ကို mute လုပ်ခြင်း
→ m / h / d duration သတ်မှတ်နိုင်

🔊 <b>/unmute</b>
→ User ရဲ့ mute ကို ဖြည်ခြင်း

🔕 <b>/offrp</b>
→ Group ရဲ့ Auto Reply ပိတ်ခြင်း

🔔 <b>/onrp</b>
→ Group ရဲ့ Auto Reply ပြန်ဖွင့်ခြင်း

🌐 <b>/tr</b>
→ Reply လုပ်ထားတဲ့ message ကို ဘာသာပြန်ခြင်း

👥 <b>/all</b>
→ Group member များကို mention/call လုပ်ခြင်း

🟢 <b>/call</b>
→ Online member များကို mention/call လုပ်ခြင်း

👮 <b>/adm</b>
→ Group Admin များကို mention/call လုပ်ခြင်း

🛑 <b>/stop</b>
→ /all နှင့် /call လုပ်နေသော process ကို ရပ်ခြင်း

📊 <b>/show</b>
→ User ရဲ့ daily added-member statistics ပြခြင်း

📢 <b>/broadcast</b>
→ Reply လုပ်ထားတဲ့ message ကို database ထဲရှိ users/groups ဆီ broadcast လုပ်ခြင်း

╚════════════════════════════════════╝

<b>Owner :</b> @ThaGyiTharBoruto
<b>Channel :</b> @thagyitharboruto_official
</blockquote>"""


@bot.on(events.NewMessage(pattern=r"^/help$"))
async def show_menu(event):
    await event.reply(
        MENU_TEXT,
        parse_mode="html",
        buttons=[
            [Button.inline("📋 Open Command List", data=b"group_cmds")],
            [Button.url("📢 Channel", "https://t.me/thagyitharboruto_official")]
        ]
    )


@bot.on(events.CallbackQuery(data=b"group_cmds"))
async def show_group_cmds(event):
    await event.edit(
        GROUP_CMDS,
        parse_mode="html",
        buttons=[
            [Button.inline("🔙 Back", data=b"help_back")],
            [Button.url("📢 Channel", "https://t.me/thagyitharboruto_official")]
        ]
    )


@bot.on(events.CallbackQuery(data=b"help_back"))
async def help_back(event):
    await event.edit(
        MENU_TEXT,
        parse_mode="html",
        buttons=[
            [Button.inline("📋 Open Command List", data=b"group_cmds")],
            [Button.url("📢 Channel", "https://t.me/thagyitharboruto_official")]
        ]
    )

# =========================================================
# CLOUD JSON COMMANDS
# =========================================================

@bot.on(events.NewMessage(pattern=r"^/reload(?:@\w+)?$"))
async def cloud_reload_command(event):
    # Database ကို ပြန် load လုပ်နိုင်တာ Owner ပဲ ဖြစ်စေပါမယ်။
    if event.sender_id not in OWNER_IDS:
        return

    status = await event.reply("☁️ Cloud JSON ၃ ခုကို ပြန်ရယူနေပါတယ်...\n⏳ ခဏစောင့်ပါ။")
    try:
        result = await load_cloud_jsons(show_result=True)
        await status.edit(
            "☁️ <b>Cloud JSON Reload ပြီးပါပြီ</b>\n\n" + result,
            parse_mode="html"
        )
    except Exception as e:
        await status.edit(f"❌ Reload Error: {html.escape(str(e))}")


@bot.on(events.NewMessage(pattern=r"^/extdata(?:@\w+)?$"))
async def export_json_command(event):
    # Private Chat only
    if not event.is_private:
        return

    # JSON databases အားလုံးကို export လုပ်နိုင်တာ Owner ပဲ ဖြစ်စေပါမယ်။
    if event.sender_id not in OWNER_IDS:
        return

    status = await event.reply("📦 JSON data ၃ ခုကို export လုပ်နေပါတယ်...\n⏳ ခဏစောင့်ပါ။")

    try:
        # Current local data ကို ပြန် load လုပ်ပြီး current state ကိုပဲ export လုပ်ပါမယ်။
        export_files = [
            USERS_FILE,
            GROUPS_FILE,
            REPLY_FILE,
        ]

        for filename in export_files:
            if not os.path.exists(filename):
                save_json(filename, {})

            await client.send_file(
                event.chat_id,
                filename,
                caption=f"📄 <b>{html.escape(filename)}</b>",
                parse_mode="html"
            )

        await status.edit("✅ <b>Export ပြီးပါပြီ။</b>\n\nJSON file ၃ ခုလုံး ပို့ပြီးပါပြီ။", parse_mode="html")

    except Exception as e:
        await status.edit(f"❌ Export Error: {html.escape(str(e))}")


# =========================================================
# RUN
# =========================================================

print(
    "✅ Start Bot + Learning Reply System Is Running... 🔥"
)

print(
    f"📁 Users Database: {USERS_FILE}"
)

print(
    f"📁 Groups Database: {GROUPS_FILE}"
)

print(
    f"📁 Reply Database: {REPLY_FILE}"
)

print(
    f"📁 Reply Media: {REPLY_MEDIA_DIR}"
)


# =========================================================
# TIKTOK DOWNLOADER
# /tt <TikTok URL>
# =========================================================

TIKTOK_API_URL = "https://tikwm.com/api/"


def register_tiktok_system(client):

    @client.on(events.NewMessage(pattern=r"^/tt(?:\s+(.+))?$"))
    async def tiktok(event):

        url = event.pattern_match.group(1)

        if not url:
            return await event.reply(
                "❌ TikTok URL ထည့်ပေးပါ။\n\n"
                "ဥပမာ - `/tt https://vt.tiktok.com/xxxx/`"
            )

        msg = await event.reply(
            "⏳ **TikTok Media ရှာနေပါတယ်...**"
        )

        try:
            # =================================================
            # API REQUEST
            # =================================================

            timeout = aiohttp.ClientTimeout(total=60)

            async with aiohttp.ClientSession(timeout=timeout) as session:

                async with session.get(
                    TIKTOK_API_URL,
                    params={"url": url}
                ) as response:

                    if response.status != 200:
                        return await msg.edit(
                            f"❌ API Error\n"
                            f"HTTP Status: `{response.status}`"
                        )

                    res = await response.json(
                        content_type=None
                    )

            # =================================================
            # API RESULT CHECK
            # =================================================

            if res.get("code") != 0:
                return await msg.edit(
                    "❌ TikTok Media မတွေ့ပါ။\n"
                    "Link မှန်/မမှန် ပြန်စစ်ပေးပါ။"
                )

            data = res.get("data") or {}

            # =================================================
            # 1. LIVE PHOTO
            # =================================================

            live_photo = (
                data.get("live_photo")
                or data.get("livePhoto")
                or data.get("live")
                or data.get("live_url")
                or data.get("livePhotoUrl")
                or data.get("live_photo_url")
            )

            if live_photo:

                if isinstance(live_photo, list):
                    live_photo = (
                        live_photo[0]
                        if live_photo
                        else None
                    )

                if live_photo:

                    try:
                        is_mp4 = (
                            ".mp4" in live_photo.lower()
                            or "video" in live_photo.lower()
                            or "mp4" in live_photo.lower()
                        )

                        if is_mp4:

                            await event.reply(
                                file=live_photo,
                                force_document=False,
                                supports_streaming=True,
                                message=(
                                    "📸 **TikTok Live Photo**\n\n"
                                    "🎬 Format: MP4\n"
                                    "✨ No Watermark"
                                )
                            )

                        else:

                            await event.reply(
                                file=live_photo,
                                message=(
                                    "📸 **TikTok Live Photo**\n\n"
                                    "✨ No Watermark"
                                )
                            )

                        await msg.delete()
                        return

                    except Exception as live_error:

                        print(
                            f"[Live Photo Error] {live_error}"
                        )

            # =================================================
            # 2. PHOTO POST
            # =================================================

            images = (
                data.get("images")
                or data.get("image")
                or data.get("photo")
                or data.get("photos")
            )

            if images:

                if isinstance(images, str):
                    images = [images]

                if isinstance(images, list) and images:

                    try:

                        await event.reply(
                            file=images,
                            message=(
                                "🖼 **TikTok Photo Post**\n\n"
                                f"📷 Photos: `{len(images)}`"
                            )
                        )

                        await msg.delete()
                        return

                    except Exception as photo_error:

                        print(
                            f"[TikTok Photo Error] "
                            f"{photo_error}"
                        )

            # =================================================
            # 3. NORMAL VIDEO
            # =================================================
            # HD No-Watermark ကို ဦးစားပေး
            # =================================================

            video = (
                data.get("hdplay")
                or data.get("play")
                or data.get("wmplay")
            )

            if video:

                if data.get("hdplay"):

                    caption = (
                        "🎬 **TikTok HD Video**\n\n"
                        "✨ No Watermark"
                    )

                elif data.get("play"):

                    caption = (
                        "🎬 **TikTok Video**\n\n"
                        "✨ No Watermark"
                    )

                else:

                    caption = (
                        "🎬 **TikTok Video**\n\n"
                        "⚠️ Watermark Version"
                    )

                try:

                    await event.reply(
                        file=video,
                        message=caption
                    )

                    await msg.delete()
                    return

                except Exception as video_error:

                    print(
                        f"[TikTok Video Error] "
                        f"{video_error}"
                    )

            # =================================================
            # 4. NOTHING FOUND
            # =================================================

            await msg.edit(
                "❌ **Supported Media မတွေ့ပါ။**\n\n"
                "Support:\n"
                "🎬 Video\n"
                "🖼 Photo\n"
                "📸 Live Photo"
            )

        except aiohttp.ClientError as e:

            await msg.edit(
                "❌ **Network Error**\n\n"
                f"`{e}`"
            )

        except Exception as e:

            print(
                f"[TikTok Downloader Error] {e}"
            )

            await msg.edit(
                "❌ **Download Error**\n\n"
                f"`{e}`"
            )


# Register /tt handler on the main active Telethon client.
register_tiktok_system(bot)


# =========================================================
# ILY / SHIP / MISS SYSTEM
# =========================================================

# Use the global OWNER_IDS defined above.
# Do not overwrite it here, so both bot owners keep owner privileges.

BREAKUP_LIMIT = 3
SHIP_FILE = os.path.join(DATA_DIR, "ship_db.json")

# Cloud URL for ship_db.json.
# Put the raw Telegram message URL here, e.g.:
# SHIP_FILE_URL = "https://t.me/c/1234567890/123"
SHIP_FILE_URL = os.getenv("SHIP_FILE_URL", "")

pending_ily = {}
owner_force_ily = {}
breakup_requests = {}


def load_ship_local():
    if os.path.exists(SHIP_FILE):
        try:
            with open(SHIP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


ship_db = load_ship_local()


def save_ship_local():
    tmp = SHIP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ship_db, f, indent=4, ensure_ascii=False)
    os.replace(tmp, SHIP_FILE)


def get_ship_partner(user_id):
    data = ship_db.get(str(user_id))
    return data.get("partner") if isinstance(data, dict) else None


def get_ship_data(user_id):
    return ship_db.get(str(user_id))


def create_ship(user1, user2, chat_id, chat_name):
    ship_db[str(user1)] = {
        "partner": str(user2),
        "chat_id": str(chat_id),
        "chat_name": str(chat_name),
    }
    ship_db[str(user2)] = {
        "partner": str(user1),
        "chat_id": str(chat_id),
        "chat_name": str(chat_name),
    }
    save_ship_local()


def remove_ship(user1, user2):
    ship_db.pop(str(user1), None)
    ship_db.pop(str(user2), None)
    save_ship_local()


def get_ship_name(user):
    return (
        f"@{user.username}"
        if getattr(user, "username", None)
        else (getattr(user, "first_name", None) or str(user.id))
    )


async def download_ship_db_from_url(client):
    """Download ship_db.json from SHIP_FILE_URL if configured."""
    if not SHIP_FILE_URL:
        return False

    try:
        parsed = parse_telegram_message_url(SHIP_FILE_URL)
        if not parsed:
            print("⚠️ SHIP_FILE_URL is invalid.")
            return False

        temp_file = SHIP_FILE + ".download"

        ok = await download_telegram_file_from_url(
            SHIP_FILE_URL,
            temp_file,
        )

        if not ok or not os.path.exists(temp_file):
            return False

        with open(temp_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("ship_db.json must contain a JSON object.")

        tmp = SHIP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, SHIP_FILE)
        os.remove(temp_file)

        global ship_db
        ship_db = data
        print("☁️ ship_db.json loaded from URL.")
        return True

    except Exception as e:
        print(f"⚠️ Failed to load ship_db.json: {e}")
        return False


async def upload_ship_db_to_cloud(client):
    """
    Upload/update ship_db.json is intentionally not automatic because a
    Telegram message cannot be edited into a new file through a simple URL.
    The file is always saved locally; set up your existing cloud upload
    mechanism separately if you want automatic publishing.
    """
    save_ship_local()
    return True


def register_ily_handlers(client):

    @client.on(events.NewMessage(pattern=r"^/ily(?:\s+(.+))?$"))
    async def ily_handler(event):
        sender = await event.get_sender()
        sender_id = sender.id
        target = None

        if event.is_reply:
            reply = await event.get_reply_message()
            if not reply.sender:
                return await event.reply("❌ User မတွေ့ပါ")
            target = await reply.get_sender()
        else:
            match = event.pattern_match.group(1)
            if not match:
                return await event.reply(
                    "အသုံးပြုပုံ:\n/ily @user\nသို့မဟုတ် reply + /ily"
                )
            try:
                target = await client.get_entity(match.strip())
            except Exception:
                return await event.reply("❌ User ကိုရှာမတွေ့ဘူး")

        target_id = target.id

        if sender_id == target_id:
            return await event.reply("💀 ကိုယ့်ကိုယ်ကိုယ် ချစ်နေတာလား")

        if getattr(target, "bot", False):
            return await event.reply("🤖 Bot ကိုတော့ မရဘူး")

        partner_id = get_ship_partner(target_id)
        if partner_id:
            try:
                partner = await client.get_entity(int(partner_id))
                return await event.reply(
                    f"💔 သူ့မှာ ပိုင်ရှင်ဖြစ်တဲ့ {get_ship_name(partner)} ရှိပါတယ်"
                )
            except Exception:
                return await event.reply("💔 သူ့မှာ ပိုင်ရှင်ရှိပါတယ်")

        my_ship = get_ship_data(sender_id)
        if my_ship:
            partner_id = my_ship.get("partner")
            ship_chat_id = my_ship.get("chat_id")
            ship_chat_name = my_ship.get("chat_name")

            try:
                partner = await client.get_entity(int(partner_id))
                partner_name = get_ship_name(partner)
            except Exception:
                partner_name = "Unknown"

            if str(event.chat_id) != str(ship_chat_id):
                texts = [
                    f"🤨 မင်းဆီမှာ {ship_chat_name} က {partner_name} ရှိနေပီလေ\n\nဒါက ဘာလုပ်တာလဲ 😑",
                    f"💀 မင်းရဲ့ချစ်သူက {partner_name} မဟုတ်ဘူးလား\n\nဒါက ဘာလုပ်နေတာလဲ 🤨",
                    f"🥲 {partner_name} သာသိရင် ဝမ်းနည်းတော့မှာပဲ",
                    f"🤨 မင်းရဲ့ Partner က {ship_chat_name} ထဲမှာ ရှိနေတာလေ",
                ]
            else:
                texts = [
                    f"💞 မင်းမှာ {partner_name} ရှိပီးသားလေ 🥺",
                    f"🤨 ဒါဘာလုပ်တာလဲ {partner_name} သာသိရင် စိတ်ဆိုးတော့မယ်",
                    f"💔 {partner_name} ကို အားနာပါဦး",
                    f"🥺 မင်းရဲ့ Partner က {partner_name} ပါ",
                ]
            return await event.reply(random.choice(texts))

        sender_name = get_ship_name(sender)
        target_name = get_ship_name(target)

        buttons = [[
            Button.inline(
                "💖 လက်ခံပါတယ်",
                data=f"ily_accept_{sender_id}_{target_id}",
            ),
            Button.inline(
                "💔 ငြင်းပါတယ်",
                data=f"ily_reject_{sender_id}_{target_id}",
            ),
        ]]

        pending_ily[str(target_id)] = {
            "sender_id": sender_id,
            "chat_id": event.chat_id,
        }

        await event.reply(
            f"💌 ဟိတ် {target_name}\n\n"
            f"{sender_name} က မင်းကို ချစ်တယ်တဲ့ ❤️",
            buttons=buttons,
        )

    @client.on(events.NewMessage(pattern=r"^/ilyo(?:\s+(.+))?$"))
    async def ilyo_handler(event):
        sender = await event.get_sender()
        sender_id = sender.id

        if sender_id not in OWNER_IDS:
            return await event.reply("❌ ဒီ command ကို Owner ဘဲသုံးလို့ရပါတယ်")

        target = None
        if event.is_reply:
            reply = await event.get_reply_message()
            if not reply.sender:
                return await event.reply("❌ User မတွေ့ပါ")
            target = await reply.get_sender()
        else:
            match = event.pattern_match.group(1)
            if not match:
                return await event.reply(
                    "အသုံးပြုပုံ:\n/ilyo @user\nသို့မဟုတ် reply + /ilyo"
                )
            try:
                target = await client.get_entity(match.strip())
            except Exception:
                return await event.reply("❌ User ကိုရှာမတွေ့ဘူး")

        target_id = target.id

        if sender_id == target_id:
            return await event.reply("💀 ကိုယ့်ကိုယ်ကိုယ် ချစ်နေတာလား")
        if getattr(target, "bot", False):
            return await event.reply("🤖 Bot ကိုတော့ မရဘူး")
        if get_ship_partner(sender_id):
            return await event.reply("💔 Owner မှာ Partner ရှိပြီးသား")
        if get_ship_partner(target_id):
            return await event.reply("💔 သူ့မှာ Partner ရှိပြီးသား")

        owner_force_ily[str(target_id)] = {
            "sender_id": sender_id,
            "chat_id": event.chat_id,
        }

        buttons = [[
            Button.inline(
                "💖 လက်ခံပါတယ်",
                data=f"ily_accept_{sender_id}_{target_id}",
            ),
            Button.inline(
                "💖 လက်ခံပါတယ်",
                data=f"ily_accept_{sender_id}_{target_id}",
            ),
        ]]

        await event.reply(
            f"💌 ဟိတ် {get_ship_name(target)}\n\n"
            f"{get_ship_name(sender)} က မင်းကို ချစ်တယ်တဲ့ ❤️",
            buttons=buttons,
        )

    @client.on(events.NewMessage(pattern=r"^/stilyo$"))
    async def stilyo_handler(event):
        sender = await event.get_sender()
        if sender.id not in OWNER_IDS:
            return await event.reply("❌ ဒီ command ကို Owner ဘဲသုံးလို့ရပါတယ်")

        if not owner_force_ily:
            return await event.reply("❌ ဘယ်သူ့ကိုမှ Reminder မလုပ်ထားပါ")

        stopped_users = []
        for target_id in list(owner_force_ily):
            try:
                user = await client.get_entity(int(target_id))
                stopped_users.append(get_ship_name(user))
            except Exception:
                stopped_users.append(str(target_id))
            owner_force_ily.pop(target_id, None)

        await event.reply(
            "🛑 /ilyo Reminder ကို ရပ်လိုက်ပါပြီ\n\n"
            "Stopped Users:\n" + "\n".join(stopped_users)
        )

    @client.on(events.NewMessage)
    async def owner_force_reminder(event):
        if not event.raw_text or event.raw_text.startswith("/"):
            return

        sender_id = str(event.sender_id)
        data = owner_force_ily.get(sender_id)
        if not data:
            return

        owner_id = data["sender_id"]

        if get_ship_partner(owner_id) or get_ship_partner(sender_id):
            owner_force_ily.pop(sender_id, None)
            return

        sender = await client.get_entity(owner_id)
        buttons = [[
            Button.inline(
                "💖 လက်ခံပါတယ်",
                data=f"ily_accept_{owner_id}_{sender_id}",
            ),
            Button.inline(
                "💖 လက်ခံပါတယ်",
                data=f"ily_accept_{owner_id}_{sender_id}",
            ),
        ]]

        await event.reply(
            f"💌 {get_ship_name(sender)} က မင်းကို ချစ်နေပါတယ် ❤️\n\n"
            f"လက်ခံပါသလား 💖 ငြင်းပါသလားဟင် 💔",
            buttons=buttons,
        )

    @client.on(events.CallbackQuery(pattern=rb"ily_accept_(\d+)_(\d+)"))
    async def ily_accept(event):
        sender_id = int(event.pattern_match.group(1))
        target_id = int(event.pattern_match.group(2))

        if event.sender_id != target_id:
            return await event.answer(
                "❌ ဒီ Button ကို မင်းနှိပ်လို့မရဘူး", alert=True
            )

        if get_ship_partner(sender_id) or get_ship_partner(target_id):
            return await event.answer(
                "💔 တစ်ယောက်ယောက်မှာ Partner ရှိပြီးသား", alert=True
            )

        sender = await client.get_entity(sender_id)
        target = await client.get_entity(target_id)
        chat = await event.get_chat()
        chat_name = getattr(chat, "title", "Private Chat")

        create_ship(sender_id, target_id, event.chat_id, chat_name)
        pending_ily.pop(str(target_id), None)
        owner_force_ily.pop(str(target_id), None)

        await event.edit(
            f"💞 Ship Success!\n\n"
            f"{get_ship_name(sender)} ❤️ {get_ship_name(target)}\n\n"
            f"အခုသူတို့ ၂ ယောက်က Official Couple ဖြစ်သွားပါပြီ 🎉"
        )

    @client.on(events.CallbackQuery(pattern=rb"ily_reject_(\d+)_(\d+)"))
    async def ily_reject(event):
        sender_id = int(event.pattern_match.group(1))
        target_id = int(event.pattern_match.group(2))

        if event.sender_id != target_id:
            return await event.answer(
                "❌ ဒီ Button ကို မင်းနှိပ်လို့မရဘူး", alert=True
            )

        sender = await client.get_entity(sender_id)
        target = await client.get_entity(target_id)
        owner_force_ily.pop(str(target_id), None)

        reject_messages = [
            "💔 အားမငယ်နဲ့ နောက်တစ်ယောက်ရှိသေးတယ်",
            "😔 Love Failed...",
            "💀 Bro got rejected",
            "🥀 သူမချစ်လည်း Bot ကတော့ချစ်တယ်",
            "🙂 ကြိုးစားမှုက အရေးကြီးပါတယ်",
        ]

        await event.edit(
            f"{get_ship_name(target)} က {get_ship_name(sender)} ကို "
            f"ငြင်းလိုက်ပါတယ် 💔\n\n{random.choice(reject_messages)}"
        )

    @client.on(events.NewMessage(pattern=r"^/iby$"))
    async def iby_handler(event):
        sender = await event.get_sender()
        sender_id = sender.id
        partner_id = get_ship_partner(sender_id)

        if not partner_id:
            return await event.reply("💔 မင်းမှာ Relationship မရှိပါ")

        partner = await client.get_entity(int(partner_id))
        breakup_requests.setdefault(str(sender_id), 0)
        breakup_requests[str(sender_id)] += 1
        count = breakup_requests[str(sender_id)]

        if count >= BREAKUP_LIMIT:
            remove_ship(sender_id, partner_id)
            breakup_requests.pop(str(sender_id), None)
            breakup_requests.pop(str(partner_id), None)
            return await event.reply(
                f"{get_ship_name(sender)} ❤️ {get_ship_name(partner)}\n\n"
                f"💔 ဒီအတွဲဟာ အဆင်မပြေမှုတွေများလာလို့ထင်ပါတယ်...\n\n"
                f"၃ ကြိမ်တောင် လမ်းခွဲဖို့လုပ်ခဲ့တာကြောင့် Officially "
                f"လမ်းခွဲလိုက်ပါပြီ"
            )

        buttons = [[
            Button.inline(
                "💔 လမ်းခွဲမယ်",
                data=f"iby_yes_{sender_id}_{partner_id}",
            ),
            Button.inline(
                "❤️ မခွဲဘူး",
                data=f"iby_no_{sender_id}_{partner_id}",
            ),
        ]]

        await event.reply(
            f"{get_ship_name(partner)}\n\n"
            f"{get_ship_name(sender)} က မင်းကို လမ်းခွဲချင်နေပါတယ် 💔\n\n"
            f"({count}/{BREAKUP_LIMIT})",
            buttons=buttons,
        )

    @client.on(events.CallbackQuery(pattern=rb"iby_yes_(\d+)_(\d+)"))
    async def iby_yes(event):
        sender_id = int(event.pattern_match.group(1))
        partner_id = int(event.pattern_match.group(2))

        if event.sender_id != partner_id:
            return await event.answer(
                "❌ ဒီ Button ကို မင်းနှိပ်လို့မရဘူး", alert=True
            )

        sender = await client.get_entity(sender_id)
        partner = await client.get_entity(partner_id)

        remove_ship(sender_id, partner_id)
        breakup_requests.pop(str(sender_id), None)
        breakup_requests.pop(str(partner_id), None)

        await event.edit(
            f"{get_ship_name(sender)} ❤️ {get_ship_name(partner)}\n\n"
            f"💔 ၂ ဦးသဘောတူ လမ်းခွဲလိုက်ပါပြီ\n\n"
            f"သူတို့ Relationship ဟာ အဆုံးသတ်သွားပါပြီ..."
        )

    @client.on(events.CallbackQuery(pattern=rb"iby_no_(\d+)_(\d+)"))
    async def iby_no(event):
        sender_id = int(event.pattern_match.group(1))
        partner_id = int(event.pattern_match.group(2))

        if event.sender_id != partner_id:
            return await event.answer(
                "❌ ဒီ Button ကို မင်းနှိပ်လို့မရဘူး", alert=True
            )

        sender = await client.get_entity(sender_id)
        partner = await client.get_entity(partner_id)

        messages = [
            "❤️ ပြဿနာတွေရှိလာရင် နားလည်မှုနဲ့ အေးဆေးဖြေရှင်းကြပါ",
            "💞 Relationship တစ်ခုမှာ နားလည်မှုက အရေးကြီးပါတယ်",
            "🥺 တစ်ယောက်ကို တစ်ယောက်တန်ဖိုးထားကြပါ",
            "✨ အချစ်ဆိုတာ သည်းခံမှုလည်းလိုပါတယ်",
        ]

        await event.edit(
            f"{get_ship_name(sender)} ❤️ {get_ship_name(partner)}\n\n"
            f"{random.choice(messages)}"
        )

    @client.on(events.NewMessage(pattern=r"^/miss(?:\s+(.+))?$"))
    async def miss_handler(event):
        sender = await event.get_sender()
        sender_id = sender.id
        sender_name = get_ship_name(sender)
        match = event.pattern_match.group(1)

        if not match:
            partner_id = get_ship_partner(sender_id)
            if not partner_id:
                return await event.reply(
                    "🥀 မင်းမှာ လွမ်းရမဲ့သူမှ မရှိတာ..."
                )

            try:
                partner = await client.get_entity(int(partner_id))
            except Exception:
                return await event.reply("❌ Partner ကိုရှာမတွေ့ဘူး")

            partner_name = get_ship_name(partner)
            messages = [
                f"{partner_name} 💌\n\nမင်းရဲ့အချစ်ကလေး {sender_name} က မင်းကိုလွမ်းနေတယ် 🥺",
                f"🥺 {partner_name}\n\n{sender_name} က မင်းကိုသတိရနေတယ်တဲ့ ❤️",
                f"💞 {partner_name}\n\n{sender_name} က မင်းမရှိရင် မနေနိုင်ဘူးတဲ့",
                f"🌸 {partner_name}\n\nမင်းရဲ့ချစ်သူ {sender_name} က မင်းကိုလွမ်းနေတာပါ",
            ]
            return await event.reply(random.choice(messages))

        try:
            target = await client.get_entity(match.strip())
        except Exception:
            return await event.reply("❌ User ကိုရှာမတွေ့ဘူး")

        target_id = target.id
        target_name = get_ship_name(target)

        if sender_id == target_id:
            return await event.reply("💀 ကိုယ့်ကိုယ်ကိုယ် လွမ်းနေတာလား")

        my_ship = get_ship_data(sender_id)
        if my_ship:
            partner_id = my_ship.get("partner")
            if str(target_id) != str(partner_id):
                try:
                    partner = await client.get_entity(int(partner_id))
                    partner_name = get_ship_name(partner)
                except Exception:
                    partner_name = "Unknown"

                texts = [
                    f"🤨 မင်းမှာ {partner_name} ရှိပါလျက်နဲ့ ဘယ်သူ့ကို လွမ်းနေတာလဲ",
                    f"💔 {partner_name} သာသိရင် ဝမ်းနည်းတော့မှာပဲ",
                    f"🥀 မင်းရဲ့ Partner က {partner_name} လေ",
                    f"🤨 {partner_name} ကို အားနာပါဦး",
                ]
                return await event.reply(random.choice(texts))

        messages = [
            f"💌 {target_name}\n\n{sender_name} က မင်းကိုလွမ်းနေတာ ❤️",
            f"🥺 {target_name}\n\n{sender_name} က မင်းကိုသတိရနေတယ်တဲ့",
            f"💞 {target_name}\n\n{sender_name} က မင်းကိုတွေ့ချင်နေတယ်",
            f"🌸 {target_name}\n\n{sender_name} က မင်းကိုအရမ်းလွမ်းနေတာပါ",
        ]
        await event.reply(random.choice(messages))


# =========================================================
# REGISTER ILY / SHIP / MISS HANDLERS
# =========================================================
try:
    register_ily_handlers(bot)
except NameError:
    # If the main client is named differently in a customized build,
    # call register_ily_handlers(<your client>) after client creation.
    pass


# =========================================================
# RUN BOT
# =========================================================

print("🚀 Bot is ready. Starting event loop...")
bot.run_until_disconnected()
