import discord
from discord.ext import commands, tasks
import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pymongo import MongoClient
from datetime import datetime, timedelta
from google.oauth2 import service_account
import tempfile
import requests
import random
import string
import asyncio
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import shutil
import rarfile
import zipfile

# Load environment variables
load_dotenv()

# Environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
GOOGLE_DRIVE_FOLDER_ID = "154LDz0RCSIaXfyD9wiyzOCLM9wCgIGHT"
LOG_CHANNEL_ID = 1349221350811635712
CATEGORY_ID = 1226130309754654751
ROLE_NOTIFICATION_CHANNEL_ID = 1349595653629804555

# Thiết lập bot Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Thiết lập Google Drive API
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
creds = None

# Đọc credentials từ biến môi trường
creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if creds_json:
    creds = service_account.Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
else:
    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json:
        with open("token.json", "w") as f:
            f.write(token_json)
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    else:
        if os.path.exists("credentials.json"):
            creds = Credentials.from_authorized_user_file("credentials.json", SCOPES)
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())

drive_service = build("drive", "v3", credentials=creds)

# Thiết lập MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["discord_bot_db"]
files_collection = db["uploaded_files"]
downloads_collection = db["downloads"]

# Lưu trạng thái tạm thời
pending_uploads = {}
channel_timers = {}  # {user_id: (channel, task)}
role_timers = {}  # {user_id: {role_name: (expiration_time, last_notified)}}

# Giới hạn kích thước file
MAX_FILE_SIZE = 8 * 1024 * 1024

# Hàm tạo ID ngẫu nhiên
def generate_download_id():
    characters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(14))

# Hàm kiểm tra role
def has_role(member, role_names):
    return any(role.name in role_names for role in member.roles)

# Hàm thêm watermark
def add_watermark(input_path, output_path, watermark_text="Watermarked by Bot", opacity=50):
    try:
        image = Image.open(input_path).convert("RGBA")
        width, height = image.size
        watermark_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)
        font_size = int(min(width, height) * 0.01)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()  # Sử dụng font mặc định nếu arial.ttf không có
        text_width, text_height = draw.textbbox((0, 0), watermark_text, font=font)[2:]
        x = random.randint(0, max(0, width - text_width))
        y = random.randint(0, max(0, height - text_height))
        fill_color = (0, 0, 0, int(255 * (opacity / 100)))
        draw.text((x, y), watermark_text, font=font, fill=fill_color)
        watermarked_image = Image.alpha_composite(image, watermark_layer)
        watermarked_image = watermarked_image.convert("RGB")
        watermarked_image.save(output_path, "JPEG")
    except Exception as e:
        print(f"Error adding watermark: {e}")

# Hàm giải nén file RAR
def extract_rar(rar_path, extract_dir):
    try:
        with rarfile.RarFile(rar_path) as rf:
            rf.extractall(extract_dir)
    except rarfile.BadRarFile:
        print(f"Error: File {rar_path} is not a valid RAR file.")
        raise
    except rarfile.RarCannotExec:
        print("Error: Cannot find unrar tool. Please ensure unrar is installed.")
        raise
    except Exception as e:
        print(f"Error extracting RAR: {e}")
        raise

# Hàm nén file thành ZIP
def create_zip(output_path, source_dir):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                zf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), source_dir))

# Hàm xóa kênh sau 5 phút
async def delete_channel_after_delay(channel, user_id):
    await asyncio.sleep(300)  # 5 phút (300 giây)
    await channel.delete()
    if user_id in channel_timers:
        del channel_timers[user_id]

# Hàm xóa role sau thời gian quy định
async def remove_role_after_delay(member, role, user_id):
    await asyncio.sleep((datetime.utcnow() - role_timers[user_id][role.name][0]).total_seconds() * -1)
    await member.remove_roles(role)
    if user_id in role_timers and role.name in role_timers[user_id]:
        del role_timers[user_id][role.name]
        if not role_timers[user_id]:
            del role_timers[user_id]
    channel = bot.get_channel(ROLE_NOTIFICATION_CHANNEL_ID)
    if channel:
        await channel.send(f"{member.mention}, role {role.name} của bạn đã hết hạn và bị gỡ!")

