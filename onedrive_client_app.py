"""
OneDrive client using application permissions (client credentials flow).
This version works without user interaction - perfect for hosted/automated scenarios.
"""

import os
import requests
from datetime import datetime


class OneDriveClientApp:
    """OneDrive client using application permissions with client credentials."""
    
    def __init__(self, tenant_id, client_id, client_secret, user_email, folder_name="Input_attachments"):
        """
        Initialize OneDrive client with app credentials.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: Application (client) ID
            client_secret: Client secret
            user_email: Email of the user whose OneDrive to access
            folder_name: Name of the folder to monitor
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_email = user_email
        self.folder_name = folder_name
        self.access_token = None
        self.token_expiry = None
    
    def _get_access_token(self):
        """Get access token using client credentials flow."""
        if self.access_token and self.token_expiry and datetime.now().timestamp() < self.token_expiry:
            return self.access_token
        
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default"
        }
        
        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600) - 300
            self.token_expiry = datetime.now().timestamp() + expires_in
            
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get access token: {str(e)}")
    
    def _get_headers(self):
        """Get headers with access token."""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def list_files(self):
        """List all files in the specified OneDrive folder."""
        try:
            # Search for the folder in the user's OneDrive
            # Using /users/{email} instead of /me for app-only access
            search_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root/search(q='{self.folder_name}')"
            
            response = requests.get(search_url, headers=self._get_headers())
            response.raise_for_status()
            
            items = response.json().get("value", [])
            folder_id = None
            
            # Find the folder
            for item in items:
                if item.get("name") == self.folder_name and "folder" in item:
                    folder_id = item["id"]
                    break
            
            if not folder_id:
                raise Exception(f"Folder '{self.folder_name}' not found in OneDrive root")
            
            # List files in the folder
            files_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{folder_id}/children"
            
            response = requests.get(files_url, headers=self._get_headers())
            response.raise_for_status()
            
            items = response.json().get("value", [])
            
            # Filter to only files
            files = []
            for item in items:
                if "file" in item:
                    file_info = {
                        "id": item["id"],
                        "name": item["name"],
                        "size": item.get("size", 0),
                        "modified": item.get("lastModifiedDateTime", ""),
                        "web_url": item.get("webUrl", ""),
                        "download_url": item.get("@microsoft.graph.downloadUrl", "")
                    }
                    files.append(file_info)
            
            return files
            
        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")
    
    def download_file(self, file_info, local_dir="input"):
        """Download a file from OneDrive."""
        try:
            os.makedirs(local_dir, exist_ok=True)
            
            file_name = file_info['name']
            local_path = os.path.join(local_dir, file_name)

            # If file already exists locally, skip downloading
            if os.path.exists(local_path):
                print(f"\n⚠ Skipping existing file: {file_name}")
                return local_path
            
            # Use download URL if available
            if file_info.get('download_url'):
                response = requests.get(file_info['download_url'], stream=True)
            else:
                # Use authenticated download
                file_id = file_info['id']
                url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{file_id}/content"
                response = requests.get(url, headers=self._get_headers(), stream=True)
            
            response.raise_for_status()
            
            local_path = os.path.join(local_dir, file_name)
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return local_path
            
        except Exception as e:
            raise Exception(f"Failed to download file: {str(e)}")
    
    def download_all_files(self, local_dir="input", file_extension=".pdf"):
        """Download all files from OneDrive folder."""
        downloaded_files = []
        
        try:
            files = self.list_files()
            
            print(f"\n📁 Found {len(files)} files in OneDrive folder '{self.folder_name}'")
            
            if file_extension:
                files = [f for f in files if f['name'].lower().endswith(file_extension.lower())]
                print(f"   Filtered to {len(files)} {file_extension} files")
            
            for file_info in files:
                # Skip if the same file already exists locally
                local_path = os.path.join(local_dir, file_info['name'])
                if os.path.exists(local_path):
                    print(f"\n⚠ Skipping existing file: {file_info['name']}")
                    continue

                print(f"\n📥 Downloading: {file_info['name']} ({file_info['size']} bytes)")
                
                local_path = self.download_file(file_info, local_dir)
                if local_path:
                    downloaded_files.append(local_path)
                    print(f"   ✓ Saved to: {local_path}")
            
            return downloaded_files
            
        except Exception as e:
            print(f"\n✗ Error: {str(e)}")
            return downloaded_files
    
    def _create_folder_if_not_exists(self, folder_name):
        """Create a folder in OneDrive root if it doesn't exist.
        
        Args:
            folder_name: Name of the folder to create
            
        Returns:
            Folder ID or None if failed
        """
        try:
            # First, try to get the folder if it exists
            folder_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{folder_name}"
            
            response = requests.get(folder_url, headers=self._get_headers())
            
            if response.status_code == 200:
                # Folder exists
                return response.json().get("id")
            
            # Folder doesn't exist, create it
            create_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root/children"
            
            data = {
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename"
            }
            
            response = requests.post(create_url, headers=self._get_headers(), json=data)
            response.raise_for_status()
            
            result = response.json()
            print(f"  ✓ Created OneDrive folder: {folder_name}")
            return result.get("id")
            
        except Exception as e:
            print(f"  ✗ Error creating folder: {str(e)}")
            return None
    
    def upload_file(self, local_file_path, onedrive_folder_name=None):
        """Upload a file to a OneDrive folder.
        
        Args:
            local_file_path: Path to the local file to upload
            onedrive_folder_name: Name of the OneDrive folder (defaults to self.folder_name)
        
        Returns:
            Dictionary with upload info or None if failed
        """
        try:
            folder_name = onedrive_folder_name or self.folder_name
            file_name = os.path.basename(local_file_path)
            
            # Ensure folder exists (create if needed)
            folder_id = self._create_folder_if_not_exists(folder_name)
            
            if not folder_id:
                raise Exception(f"Could not access or create folder '{folder_name}'")
            
            # Upload the file using direct path
            upload_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{folder_name}/{file_name}:/content"
            
            with open(local_file_path, 'rb') as f:
                file_content = f.read()
            
            headers = self._get_headers()
            headers["Content-Type"] = "application/octet-stream"
            
            response = requests.put(upload_url, headers=headers, data=file_content)
            response.raise_for_status()
            
            result = response.json()
            
            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "size": result.get("size"),
                "web_url": result.get("webUrl"),
                "success": True
            }
            
        except Exception as e:
            print(f"  ✗ Error uploading file: {str(e)}")
            return None

    def delete_file(self, file_id):
        """Delete a file from OneDrive.
        
        Args:
            file_id: The ID of the file to delete.
        """
        try:
            delete_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{file_id}"
            
            response = requests.delete(delete_url, headers=self._get_headers())
            
            if response.status_code == 204:
                return True
            else:
                response.raise_for_status()
                
        except Exception as e:
            raise Exception(f"Failed to delete file: {str(e)}")
    
    def move_file(self, file_id, destination_folder_name):
        """Move a file to a different OneDrive folder.
        
        Args:
            file_id: The ID of the file to move
            destination_folder_name: Name of the destination folder
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure destination folder exists
            folder_id = self._create_folder_if_not_exists(destination_folder_name)
            
            if not folder_id:
                raise Exception(f"Could not access or create folder '{destination_folder_name}'")
            
            # Get file info to check name
            file_info_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{file_id}"
            response = requests.get(file_info_url, headers=self._get_headers())
            response.raise_for_status()
            file_info = response.json()
            file_name = file_info.get('name')
            
            # Check if file with same name exists in destination folder
            check_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{folder_id}/children"
            response = requests.get(check_url, headers=self._get_headers())
            response.raise_for_status()
            existing_files = response.json().get('value', [])
            
            # Delete existing file with same name if found
            for existing_file in existing_files:
                if existing_file.get('name') == file_name:
                    delete_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{existing_file['id']}"
                    requests.delete(delete_url, headers=self._get_headers())
                    break
            
            # Move the file using PATCH request
            move_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{file_id}"
            
            data = {
                "parentReference": {
                    "id": folder_id
                }
            }
            
            response = requests.patch(move_url, headers=self._get_headers(), json=data)
            response.raise_for_status()
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to move file: {str(e)}")


def test_app_auth():
    """Test OneDrive connection with app credentials."""
    from dotenv import load_dotenv
    
    load_dotenv()
    
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_email = os.getenv("ONEDRIVE_USER_EMAIL")
    folder_name = os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments")
    
    if not all([tenant_id, client_id, client_secret, user_email]):
        print("✗ Error: Missing credentials")
        print("  Required: ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_ID, ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_EMAIL")
        return False
    
    try:
        print("Testing OneDrive with app credentials (no user interaction)...")
        client = OneDriveClientApp(tenant_id, client_id, client_secret, user_email, folder_name)
        
        files = client.list_files()
        
        print(f"\n✓ Successfully connected!")
        print(f"  Found {len(files)} files in '{folder_name}' folder")
        
        for file in files:
            print(f"  - {file['name']} ({file['size']} bytes)")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Connection failed: {str(e)}")
        print("\n💡 Make sure:")
        print("  1. Admin has granted consent for application permissions")
        print("  2. Files.Read.All permission is granted")
        print("  3. User email is correct")
        return False


if __name__ == "__main__":
    test_app_auth()
