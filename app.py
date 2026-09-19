import streamlit as st
import sqlite3
import re
import io
import os
import json
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path

# ============================================================
# OPTIONAL LIBRARIES
# ============================================================

try:
    from translate import Translator
    TRANSLATE_AVAILABLE = True
except Exception:
    TRANSLATE_AVAILABLE = False

try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False

try:
    from docx import Document
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

try:
    import pyttsx3
    TTS_AVAILABLE = True
except Exception:
    TTS_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
except Exception:
    SPEECH_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except Exception:
    REQUESTS_AVAILABLE = False


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="AI Language Translation Studio",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# LANGUAGE DATABASE
# ============================================================

LANGUAGES = {
    "English": "en",
    "Hindi": "hi",
    "Telugu": "te",
    "Tamil": "ta",
    "Kannada": "kn",
    "Malayalam": "ml",
    "Bengali": "bn",
    "Marathi": "mr",
    "Gujarati": "gu",
    "Punjabi": "pa",
    "Urdu": "ur",
    "French": "fr",
    "German": "de",
    "Spanish": "es",
    "Italian": "it",
    "Portuguese": "pt",
    "Russian": "ru",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese": "zh",
    "Arabic": "ar",
    "Turkish": "tr",
    "Dutch": "nl",
    "Greek": "el",
    "Vietnamese": "vi",
    "Indonesian": "id",
    "Thai": "th",
    "Polish": "pl",
    "Swedish": "sv"
}

LANGUAGE_NAMES = list(LANGUAGES.keys())


# ============================================================
# DATABASE
# ============================================================

DB_NAME = "translation_history.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def initialize_database():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_language TEXT,
            target_language TEXT,
            original_text TEXT,
            translated_text TEXT,
            mode TEXT,
            created_at TEXT,
            favorite INTEGER DEFAULT 0
        )
    """)

    # Existing database compatibility
    cursor.execute("PRAGMA table_info(translations)")
    columns = [row[1] for row in cursor.fetchall()]

    if "favorite" not in columns:
        cursor.execute(
            "ALTER TABLE translations ADD COLUMN favorite INTEGER DEFAULT 0"
        )

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            created_at TEXT
        )
    """)

    # Analytics/events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            event_type TEXT,
            details TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


