import os
import io
import re
import fitz
import docx
import json
import time
import mysql.connector
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# --- Google Drive API Imports ---
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow

# -------------------- SETUP --------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "database": "drive_to_sql_v2" # Puthu DB name create panna marakkatha
}

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID") 
PROCESSED_CACHE = 'processed_filenames.json' 
CURRENT_YEAR = datetime.now().year

MAX_RESUMES_TO_PROCESS = 5000  

total_input_tokens = 0
total_output_tokens = 0

# -------------------- CACHE & DB SETUP --------------------
def load_processed_files():
    if os.path.exists(PROCESSED_CACHE):
        with open(PROCESSED_CACHE, 'r') as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    return set()

def save_processed_files(processed_set):
    with open(PROCESSED_CACHE, 'w') as f:
        json.dump(list(processed_set), f)

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def get_drive_service():
    creds = None
    SCOPES = ['https://www.googleapis.com/auth/drive']
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

# -------------------- EXTRACTION --------------------
def extract_text_from_memory(file_bytes, filename):
    text = ""
    try:
        if filename.lower().endswith(".pdf"):
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                text = " ".join([p.get_text() for p in doc])
        elif filename.lower().endswith(".docx"):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"⚠️ Text Extraction Error on {filename}: {e}")
    return text

# -------------------- AI BRAIN (UNGA ORIGINAL RULES + EMAIL/PHONE) --------------------
def extract_all_candidate_info(text, filename):
    global total_input_tokens, total_output_tokens
    try:
        # UNGA ORIGINAL PROMPT RULES WITH ADDED EMAIL/PHONE
        prompt = f"""
        Act as an expert US Technical Recruiter. Analyze the resume text and filename.
        
        STRICT EXTRACTION RULES:
        1. NAME: Extract Full Name from Header. Cross-verify with filename. No 'Resume' or 'CV'.
        2. ROLE: Extract the EXACT Most Recent Job Title. 
        
        3. EXPERIENCE (PRIORITY ORDER):
           - FIRST: Scan 'Professional Summary' or 'Header' for explicit total years (e.g., "30+ years of IT experience"). If found, use that integer and STOP.
           - SECOND: Only if no explicit total is found, calculate: Current Year ({CURRENT_YEAR}) minus the Start Year of the first job.
           - Return ONLY an integer.

        4. LOCATION (PRIORITY ORDER):
           - FIRST: Use City/State from the Contact Header.
           - SECOND: If missing, use the Location of the MOST RECENT/CURRENT job entry.
           - THIRD: If still missing, infer the 2-letter US State Code from the phone number AREA CODE.
           - Return ONLY the 2-letter State Code.

        5. SKILLS: Top 10-15 technical skills as comma-separated string.
        
        6. UNIQUE ID: Extract the Candidate's EMAIL and PHONE NUMBER. 

        Return ONLY JSON format:
        {{ 
          "name": "Full Name", 
          "role": "Recent Title", 
          "experience": 10, 
          "skills": "Skill1, Skill2", 
          "location": "ST",
          "email": "example@mail.com",
          "phone": "1234567890"
        }}

        Resume Text:
        {text[:6000]}
        """
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            response_format={"type":"json_object"},
            temperature=0
        )
        total_input_tokens += res.usage.prompt_tokens
        total_output_tokens += res.usage.completion_tokens
        data = json.loads(res.choices[0].message.content)
        
        exp = data.get("experience", 0)
        if isinstance(exp, str):
            match = re.search(r'\d+', exp)
            exp = int(match.group()) if match else 0
        data["experience"] = exp
            
        return data
    except Exception as e:
        print(f"AI Error: {e}")
        return None

# -------------------- MAIN ENGINE --------------------
def process_resumes():
    service = get_drive_service()
    db = get_db()
    cursor = db.cursor(buffered=True)
    processed_files = load_processed_files()
    print(f"🚀 Started! Already in Cache: {len(processed_files)}")

    query = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"
    page_token = None
    count = 0

    while True:
        results = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, mimeType)",
            orderBy="modifiedTime desc",
            pageToken=page_token, 
            pageSize=100
        ).execute()
        
        files = results.get('files', [])
        if not files: break
            
        for file in files:
            if MAX_RESUMES_TO_PROCESS and count >= MAX_RESUMES_TO_PROCESS:
                break

            file_id, filename = file['id'], file['name']
            if not filename.lower().endswith(('.pdf', '.docx')): continue
            
            # 1. Filename Check
            if filename in processed_files: continue

            try:
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    _, done = downloader.next_chunk()
                
                text = extract_text_from_memory(fh.getvalue(), filename)
                if not text.strip():
                    processed_files.add(filename); save_processed_files(processed_files)
                    continue

                # Get Data from AI
                data = extract_all_candidate_info(text, filename)
                if not data: continue

                email = data.get("email", "").lower().strip()
                phone = str(data.get("phone", "")).strip()

                # 2. SMART DUPLICATE CHECK (By Email or Phone) 
                cursor.execute("SELECT id FROM users WHERE email = %s OR (phone = %s AND phone != '')", (email, phone))
                if cursor.fetchone():
                    print(f"⏭️ Skipping {filename} (Duplicate Email/Phone found)")
                    processed_files.add(filename)
                    save_processed_files(processed_files)
                    continue

                # 3. Insert into DB (Unga table columns match aaganum)
                cursor.execute(
                    "INSERT IGNORE INTO users (name, role, experience, skills, location, filename, resume_text, email, phone) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (data['name'], data['role'], data['experience'], data['skills'], data['location'], filename, text, email, phone)
                )
                db.commit()

                # 4. Finalize Cache
                processed_files.add(filename)
                save_processed_files(processed_files)

                count += 1
                print(f"✅ [{count}] {data['name']} | {data['location']} | {data['experience']}yrs | Tokens: In={total_input_tokens}, Out={total_output_tokens}")
                
            except Exception as e:
                print(f"❌ Error {filename}: {e}")
                continue
        
        if (MAX_RESUMES_TO_PROCESS and count >= MAX_RESUMES_TO_PROCESS) or not results.get('nextPageToken'):
            break
        page_token = results.get('nextPageToken')

    cursor.close(); db.close()
    print(f"\n🎯 DONE! Total Processed: {count}")

if __name__ == "__main__":
    process_resumes()