import os
import io
import re
import fitz
import docx
import json
import mysql.connector
import pytesseract
from pdf2image import convert_from_bytes
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CURRENT_YEAR = datetime.now().year

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "database": "drive_to_sql_v2"
}

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
MAX_RESUMES = None
THREADS = 2

total_input_tokens = 0
total_output_tokens = 0

VALID_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","N/A"
}

# --- VALIDATORS ---
def validate_experience(exp):
    if isinstance(exp, int): return min(exp, 45)
    if isinstance(exp, str):
        match = re.search(r'\d+', exp)
        return min(int(match.group()), 45) if match else 0
    return 0

def validate_location(loc):
    if not loc: return "N/A"
    loc = loc.strip().upper()
    if loc in VALID_STATES: return loc
    if "," in loc:
        state = loc.split(",")[-1].strip()
        if state in VALID_STATES: return state
    return "N/A"

# --- AUTH ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        r'C:\Users\LENOVO\OneDrive\Desktop\resume_parser\service_account.json',
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    return build('drive', 'v3', credentials=creds)

# --- DB TRACK ---
def get_processed_file_ids():
    db = mysql.connector.connect(**DB_CONFIG)
    cursor = db.cursor()
    cursor.execute("SELECT drive_file_id FROM users WHERE drive_file_id IS NOT NULL")
    ids = set(row[0] for row in cursor.fetchall())
    cursor.close(); db.close()
    return ids

# --- EXTRACTION ---
def extract_text(file_bytes, filename):
    text = ""; is_ocr = False
    try:
        if filename.lower().endswith(".pdf"):
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                text = " ".join([p.get_text() for p in doc])
            if len(text.strip()) < 100:
                print(f"🔍 OCR-ing scanned PDF: {filename}")
                images = convert_from_bytes(file_bytes, dpi=100)
                text = " ".join([pytesseract.image_to_string(img) for img in images])
                is_ocr = True
        elif filename.lower().endswith(".docx"):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"⚠️ Extract error {filename}: {e}")
    return text, is_ocr

# --- AI BRAIN ---
def extract_info(text, filename):
    global total_input_tokens, total_output_tokens
    try:
        prompt = f"""
        Act as an expert US Technical Recruiter. Analyze the resume text and filename.
        
        STRICT EXTRACTION RULES:
        1. NAME: Extract Full Name from Header. Cross-verify with filename. No 'Resume' or 'CV'.
        2. ROLE: Extract the EXACT Most Recent Job Title. 
        
        3. EXPERIENCE (PRIORITY ORDER):
           - FIRST: Scan 'Professional Summary' or 'Header' for explicit total years (e.g., "30+ years of IT experience"). If found, use that integer and STOP.
           - SECOND: Only if no explicit total is found, calculate: {CURRENT_YEAR} minus the Start Year of the first job.
           - Return ONLY an integer.

        4. LOCATION (PRIORITY ORDER):
           - FIRST: Use City/State from the Contact Header.
           - SECOND: If missing, use the Location of the MOST RECENT/CURRENT job entry.
           - THIRD: If still missing, infer the 2-letter US State Code from the phone number AREA CODE.
           - Return ONLY the 2-letter State Code.

        5. SKILLS: Top 10-15 technical skills as comma-separated string.
        6. UNIQUE ID: Extract the Candidate's EMAIL and PHONE NUMBER.
        7. FLAGS: Note if data was inferred or suspicious. Else empty string.

        Return ONLY JSON format:
        {{ "name": "", "role": "", "experience": 0, "skills": "", "location": "ST", "email": "", "phone": "", "flags": "" }}

        Resume Text:
        {text[:5000]}
        """
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        total_input_tokens += res.usage.prompt_tokens
        total_output_tokens += res.usage.completion_tokens

        data = json.loads(res.choices[0].message.content)
        data['experience'] = validate_experience(data.get('experience', 0))
        data['location'] = validate_location(data.get('location', ''))
        data['email'] = data.get('email', '').lower().strip()
        data['phone'] = str(data.get('phone', '')).strip()
        return data
    except Exception as e:
        print(f"❌ AI Error {filename}: {e}")
        return None

