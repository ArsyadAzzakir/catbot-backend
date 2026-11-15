from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from prisma import Prisma
from typing import Optional
from PIL import Image
import io
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Inisialisasi Aplikasi FastAPI & Gemini
app = FastAPI(title="CatBot API")
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Inisialisasi Database Prisma
db = Prisma()

@app.on_event("startup")
async def startup():
    await db.connect()

@app.on_event("shutdown")
async def shutdown():
    await db.disconnect()

class AuthRequest(BaseModel):
    email: str
    password: str

# ENDPOINT 1: REGISTER
@app.post("/api/register")
async def register(request: AuthRequest):
    existing_user = await db.user.find_unique(where={"email": request.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    new_user = await db.user.create(
        data={
            "email": request.email,
            "password": request.password
        }
    )
    return {"message": "Pendaftaran berhasil!", "user_id": new_user.id}

# ENDPOINT 2: LOGIN
@app.post("/api/login")
async def login(request: AuthRequest):
    user = await db.user.find_unique(where={"email": request.email})
    if not user or user.password != request.password:
        raise HTTPException(status_code=400, detail="Email atau kata sandi salah")

    return {"message": "Login berhasil!", "token": "token_asli_berhasil_masuk"}

# ENDPOINT 3: CHAT AI + UPLOAD FOTO KUCING
@app.post("/api/chat")
async def chat_with_catbot(
    message: str = Form(...),
    image: Optional[UploadFile] = File(None)
):
    try:
        model = genai.GenerativeModel('gemini-3.8-flash')
        prompt = (
            "Kamu adalah CatBot Assistant, dokter hewan virtual khusus kucing. "
            "Berikan analisis gejala, pertolongan pertama yang aman, dan saran perawatan "
            f"dengan ramah dan jelas untuk keluhan berikut: {message}"
        )

        if image:
            image_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(image_bytes))
            response = model.generate_content([prompt, pil_image])
        else:
            response = model.generate_content(prompt)

        return {"reply": response.text, "status": "success"}

    except Exception as e:
        error_msg = str(e)
        # Cadangan otomatis jika terkena limit kuota 5 request/menit
        if "429" in error_msg or "Quota exceeded" in error_msg:
            return {
                "reply": (
                    f"Meow! Berdasarkan keluhan '{message}' dan pemeriksaan awal, "
                    "pastikan kucing berada di tempat yang tenang, tetap terhidrasi, dan berikan "
                    "makanan basah beraroma kuat. Pantau kondisinya dalam 24 jam ke depan. "
                    "Jika gejala memburuk, segera bawa ke klinik dokter hewan terdekat ya!"
                ),
                "status": "fallback_rate_limit"
            }
        return {"reply": f"Meow! Terjadi kendala teknis: {error_msg}", "status": "error"}