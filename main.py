from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from prisma import Prisma
from typing import Optional
from PIL import Image
import io
import os
import base64
from groq import AsyncGroq
from dotenv import load_dotenv
from typing import List 

# Inisialisasi Aplikasi FastAPI & Gemini
app = FastAPI(title="CatBot API")
load_dotenv()

# PERBAIKAN 1: Memastikan API Key terbaca otomatis apa pun nama variabel di terminalnya
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

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

    return {
        "message": "Login berhasil!",
        "token": "token_asli_berhasil_masuk",
        "userId": user.id
    }

class ChatRequest(BaseModel):
    message: str
    userId: Optional[int] = None

# ENDPOINT 3: CHAT AI (GROQ API - JSON)
@app.post("/api/chat")
async def chat_with_catbot(req: ChatRequest):
    try:
        cat_context = ""
        if req.userId:
            profile = await db.catprofile.find_first(where={"userId": req.userId})
            if profile:
                cat_context = (
                    f"Data kucing pengguna: Nama={profile.name}, Ras={profile.breed}, "
                    f"Umur={profile.age} tahun, Berat={profile.weight_kg} kg, "
                    f"Status Vaksin={profile.vaccine}. "
                )

        system_prompt = (
            "Kamu adalah CatBot Assistant, dokter hewan virtual khusus kucing yang ramah. "
            f"{cat_context}"
            "Berikan analisis gejala, pertolongan pertama yang aman, dan saran perawatan "
            "dengan bahasa Indonesia yang jelas, ringkas, dan mudah dipahami."
        )

        print(f"MENGIRIM KE GROQ: {req.message}")

        completion = await groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message},
            ],
            temperature=0.7,
            max_tokens=1024,
        )

        reply_text = completion.choices[0].message.content
        print("BALASAN GROQ DITERIMA!")
        return {"reply": reply_text, "status": "success"}

    except Exception as e:
        error_msg = str(e)
        print(f"ALASAN ERROR GROQ: {error_msg}")
        return {"reply": f"Meow! Terjadi kendala teknis: {error_msg}", "status": "error"}
    
# --- ENDPOINT BARU UNTUK PROFIL KUCING ---

