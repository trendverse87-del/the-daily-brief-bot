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
    
    # Breaking News Tag (Moved lower to clear YouTube top icons)
    draw.rounded_rectangle([(60, 260), (430, 325)], radius=12, fill=(239, 68, 68))
    draw.text((80, 275), "BREAKING NEWS", fill=(255, 255, 255), font=font_badge)
    
    # 1. Headline Card
    draw.rounded_rectangle([(60, 345), (1020, 660)], radius=20, fill=(30, 41, 59))
    wrapped_title = textwrap.fill(title, width=32)
    draw.text((90, 380), wrapped_title, fill=(255, 255, 255), font=font_title, spacing=14)
    
    # 2. News Image Placement
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

    # 3. Script Summary Card
    draw.rounded_rectangle([(60, 1260), (1020, 1690)], radius=20, fill=(30, 41, 59))
    clean_summary = news_text.replace('\n', ' ')
    wrapped_body = textwrap.fill(clean_summary[:210] + "...", width=34)
    draw.text((90, 1300), wrapped_body, fill=(226, 232, 240), font=font_body, spacing=14)
    
    img.save(output_path)
