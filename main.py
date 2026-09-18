import os
import sys
import time
import asyncio
import datetime
import feedparser
import requests
import edge_tts
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont
from google import genai
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip
)
from moviepy.video.VideoClip import VideoClip
from moviepy.audio.AudioClip import AudioClip
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- 1. CONFIGURATION ---
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"
]

HISTORY_FILE = "last_news.txt"
DAILY_LIMIT = 8
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or "AQ.Ab8RN6KeN6UXhMEwUVaPinOKpjtLNUDgEf0qNFBRBm992InRqA"

# --- 2. CHECK HISTORY & DAILY LIMIT ---
seen_links = set()
today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
today_uploads = 0

if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            parts = line_str.split("|")
            seen_links.add(parts[0])
            if len(parts) > 1 and parts[1] == today_str:
                today_uploads += 1

if today_uploads >= DAILY_LIMIT:
    print(f"Daily limit reached ({today_uploads}/{DAILY_LIMIT}). Exiting.")
    sys.exit(0)

# --- 3. FETCH RSS FEEDS & GET LATEST VIRAL STORY ---
print("Fetching BBC News Categories...")
all_entries = []

for feed_url in RSS_FEEDS:
    try:
        f = feedparser.parse(feed_url)
        all_entries.extend(f.entries)
    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")

all_entries.sort(
    key=lambda x: x.get("published_parsed") or x.get("updated_parsed") or time.gmtime(0),
    reverse=True
)

selected_entry = None
primary_image = None

for entry in all_entries:
    entry_id = entry.get("id") or entry.get("link")
    if entry_id in seen_links:
        continue

    found_img = None
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        found_img = entry.media_thumbnail[0]["url"]
    elif "enclosures" in entry:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                found_img = enc.get("url") or enc.get("href")
                break

    if found_img:
        selected_entry = entry
        primary_image = found_img
        break

if not selected_entry:
    print("No fresh news found. Exiting.")
    sys.exit(0)

title = selected_entry.title
summary = selected_entry.get("summary", "")
target_id = selected_entry.get("id") or selected_entry.get("link")
print(f"Selected Viral Story: {title}")