# Hàm định dạng thời gian còn lại
def format_remaining_time(expiration_time):
    remaining = expiration_time - datetime.utcnow()
    total_seconds = remaining.total_seconds()
    if total_seconds <= 0:
        return "0 ngày 0 giờ 0 phút 0 giây"
    days = int(total_seconds // (24 * 3600))
    hours = int((total_seconds % (24 * 3600)) // 3600)
    minutes = int((total_seconds % 3600) // 60)
    return f"{days} ngày {hours} giờ {minutes} phút"

# Ánh xạ role và thời gian
role_mapping = {
    "hiepsi": "HV Hiệp Sĩ",
    "namtuoc": "HV Nam Tước",
    "tutuoc": "HV Tử Tước",
    "batuoc": "HV Bá Tước",
    "hautuoc": "HV Hầu Tước",
    "congtuoc": "HV Công Tước",
    "dct": "HV Đại Công Tước",
    "ht": "HV Hoàng Tộc",
    "xsv": "Xích Sắc Vương",
    "tsv": "Thanh Sắc Vương",
    "tusv": "Tử Sắc Vương",
    "dv": "Đế Vương"
}
role_durations = {
    "HV Hiệp Sĩ": 3456000,      # 40 ngày
    "HV Nam Tước": 6912000,     # 80 ngày
    "HV Tử Tước": 13824000,     # 160 ngày
    "HV Bá Tước": 20736000,     # 240 ngày
    "HV Hầu Tước": 27648000,    # 320 ngày
    "HV Công Tước": 34560000,   # 400 ngày
    "HV Đại Công Tước": None,
    "HV Hoàng Tộc": None,
    "Xích Sắc Vương": None,
    "Thanh Sắc Vương": None,
    "Tử Sắc Vương": None,
    "Đế Vương": None
}

@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng với tên {bot.user}")
    check_role_expirations.start()

@bot.command()
async def hotro(ctx, command=None):
    commands_info = {
        "add": "Thêm truyện mới",
        "delete": "Xóa truyện",
        "list": "Hiển thị danh sách các truyện hiện có",
        "getkey": "Lấy ObjectID của truyện cần tải",
        "download": "Tải và gửi vào kênh riêng",
        "check": "Kiểm tra thông tin lượt tải với Download ID",
        "set": "Cấp role cho user",
        "cr": "Kiểm tra role hiện tại của bạn hoặc người khác"
    }
    is_admin_mod_team = has_role(ctx.author, ["Admin", "Mod", "Team"])
    if command is None:
        if is_admin_mod_team:
            help_message = (
                "```yaml\n"
                "**Danh sách chức năng hiện có :**\n"
                f"{'add':<12} {commands_info['add']}\n"
                f"{'delete':<12} {commands_info['delete']}\n"
                f"{'getkey':<12} {commands_info['getkey']}\n"
                f"{'list':<12} {commands_info['list']}\n"
                f"{'download':<12} {commands_info['download']}\n"
                f"{'check':<12} {commands_info['check']}\n"
                f"{'set':<12} {commands_info['set']}\n"
                f"{'cr':<12} {commands_info['cr']}\n"
                "```\nGõ !hotro <lệnh> để xem chi tiết."
            )
        else:
            help_message = (
                "```yaml\n"
                "**Danh sách chức năng hiện có :**\n"
                f"{'list':<12} {commands_info['list']}\n"
                f"{'getkey':<12} {commands_info['getkey']}\n"
                f"{'download':<12} {commands_info['download']}\n"
                f"{'cr':<12} {commands_info['cr']}\n"
                "```\nGõ !hotro <lệnh> để xem chi tiết."
            )
        await ctx.send(help_message)
    else:
        command = command.lower()
        if command in commands_info:
            if command in ["add", "delete", "check", "set"] and not is_admin_mod_team:
                await ctx.send("Bạn không có quyền xem chi tiết lệnh này!")
            else:
                await ctx.send(f"**{command}**: {commands_info[command]}")
        else:
            await ctx.send(f"Không tìm thấy lệnh '{command}'. Sử dụng !hotro để xem danh sách lệnh.")

@bot.command()
@commands.check(lambda ctx: has_role(ctx.author, ["Admin", "Mod", "Team"]))
async def add(ctx):
    if not ctx.message.attachments:
        await ctx.send("Vui lòng đính kèm một file!")
        return
    attachment = ctx.message.attachments[0]
    pending_uploads[ctx.author.id] = attachment
    await ctx.send("Bạn muốn đặt tên file này là gì? Vui lòng trả lời tên file.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.author.id in pending_uploads and not message.content.startswith("!"):
        attachment = pending_uploads.pop(message.author.id)
        file_name = message.content.strip()
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        await attachment.save(temp_file.name)
        file_metadata = {"name": file_name, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaFileUpload(temp_file.name)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        file_id = file.get("id")
        drive_service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
        file_url = f"https://drive.google.com/uc?id={file_id}"
        file_data = {
            "name": file_name,
            "url": file_url,
            "upload_time": datetime.utcnow(),
            "uploader": message.author.name,
            "drive_file_id": file_id
        }
        result = files_collection.insert_one(file_data)
        await message.channel.send(f"File '{file_name}' đã được upload! ObjectID: {result.inserted_id}")
        os.unlink(temp_file.name)
    await bot.process_commands(message)

@bot.command()
@commands.check(lambda ctx: has_role(ctx.author, ["Admin", "Mod", "Team"]))
async def delete(ctx, object_id: str):
    try:
        from bson.objectid import ObjectId
        file = files_collection.find_one({"_id": ObjectId(object_id)})
        if not file:
            await ctx.send("Không tìm thấy file với ObjectID này!")
            return
        drive_file_id = file["drive_file_id"]
        drive_service.files().delete(fileId=drive_file_id).execute()
        files_collection.delete_one({"_id": ObjectId(object_id)})
        await ctx.send(f"File '{file['name']}' đã được xóa!")
    except Exception as e:
        await ctx.send(f"Có lỗi xảy ra: {str(e)}")
        return

@bot.command()
async def list(ctx):
    files = files_collection.find()
    file_list = [f"{file['name']}" for file in files]
    if not file_list:
        await ctx.send("Chưa có file nào!")
    else:
        await ctx.send("Danh sách các file:\n" + "\n".join(file_list))

@bot.command()
async def getkey(ctx, name: str):
    file = files_collection.find_one({"name": name})
    if file:
        await ctx.reply(f"{ctx.author.mention}, key của '{name}' là {file['_id']}")
    else:
        await ctx.reply(f"{ctx.author.mention}, không tìm thấy file với tên '{name}'!")

@bot.command()
async def check(ctx, download_id: str):
    try:
        download_log = downloads_collection.find_one({"download_id": download_id})
        if not download_log:
            await ctx.send(f"Không tìm thấy Download ID: {download_id}")
            return
        user_name = download_log["user_name"]
        file_name = download_log["file_name"]
        download_time = download_log["download_time"].strftime("%Y-%m-%d %H:%M:%S UTC")
        watermarked_files = download_log["watermarked_files"] if download_log["watermarked_files"] else "Không có"
        response = (
            f"**Thông tin lượt tải với Download ID: {download_id}**\n"
            f"- User: {user_name}\n"
            f"- File tải: {file_name}\n"
            f"- Thời gian tải: {download_time}\n"
            f"- File được watermark: {watermarked_files}"
        )
        await ctx.send(response)
    except Exception as e:
        await ctx.send(f"Có lỗi xảy ra: {str(e)}")
        return

@bot.command()
async def download(ctx, object_id: str):
    try:
        from bson.objectid import ObjectId
        guild = ctx.guild
        category = discord.utils.get(guild.categories, id=CATEGORY_ID)
        if not category:
            await ctx.reply(f"{ctx.author.mention}, không tìm thấy danh mục!")
            return
        file = files_collection.find_one({"_id": ObjectId(object_id)})
        if not file:
            await ctx.reply(f"{ctx.author.mention}, không tìm thấy file!")
            return
        url = file["url"]
        file_name = file["name"]
        download_id = generate_download_id()
        downloads_dir = "/tmp"  # Thay đổi sang thư mục tạm của Railway
        temp_dir = os.path.join(downloads_dir, f"temp_{file_name}_{download_id}")
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, file_name)
        print(f"Downloading to {temp_file_path}")
        response = requests.get(url)
        with open(temp_file_path, "wb") as f:
            f.write(response.content)
        print(f"Downloaded file size: {os.path.getsize(temp_file_path)} bytes")
        extracted_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extracted_dir, exist_ok=True)
        # Giải nén file RAR
        try:
            extract_rar(temp_file_path, extracted_dir)
        except Exception as e:
            await ctx.reply(f"{ctx.author.mention}, lỗi khi giải nén file: {str(e)}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        # Lấy danh sách các file ảnh
        image_files = [os.path.join(root, file) for root, _, files in os.walk(extracted_dir) for file in files if file.lower().endswith((".jpg", ".jpeg", ".png"))]
        # Kiểm tra role của người dùng
        skip_watermark = has_role(ctx.author, ["HV Bá Tước"])
        # Xác định số lượng ảnh cần watermark (nếu không skip)
        if not skip_watermark:
            total_images = len(image_files)
            if total_images < 40:
                num_to_watermark = min(5, total_images)
            elif 41 <= total_images <= 70:
                num_to_watermark = min(15, total_images)
            else:
                num_to_watermark = min(30, total_images)
            if image_files and num_to_watermark > 0:
                selected_images = random.sample(image_files, num_to_watermark)
                for selected_image in selected_images:
                    output_path = os.path.join(os.path.dirname(selected_image), f"watermarked_{os.path.basename(selected_image)}")
                    add_watermark(selected_image, output_path, watermark_text=download_id, opacity=50)
                    if os.path.exists(output_path):
                        os.replace(output_path, selected_image)
        else:
            selected_images = []
        for root, _, files in os.walk(extracted_dir):
            for file in files:
                s = os.path.join(root, file)
                d = os.path.join(temp_dir, file)
                if os.path.isfile(s):
                    base, extension = os.path.splitext(file)
                    counter = 1
                    new_d = d
                    while os.path.exists(new_d):
                        new_d = os.path.join(temp_dir, f"{base}_{counter}{extension}")
                        counter += 1
                    shutil.move(s, new_d)
        shutil.rmtree(extracted_dir)
        output_zip_path = os.path.join(downloads_dir, f"{file_name}.zip")
        files_to_archive = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
        if files_to_archive:
            create_zip(output_zip_path, temp_dir)
        else:
            await ctx.reply(f"{ctx.author.mention}, không có file nào để nén!")
            shutil.rmtree(temp_dir)
            return
        file_size = os.path.getsize(output_zip_path)
        # Xác định giới hạn kích thước file dựa trên cấp độ boost
        boost_level = guild.premium_tier
        if boost_level == 0:
            max_file_size = 8 * 1024 * 1024
        elif boost_level == 1:
            max_file_size = 25 * 1024 * 1024
        elif boost_level == 2:
            max_file_size = 50 * 1024 * 1024
        elif boost_level == 3:
            max_file_size = 100 * 1024 * 1024
        if file_size > max_file_size:
            await ctx.reply(f"{ctx.author.mention}, file quá lớn ({file_size / (1024 * 1024):.2f} MB). Giới hạn: {max_file_size / (1024 * 1024):.2f} MB.")
            shutil.rmtree(temp_dir)
            return
        user = ctx.author
        channel_name = f"{user.name.lower()}-channel"
        if user.id in channel_timers:
            existing_channel = channel_timers[user.id][0]
            old_task = channel_timers[user.id][1]
            old_task.cancel()
            with open(output_zip_path, "rb") as f:
                await existing_channel.send(file=discord.File(f, f"{file_name}.zip"))
            await existing_channel.send("File đã được gửi! Kênh sẽ xóa sau 5 phút.")
            new_task = asyncio.create_task(delete_channel_after_delay(existing_channel, user.id))
            channel_timers[user.id] = (existing_channel, new_task)
        else:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            new_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
            with open(output_zip_path, "rb") as f:
                await new_channel.send(file=discord.File(f, f"{file_name}.zip"))
            await new_channel.send("File đã được gửi! Kênh sẽ xóa sau 5 phút.")
            task = asyncio.create_task(delete_channel_after_delay(new_channel, user.id))
            channel_timers[user.id] = (new_channel, task)
        os.remove(output_zip_path)
        await ctx.reply(f"{ctx.author.mention}, đã gửi file vào kênh riêng!")
        shutil.rmtree(temp_dir)
        download_log = {
            "download_time": datetime.utcnow(),
            "user_name": f"{ctx.author.name}#{ctx.author.discriminator}",
            "download_id": download_id,
            "file_name": file_name,
            "watermarked_files": [os.path.basename(img) for img in selected_images] if 'selected_images' in locals() else []
        }
        downloads_collection.insert_one(download_log)
        if ctx.channel.id == 1349219192666194063:
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                download_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                log_message = (
                    f"Watermark vào các file: {', '.join(download_log['watermarked_files']) if download_log['watermarked_files'] else 'Không có'}\n"
                    f"User: {ctx.author.name}#{ctx.author.discriminator}\n"
                    f"Time: {download_time}\n"
                    f"Download ID: {download_id}"
                )
                await log_channel.send(log_message)
    except Exception as e:
        print(f"Error in download: {e}")
        await ctx.reply(f"{ctx.author.mention}, có lỗi xảy ra: {str(e)}")
        return

@bot.command()
@commands.check(lambda ctx: has_role(ctx.author, ["Admin", "Mod", "Team"]))
async def set(ctx):
    if len(ctx.message.mentions) != 1:
        await ctx.send("Vui lòng mention đúng một người!")
        return
    user = ctx.message.mentions[0]
    role_part = ctx.message.content.split(maxsplit=2)[2] if len(ctx.message.content.split()) > 2 else ""
    if not role_part:
        await ctx.send("Vui lòng cung cấp danh sách role (ví dụ: hiepsi-namtuoc-tutuoc-batuoc)!")
        return
    roles_input = role_part.split("-")
    roles_to_add = []
    invalid_roles = []
    for role_input in roles_input:
        if role_input in role_mapping:
            role_name = role_mapping[role_input]
            role = discord.utils.get(ctx.guild.roles, name=role_name)
            if role:
                roles_to_add.append(role)
            else:
                invalid_roles.append(role_name)
        else:
            invalid_roles.append(role_input)
    if invalid_roles:
        await ctx.send(f"Hiện chưa có role {' và '.join(invalid_roles)}, vui lòng tạo role rồi gửi lại yêu cầu!")
        return
    if roles_to_add:
        await user.add_roles(*roles_to_add)
        role_names = ", ".join(role.name for role in roles_to_add)
        for role in roles_to_add:
            duration = role_durations.get(role.name)
            if duration is not None:  # Chỉ tạo bộ đếm nếu duration có giá trị
                expiration_time = datetime.utcnow() + timedelta(seconds=duration)
                if user.id not in role_timers:
                    role_timers[user.id] = {}
                role_timers[user.id][role.name] = (expiration_time, None)
                asyncio.create_task(remove_role_after_delay(user, role, user.id))
        await ctx.send(f"{user.mention}, bạn đã được cấp role {role_names}!")
        notification_channel = bot.get_channel(ROLE_NOTIFICATION_CHANNEL_ID)
        if notification_channel:
            await notification_channel.send(f"{user.mention}, bạn đã được cấp role {role_names}!")

@bot.command()
async def cr(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    else:
        if not has_role(ctx.author, ["Admin", "Mod", "Team"]):
            await ctx.send(f"{ctx.author.mention}, bạn không có quyền kiểm tra role của người khác! Hãy dùng `!cr` để kiểm tra role của chính bạn.")
            return
    user_id = user.id
    if user_id in role_timers and role_timers[user_id]:
        role_messages = []
        for role_name, (expiration_time, last_notified) in role_timers[user_id].items():
            remaining = expiration_time - datetime.utcnow()
            total_seconds = remaining.total_seconds()
            if total_seconds > 0:
                days = int(total_seconds // (24 * 3600))
                hours = int((total_seconds % (24 * 3600)) // 3600)
                minutes = int((total_seconds % 3600) // 60)
                role_messages.append(f"Role {role_name} của {user.name} còn {days} ngày {hours} giờ {minutes} phút")
        if role_messages:
            await ctx.send(", ".join(role_messages))
        else:
            await ctx.send(f"{user.name} không có role nào đang hoạt động!")
    else:
        await ctx.send(f"{user.name} không có role nào!")

@tasks.loop(minutes=10)
async def check_role_expirations():
    guild = bot.guilds[0]
    notification_channel = bot.get_channel(ROLE_NOTIFICATION_CHANNEL_ID)
    if not notification_channel:
        print("Không tìm thấy kênh thông báo thời gian còn lại!")
        return
    current_time = datetime.utcnow()
    for member in guild.members:
        if member.id in role_timers:
            for role_name, (expiration_time, last_notified) in list(role_timers[member.id].items()):
                remaining_time = expiration_time - current_time
                remaining_seconds = remaining_time.total_seconds()
                if 0 < remaining_seconds < 5 * 24 * 3600:
                    if last_notified is None or (current_time - last_notified).total_seconds() >= 10:
                        formatted_time = format_remaining_time(expiration_time)
                        await notification_channel.send(
                            f"{member.mention}, role {role_name} của bạn còn {formatted_time}, "
                            f"vui lòng nhớ gia hạn, xin cảm ơn!"
                        )
                        role_timers[member.id][role_name] = (expiration_time, current_time)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("Bạn không có quyền sử dụng lệnh này!")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("Không tìm thấy người dùng! Vui lòng mention một người dùng hợp lệ (ví dụ: @user).")
    else:
        raise error

# Chạy bot
bot.run(DISCORD_TOKEN)
