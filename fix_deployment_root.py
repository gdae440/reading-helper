import os

BACKEND_FILE = "backend.py"

print("🔧 正在修正后端入口，使其默认显示网页界面...")

# 这是一个完整的、修正后的 backend.py
# 包含了所有功能 (TTS, OCR, 翻译, Anki) + 正确的静态文件托管逻辑
backend_code = """
import asyncio
import json
import os
import io
import base64
import random
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx
from PIL import Image
import edge_tts
from gtts import gTTS
import genanki

# ================= 1. 配置 =================
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
VOCAB_FILE = "my_vocab.json"

VOICE_MAP_EDGE = {
    "🇬🇧 英语": [("en-GB-RyanNeural", "Ryan (英/男)"), ("en-US-ChristopherNeural", "Chris (美/男)"), ("en-US-AriaNeural", "Aria (美/女)")],
    "🇫🇷 法语": [("fr-FR-HenriNeural", "Henri (法/男)"), ("fr-FR-DeniseNeural", "Denise (法/女)")],
    "🇩🇪 德语": [("de-DE-ConradNeural", "Conrad (德/男)"), ("de-DE-KatjaNeural", "Katja (德/女)")],
    "🇷🇺 俄语": [("ru-RU-DmitryNeural", "Dmitry (俄/男)"), ("ru-RU-SvetlanaNeural", "Svetlana (俄/女)")],
    "🇨🇳 中文": [("zh-CN-XiaoxiaoNeural", "Xiaoxiao (女)"), ("zh-CN-YunxiNeural", "Yunxi (男)")],
}
VOICE_MAP_SF = {
    "男声 - Benjamin (英伦风)": "FunAudioLLM/CosyVoice2-0.5B:benjamin",
    "男声 - Alex (沉稳)": "FunAudioLLM/CosyVoice2-0.5B:alex",
    "女声 - Bella (温柔)": "FunAudioLLM/CosyVoice2-0.5B:bella",
    "女声 - Claire (清晰)": "FunAudioLLM/CosyVoice2-0.5B:claire"
}
LANG_MAP_GOOGLE = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru", "🇨🇳 中文": "zh"}

def load_vocab_data():
    if os.path.exists(VOCAB_FILE):
        try: return json.load(open(VOCAB_FILE, "r", encoding="utf-8"))
        except: return []
    return []

def save_vocab_data(data):
    try: json.dump(data, open(VOCAB_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except: pass

def compress_image(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((1024, 1024))
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# ================= 2. 核心逻辑 =================

async def get_audio_bytes_mixed_async(text, engine_type, voice_id, speed_int, api_key, base_url=None):
    if "Edge" in engine_type:
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=f"{speed_int:+d}%")
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge Error: {e}"
    elif "SiliconFlow" in engine_type:
        if not api_key: return None, "Need API Key"
        url = base_url or DEFAULT_BASE_URL
        headers = {"Authorization": f"Bearer {api_key}"}
        model_id = voice_id.split(":")[0] if ":" in voice_id else "FunAudioLLM/CosyVoice2-0.5B"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{url}/audio/speech", headers=headers, json={"model": model_id, "voice": voice_id, "input": text, "speed": 1.0 + (speed_int/100.0)}, timeout=30.0)
                res.raise_for_status()
                return res.content, None
        except Exception as e: return None, str(e)
    elif "Google" in engine_type:
        try:
            tts = gTTS(text=text, lang=LANG_MAP_GOOGLE.get(voice_id, "en"))
            mp3_fp = io.BytesIO()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, tts.write_to_fp, mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e: return None, str(e)
    return None, "Unknown Engine"

async def ai_api_call_async(type, api_key, content=None, image_bytes=None, chat_model=None, ocr_model=None, base_url=None):
    if not api_key: return None, "Need API Key"
    url = base_url or DEFAULT_BASE_URL
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    if not chat_model: chat_model = "deepseek-ai/DeepSeek-V3"
    if not ocr_model: ocr_model = "Qwen/Qwen2.5-VL-72B-Instruct"

    try:
        async with httpx.AsyncClient(base_url=url) as client:
            if type == "ocr" and image_bytes:
                b64 = compress_image(image_bytes)
                payload = {"model": ocr_model, "messages": [{"role": "user", "content": [{"type": "text", "text": "OCR text only. Keep formatting."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
                res = await client.post("/chat/completions", headers=headers, json=payload, timeout=60.0)
                res.raise_for_status()
                return res.json()['choices'][0]['message']['content'], None
            elif type == "lookup" and content:
                prompt = f\"\"\"Dictionary API. User input: "{content}". Return JSON: {{ "lang": "...", "ipa": "...", "zh": "...", "ru": "..." }} (lang example: "🇬🇧 英语", "🇷🇺 俄语")\"\"\"
                payload = {"model": chat_model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
                res = await client.post("/chat/completions", headers=headers, json=payload, timeout=30.0)
                res.raise_for_status()
                return json.loads(res.json()['choices'][0]['message']['content']), None
            elif type == "trans" and content:
                res = await client.post("/chat/completions", headers=headers, json={
                    "model": chat_model,
                    "messages": [{"role": "user", "content": f"Translate the following text to Chinese (keep it natural and concise):\\n\\n{content}"}]
                }, timeout=30.0)
                res.raise_for_status()
                return res.json()['choices'][0]['message']['content'], None
    except Exception as e: return None, str(e)

# ================= 3. API 接口 =================

app = FastAPI(title="跟读助手 Pro - Backend API", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# API Routes
class TTSRequest(BaseModel):
    text: str
    engine: str
    voice_role: str
    speed: int
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class OCRRequest(BaseModel):
    image_base64: str
    ocr_model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class LookupRequest(BaseModel):
    word: str
    chat_model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class TranslateRequest(BaseModel):
    text: str
    chat_model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class VocabItem(BaseModel):
    word: str
    lang: str = "🇬🇧 英语"
    ipa: Optional[str] = ""
    zh: Optional[str] = ""
    ru: Optional[str] = ""
    date: Optional[str] = ""

class AnkiExportRequest(BaseModel):
    words: List[str]
    api_key: Optional[str] = None
    base_url: Optional[str] = None

@app.post("/tts")
async def tts(req: TTSRequest):
    b, e = await get_audio_bytes_mixed_async(req.text, req.engine, req.voice_role, req.speed, req.api_key, req.base_url)
    if e: raise HTTPException(500, e)
    return base64.b64encode(b).decode('utf-8')

@app.post("/ocr")
async def ocr(req: OCRRequest):
    try: img_b = base64.b64decode(req.image_base64)
    except: raise HTTPException(400, "Invalid Image")
    t, e = await ai_api_call_async("ocr", req.api_key, image_bytes=img_b, ocr_model=req.ocr_model, base_url=req.base_url)
    if e: raise HTTPException(500, e)
    return {"text": t}

@app.post("/lookup")
async def lookup(req: LookupRequest):
    info, e = await ai_api_call_async("lookup", req.api_key, content=req.word, chat_model=req.chat_model, base_url=req.base_url)
    if e: raise HTTPException(500, e)
    return info

@app.post("/translate")
async def translate(req: TranslateRequest):
    t, e = await ai_api_call_async("trans", req.api_key, content=req.text, chat_model=req.chat_model, base_url=req.base_url)
    if e: raise HTTPException(500, e)
    return {"text": t}

@app.get("/config/voices")
async def voices(): return {"edge": VOICE_MAP_EDGE, "siliconflow": VOICE_MAP_SF, "google_langs": LANG_MAP_GOOGLE}

@app.get("/vocab")
async def get_vocab(): return load_vocab_data()

@app.post("/vocab/add")
async def add_vocab(item: VocabItem):
    v = load_vocab_data()
    if not any(x['word'] == item.word for x in v):
        v.insert(0, item.dict())
        save_vocab_data(v)
    return {"status": "ok", "vocab": v}

@app.post("/vocab/delete")
async def delete_vocab(req: Dict[str, str]):
    word = req.get("word")
    v = [x for x in load_vocab_data() if x['word'] != word]
    save_vocab_data(v)
    return {"status": "ok", "vocab": v}

@app.post("/vocab/anki_export")
async def export_anki_post(req: AnkiExportRequest):
    all_vocab = load_vocab_data()
    target_words = set(req.words)
    export_list = [v for v in all_vocab if v['word'] in target_words]
    if not export_list: raise HTTPException(400, "Empty selection")
    
    deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), '跟读助手生词本')
    model = genanki.Model(
        random.randrange(1 << 30, 1 << 31), 'Simple Model',
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{'name': 'Card 1', 'qfmt': '{{Question}}<br>{{Audio}}', 'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}'}]
    )
    
    media_files = []
    temp_files = []
    for i, item in enumerate(export_list):
        try:
            lang = item.get('lang', '')
            voice_role = "en-US-AriaNeural"
            if "俄" in lang or "ru" in lang or item.get('ru'): voice_role = "ru-RU-DmitryNeural"
            elif "法" in lang or "fr" in lang: voice_role = "fr-FR-HenriNeural"
            elif "德" in lang or "de" in lang: voice_role = "de-DE-ConradNeural"
            
            audio_bytes, _ = await get_audio_bytes_mixed_async(item['word'], "Edge (推荐)", voice_role, 0, req.api_key, req.base_url)
            fname = f"anki_{random.randint(10000,99999)}_{i}.mp3"
            if audio_bytes:
                with open(fname, "wb") as f: f.write(audio_bytes)
                media_files.append(fname)
                temp_files.append(fname)
                audio_field = f"[sound:{fname}]"
            else: audio_field = ""
            
            deck.add_note(genanki.Note(model=model, fields=[
                f"<div style='font-size:24px; font-weight:bold;'>{item['word']}</div><br><span style='color:grey'>[{item.get('ipa','')}]</span>",
                f"🇨🇳 {item.get('zh','')}<br>🇷🇺 {item.get('ru','')}", audio_field
            ]))
        except: continue
            
    pkg = genanki.Package(deck)
    pkg.media_files = media_files
    out_stream = io.BytesIO()
    pkg.write_to_file(out_stream)
    for f in temp_files:
        if os.path.exists(f): os.remove(f)
    out_stream.seek(0)
    return Response(content=out_stream.read(), media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename=anki_select.apkg"})

# --- 关键修复：静态文件托管 (网页界面) ---
# 1. 挂载静态资源 (CSS, JS)
if os.path.exists("frontend/dist"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

# 2. 根路径 "/" 直接返回 index.html (显示网页)
@app.get("/")
async def serve_root():
    if os.path.exists("frontend/dist/index.html"):
        return FileResponse("frontend/dist/index.html")
    return {"message": "Backend Online. Frontend not built. Please run 'npm run build' first."}

# 3. 捕获所有其他路径 (React Router 支持)
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # 排除 API 路径
    if full_path.startswith("api") or full_path.startswith("tts") or full_path.startswith("ocr"):
        raise HTTPException(404)
    if os.path.exists("frontend/dist/index.html"):
        return FileResponse("frontend/dist/index.html")
    return {"message": "Frontend not built"}
"""

with open(BACKEND_FILE, "w", encoding="utf-8") as f:
    f.write(backend_code.strip())
    print("✅ 后端入口已修复：访问 http://localhost:8000 现在会直接显示网页！")

print("-" * 40)
print("👉 请务必重启 uvicorn (backend) 才能生效。")