initialize_database()


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "logged_in": False,
    "username": "",
    "translated_text": "",
    "last_source": "",
    "last_target": "",
    "last_record_id": None,
    "conversation_result": "",
    "detected_language": "English"
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def log_event(event_type, details=""):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO app_events
        (username, event_type, details, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        st.session_state.get("username", "guest"),
        event_type,
        details,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def save_translation(
    source_language,
    target_language,
    original_text,
    translated_text,
    mode="Translator"
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO translations
        (
            source_language,
            target_language,
            original_text,
            translated_text,
            mode,
            created_at,
            favorite
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (
        source_language,
        target_language,
        original_text,
        translated_text,
        mode,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    record_id = cursor.lastrowid

    conn.commit()
    conn.close()

    log_event("translation", mode)

    return record_id


def get_history():

    conn = get_connection()

    rows = conn.execute("""
        SELECT
            id,
            source_language,
            target_language,
            original_text,
            translated_text,
            mode,
            created_at,
            favorite
        FROM translations
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return rows


def get_favorites():

    conn = get_connection()

    rows = conn.execute("""
        SELECT
            id,
            source_language,
            target_language,
            original_text,
            translated_text,
            mode,
            created_at,
            favorite
        FROM translations
        WHERE favorite = 1
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return rows


def set_favorite(record_id, value):

    conn = get_connection()

    conn.execute(
        "UPDATE translations SET favorite=? WHERE id=?",
        (value, record_id)
    )

    conn.commit()
    conn.close()


def delete_translation(record_id):

    conn = get_connection()

    conn.execute(
        "DELETE FROM translations WHERE id=?",
        (record_id,)
    )

    conn.commit()
    conn.close()

    log_event("delete_translation", str(record_id))


def clear_history():

    conn = get_connection()

    conn.execute("DELETE FROM translations")

    conn.commit()
    conn.close()

    log_event("clear_history")


# ============================================================
# USER SYSTEM
# ============================================================

def register_user(username, password):

    username = username.strip()

    if not username or not password:
        return False, "Username and password are required."

    if len(password) < 4:
        return False, "Password must contain at least 4 characters."

    conn = get_connection()

    try:

        conn.execute("""
            INSERT INTO users
            (username, password, created_at)
            VALUES (?, ?, ?)
        """, (
            username,
            password,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        conn.close()

        return True, "Account created successfully."

    except sqlite3.IntegrityError:

        conn.close()

        return False, "Username already exists."


def login_user(username, password):

    conn = get_connection()

    row = conn.execute("""
        SELECT id, username
        FROM users
        WHERE username=? AND password=?
    """, (
        username.strip(),
        password
    )).fetchone()

    conn.close()

    return row is not None


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):

    if not text or not text.strip():
        return "Unknown"

    text = text.strip()

    # Unicode script detection

    if re.search(r"[\u0C00-\u0C7F]", text):
        return "Telugu"

    if re.search(r"[\u0900-\u097F]", text):
        return "Hindi"

    if re.search(r"[\u0B80-\u0BFF]", text):
        return "Tamil"

    if re.search(r"[\u0C80-\u0CFF]", text):
        return "Kannada"

    if re.search(r"[\u0D00-\u0D7F]", text):
        return "Malayalam"

    if re.search(r"[\u0980-\u09FF]", text):
        return "Bengali"

    if re.search(r"[\u0A80-\u0AFF]", text):
        return "Gujarati"

    if re.search(r"[\u0A00-\u0A7F]", text):
        return "Punjabi"

    if re.search(r"[\u0600-\u06FF]", text):
        return "Arabic"

    if re.search(r"[\u3040-\u30FF]", text):
        return "Japanese"

    if re.search(r"[\uAC00-\uD7AF]", text):
        return "Korean"

    if re.search(r"[\u4E00-\u9FFF]", text):
        return "Chinese"

    if re.search(r"[\u0400-\u04FF]", text):
        return "Russian"

    # Simple Latin-language detection

    lower = text.lower()

    spanish_words = [
        "hola", "gracias", "cómo", "que", "para",
        "usted", "está", "buenos"
    ]

    french_words = [
        "bonjour", "merci", "vous", "avec",
        "pour", "être", "comment"
    ]

    german_words = [
        "hallo", "danke", "und", "ich",
        "nicht", "wie", "für"
    ]

    italian_words = [
        "ciao", "grazie", "come", "sono",
        "per", "questo"
    ]

    portuguese_words = [
        "olá", "obrigado", "como", "você",
        "para", "está"
    ]

    scores = {
        "Spanish": sum(word in lower for word in spanish_words),
        "French": sum(word in lower for word in french_words),
        "German": sum(word in lower for word in german_words),
        "Italian": sum(word in lower for word in italian_words),
        "Portuguese": sum(word in lower for word in portuguese_words)
    }

    best_language = max(scores, key=scores.get)

    if scores[best_language] > 0:
        return best_language

    return "English"


# ============================================================
# TRANSLATION
# ============================================================

def translate_text(text, source_language, target_language):

    if not text.strip():
        return ""

    if source_language == target_language:
        return text

    if not TRANSLATE_AVAILABLE:
        return "Translation package is not installed."

    try:

        translator = Translator(
            from_lang=LANGUAGES[source_language],
            to_lang=LANGUAGES[target_language]
        )

        # Chunk large text
        chunks = []

        paragraphs = text.split("\n")

        current = ""

        for paragraph in paragraphs:

            if len(current) + len(paragraph) < 3500:
                current += paragraph + "\n"
            else:
                chunks.append(current)
                current = paragraph + "\n"

        if current:
            chunks.append(current)

        results = []

        for chunk in chunks:

            try:
                translated = translator.translate(chunk)
                results.append(translated)

            except Exception as e:
                results.append(
                    f"[Translation error: {str(e)}]"
                )

        return "\n".join(results)

    except Exception as e:

        return f"Translation error: {str(e)}"


# ============================================================
# OLLAMA LOCAL GENAI
# ============================================================

def ollama_available():

    if not REQUESTS_AVAILABLE:
        return False

    try:

        response = requests.get(
            "http://localhost:11434/api/tags",
            timeout=2
        )

        return response.status_code == 200

    except Exception:
        return False


def ollama_generate(prompt, model="llama3.2:3b"):

    if not ollama_available():

        return None

    try:

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        if response.status_code == 200:

            data = response.json()

            return data.get("response", "").strip()

    except Exception:
        pass

    return None


# ============================================================
# RULE-BASED SMART WRITING FALLBACK
# ============================================================

def rule_based_writing(text, mode):

    text = text.strip()

    if not text:
        return ""

    # Basic cleanup
    result = re.sub(r"\s+", " ", text)

    sentences = re.split(r"(?<=[.!?])\s+", result)

    sentences = [
        sentence.strip().capitalize()
        for sentence in sentences
        if sentence.strip()
    ]

    result = " ".join(sentences)

    if mode == "Professional":

        result = result.replace(
            "hello sir",
            "Dear Sir/Madam"
        )

        result = result.replace(
            "hello madam",
            "Dear Sir/Madam"
        )

        result = result.replace(
            "please give me",
            "I kindly request you to provide me with"
        )

        result = result.replace(
            "i want",
            "I would like"
        )

        result = result.replace(
            "i need",
            "I require"
        )

    elif mode == "Formal":

        result = result.replace(
            "hi",
            "Dear Sir/Madam"
        )

        result = result.replace(
            "thanks",
            "Thank you"
        )

        result = result.replace(
            "can you",
            "Could you please"
        )

    elif mode == "Simple":

        result = result.replace(
            "approximately",
            "about"
        )

        result = result.replace(
            "utilize",
            "use"
        )

    elif mode == "Shorten":

        sentences = sentences[:2]

        result = " ".join(sentences)

        if len(result) > 250:
            result = result[:250] + "..."

    elif mode == "Expand":

        result += (
            "\n\nThis message can be further explained "
            "with additional details, examples, and "
            "supporting information depending on the context."
        )

    return result


def smart_write(text, mode):

    prompt = f"""
You are an intelligent writing assistant.

Rewrite the following text in {mode} style.

Requirements:
- Correct grammar.
- Improve clarity.
- Keep the original meaning.
- Do not invent facts.
- Return only the improved text.

TEXT:
{text}
"""

    # Try local GenAI first
    result = ollama_generate(prompt)

    if result:
        log_event("genai_writing", mode)
        return result, "Local GenAI (Ollama)"

    # Free fallback
    result = rule_based_writing(text, mode)

    log_event("smart_writing", mode)

    return result, "Smart Writing fallback"


# ============================================================
# DOCUMENT EXTRACTION
# ============================================================

def extract_pdf(uploaded_file):

    if not PDF_AVAILABLE:
        return "pypdf is not installed."

    try:

        reader = PdfReader(uploaded_file)

        pages = []

        for page in reader.pages:

            try:
                text = page.extract_text() or ""
                pages.append(text)
            except Exception:
                pass

        return "\n\n".join(pages)

    except Exception as e:
        return f"PDF extraction error: {e}"


def extract_docx(uploaded_file):

    if not DOCX_AVAILABLE:
        return "python-docx is not installed."

    try:

        document = Document(uploaded_file)

        paragraphs = [
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        return "\n".join(paragraphs)

    except Exception as e:
        return f"DOCX extraction error: {e}"


def extract_text_file(uploaded_file):

    try:

        data = uploaded_file.read()

        return data.decode(
            "utf-8",
            errors="ignore"
        )

    except Exception as e:

        return f"Text extraction error: {e}"


# ============================================================
# ADVANCED OCR
# ============================================================

def preprocess_image(image):

    if not PIL_AVAILABLE:
        return image

    image = image.convert("L")

    image = ImageOps.autocontrast(image)

    image = ImageEnhance.Contrast(image).enhance(2.0)

    image = ImageEnhance.Sharpness(image).enhance(2.0)

    image = image.filter(
        ImageFilter.SHARPEN
    )

    # Upscale
    width, height = image.size

    if width < 1800:

        scale = 1800 / width

        image = image.resize(
            (
                int(width * scale),
                int(height * scale)
            )
        )

    return image


def perform_ocr(image, language="eng"):

    if not OCR_AVAILABLE:
        return "pytesseract is not installed."

    try:

        processed = preprocess_image(image)

        text = pytesseract.image_to_string(
            processed,
            lang=language
        )

        return text.strip()

    except Exception as e:

        return f"OCR error: {e}"


# ============================================================
# SPEECH TO TEXT
# ============================================================

def speech_to_text(audio_bytes):

    if not SPEECH_AVAILABLE:
        return None, "SpeechRecognition package is not installed."

    recognizer = sr.Recognizer()

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        ) as temp:

            temp.write(audio_bytes)

            temp_path = temp.name

        with sr.AudioFile(temp_path) as source:

            audio = recognizer.record(source)

        text = recognizer.recognize_google(
            audio
        )

        try:
            os.remove(temp_path)
        except Exception:
            pass

        return text, None

    except sr.UnknownValueError:

        return None, "Could not understand the audio."

    except sr.RequestError as e:

        return None, f"Speech recognition service error: {e}"

    except Exception as e:

        return None, f"Voice error: {e}"


# ============================================================
# TEXT TO SPEECH
# ============================================================

def text_to_speech(text):

    if not TTS_AVAILABLE:
        return None

    if not text.strip():
        return None

    try:

        engine = pyttsx3.init()

        engine.setProperty(
            "rate",
            165
        )

        output_path = os.path.join(
            tempfile.gettempdir(),
            "translation_speech.wav"
        )

        engine.save_to_file(
            text,
            output_path
        )

        engine.runAndWait()

        if os.path.exists(output_path):

            with open(
                output_path,
                "rb"
            ) as file:

                return file.read()

    except Exception:
        return None

    return None


# ============================================================
# UI STYLE
# ============================================================

st.markdown("""
<style>

.main-title {
    font-size: 42px;
    font-weight: 800;
    margin-bottom: 5px;
}

.subtitle {
    font-size: 18px;
    opacity: 0.75;
    margin-bottom: 25px;
}

.feature-card {
    padding: 18px;
    border-radius: 15px;
    border: 1px solid rgba(128,128,128,0.25);
    margin-bottom: 10px;
}

.metric-card {
    padding: 20px;
    border-radius: 15px;
    border: 1px solid rgba(128,128,128,0.25);
    text-align: center;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# LOGIN / REGISTRATION
# ============================================================

if not st.session_state.logged_in:

    st.markdown(
        '<div class="main-title">🌐 AI Language Translation Studio</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">Free Python Translation + AI Writing Platform</div>',
        unsafe_allow_html=True
    )

    login_tab, register_tab = st.tabs(
        ["🔐 Login", "📝 Create Account"]
    )

    with login_tab:

        username = st.text_input(
            "Username",
            key="login_username"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="login_password"
        )

        if st.button(
            "🔓 Login",
            use_container_width=True
        ):

            if login_user(username, password):

                st.session_state.logged_in = True
                st.session_state.username = username.strip()

                log_event(
                    "login",
                    username
                )

                st.success("Login successful.")

                st.rerun()

            else:

                st.error(
                    "Invalid username or password."
                )

    with register_tab:

        new_username = st.text_input(
            "Create username",
            key="register_username"
        )

        new_password = st.text_input(
            "Create password",
            type="password",
            key="register_password"
        )

        confirm_password = st.text_input(
            "Confirm password",
            type="password"
        )

        if st.button(
            "📝 Create Account",
            use_container_width=True
        ):

            if new_password != confirm_password:

                st.error(
                    "Passwords do not match."
                )

            else:

                success, message = register_user(
                    new_username,
                    new_password
                )

                if success:
                    st.success(message)
                else:
                    st.error(message)

    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("🌐 Translation Studio")

st.sidebar.success(
    f"👤 {st.session_state.username}"
)

page = st.sidebar.radio(
    "Navigation",
    [
        "🌐 Translator",
        "📄 Documents",
        "🖼️ Image OCR",
        "🎤 Voice Translator",
        "💬 Voice Conversation",
        "🌍 Multi Translator",
        "✍️ Smart Writing",
        "📊 Analytics",
        "🕘 History",
        "⭐ Favorites",
        "⚙️ Settings"
    ]
)

if st.sidebar.button(
    "🚪 Logout",
    use_container_width=True
):

    log_event(
        "logout",
        st.session_state.username
    )

    st.session_state.logged_in = False
    st.session_state.username = ""

    st.rerun()


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">🌐 AI Language Translation Studio</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">Translation • OCR • Voice • GenAI Writing • Analytics</div>',
    unsafe_allow_html=True
)


# ============================================================
# TRANSLATOR
# ============================================================

if page == "🌐 Translator":

    st.header("🌐 Text Translator")

    col1, col2 = st.columns(2)

    with col1:

        source_language = st.selectbox(
            "Source Language",
            LANGUAGE_NAMES,
            index=0
        )

    with col2:

        target_language = st.selectbox(
            "Target Language",
            LANGUAGE_NAMES,
            index=2
        )

    text = st.text_area(
        "Enter text",
        height=220,
        placeholder="Type or paste your text here..."
    )

    c1, c2, c3 = st.columns(3)

    with c1:

        if st.button(
            "🌐 Translate",
            use_container_width=True
        ):

            if text.strip():

                translated = translate_text(
                    text,
                    source_language,
                    target_language
                )

                st.session_state.translated_text = translated
                st.session_state.last_source = source_language
                st.session_state.last_target = target_language

                record_id = save_translation(
                    source_language,
                    target_language,
                    text,
                    translated,
                    "Translator"
                )

                st.session_state.last_record_id = record_id

                st.success("Translation completed.")

            else:

                st.warning("Please enter some text.")

    with c2:

        if st.button(
            "🔍 Detect Language",
            use_container_width=True
        ):

            detected = detect_language(text)

            st.session_state.detected_language = detected

            st.info(
                f"Detected Language: **{detected}**"
            )

    with c3:

        if st.button(
            "🗑️ Clear",
            use_container_width=True
        ):

            st.session_state.translated_text = ""

            st.rerun()

    if st.session_state.translated_text:

        st.subheader("Translation Result")

        st.text_area(
            "Translated text",
            value=st.session_state.translated_text,
            height=220,
            key="translation_result"
        )

        record_id = st.session_state.last_record_id

        col_a, col_b, col_c = st.columns(3)

        with col_a:

            if record_id:

                history = get_history()

                favorite = False

                for row in history:

                    if row[0] == record_id:
                        favorite = bool(row[7])

                if favorite:

                    if st.button(
                        "⭐ Remove from Favorites",
                        use_container_width=True
                    ):

                        set_favorite(
                            record_id,
                            0
                        )

                        st.rerun()

                else:

                    if st.button(
                        "⭐ Add to Favorites",
                        use_container_width=True
                    ):

                        set_favorite(
                            record_id,
                            1
                        )

                        st.rerun()

        with col_b:

            st.download_button(
                "⬇️ Download Translation",
                data=st.session_state.translated_text,
                file_name="translation.txt",
                mime="text/plain",
                use_container_width=True
            )

        with col_c:

            if st.button(
                "🔊 Speak Translation",
                use_container_width=True
            ):

                audio = text_to_speech(
                    st.session_state.translated_text
                )

                if audio:

                    st.audio(
                        audio,
                        format="audio/wav"
                    )

                else:

                    st.warning(
                        "Text-to-Speech is not available."
                    )

    if text:

        st.subheader("📊 Text Analysis")

        words = len(
            re.findall(
                r"\b\w+\b",
                text
            )
        )

        chars = len(text)

        sentences = len(
            re.findall(
                r"[.!?]+",
                text
            )
        )

        a, b, c = st.columns(3)

        a.metric("Words", words)
        b.metric("Characters", chars)
        c.metric("Sentences", sentences)


# ============================================================
# DOCUMENTS
# ============================================================

elif page == "📄 Documents":

    st.header("📄 Document Translator")

    uploaded = st.file_uploader(
        "Upload PDF, DOCX or TXT",
        type=["pdf", "docx", "txt"]
    )

    if uploaded:

        st.info(
            f"📄 File: {uploaded.name}"
        )

        file_size_mb = uploaded.size / (
            1024 * 1024
        )

        st.caption(
            f"Size: {file_size_mb:.2f} MB"
        )

        if st.button(
            "📖 Extract Text",
            use_container_width=True
        ):

            extension = Path(
                uploaded.name
            ).suffix.lower()

            if extension == ".pdf":

                extracted = extract_pdf(
                    uploaded
                )

            elif extension == ".docx":

                extracted = extract_docx(
                    uploaded
                )

            else:

                extracted = extract_text_file(
                    uploaded
                )

            st.session_state.document_text = extracted

    if "document_text" in st.session_state:

        document_text = st.session_state.document_text

        st.subheader("Extracted Text")

        st.text_area(
            "Document content",
            value=document_text,
            height=300
        )

        detected = detect_language(
            document_text[:5000]
        )

        st.info(
            f"Detected source language: **{detected}**"
        )

        target = st.selectbox(
            "Translate document to",
            LANGUAGE_NAMES,
            index=2
        )

        if st.button(
            "🌐 Translate Document",
            use_container_width=True
        ):

            translated_document = translate_text(
                document_text,
                detected if detected in LANGUAGES else "English",
                target
            )

            st.session_state.document_translation = (
                translated_document
            )

            save_translation(
                detected if detected in LANGUAGES else "English",
                target,
                document_text,
                translated_document,
                "Document"
            )

            st.success(
                "Document translation completed."
            )

        if "document_translation" in st.session_state:

            st.subheader(
                "Translated Document"
            )

            st.text_area(
                "Translation",
                value=st.session_state.document_translation,
                height=350
            )

            st.download_button(
                "⬇️ Download Translated Text",
                data=st.session_state.document_translation,
                file_name="translated_document.txt",
                mime="text/plain",
                use_container_width=True
            )


# ============================================================
# IMAGE OCR
# ============================================================

elif page == "🖼️ Image OCR":

    st.header("🖼️ Advanced OCR + Translation")

    image_file = st.file_uploader(
        "Upload an image",
        type=[
            "png",
            "jpg",
            "jpeg",
            "webp",
            "bmp"
        ]
    )

    if image_file:

        image = Image.open(
            image_file
        ) if PIL_AVAILABLE else None

        if image:

            st.image(
                image,
                caption="Uploaded Image",
                use_container_width=True
            )

            ocr_language = st.selectbox(
                "OCR Language",
                [
                    "English (eng)",
                    "Hindi (hin)",
                    "Telugu (tel)",
                    "Tamil (tam)",
                    "Kannada (kan)"
                ]
            )

            ocr_code = ocr_language.split("(")[-1].replace(
                ")",
                ""
            )

            if st.button(
                "🔍 Extract Text with Advanced OCR",
                use_container_width=True
            ):

                extracted = perform_ocr(
                    image,
                    ocr_code
                )

                st.session_state.ocr_text = extracted

        if "ocr_text" in st.session_state:

            st.subheader(
                "Extracted Text"
            )

            ocr_text = st.text_area(
                "OCR result",
                value=st.session_state.ocr_text,
                height=250
            )

            detected = detect_language(
                ocr_text
            )

            st.info(
                f"Detected language: **{detected}**"
            )

            target = st.selectbox(
                "Target language",
                LANGUAGE_NAMES,
                index=2
            )

            if st.button(
                "🌐 Translate OCR Text",
                use_container_width=True
            ):

                translated = translate_text(
                    ocr_text,
                    detected if detected in LANGUAGES else "English",
                    target
                )

                st.session_state.ocr_translation = translated

                save_translation(
                    detected if detected in LANGUAGES else "English",
                    target,
                    ocr_text,
                    translated,
                    "OCR"
                )

            if "ocr_translation" in st.session_state:

                st.subheader(
                    "Translated Text"
                )

                st.text_area(
                    "Result",
                    value=st.session_state.ocr_translation,
                    height=250
                )

                st.download_button(
                    "⬇️ Download OCR Translation",
                    data=st.session_state.ocr_translation,
                    file_name="ocr_translation.txt",
                    mime="text/plain",
                    use_container_width=True
                )


# ============================================================
# VOICE TRANSLATOR
# ============================================================

elif page == "🎤 Voice Translator":

    st.header("🎤 Voice Input → Translation → Speech")

    st.info(
        "Speak into your microphone, convert speech to text, "
        "translate it, and optionally hear the result."
    )

    source = st.selectbox(
        "Source Language",
        LANGUAGE_NAMES,
        key="voice_source"
    )

    target = st.selectbox(
        "Target Language",
        LANGUAGE_NAMES,
        index=2,
        key="voice_target"
    )

    audio_input = st.audio_input(
        "🎤 Record your voice"
    )

    if audio_input:

        if st.button(
            "📝 Convert Voice to Text",
            use_container_width=True
        ):

            text, error = speech_to_text(
                audio_input.getvalue()
            )

            if error:

                st.error(error)

            else:

                st.session_state.voice_text = text

                st.success(
                    "Voice converted to text."
                )

    if "voice_text" in st.session_state:

        st.subheader(
            "Recognized Speech"
        )

        st.text_area(
            "Speech text",
            value=st.session_state.voice_text,
            height=150
        )

        if st.button(
            "🌐 Translate Voice",
            use_container_width=True
        ):

            translated = translate_text(
                st.session_state.voice_text,
                source,
                target
            )

            st.session_state.voice_translation = (
                translated
            )

            save_translation(
                source,
                target,
                st.session_state.voice_text,
                translated,
                "Voice"
            )

        if "voice_translation" in st.session_state:

            st.subheader(
                "Translated Speech"
            )

            st.text_area(
                "Translation",
                value=st.session_state.voice_translation,
                height=150
            )

            if st.button(
                "🔊 Generate Voice",
                use_container_width=True
            ):

                audio = text_to_speech(
                    st.session_state.voice_translation
                )

                if audio:

                    st.audio(
                        audio,
                        format="audio/wav"
                    )

                else:

                    st.warning(
                        "Text-to-Speech is unavailable."
                    )


# ============================================================
# VOICE CONVERSATION
# ============================================================

elif page == "💬 Voice Conversation":

    st.header("💬 Voice Conversation Mode")

    st.info(
        "Two people can speak using two different languages."
    )

    person_a = st.selectbox(
        "Person A Language",
        LANGUAGE_NAMES,
        index=0
    )

    person_b = st.selectbox(
        "Person B Language",
        LANGUAGE_NAMES,
        index=2
    )

    st.divider()

    st.subheader(
        "👤 Person A"
    )

    audio_a = st.audio_input(
        "Record Person A",
        key="conversation_a"
    )

    if audio_a:

        if st.button(
            "Translate Person A",
            use_container_width=True
        ):

            text_a, error = speech_to_text(
                audio_a.getvalue()
            )

            if error:

                st.error(error)

            else:

                translated_a = translate_text(
                    text_a,
                    person_a,
                    person_b
                )

                st.session_state.conversation_a = (
                    translated_a
                )

                save_translation(
                    person_a,
                    person_b,
                    text_a,
                    translated_a,
                    "Conversation"
                )

    if "conversation_a" in st.session_state:

        st.success(
            st.session_state.conversation_a
        )

        audio = text_to_speech(
            st.session_state.conversation_a
        )

        if audio:
            st.audio(
                audio,
                format="audio/wav"
            )

    st.divider()

    st.subheader(
        "👤 Person B"
    )

    audio_b = st.audio_input(
        "Record Person B",
        key="conversation_b"
    )

    if audio_b:

        if st.button(
            "Translate Person B",
            use_container_width=True
        ):

            text_b, error = speech_to_text(
                audio_b.getvalue()
            )

            if error:

                st.error(error)

            else:

                translated_b = translate_text(
                    text_b,
                    person_b,
                    person_a
                )

                st.session_state.conversation_b = (
                    translated_b
                )

                save_translation(
                    person_b,
                    person_a,
                    text_b,
                    translated_b,
                    "Conversation"
                )

    if "conversation_b" in st.session_state:

        st.success(
            st.session_state.conversation_b
        )

        audio = text_to_speech(
            st.session_state.conversation_b
        )

        if audio:
            st.audio(
                audio,
                format="audio/wav"
            )


# ============================================================
# MULTI TRANSLATOR
# ============================================================

elif page == "🌍 Multi Translator":

    st.header("🌍 Multi-Language Translator")

    source = st.selectbox(
        "Source Language",
        LANGUAGE_NAMES,
        key="multi_source"
    )

    targets = st.multiselect(
        "Target Languages",
        [
            language
            for language in LANGUAGE_NAMES
            if language != source
        ],
        default=["Telugu", "Hindi", "French"]
    )

    text = st.text_area(
        "Enter text",
        height=180,
        key="multi_text"
    )

    if st.button(
        "🌐 Translate into All Languages",
        use_container_width=True
    ):

        if text.strip() and targets:

            for target in targets:

                with st.container():

                    st.markdown(
                        f"### {target}"
                    )

                    result = translate_text(
                        text,
                        source,
                        target
                    )

                    st.write(result)

                    save_translation(
                        source,
                        target,
                        text,
                        result,
                        "Multi Translator"
                    )

        else:

            st.warning(
                "Enter text and select target languages."
            )


# ============================================================
# SMART WRITING
# ============================================================

elif page == "✍️ Smart Writing":

    st.header("✍️ AI / GenAI Writing Assistant")

    if ollama_available():

        st.success(
            "🤖 Local GenAI detected — Ollama is available."
        )

    else:

        st.info(
            "🆓 Free fallback mode is active. "
            "Install/run Ollama with a local model to enable "
            "true local GenAI."
        )

    writing_mode = st.selectbox(
        "Writing Mode",
        [
            "Professional",
            "Formal",
            "Simple",
            "Shorten",
            "Expand",
            "Grammar Correction"
        ]
    )

    writing_text = st.text_area(
        "Enter text to improve",
        height=250,
        placeholder="Write your text here..."
    )

    if st.button(
        "🤖 Improve Writing",
        use_container_width=True
    ):

        if writing_text.strip():

            result, engine = smart_write(
                writing_text,
                writing_mode
            )

            st.subheader(
                "Improved Result"
            )

            st.text_area(
                "Result",
                value=result,
                height=250
            )

            st.caption(
                f"Engine: {engine}"
            )

            st.download_button(
                "⬇️ Download Improved Text",
                data=result,
                file_name="improved_text.txt",
                mime="text/plain",
                use_container_width=True
            )

        else:

            st.warning(
                "Please enter some text."
            )


# ============================================================
# ANALYTICS
# ============================================================

elif page == "📊 Analytics":

    st.header("📊 Translation Analytics Dashboard")

    history = get_history()

    if not history:

        st.info(
            "No translation data available yet."
        )

    else:

        total = len(history)

        favorites = sum(
            1
            for row in history
            if row[7]
        )

        unique_modes = len(
            set(
                row[5]
                for row in history
            )
        )

        unique_languages = len(
            set(
                [row[1] for row in history] +
                [row[2] for row in history]
            )
        )

        a, b, c, d = st.columns(4)

        a.metric(
            "Total Translations",
            total
        )

        b.metric(
            "Favorites",
            favorites
        )

        c.metric(
            "Modes Used",
            unique_modes
        )

        d.metric(
            "Languages Used",
            unique_languages
        )

        st.subheader(
            "🌐 Language Usage"
        )

        language_counts = {}

        for row in history:

            language_counts[row[2]] = (
                language_counts.get(
                    row[2],
                    0
                ) + 1
            )

        if language_counts:

            st.bar_chart(
                language_counts
            )

        st.subheader(
            "🛠️ Feature Usage"
        )

        mode_counts = {}

        for row in history:

            mode_counts[row[5]] = (
                mode_counts.get(
                    row[5],
                    0
                ) + 1
            )

        if mode_counts:

            st.bar_chart(
                mode_counts
            )


# ============================================================
# HISTORY
# ============================================================

elif page == "🕘 History":

    st.header("🕘 Translation History")

    history = get_history()

    if not history:

        st.info(
            "No history available."
        )

    else:

        for row in history:

            (
                record_id,
                source,
                target,
                original,
                translated,
                mode,
                created_at,
                favorite
            ) = row

            with st.expander(
                f"{'⭐' if favorite else '☆'} "
                f"{source} → {target} | {mode} | {created_at}"
            ):

                st.markdown(
                    "**Original:**"
                )

                st.write(original)

                st.markdown(
                    "**Translation:**"
                )

                st.write(translated)

                col1, col2 = st.columns(2)

                with col1:

                    if favorite:

                        if st.button(
                            "⭐ Remove Favorite",
                            key=f"hist_unfav_{record_id}",
                            use_container_width=True
                        ):

                            set_favorite(
                                record_id,
                                0
                            )

                            st.rerun()

                    else:

                        if st.button(
                            "☆ Add Favorite",
                            key=f"hist_fav_{record_id}",
                            use_container_width=True
                        ):

                            set_favorite(
                                record_id,
                                1
                            )

                            st.rerun()

                with col2:

                    if st.button(
                        "🗑️ Delete",
                        key=f"hist_del_{record_id}",
                        use_container_width=True
                    ):

                        delete_translation(
                            record_id
                        )

                        st.rerun()

        st.divider()

        if st.button(
            "⚠️ Clear All History",
            use_container_width=True
        ):

            clear_history()

            st.success(
                "History cleared."
            )

            st.rerun()


# ============================================================
# FAVORITES
# ============================================================

elif page == "⭐ Favorites":

    st.header("⭐ Favorite Translations")

    favorites = get_favorites()

    if not favorites:

        st.info(
            "No favorite translations yet."
        )

    else:

        for row in favorites:

            (
                record_id,
                source,
                target,
                original,
                translated,
                mode,
                created_at,
                favorite
            ) = row

            with st.expander(
                f"⭐ {source} → {target} | {created_at}"
            ):

                st.markdown(
                    "**Original:**"
                )

                st.write(original)

                st.markdown(
                    "**Translation:**"
                )

                st.write(translated)

                col1, col2 = st.columns(2)

                with col1:

                    if st.button(
                        "☆ Remove Favorite",
                        key=f"fav_remove_{record_id}",
                        use_container_width=True
                    ):

                        set_favorite(
                            record_id,
                            0
                        )

                        st.rerun()

                with col2:

                    if st.button(
                        "🗑️ Delete",
                        key=f"fav_delete_{record_id}",
                        use_container_width=True
                    ):

                        delete_translation(
                            record_id
                        )

                        st.rerun()


# ============================================================
# SETTINGS
# ============================================================

elif page == "⚙️ Settings":

    st.header("⚙️ Settings")

    st.subheader(
        "👤 Account"
    )

    st.write(
        f"Logged in as: **{st.session_state.username}**"
    )

    st.divider()

    st.subheader(
        "🆓 Free Technology Stack"
    )

    st.write(
        """
        • Python  
        • Streamlit  
        • SQLite  
        • Translate package  
        • PyPDF  
        • python-docx  
        • Tesseract OCR  
        • Pillow  
        • pyttsx3  
        • SpeechRecognition  
        • Optional local Ollama GenAI
        """
    )

    st.divider()

    st.subheader(
        "🤖 GenAI Status"
    )

    if ollama_available():

        st.success(
            "Local Ollama GenAI is available."
        )

    else:

        st.warning(
            "Ollama is not currently available. "
            "Smart Writing uses the free fallback engine."
        )

    st.divider()

    st.subheader(
        "🎤 Voice Status"
    )

    if SPEECH_AVAILABLE:

        st.success(
            "Speech recognition package available."
        )

    else:

        st.warning(
            "SpeechRecognition package is not installed."
        )

    if TTS_AVAILABLE:

        st.success(
            "Text-to-Speech package available."
        )

    else:

        st.warning(
            "pyttsx3 package is not installed."
        )

    st.divider()

    st.subheader(
        "🖼️ OCR Status"
    )

    if OCR_AVAILABLE:

        st.success(
            "Tesseract OCR integration available."
        )

    else:

        st.warning(
            "pytesseract is not available."
        )

    st.divider()

    st.subheader(
        "💾 Database"
    )

    st.write(
        f"Database: `{DB_NAME}`"
    )

    st.success(
        "Existing translation history database is preserved."
    )

    st.divider()

    st.subheader(
        "🚀 Project Features"
    )

    features = [
        "🧠 Smart Language Detection",
        "🤖 Local GenAI / Smart Writing",
        "🎤 Voice Input",
        "🔊 Text-to-Speech",
        "💬 Voice Conversation",
        "📑 Document Translation",
        "🖼️ Advanced OCR",
        "🌍 Multi-Language Translation",
        "📊 Analytics Dashboard",
        "🔐 User Login",
        "⭐ Favorites",
        "🕘 Translation History",
        "🗄️ SQLite Database"
    ]

    for feature in features:

        st.write(
            f"✅ {feature}"
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "🌐 AI Language Translation Studio | "
    "Python + Streamlit + SQLite | "
    "Free Mode | Final Year AI Project"
)