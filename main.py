import os
import sys
import time
import math
import datetime
import urllib.parse
import feedparser
import requests
import numpy as np
from PIL import Image, ImageFilter
from google import genai
from gtts import gTTS
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips
)
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

# --- 4. GENERATE SCRIPT VIA GEMINI WITH FALLBACK ---
script_text = None
try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
Write a suspenseful 20-second YouTube Shorts script about this news story.
Headline: {title}
Context: {summary}
Output spoken text only.
"""
    res = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    if res.text:
        script_text = res.text.strip().replace("*", "")
except Exception as e:
    print(f"AI generation bypassed: {e}")

if not script_text:
    script_text = f"Breaking news update. {title}. {summary}"

print(f"Script: {script_text}")

# --- 5. TEXT TO SPEECH ---
tts = gTTS(text=script_text, lang='en', tld='com')
tts.save("voice.mp3")
voice_audio = AudioFileClip("voice.mp3")
total_duration = voice_audio.duration + 0.8

# --- 6. MULTI-IMAGE ACQUISITION & SAFE 9:16 RENDERING ---
def build_portrait_slide(img_path, output_name):
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        # 1. Blurred background
        bg_scale = max(1080 / im.width, 1920 / im.height)
        bg_sz = (int(im.width * bg_scale), int(im.height * bg_scale))
        bg = im.resize(bg_sz, Image.Resampling.LANCZOS)
        l = (bg.width - 1080) // 2
        t = (bg.height - 1920) // 2
        bg = bg.crop((l, t, l + 1080, t + 1920)).filter(ImageFilter.GaussianBlur(radius=30))
        
        # 2. Sharp foreground
        fg_scale = 1000 / im.width
        fg_sz = (1000, int(im.height * fg_scale))
        fg = im.resize(fg_sz, Image.Resampling.LANCZOS)
        x = (1080 - 1000) // 2
        y = (1920 - fg.height) // 2 - 30
        bg.paste(fg, (x, y))
        bg.save(output_name, quality=95)

# Primary Story Image
r1 = requests.get(primary_image, timeout=15)
with open("img1_raw.jpg", "wb") as f:
    f.write(r1.content)
build_portrait_slide("img1_raw.jpg", "slide1.jpg")

image_files = ["slide1.jpg"]

for idx in range(2, 4):
    try:
        extra_url = f"https://picsum.photos/1080/720?random={idx}"
        r_extra = requests.get(extra_url, timeout=10)
        raw_name = f"img{idx}_raw.jpg"
        slide_name = f"slide{idx}.jpg"
        with open(raw_name, "wb") as f:
            f.write(r_extra.content)
        build_portrait_slide(raw_name, slide_name)
        image_files.append(slide_name)
    except Exception:
        pass

# --- 7. SLIDESHOW (PILLOW-POWERED SMOOTH ZOOM) ---
slide_dur = total_duration / len(image_files)
video_slides = []

for s_path in image_files:
    pil_img = Image.open(s_path).convert("RGB")
    
    # Custom frame function avoiding MoviePy resize bugs
    def make_zoom_frame(t, base_im=pil_img, dur=slide_dur):
        zoom = 1.0 + 0.04 * (t / dur)
        w, h = base_im.size
        new_w, new_h = int(w * zoom), int(h * zoom)
        resized = base_im.resize((new_w, new_h), Image.Resampling.BILINEAR)
        left = (new_w - 1080) // 2
        top = (new_h - 1920) // 2
        cropped = resized.crop((left, top, left + 1080, top + 1920))
        return np.array(cropped)

    from moviepy.video.VideoClip import VideoClip
    clip = VideoClip(make_zoom_frame, duration=slide_dur)
    video_slides.append(clip)

slideshow = concatenate_videoclips(video_slides, method="compose")

# Overlay Badges & Headline
badge = TextClip(
    "🔴 BREAKING NEWS",
    fontsize=34,
    color='#FF0033',
    font='DejaVu-Sans-Bold',
    bg_color='white'
).set_position(('center', 220)).set_duration(total_duration)

headline = TextClip(
    title,
    fontsize=44,
    color='white',
    font='DejaVu-Sans-Bold',
    method='caption',
    size=(960, None),
    bg_color='rgba(0,0,0,0.75)'
).set_position(('center', 280)).set_duration(total_duration)

# --- 8. DRAMATIC NEWS SFX AUDIO ---
def news_sound_effect(t):
    pulse = 0.07 * math.sin(2 * math.pi * 90 * t)
    tick = 0.05 * math.sin(2 * math.pi * 1200 * t) * (math.exp(-60 * (t % 0.5)))
    return pulse + tick

sfx_audio = AudioClip(news_sound_effect, duration=total_duration).volumex(0.35)
final_audio = CompositeAudioClip([voice_audio.volumex(1.0), sfx_audio])

# Render Output Video
video = CompositeVideoClip([slideshow, badge, headline], size=(1080, 1920))
video = video.set_audio(final_audio)
video.write_videofile("final_shorts.mp4", fps=24, codec="libx264", audio_codec="aac")

# --- 9. YOUTUBE UPLOAD ---
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

# --- 10. UPDATE LOG ---
with open(HISTORY_FILE, "a", encoding="utf-8") as f:
    f.write(f"{target_id}|{today_str}\n")
print(f"Saved {target_id} to {HISTORY_FILE}")
