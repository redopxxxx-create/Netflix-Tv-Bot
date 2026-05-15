import os

# List of random images (must be a list, not a tuple)
PICS = (
    "https://spiritcat122.github.io/Images/p/14822.jpg",
    "https://spiritcat122.github.io/Images/p/14832.jpg",
    "https://spiritcat122.github.io/Images/p/16935.png",
    "https://spiritcat122.github.io/Images/p/19707529050667fbd4b3b22e0044fcd2.jpg",
    "https://spiritcat122.github.io/Images/p/24252.webp",
    "https://spiritcat122.github.io/Images/p/406dcfbd66f2eba1fdd642632c64ea26.jpeg",
    "https://spiritcat122.github.io/Images/p/4f5d5764-3ee2-499c-8e03-ece55ea51e05-blue-exorcist-wallpaper.webp",
    "https://spiritcat122.github.io/Images/p/6d36a24ba86063c5ea9c13b216e5d080.jpg",
    "https://spiritcat122.github.io/Images/p/753046-4k-ultra-hd-one-piece-wallpaper-and-background-image.jpg",
    "https://spiritcat122.github.io/Images/p/7830f5da-0100-4172-bf5f-aa7f94716c71-anime-background.webp",
    "https://spiritcat122.github.io/Images/p/986f9ff7e262b9d57f4256c7a5a0b838.jpeg",
    "https://spiritcat122.github.io/Images/p/GrszpcQXoAAtyUk.jpg",
    "https://spiritcat122.github.io/Images/p/alone-anime-guy-with-umbrella-under-the-water-city-wallpaper-1280x720_45.jpg",
    "https://spiritcat122.github.io/Images/p/anime-eyes-illustration_23-2151660526.jpg",
    "https://spiritcat122.github.io/Images/p/anime-scenery-sitting-4k-hs-1920x1080.jpg",
    "https://spiritcat122.github.io/Images/p/b1BfOn.jpg",
    "https://spiritcat122.github.io/Images/p/dI-PlrAnrf2X70rq6LxiFsboPA4hzS-2Zp4--llgH2c.webp",
    "https://spiritcat122.github.io/Images/p/download.jpeg",
    "https://spiritcat122.github.io/Images/p/guts-manga-berserk-5k-uk.jpg",
    "https://spiritcat122.github.io/Images/p/johan_liebert_minimalist__monster__by_earthlurker_db6gruz-fullview.png",
    "https://spiritcat122.github.io/Images/p/keyakizaka46-wallpaper-1280x768_13.jpg",
    "https://spiritcat122.github.io/Images/p/makima-from-chainsaw-man-4k-hl.jpg",
    "https://spiritcat122.github.io/Images/p/new-desktop-wallpaper-i-just-love-hild-so-much-v0-pr51ftkjbv9c1.webp",
    "https://spiritcat122.github.io/Images/p/one-piece-nico-robin-epic-desktop-wallpaper-preview.jpg",
    "https://ik.imagekit.io/jbxs2z512/samurai-hd-wallpap.png?updatedAt=1760517212353",
    "https://spiritcat122.github.io/Images/p/samurai-on-horseback-landscape-desktop-wallpaper-preview.jpg",
    "https://spiritcat122.github.io/Images/p/satoru-gojo-red-reversal-jujutsu-kaisen-9166.jpg",
    "https://ik.imagekit.io/jbxs2z512/zzz-1-4-banners-miyabi-harumasa.jpg_width=1200&height=900&fit=crop&quality=100&format=png&enable=upscale&auto=webp?updatedAt=1760517596231",
    "https://ik.imagekit.io/jbxs2z512/thumb-1920-1371019.png",
    "https://ik.imagekit.io/jbxs2z512/sb1ybl6cxf4b1.png?updatedAt=1760517673506",
    "https://ik.imagekit.io/jbxs2z512/e99cc5906da542ac599442b29bae4c8e.jpg?updatedAt=1760517929037",
    "https://ik.imagekit.io/jbxs2z512/7e1f4bcfec6be57c87e942c601b5271e.jpg?updatedAt=1760517959267",
    "https://ik.imagekit.io/jbxs2z512/a8dc6f1ff50cf0569297b875f601cb16.jpg?updatedAt=1760517993653",
    "https://ik.imagekit.io/jbxs2z512/01_648c4ba8-9d85-4e51-b332-22afbb9b05bb.jpg_v=1750670418?updatedAt=1760518085669",
    "https://ik.imagekit.io/jbxs2z512/vivian-wallpaper_8803af5f-cb42-4a6b-8e8a-db03142ef67d.jpg_v=1750671646?updatedAt=1760518112679",
    "https://ik.imagekit.io/jbxs2z512/08_b44d65b0-12ee-4aed-bab7-f7270aa9dcc9.jpg_v=1750670790?updatedAt=1760518142703",
    "https://ik.imagekit.io/jbxs2z512/Vivians-kit-coninues-the-off-field-attacks-in-ZZZ.jpg?updatedAt=1760518176568",
    "https://ik.imagekit.io/jbxs2z512/GpgedBkWkAAyKPU_format=jpg&name=4096x4096?updatedAt=1760518212517",
    "https://ik.imagekit.io/jbxs2z512/06_7445c21b-c17b-462f-a381-a1081483bdec.jpg_v=1750670790?updatedAt=1760518255243",
    "https://ik.imagekit.io/jbxs2z512/05_f9d4355c-5a73-4c13-a994-74ff8a0b6199.jpg_v=1750670460?updatedAt=1760518285743",
    "https://ik.imagekit.io/jbxs2z512/bf82e8564b7b2b5d786160016234c8cf_6003966760177598255.webp_x-oss-process=image_2Fresize_2Cs_1000_2Fauto-orient_2C0_2Finterlace_2C1_2Fformat_2Cwebp_2Fquality_2Cq_70?updatedAt=1760518374448",
    "https://ik.imagekit.io/jbxs2z512/1386555.jpg?updatedAt=1760518403026"
)

# Telegram API credentials (read from env or fallback to existing values)
API_ID = int(os.getenv("API_ID", "33010075"))
API_HASH = os.getenv("API_HASH", "79009639612f5bfc9c250b78140df80f")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8643787387:AAFRavDqsiczaqIicX0bVjPBIQn4iOU589k")

# Admin IDs (comma-separated env var, fallback to hardcoded list)
_admins_env = os.getenv("ADMINS", "5376744566,6227927913")
ADMINS = [int(x) for x in _admins_env.split(",") if x.strip()]

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://mifeto6598_db_user:YOUR_PASSWORD@cluster0.a8qiney.mongodb.net/netflixtvlogbot")
DB_NAME = os.getenv("DB_NAME", "netflixtvlogbot")

# Thread configuration
MAX_THREADS = int(os.getenv("MAX_THREADS", "50"))

# Force Subscribe configuration
# Format: "Channel Name:ChannelID" (optional invite link after a colon)
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "Join Channel:-1003910786672")

# Force Subscribe message
FORCE_SUB_TEXT = os.getenv("FORCE_SUB_TEXT", "<b>⚠️ You must join our channels to use this bot!</b>\n\nPlease join the channels below and click REFRESH.")

# Log channel for errors (must be an integer, with negative sign for supergroups)
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "-1003910786672"))