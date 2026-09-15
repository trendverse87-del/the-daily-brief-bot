import os
import sys
import io
import textwrap
import asyncio
import requests
import feedparser
import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont, ImageOps
from moviepy.editor import ImageClip, AudioFileClip

HISTORY_FILE = "processed_history.txt"

def get_processed_ids():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_processed_id(news_id):
    with open(HISTORY_FILE, "a") as f:
        f.write(f"{news_id}\n")

def get_new_stories(limit=3):
    feed = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
    if not feed.entries:
        print("News feed is empty.")
        return []

    processed_ids = get_processed_ids()
    new_stories = []

    for entry in feed.entries:
        news_id = getattr(entry, "id", entry.link)
        if news_id not in processed_ids:
            image_url = None
            if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
                image_url = entry.media_thumbnail[0]["url"]
            elif "links" in entry:
                for link in entry.links:
                    if link.get("type", "").startswith("image/"):
                        image_url = link.get("href")
                        break

            new_stories.append({
                "id": news_id,
                "title": entry.title,
                "summary": entry.summary,
                "image_url": image_url
            })
            if len(new_stories) >= limit:
                break

    return new_stories

def generate_script(title, summary):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = (
        f"You are a fast-paced YouTube Shorts news reporter. Based on this news:\n"
        f"Title: {title}\nSummary: {summary}\n\n"
        f"Write an energetic 30-40 word script suitable for a 15-20 second YouTube Short. "
        f"Provide ONLY the spoken text, without markdown, notes, or emojis."
    )
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    return response.text.strip()

async def create_voiceover(text, audio_path="voice.mp3"):
    communicate = edge_tts.Communicate(text, voice="en-US-ChristopherNeural")
    await communicate.save(audio_path)

def create_image(title, news_text, image_url=None, output_path="frame.png"):
    img = Image.new("RGB", (1080, 1920), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    font_bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_normal_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    font_header = ImageFont.truetype(font_bold_path, 60) if os.path.exists(font_bold_path) else ImageFont.load_default()
    font_badge = ImageFont.truetype(font_bold_path, 34) if os.path.exists(font_bold_path) else ImageFont.load_default()
    font_title = ImageFont.truetype(font_bold_path, 46) if os.path.exists(font_bold_path) else ImageFont.load_default()
    font_body = ImageFont.truetype(font_normal_path, 38) if os.path.exists(font_normal_path) else ImageFont.load_default()

    # Red Top Banner
    draw.rectangle([(0, 0), (1080, 220)], fill=(220, 38, 38))
    draw.text((60, 75), "THE DAILY BRIEF", fill=(255, 255, 255), font=font_header)

    # Breaking News Tag
    draw.rounded_rectangle([(60, 260), (430, 325)], radius=12, fill=(239, 68, 68))
    draw.text((80, 275), "BREAKING NEWS", fill=(255, 255, 255), font=font_badge)

    # Headline Card
    draw.rounded_rectangle([(60, 345), (1020, 660)], radius=20, fill=(30, 41, 59))
    wrapped_title = textwrap.fill(title, width=32)
    draw.text((90, 380), wrapped_title, fill=(255, 255, 255), font=font_title, spacing=14)

    # Image Card
    img_box = (60, 690, 1020, 1230)
    img_w = img_box[2] - img_box[0]
    img_h = img_box[3] - img_box[1]

    loaded_thumb = None
    if image_url:
        try:
            res = requests.get(image_url, timeout=10)
            if res.status_code == 200:
                raw_img = Image.open(io.BytesIO(res.content)).convert("RGB")
                loaded_thumb = ImageOps.fit(raw_img, (img_w, img_h), method=Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"Failed to fetch image: {e}")

    if loaded_thumb:
        img.paste(loaded_thumb, (img_box[0], img_box[1]))
    else:
        draw.rounded_rectangle(img_box, radius=20, fill=(51, 65, 85))
        draw.text((380, 930), "[ WORLD NEWS ]", fill=(148, 163, 184), font=font_title)

    # Summary Card
    draw.rounded_rectangle([(60, 1260), (1020, 1690)], radius=20, fill=(30, 41, 59))
    clean_summary = news_text.replace("\n", " ")
    wrapped_body = textwrap.fill(clean_summary[:210] + "...", width=34)
    draw.text((90, 1300), wrapped_body, fill=(226, 232, 240), font=font_body, spacing=14)

    img.save(output_path)

def build_video():
    audio = AudioFileClip("voice.mp3")
    clip = ImageClip("frame.png").set_duration(audio.duration).set_audio(audio)
    clip.write_videofile("short.mp4", fps=24, codec="libx264", audio_codec="aac")

def upload_to_youtube(title, description):
    creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload"])
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": f"{title[:80]} #Shorts #News",
            "description": f"{description}\n\n#Shorts #TheDailyBrief #News",
            "tags": ["Shorts", "News", "BBC", "WorldNews"],
            "categoryId": "25"
        },
        "status": {
            "privacyStatus": "public"
        }
    }

    media = MediaFileUpload("short.mp4", chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"Uploaded Successfully! Video ID: {response.get('id')}")

def main():
    print("Checking for new stories...")
    stories = get_new_stories(limit=3)

    if not stories:
        print("No new news stories found. Exiting cleanly...")
        sys.exit(0)

    print(f"Found {len(stories)} new stories. Processing...")

    for i, story in enumerate(stories, 1):
        print(f"\n--- Processing Story {i}/{len(stories)}: {story['title']} ---")
        script = generate_script(story["title"], story["summary"])
        asyncio.run(create_voiceover(script))
        create_image(story["title"], script, story["image_url"])
        build_video()
        upload_to_youtube(story["title"], script)
        save_processed_id(story["id"])
        print(f"Story {i} completed and marked as processed.")

if __name__ == "__main__":
    main()
