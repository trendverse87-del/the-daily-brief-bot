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

def check_and_get_news():
    feed = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
    if not feed.entries:
        print("News feed is empty.")
        sys.exit(0)
        
    entry = feed.entries[0]
    news_id = getattr(entry, "id", entry.link)
    
    with open("last_news.txt", "w") as f:
        f.write(news_id)
        
    # Extract news image URL from media_thumbnail or enclosures
    image_url = None
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        image_url = entry.media_thumbnail[0]["url"]
    elif "links" in entry:
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                image_url = link.get("href")
                break
                
    return entry.title, entry.summary, image_url

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
    draw.rounded_rectangle([(60, 280), (420, 345)], radius=12, fill=(239, 68, 68))
    draw.text((80, 295), "BREAKING NEWS", fill=(255, 255, 255), font=font_badge)
    
    # 1. Headline Card
    draw.rounded_rectangle([(60, 370), (1020, 690)], radius=20, fill=(30, 41, 59))
    wrapped_title = textwrap.fill(title, width=32)
    draw.text((90, 405), wrapped_title, fill=(255, 255, 255), font=font_title, spacing=14)
    
    # 2. News Image Placement
    img_box = (60, 720, 1020, 1260)
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
        draw.text((380, 960), "[ WORLD NEWS ]", fill=(148, 163, 184), font=font_title)

    # 3. Script Summary Card
    draw.rounded_rectangle([(60, 1290), (1020, 1720)], radius=20, fill=(30, 41, 59))
    clean_summary = news_text.replace('\n', ' ')
    wrapped_body = textwrap.fill(clean_summary[:210] + "...", width=34)
    draw.text((90, 1330), wrapped_body, fill=(226, 232, 240), font=font_body, spacing=14)
    
    img.save(output_path)

def build_video():
    audio = AudioFileClip("voice.mp3")
    clip = ImageClip("frame.png").set_duration(audio.duration).set_audio(audio)
    clip.write_videofile("short.mp4", fps=24, codec="libx264", audio_codec="aac")

def upload_to_youtube(title, description):
    creds = Credentials.from_authorized_user_file("token.json", ['https://www.googleapis.com/auth/youtube.upload'])
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
    title, summary, image_url = check_and_get_news()
    
    print(f"News image URL: {image_url}")
    print("Generating AI script...")
    script = generate_script(title, summary)
    
    print("Generating TTS voiceover...")
    asyncio.run(create_voiceover(script))
    
    print("Generating visual frame with image...")
    create_image(title, script, image_url)
    
    print("Rendering video...")
    build_video()
    
    print("Uploading to YouTube...")
    upload_to_youtube(title, script)

if __name__ == "__main__":
    main()
