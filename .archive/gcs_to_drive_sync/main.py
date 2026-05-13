import io
from google.cloud import storage
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import google.auth

# ================= CONFIGURATION =================
# We use the same Drive Folder ID as before
DRIVE_FOLDER_ID = '1wCo_3qi6QPeRDm2uLOrOBD7AylqnUGmw'
# =================================================

def gcs_to_drive_sync(event, context):
    """
    Cloud Function triggered by a change to a Cloud Storage bucket.
    Args:
        event (dict): Event payload.
        context (google.cloud.functions.Context): Metadata for the event.
    """
    bucket_name = event['bucket']
    blob_name = event['name']
    
    # We only care about files in the 'rechnungen/' folder
    if not blob_name.startswith('rechnungen/') or blob_name.endswith('/'):
        print(f"Skipping {blob_name}: Not in rechnungen/ folder.")
        return

    print(f"New file detected: {blob_name} in bucket {bucket_name}")

    try:
        # Use default application credentials (the Cloud Function's service account)
        creds, project = google.auth.default(scopes=[
            'https://www.googleapis.com/auth/devstorage.read_only',
            'https://www.googleapis.com/auth/drive.file'
        ])

        # Initialize Services
        storage_client = storage.Client(credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        filename = blob_name.split('/')[-1]

        # 1. Download into memory
        file_stream = io.BytesIO()
        blob.download_to_file(file_stream)
        file_stream.seek(0)

        # 2. Upload to Drive
        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload(
            file_stream, 
            mimetype=blob.content_type or 'application/octet-stream', 
            resumable=True
        )

        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True 
        ).execute()

        print(f"✓ Successfully synced {filename} to Drive. File ID: {file.get('id')}")

    except Exception as e:
        print(f"Error syncing {blob_name}: {e}")
        raise e
