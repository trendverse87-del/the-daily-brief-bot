import os
import sys
import textwrap
import asyncio
import feedparser
import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont
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
        
    return entry.title, entry.summary

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

def create_image(title, news_text, image_path="frame.png"):
    img = Image.new("RGB", (1080, 1920), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    
    # Load Ubuntu system fonts safely
    font_bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_normal_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    if os.path.exists(font_bold_path):
        font_header = ImageFont.truetype(font_bold_path, 60)
        font_badge = ImageFont.truetype(font_bold_path, 38)
        font_title = ImageFont.truetype(font_bold_path, 54)
    else:
        font_header = font_badge = font_title = ImageFont.load_default()

    if os.path.exists(font_normal_path):
        font_body = ImageFont.truetype(font_normal_path, 42)
    else:
        font_body = ImageFont.load_default()

    # Red Top Banner
    draw.rectangle([(0, 0), (1080, 220)], fill=(220, 38, 38))
    draw.text((60, 80), "THE DAILY BRIEF", fill=(255, 255, 255), font=font_header)
    
    # Breaking News Badge
    draw.rounded_rectangle([(70, 300), (450, 370)], radius=12, fill=(239, 68, 68))
    draw.text((95, 314), "BREAKING NEWS", fill=(255, 255, 255), font=font_badge)
    
    # Headline Card
    draw.rounded_rectangle([(70, 410), (1010, 850)], radius=24, fill=(30, 41, 59))
    wrapped_title = textwrap.fill(title, width=30)
    draw.text((110, 460), wrapped_title, fill=(255, 255, 255), font=font_title, spacing=16)
    
    # Summary Card
    draw.rounded_rectangle([(70, 900), (1010, 1520)], radius=24, fill=(30, 41, 59))
    clean_summary = news_text.replace('\n', ' ')
    wrapped_body = textwrap.fill(clean_summary[:220] + "...", width=34)
    draw.text((110, 950), wrapped_body, fill=(226, 232, 240), font=font_body, spacing=18)
    
    img.save(image_path)

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
    title, summary = check_and_get_news()
    
    print("Generating AI script...")
    script = generate_script(title, summary)
    
    print("Generating TTS voiceover...")
    asyncio.run(create_voiceover(script))
    
    print("Generating visual frame...")
    create_image(title, script)
    
    print("Rendering video...")
    build_video()
    
    print("Uploading to YouTube...")
    upload_to_youtube(title, script)

if __name__ == "__main__":
    main()