# --- 4. GENERATE SCRIPT VIA GEMINI WITH RETENTION HOOK ---
script_text = None
try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
Write a suspenseful, fast-paced 15-20 second YouTube Shorts news script.
Hook viewers intensely in the first sentence.
End with a fast call-to-action: "Follow for instant daily updates!"
Headline: {title}
Context: {summary}
Output spoken words only. No labels, markdown, emojis, or sound notes.
"""
    res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    if res.text:
        script_text = res.text.strip().replace("*", "").replace("\n", " ")
except Exception as e:
    print(f"AI generation bypassed: {e}")

if not script_text:
    script_text = f"Breaking news update. {title}. {summary}. Follow for instant daily updates!"

print(f"Script: {script_text}")

# --- 5. REALISTIC MALE AI VOICE (MICROSOFT EDGE TTS - CHRISTOPHER) ---
async def generate_voice(text, output_file):
    communicate = edge_tts.Communicate(text, voice="en-US-ChristopherNeural", rate="+15%")
    await communicate.save(output_file)

asyncio.run(generate_voice(script_text, "voice.mp3"))
voice_audio = AudioFileClip("voice.mp3")
total_duration = voice_audio.duration + 0.8

# --- 6. SUBTITLE CHUNKING LOGIC ---
words = script_text.split()
chunk_size = 3
chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
chunk_duration = total_duration / max(len(chunks), 1)

# --- 7. IMAGE PREPARATION & FONTS ---
r1 = requests.get(primary_image, timeout=15)
with open("raw.jpg", "wb") as f:
    f.write(r1.content)

raw_im = Image.open("raw.jpg").convert("RGB")

# 1. Blurred 9:16 background
bg_scale = max(1080 / raw_im.width, 1920 / raw_im.height)
bg_sz = (int(raw_im.width * bg_scale), int(raw_im.height * bg_scale))
bg_base = raw_im.resize(bg_sz, Image.Resampling.BILINEAR)
l = (bg_base.width - 1080) // 2
t = (bg_base.height - 1920) // 2
bg_base = bg_base.crop((l, t, l + 1080, t + 1920)).filter(ImageFilter.GaussianBlur(radius=35))

# Font loaders with fallbacks
def load_font(size):
    for f in ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(f, size)
        except:
            pass
    return ImageFont.load_default()

font_badge = load_font(34)
font_title = load_font(44)
font_caption = load_font(48)

# Title line wrap
def wrap_title(text, max_chars=30):
    lines, cur = [], []
    for w in text.split():
        if sum(len(x) for x in cur) + len(cur) + len(w) <= max_chars:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines

title_lines = wrap_title(title, max_chars=30)[:3]

# --- 8. FRAME RENDERING (KEN BURNS + TITLES + DYNAMIC CAPTIONS) ---
fg_w = 1000
fg_h = int(fg_w * (raw_im.height / raw_im.width))

def make_cinematic_frame(t):
    frame = bg_base.copy()
    draw = ImageDraw.Draw(frame)

    # 1. Ken Burns Zoom & Subtle Sway on Sharp Foreground
    progress = t / total_duration
    zoom = 1.0 + 0.10 * progress
    sway = int(np.sin(progress * np.pi) * 20)

    scaled_w = int(fg_w * zoom)
    scaled_h = int(fg_h * zoom)
    scaled_img = raw_im.resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)

    crop_x = max(0, (scaled_w - fg_w) // 2 + sway)
    crop_y = max(0, (scaled_h - fg_h) // 2)
    fg_cropped = scaled_img.crop((crop_x, crop_y, crop_x + fg_w, crop_y + min(fg_h, scaled_h - crop_y)))

    pos_x = (1080 - fg_w) // 2
    pos_y = 580
    frame.paste(fg_cropped, (pos_x, pos_y))
    draw.rectangle([pos_x - 3, pos_y - 3, pos_x + fg_w + 3, pos_y + fg_cropped.height + 3], outline=(255, 255, 255), width=3)

    # 2. BREAKING NEWS Badge & Headline Overlay
    draw.rectangle([pos_x, 210, pos_x + 430, 275], fill=(220, 20, 60))
    draw.text((pos_x + 20, 222), "🔴 BREAKING NEWS", font=font_badge, fill=(255, 255, 255))

    line_y = 295
    for line in title_lines:
        draw.text((pos_x + 3, line_y + 3), line, font=font_title, fill=(0, 0, 0)) # Shadow
        draw.text((pos_x, line_y), line, font=font_title, fill=(255, 255, 255))
        line_y += 55

    # 3. Dynamic Animated Subtitles (Yellow text inside dark pill box)
    chunk_idx = min(int(t / chunk_duration), len(chunks) - 1)
    current_caption = chunks[chunk_idx].upper()

    cap_box_y = pos_y + fg_cropped.height + 90
    cap_w = len(current_caption) * 28 + 80
    cap_x1 = max(60, 540 - (cap_w // 2))
    cap_x2 = min(1020, 540 + (cap_w // 2))

    draw.rounded_rectangle([cap_x1, cap_box_y, cap_x2, cap_box_y + 85], radius=16, fill=(0, 0, 0), outline=(255, 215, 0), width=3)
    draw.text((540, cap_box_y + 42), current_caption, font=font_caption, fill=(255, 230, 0), anchor="mm")

    return np.array(frame)

animated_video = VideoClip(make_cinematic_frame, duration=total_duration)

# --- 9. SFX & AUDIO COMPOSITION ---
def news_sound_effect(t):
    pulse = 0.05 * np.sin(2 * np.pi * 90 * t)
    tick = 0.04 * np.sin(2 * np.pi * 1200 * t) * np.exp(-50 * (t % 0.5))
    mono = pulse + tick
    return np.column_stack((mono, mono))

sfx_audio = AudioClip(news_sound_effect, duration=total_duration)
final_audio = CompositeAudioClip([voice_audio, sfx_audio]).set_duration(total_duration)
animated_video = animated_video.set_audio(final_audio)

# --- 10. CRISP 8000k BITRATE RENDERING ---
print("Rendering crisp video with dynamic subtitles...")
animated_video.write_videofile(
    "final_shorts.mp4",
    fps=30,
    codec="libx264",
    audio_codec="aac",
    bitrate="8000k",
    preset="fast",
    threads=4,
    logger=None
)

# --- 11. YOUTUBE UPLOAD ---
print("Uploading to YouTube...")
creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload"])
youtube = build("youtube", "v3", credentials=creds)

upload_title = f"{title[:75]} | Breaking News #Shorts"
body = {
    "snippet": {
        "title": upload_title,
        "description": f"{script_text}\n\nStay tuned for instant news updates across the globe.\n#Shorts #BreakingNews #WorldNews #Trending",
        "tags": ["Shorts", "News", "BreakingNews", "Trending", "WorldNews"],
        "categoryId": "25"
    },
    "status": {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False
    }
}

media = MediaFileUpload("final_shorts.mp4", chunksize=-1, resumable=True, mimetype="video/mp4")
req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
res = req.execute()
print(f"Uploaded Successfully! Video ID: {res.get('id')}")

# --- 12. UPDATE LOG ---
with open(HISTORY_FILE, "a", encoding="utf-8") as f:
    f.write(f"{target_id}|{today_str}\n")
print(f"Saved {target_id} to {HISTORY_FILE}")