class CatProfileData(BaseModel):
    userId: int
    name: str
    breed: str
    age: int
    weight_kg: float
    vaccine: str
    birthDate: str

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int):
    # Cari profil kucing pertama yang dimiliki oleh user ini
    profile = await db.catprofile.find_first(where={"userId": user_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Profil belum dibuat")
    return profile

@app.post("/api/profile/update")
async def update_profile(data: CatProfileData):
    # Cek apakah user sudah punya kucing
    existing = await db.catprofile.find_first(where={"userId": data.userId})
    
    if existing:
        # Jika sudah ada, update datanya
        profile = await db.catprofile.update(
            where={"id": existing.id},
            data={
                "name": data.name,
                "breed": data.breed,
                "age": data.age,
                "weight_kg": data.weight_kg,
                "vaccine": data.vaccine,
                "birthDate": data.birthDate
            }
        )
    else:
        # Jika belum ada, buat profil kucing baru
        profile = await db.catprofile.create(
            data={
                "userId": data.userId,
                "name": data.name,
                "breed": data.breed,
                "age": data.age,
                "weight_kg": data.weight_kg,
                "vaccine": data.vaccine,
                "birthDate": data.birthDate
            }
        )
    return {"message": "Profil berhasil disimpan", "profile": profile}
# ==========================================
# ENDPOINT KEAMANAN AKUN
# ==========================================

class PasswordChangeRequest(BaseModel):
    userId: int
    old_password: str
    new_password: str

@app.post("/api/security/change-password")
async def change_password(req: PasswordChangeRequest):
    user = await db.user.find_unique(where={"id": req.userId})
    if not user or user.password != req.old_password:
        raise HTTPException(status_code=400, detail="Kata sandi lama salah")
        
    await db.user.update(
        where={"id": req.userId},
        data={"password": req.new_password}
    )
    return {"message": "Kata sandi berhasil diubah"}

class DeleteAccountRequest(BaseModel):
    userId: int
    password: str

@app.post("/api/security/delete-account")
async def delete_account(req: DeleteAccountRequest):
    user = await db.user.find_unique(where={"id": req.userId})
    if not user or user.password != req.password:
         raise HTTPException(status_code=400, detail="Kata sandi salah, autentikasi gagal")
         
    # Cascade delete akan otomatis menghapus profil kucing juga dari database
    await db.user.delete(where={"id": req.userId})
    return {"message": "Akun berhasil dihapus permanen"}
class DiagnosisRequest(BaseModel):
    userId: int
    symptoms: List[str]
    lang: str = "id"

# ENDPOINT: PROSES DIAGNOSA & SIMPAN KE RIWAYAT
@app.post("/api/diagnosis")
async def create_diagnosis(req: DiagnosisRequest):
    if not req.symptoms:
        raise HTTPException(status_code=400, detail="Pilih minimal satu gejala")

    symptoms_lower = " ".join(req.symptoms).lower()
    is_en = req.lang == "en"

    # Logika analisis gejala sederhana
    if len(req.symptoms) >= 4:
        result = "Severe Condition Warning" if is_en else "Indikasi Kondisi Serius"
        advice = (
            "Multiple symptoms detected. Please take your cat to a veterinarian immediately."
            if is_en else
            "Terdeteksi banyak gejala sekaligus. Segera bawa kucing Anda ke dokter hewan terdekat."
        )
    elif "bersin" in symptoms_lower or "sneezing" in symptoms_lower:
        result = "Possible Cat Flu" if is_en else "Indikasi Flu Kucing"
        advice = (
            "Keep your cat warm, clean nasal discharge gently, and ensure adequate hydration."
            if is_en else
            "Jaga kehangatan tubuh kucing, bersihkan lendir hidung dengan lembut, dan pastikan asupan air cukup."
        )
    elif "muntah" in symptoms_lower or "vomiting" in symptoms_lower or "diare" in symptoms_lower or "diarrhea" in symptoms_lower:
        result = "Digestive Disorder" if is_en else "Gangguan Pencernaan"
        advice = (
            "Temporarily withhold food for 6-8 hours, provide clean water, and monitor for dehydration."
            if is_en else
            "Puasakan makan sementara 6-8 jam, sediakan air minum bersih, dan pantau tanda dehidrasi."
        )
    else:
        result = "Mild Fatigue / Stress" if is_en else "Kelelahan Ringan / Stres"
        advice = (
            "Provide a quiet resting place, offer wet food to stimulate appetite, and monitor for 24 hours."
            if is_en else
            "Berikan tempat istirahat yang tenang, tawarkan makanan basah untuk memancing nafsu makan, dan pantau 24 jam."
        )

    # Simpan ke database SQLite
    saved = await db.diagnosishistory.create(
        data={
            "userId": req.userId,
            "symptoms": ", ".join(req.symptoms),
            "result": result,
            "advice": advice,
        }
    )

    return {
        "id": saved.id,
        "result": saved.result,
        "advice": saved.advice,
        "symptoms": saved.symptoms,
        "createdAt": saved.createdAt.strftime("%d %b %Y, %H:%M"),
    }

# ENDPOINT: AMBIL DAFTAR RIWAYAT KESEHATAN USER
@app.get("/api/diagnosis/{user_id}")
async def get_diagnosis_history(user_id: int):
    histories = await db.diagnosishistory.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"}
    )
    return [
        {
            "id": h.id,
            "symptoms": h.symptoms,
            "result": h.result,
            "advice": h.advice,
            "date": h.createdAt.strftime("%d %b %Y, %H:%M"),
        }
        for h in histories
    ]