# --- SINGLE FILE ENGINE ---
def process_file(file, processed_ids):
    file_id, filename = file['id'], file['name']
    if file_id in processed_ids: return None, "already_done"

    db = mysql.connector.connect(**DB_CONFIG); cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE filename=%s", (filename,))
    if cursor.fetchone():
        cursor.close(); db.close()
        return None, "duplicate_filename"
    cursor.close(); db.close()

    try:
        service = get_drive_service()
        req = service.files().get_media(fileId=file_id)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done: _, done = downloader.next_chunk()

        text, is_ocr = extract_text(fh.getvalue(), filename)
        if not text.strip(): return None, "empty_text"

        # AI-ai call pannaama email-ai kandu pudikkalaam (Token cost: $0)
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        found_emails = re.findall(email_pattern, text)
        if found_emails:
            test_email = found_emails[0].lower().strip()
            db = mysql.connector.connect(**DB_CONFIG); cursor = db.cursor()
            cursor.execute("SELECT id FROM users WHERE email=%s", (test_email,))
            if cursor.fetchone():
                cursor.close(); db.close()
                return None, "duplicate_email_skip_ai"
            cursor.close(); db.close()

        # Intha checks ellam thandunaa mattum thaan AI Call pogum
        data = extract_info(text, filename)
        if not data: return None, "ai_failed"

        db = mysql.connector.connect(**DB_CONFIG); cursor = db.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE email=%s OR (phone=%s AND phone!='')",
            (data['email'], data['phone'])
        )
        if cursor.fetchone():
            cursor.close(); db.close()
            return None, "duplicate"

        cursor.execute("""
            INSERT IGNORE INTO users
            (name, role, experience, skills, location, filename, resume_text, email, phone, quality_flags, is_ocr, drive_file_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data['name'], data['role'], data['experience'],
            data['skills'], data['location'], filename,
            text, data['email'], data['phone'],
            data.get('flags', ''), is_ocr, file_id
        ))
        db.commit(); cursor.close(); db.close()
        return data, "success"

    except Exception as e:
        return None, f"error: {e}"

# --- MAIN ENGINE ---
def process_resumes():
    processed_ids = get_processed_file_ids()
    service = get_drive_service()

    all_files = []
    page_token = None
    query = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"

    print("📂 Fetching files from Drive...")
    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            pageSize=1000
        ).execute()
        all_files.extend(results.get('files', []))
        page_token = results.get('nextPageToken')
        if not page_token: break

    to_process = [
        f for f in all_files
        if f['id'] not in processed_ids
        and f['name'].lower().endswith(('.pdf', '.docx'))
    ][:MAX_RESUMES]

    print(f"📁 Total in Drive : {len(all_files)}")
    print(f"🎯 To Process     : {len(to_process)}")
    print(f"⏭️  Already Done   : {len(processed_ids)}")

    stats = {"success": 0, "duplicate": 0, "empty": 0, "error": 0, "ai_failed": 0}

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {
            executor.submit(process_file, f, processed_ids): f
            for f in to_process
        }
        for i, future in enumerate(as_completed(futures), 1):
            data, status = future.result()
            cost = (total_input_tokens / 1e6) * 0.15 + (total_output_tokens / 1e6) * 0.60

            if status == "success":
                stats['success'] += 1
                print(f"✅ [{i}/{len(to_process)}] {data['name']} | {data['location']} | {data['experience']}yrs | 💰${cost:.3f}")
            elif status == "duplicate":
                stats['duplicate'] += 1
                print(f"⏭️  [{i}] Duplicate skipped")
            elif status == "empty_text":
                stats['empty'] += 1
                print(f"⚠️  [{i}] Empty text skipped")
            elif status == "ai_failed":
                stats['ai_failed'] += 1
                print(f"❌ [{i}] AI extraction failed")
            else:
                stats['error'] += 1
                print(f"❌ [{i}] {status}")

    print(f"""
╔══════════════════════════════╗
║      PROCESSING COMPLETE     ║
╠══════════════════════════════╣
║ ✅ Saved      : {stats['success']:>5}         ║
║ ⏭️  Duplicates : {stats['duplicate']:>5}         ║
║ ⚠️  Empty      : {stats['empty']:>5}         ║
║ ❌ Errors     : {stats['error']:>5}         ║
║ 🤖 AI Failed  : {stats['ai_failed']:>5}         ║
╠══════════════════════════════╣
║ 💰 Total Cost : ${(total_input_tokens/1e6)*0.15+(total_output_tokens/1e6)*0.60:.3f}          ║
╚══════════════════════════════╝
""")

if __name__ == "__main__":
    process_resumes()