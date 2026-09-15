import os
import re
import json
import asyncio
import requests
import feedparser
import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip

def get_latest_news():
    feed = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
    entry = feed.entries[0]
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
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()

async def create_voiceover(text, audio_path="voice.mp3"):
    communicate = edge_tts.Communicate(text, voice="en-US-ChristopherNeural")
    await communicate.save(audio_path)

def create_image(title, news_text, image_path="frame.png"):
    img = Image.new("RGB", (1080, 1920), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1080, 200)], fill=(220, 38, 38))
    draw.text((60, 75), "THE DAILY BRIEF", fill=(255, 255, 255))
    draw.text((80, 350), f"BREAKING NEWS:\n{title}", fill=(248, 250, 252))
    draw.text((80, 700), f"{news_text[:280]}...", fill=(203, 213, 225))
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
    print("Fetching news...")
    title, summary = get_latest_news()
    
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
