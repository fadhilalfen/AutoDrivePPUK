"""
drive_api.py - Integrasi Google Drive API v3
Mendukung navigasi struktur folder bertingkat (Root > Rencana Kinerja > Bulan > Nama Kegiatan),
ekstraksi ID regex, pembuatan subfolder baru, dan pengunggahan file otomatis.
"""

import os
import re
import mimetypes
from typing import Optional, Dict, Any, List, Tuple
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Scope yang dibutuhkan:
# Untuk membaca struktur pohon folder yang sudah ada di Google Drive pengguna,
# Google API membutuhkan scope drive lengkap agar dapat mengeksplorasi hierarki subfolder.
SCOPES = ['https://www.googleapis.com/auth/drive']

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def extract_folder_id(url_or_id: str) -> Optional[str]:
    """
    Mengekstrak Google Drive Folder ID dari URL atau string ID langsung.
    Contoh yang didukung:
    - https://drive.google.com/drive/folders/1A2b3c4d5e6f7g8h9i0jKlMnOpQrStUvW
    - https://drive.google.com/drive/u/0/folders/1A2b3c4d5e6f7g8h9i0jKlMnOpQrStUvW?usp=sharing
    - https://drive.google.com/open?id=1A2b3c4d5e6f7g8h9i0jKlMnOpQrStUvW
    - 1A2b3c4d5e6f7g8h9i0jKlMnOpQrStUvW (Folder ID langsung)
    """
    if not url_or_id or not isinstance(url_or_id, str):
        return None
    
    clean_str = url_or_id.strip()
    
    # 1. URL format /drive/folders/<id> atau /drive/u/X/folders/<id>
    match_folders = re.search(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]{25,})", clean_str)
    if match_folders:
        return match_folders.group(1)
    
    # 2. URL format parameter id=<id>
    match_id_param = re.search(r"drive\.google\.com/.*?[\?&]id=([a-zA-Z0-9_-]{25,})", clean_str)
    if match_id_param:
        return match_id_param.group(1)
    
    # 3. String Folder ID langsung
    match_direct = re.match(r"^([a-zA-Z0-9_-]{25,})$", clean_str)
    if match_direct:
        return match_direct.group(1)
    
    return None


class DriveManager:
    """Kelas pengelola otentikasi dan operasi Google Drive API."""

    def __init__(self, credentials_path: str = CREDENTIALS_FILE, token_path: str = TOKEN_FILE):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.creds: Optional[Credentials] = None

    def get_auth_status(self) -> Tuple[bool, str]:
        """Memeriksa apakah token OAuth valid tanpa membuka browser."""
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
                if creds and (creds.valid or (creds.expired and creds.refresh_token)):
                    return True, "Token OAuth tersedia (Siap Digunakan)"
            except Exception as e:
                return False, f"Token tidak valid: {e}"

        if not os.path.exists(self.credentials_path):
            return False, f"File '{self.credentials_path}' tidak ditemukan."
        
        return False, "Memerlukan login pertama kali via browser."

    def authenticate(self, interactive: bool = True) -> Any:
        """Melakukan otentikasi OAuth2 dan membangun Google Drive Service."""
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                print(f"[DriveManager] Gagal membaca token: {e}")
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"[DriveManager] Gagal refresh token: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"File '{self.credentials_path}' tidak ditemukan! "
                        "Silakan unduh dari Google Cloud Console dan simpan di folder aplikasi."
                    )
                if not interactive:
                    raise PermissionError("Otentikasi interaktif diperlukan tetapi dimatikan.")
                
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_path, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())

        self.creds = creds
        self.service = build('drive', 'v3', credentials=self.creds)
        return self.service

    def get_folder_metadata(self, folder_id: str) -> Dict[str, Any]:
        """Mengambil nama dan metadata sebuah folder."""
        if not self.service:
            self.authenticate()
        try:
            return self.service.files().get(
                fileId=folder_id,
                fields="id, name, mimeType"
            ).execute()
        except HttpError as e:
            raise RuntimeError(f"Gagal mengambil metadata folder ID {folder_id}: {e}")

    def list_subfolders(self, parent_folder_id: str) -> List[Dict[str, str]]:
        """
        Mengambil daftar subfolder langsung yang ada di dalam sebuah parent folder Google Drive.
        Mengembalikan list of dict: [{'id': '...', 'name': '...'}, ...]
        """
        if not self.service:
            self.authenticate()

        subfolders = []
        page_token = None
        query = (
            f"'{parent_folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )

        try:
            while True:
                response = self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name)',
                    orderBy='name',
                    pageToken=page_token
                ).execute()

                files = response.get('files', [])
                for f in files:
                    subfolders.append({'id': f['id'], 'name': f['name']})

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break

            return subfolders

        except HttpError as error:
            raise RuntimeError(f"Gagal memuat subfolder dari folder ID '{parent_folder_id}': {error}")

    def create_subfolder(self, parent_folder_id: str, folder_name: str) -> Dict[str, Any]:
        """
        Membuat subfolder baru di dalam parent folder tertentu.
        Berguna jika bulan atau nama kegiatan belum ada di Drive.
        """
        if not self.service:
            self.authenticate()

        folder_metadata = {
            'name': folder_name.strip(),
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }

        try:
            file = self.service.files().create(
                body=folder_metadata,
                fields='id, name'
            ).execute()
            return file
        except HttpError as error:
            raise RuntimeError(f"Gagal membuat folder '{folder_name}': {error}")

    def upload_file(self, file_path: str, target_folder_id: str, custom_name: Optional[str] = None) -> Dict[str, Any]:
        """Mengunggah file lokal ke folder Google Drive tujuan dengan nama kustom opsional."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File tidak ditemukan: {file_path}")

        if not self.service:
            self.authenticate(interactive=True)

        file_name = custom_name if custom_name else os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'

        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id]
        }

        media = MediaFileUpload(
            file_path,
            mimetype=mime_type,
            resumable=True
        )

        try:
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, size'
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
            
            return response

        except HttpError as error:
            raise RuntimeError(f"Gagal mengunggah file ke Google Drive: {error}")
