import os
import sys
import time
import feedparser
import requests
from google import genai
from gtts import gTTS
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip
)
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- 1. CONFIGURATION ---
RSS_FEED_URL = "http://feeds.bbci.co.uk/news/world/rss.xml"
HISTORY_FILE = "last_news.txt"

# API Key fallback with provided key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or "AQ.Ab8RN6KeN6UXhMEwUVaPinOKpjtLNUDgEf0qNFBRBm992InRqA"

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY is not set.")
    sys.exit(1)

# --- 2. LOAD SEEN NEWS HISTORY ---
seen_links = set()
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        seen_links = set(line.strip() for line in f if line.strip())

# --- 3. FETCH RSS FEED & FIND FRESH STORY ---
print("Fetching BBC RSS Feed...")
feed = feedparser.parse(RSS_FEED_URL)

selected_entry = None
image_url = None

for entry in feed.entries[:10]:
    entry_id = entry.get("id") or entry.get("link")
    if entry_id in seen_links:
        continue

    # Find image in entry media/enclosures
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
        image_url = found_img
        break

if not selected_entry:
    print("No new un-processed news with images found in top 10 items. Exiting.")
    sys.exit(0)

title = selected_entry.title
summary = selected_entry.get("summary", "")
target_id = selected_entry.get("id") or selected_entry.get("link")

print(f"Target News Found: {title}")

# --- 4. DOWNLOAD IMAGE ---
img_response = requests.get(image_url, timeout=15)
with open("news_image.jpg", "wb") as f:
    f.write(img_response.content)

# --- 5. GENERATE SCRIPT VIA GEMINI (WITH RETRY & FALLBACK) ---
client = genai.Client(api_key=GEMINI_API_KEY)
prompt = f"""
Rewrite the following news story into an engaging, 20-30 second YouTube Shorts script.
Focus on hooks, concise facts, and crisp storytelling.

Title: {title}
Summary: {summary}

Output format:
Return ONLY the voiceover narrative text. No brackets, no stage directions, no intro greetings.
"""

candidate_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
script_text = None

for model_name in candidate_models:
    for attempt in range(3):
        try:
            print(f"Calling {model_name} (Attempt {attempt + 1})...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response.text:
                script_text = response.text.strip()
                break
        except Exception as err:
            print(f"Attempt {attempt + 1} with {model_name} failed: {err}")
            time.sleep(5)
    if script_text:
        break

if not script_text:
    print("AI generation failed across models. Using headline and summary fallback.")
    script_text = f"{title}. {summary}"

print(f"Generated Script: {script_text}")

# --- 6. TEXT TO SPEECH ---
tts = gTTS(text=script_text, lang='en', tld='com')
tts.save("voiceover.mp3")

# --- 7. VIDEO RENDERING (9:16 Shorts) ---
audio = AudioFileClip("voiceover.mp3")
duration = audio.duration + 0.5

# Image background resized for 1080x1920 with padding
image_clip = (
    ImageClip("news_image.jpg")
    .resize(width=1080)
    .set_position("center")
    .set_duration(duration)
)

# Text banner for headline
headline = TextClip(
    title,
    fontsize=48,
    color='white',
    font='DejaVu-Sans-Bold',
    method='caption',
    size=(1000, None),
    bg_color='rgba(0,0,0,0.7)'
).set_position(('center', 150)).set_duration(duration)

video = CompositeVideoClip([image_clip, headline], size=(1080, 1920))
video = video.set_audio(audio)
video.write_videofile("final_shorts.mp4", fps=24, codec="libx264", audio_codec="aac")

# --- 8. YOUTUBE UPLOAD ---
creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload"])
youtube = build("youtube", "v3", credentials=creds)

upload_title = f"{title[:80]} #Shorts #News"
body = {
    "snippet": {
        "title": upload_title,
        "description": f"{script_text}\n\nSource: BBC World News\n#Shorts #BreakingNews #WorldNews",
        "tags": ["Shorts", "News", "BBC", "World News", "Breaking News"],
        "categoryId": "25"
    },
    "status": {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False
    }
}

media = MediaFileUpload("final_shorts.mp4", chunksize=-1, resumable=True, mimetype="video/mp4")
request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
upload_response = request.execute()
print(f"Uploaded Successfully! Video ID: {upload_response.get('id')}")

# --- 9. UPDATE HISTORY FILE ---
with open(HISTORY_FILE, "a", encoding="utf-8") as f:
    f.write(f"{target_id}\n")
print("Saved story to last_news.txt")
