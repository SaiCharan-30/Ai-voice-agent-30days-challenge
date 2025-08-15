from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import assemblyai as aai
from pydantic import BaseModel
from murf import Murf
import os
from dotenv import load_dotenv
import google.generativeai as genai
from fastapi import Request

chat_histories = {}

def append_to_history(session_id: str, role: str, content: str):
    """Append a message to a session's chat history."""
    if session_id not in chat_histories:
        chat_histories[session_id] = []
    chat_histories[session_id].append({"role": role, "content": content.strip()})

def get_chat_history(session_id: str):
    """Return the chat history list for a session."""
    return chat_histories.get(session_id, [])

# Load environment variables
load_dotenv()
MURF_API_KEY = os.getenv("MURF_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Validate keys
if not GEMINI_API_KEY:
    raise Exception("GEMINI_API_KEY not found in environment")

# Setup clients
aai.settings.api_key = ASSEMBLYAI_API_KEY
transcriber = aai.Transcriber()
genai.configure(api_key=GEMINI_API_KEY)

# FastAPI app setup
app = FastAPI()



app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="static")

# Ensure uploads directory exists
os.makedirs("uploads", exist_ok=True)

@app.get("/ping")
def ping():
    return {"message": "Server is running!"}

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/frontend")

# -------------------- TEXT to SPEECH --------------------
class TTSRequest(BaseModel):
    text: str
    voiceId: str = "en-UK-peter"
    style: str = "Conversational"

@app.post("/tts")
def generate_tts(request: TTSRequest):
    try:
        client = Murf(api_key=MURF_API_KEY)
        response = client.text_to_speech.generate(
            text=request.text,
            voice_id=request.voiceId
        )
        return {"audio_url": response.audio_file}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

# -------------------- FILE UPLOAD --------------------
@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    try:
        file_location = f"uploads/{file.filename}"
        with open(file_location, "wb") as f:
            f.write(await file.read())
        return {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": os.path.getsize(file_location)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# -------------------- TRANSCRIBE --------------------
@app.post("/transcribe/file")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        transcript = transcriber.transcribe(audio_bytes)
        return {"transcription": transcript.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

# -------------------- ECHO BOT --------------------
@app.post("/tts/echo")
async def echo_with_murf(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        transcript = transcriber.transcribe(audio_bytes)
        text = transcript.text

        client = Murf(api_key=MURF_API_KEY)
        response = client.text_to_speech.generate(
            text=text,
            voice_id="en-UK-peter"
        )

        return {
            "transcription": text,
            "audio_url": response.audio_file
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Echo failed: {str(e)}")

# -------------------- LLM TEXT QUERY --------------------
class LLMRequest(BaseModel):
    text: str
    model: str = "gemini-1.5-flash"

@app.post("/llm/query")
async def llm_query(request: LLMRequest):
    try:
        model = genai.GenerativeModel(request.model)
        response = model.generate_content(request.text)
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM query failed: {str(e)}")

# -------------------- LLM AUDIO QUERY (DAY 9) --------------------
@app.post("/llm/query/audio")
async def llm_query_audio(file: UploadFile = File(...), model: str = "gemini-1.5-flash"):
    try:
        # 1️⃣ Transcribe user audio
        audio_bytes = await file.read()
        transcript = transcriber.transcribe(audio_bytes)
        user_text = transcript.text

        # 2️⃣ Get LLM response
        gemini_model = genai.GenerativeModel(model)
        llm_response = gemini_model.generate_content(user_text)
        response_text = llm_response.text.strip()

        # 3️⃣ Ensure <= 3000 chars for Murf
        if len(response_text) > 3000:
            response_text = response_text[:2995] + "..."

        # 4️⃣ Generate TTS
        murf_client = Murf(api_key=MURF_API_KEY)
        tts_result = murf_client.text_to_speech.generate(
            text=response_text,
            voice_id="en-UK-peter"
        )

        return {
            "user_transcription": user_text,
            "llm_response": response_text,
            "audio_url": tts_result.audio_file
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM audio query failed: {str(e)}")

@app.post("/llm/query/text")
async def llm_query_text(request: LLMRequest):
    try:
        # 1️⃣ LLM response
        model = genai.GenerativeModel(request.model)
        llm_response = model.generate_content(request.text)
        response_text = llm_response.text.strip()

        # 2️⃣ Ensure <= 3000 chars for Murf
        if len(response_text) > 3000:
            response_text = response_text[:2995] + "..."

        # 3️⃣ Generate TTS from LLM response
        murf_client = Murf(api_key=MURF_API_KEY)
        tts_result = murf_client.text_to_speech.generate(
            text=response_text,
            voice_id="en-UK-peter"
        )

        return {
            "llm_response": response_text,
            "audio_url": tts_result.audio_file
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM text query failed: {str(e)}") 
    


@app.post("/agent/chat/{session_id}")
async def agent_chat(session_id: str, request: Request):
    try:
        content_type = request.headers.get("content-type", "")
        file_bytes = None
        input_text = None

        # --- Handle input (audio or text) ---
        try:
            if content_type.startswith("multipart/form-data"):
                form = await request.form()
                if "file" in form and hasattr(form["file"], "filename"):
                    upload_file: UploadFile = form["file"]
                    file_bytes = await upload_file.read()
                if "text" in form:
                    input_text = form["text"].strip()

            elif content_type.startswith("application/json"):
                body = await request.json()
                input_text = body.get("text", "").strip()

            else:
                input_text = None
        except Exception:
            input_text = None

        # --- STT ---
        if file_bytes:
            try:
                transcript = transcriber.transcribe(file_bytes)
                input_text = transcript.text
            except Exception:
                return {
                    "success": True,
                    "gemini_text": "Sorry, I couldn’t process the audio.",
                    "audio_urls": [],
                    "history": get_chat_history(session_id)
                }

        if not input_text:
            return {
                "success": True,
                "gemini_text": "I didn’t catch anything. Can you try again?",
                "audio_urls": [],
                "history": get_chat_history(session_id)
            }

        append_to_history(session_id, "user", input_text)

        # --- Gemini LLM ---
        try:
            history_text = "\n".join(
                f"{'User' if msg['role']=='user' else 'Assistant'}: {msg['content']}"
                for msg in get_chat_history(session_id)
            )
            prompt = f"""
You are a friendly AI voice assistant.
Continue the conversation naturally based on the following history:

{history_text}

Assistant:
"""
            model = genai.GenerativeModel("gemini-1.5-flash")
            llm_response = model.generate_content(prompt)
            gemini_text = getattr(llm_response, "text", None) or \
                          getattr(llm_response.candidates[0].content.parts[0], "text", "No response.")
        except Exception:
            gemini_text = "I had trouble thinking of a reply, but let's keep going."

        append_to_history(session_id, "assistant", gemini_text)

        # --- TTS ---
        audio_urls = []
        try:
            def chunk_text(text, max_len=3000):
                return [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for chunk in chunk_text(gemini_text):
                client = Murf(api_key=MURF_API_KEY)
                tts_response = client.text_to_speech.generate(
                    text=chunk,
                    voice_id="en-UK-peter"
                )
                audio_urls.append(tts_response.audio_file)
        except Exception:
            audio_urls = []

        return {
            "success": True,
            "gemini_text": gemini_text,
            "audio_urls": audio_urls,
            "history": get_chat_history(session_id)
        }

    except Exception:
        return {
            "success": True,
            "gemini_text": "Something unexpected happened, but I’m still here!",
            "audio_urls": [],
            "history": get_chat_history(session_id)
        }
