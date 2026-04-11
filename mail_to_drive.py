import os
import base64
import json
import time
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive'
]

DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID', 'root')
# Ipo Emails pathila Filename ah track pandrom
PROCESSED_FILES_CACHE = 'processed_filenames.json'

def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def load_processed_files():
    if os.path.exists(PROCESSED_FILES_CACHE):
        with open(PROCESSED_FILES_CACHE, 'r') as f:
            return set(json.load(f))
    return set()

def save_processed_files(processed_set):
    with open(PROCESSED_FILES_CACHE, 'w') as f:
        json.dump(list(processed_set), f)

def get_all_attachments(parts):
    attachments = []
    for part in parts:
        if part.get('filename'):
            attachments.append(part)
        if 'parts' in part:
            attachments.extend(get_all_attachments(part['parts']))
    return attachments

def get_existing_drive_files(drive_service):
    existing_files = set()
    query = "trashed=false and mimeType!='application/vnd.google-apps.folder'"
    
    if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != 'root':
        query += f" and '{DRIVE_FOLDER_ID}' in parents"

    page_token = None
    while True:
        try:
            response = drive_service.files().list(
                q=query, spaces='drive', fields='nextPageToken, files(id, name)',
                pageToken=page_token, pageSize=1000
            ).execute()
            
            for f in response.get('files', []):
                existing_files.add(f.get('name'))
                
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except Exception as e:
            print(f"Error fetching from Drive. Waiting 5s... Error: {e}")
            time.sleep(5)
            
    return existing_files

def save_to_drive(drive_service, filename, file_data, mime_type):
    media = MediaInMemoryUpload(file_data, mimetype=mime_type)
    file_metadata = {'name': filename} # Inime msg_id add aagathu, original name thaan!
    
    if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != 'root':
        file_metadata['parents'] = [DRIVE_FOLDER_ID]

    drive_service.files().create(
        body=file_metadata,
        media_body=media
    ).execute()
    print(f"Saved: {filename}")

def gmail_to_drive_bulk():
    creds = get_credentials()
    gmail_service = build('gmail', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    print("Loading local cache...")
    processed_filenames = load_processed_files()

    print("Checking Drive for existing files...")
    existing_drive_files = get_existing_drive_files(drive_service)
    
    # Rendu list aiyum merge pandrom. Ipo namma kitta pakka-vaana master list irukku!
    master_skip_list = processed_filenames.union(existing_drive_files)
    print(f"Found {len(master_skip_list)} unique resumes already saved. Ready to skip them.")

    query = 'has:attachment filename:pdf OR filename:docx OR filename:doc'
    page_token = None
    total_saved = 0

    print("Scanning Gmail for new resumes...")
    
    while True:
        try:
            results = gmail_service.users().messages().list(
                userId='me', q=query, pageToken=page_token, maxResults=500
            ).execute()

            messages = results.get('messages', [])
            if not messages:
                break

            for msg in messages:
                msg_id = msg['id']
                
                try:
                    msg_data = gmail_service.users().messages().get(
                        userId='me', id=msg_id, format='full'
                    ).execute()

                    parts = msg_data.get('payload', {}).get('parts', [])
                    attachments = get_all_attachments(parts)

                    for part in attachments:
                        # Original filename ah mattum edukkurom
                        filename = part.get('filename', '')
                        if not filename.lower().endswith(('.pdf', '.docx')):
                            continue

                        # Master list-la intha peru irukka nu check pandrom (No Email IDs involved)
                        if filename in master_skip_list:
                            print(f"Duplicate caught and skipped: {filename}")
                            continue

                        att_id = part['body'].get('attachmentId')
                        if not att_id:
                            continue

                        att = gmail_service.users().messages().attachments().get(
                            userId='me', messageId=msg_id, id=att_id
                        ).execute()

                        file_data = base64.urlsafe_b64decode(att['data'])
                        mime_type = part.get('mimeType', 'application/octet-stream')

                        save_to_drive(drive_service, filename, file_data, mime_type)
                        
                        # Upload aana udane list-la add pandrom
                        master_skip_list.add(filename)
                        processed_filenames.add(filename)
                        total_saved += 1
                        
                        # Google API Rate limit crash aagama irukka 1 second delay
                        time.sleep(1) 

                except Exception as e:
                    print(f"Error processing message {msg_id}: {e}")
                    time.sleep(2) # Error vantha 2 second wait panni adutha mail ku pogum
                    continue

            # Batch batch ah save pandrom
            save_processed_files(processed_filenames)

            page_token = results.get('nextPageToken')
            if not page_token:
                break
                
        except Exception as e:
             print(f"Gmail API Timeout/Error. Waiting 5s before retrying... Error: {e}")
             time.sleep(5)

    print(f"Process Complete! Total fresh resumes safely saved to Drive: {total_saved}")

if __name__ == "__main__":
    gmail_to_drive_bulk()