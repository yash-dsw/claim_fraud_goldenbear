"""
OneDrive client using application permissions (client credentials flow).
This version works without user interaction - perfect for hosted/automated scenarios.
"""

import os
import requests
import time
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
        self.request_timeout = int(os.getenv("ONEDRIVE_HTTP_TIMEOUT", "30"))
        self.max_retries = int(os.getenv("ONEDRIVE_HTTP_RETRIES", "3"))
        self.retry_backoff_seconds = float(os.getenv("ONEDRIVE_HTTP_RETRY_BACKOFF", "1.5"))

    def _request(self, method, url, **kwargs):
        """HTTP request helper with retry/backoff for transient Graph/Auth failures."""
        retryable_status_codes = {429, 500, 502, 503, 504}
        timeout = kwargs.pop("timeout", self.request_timeout)
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.request(method, url, timeout=timeout, **kwargs)

                if response.status_code in retryable_status_codes and attempt < self.max_retries:
                    wait_time = self.retry_backoff_seconds * (2 ** (attempt - 1))
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_time = max(wait_time, float(retry_after))
                    print(f"  ⚠ HTTP {response.status_code} from Graph/Auth. Retrying in {wait_time:.1f}s (attempt {attempt}/{self.max_retries})...")
                    time.sleep(wait_time)
                    continue

                return response

            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if attempt >= self.max_retries:
                    raise
                wait_time = self.retry_backoff_seconds * (2 ** (attempt - 1))
                print(f"  ⚠ Network error during Graph/Auth call. Retrying in {wait_time:.1f}s (attempt {attempt}/{self.max_retries}): {exc}")
                time.sleep(wait_time)

        if last_exception:
            raise last_exception
        raise Exception("HTTP request failed without a response")
    
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
            response = self._request("POST", token_url, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600) - 300
            self.token_expiry = datetime.now().timestamp() + expires_in
            
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get access token after {self.max_retries} attempts: {str(e)}")
    
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
            
            response = self._request("GET", folder_url, headers=self._get_headers())
            
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
            
            response = self._request("POST", create_url, headers=self._get_headers(), json=data)
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

    def get_folder_info(self, folder_name):
        """Get folder information including web URL.
        
        Args:
            folder_name: Name of the OneDrive folder
        
        Returns:
            Dictionary with folder info including web_url, or None if failed
        """
        try:
            folder_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{folder_name}"
            response = requests.get(folder_url, headers=self._get_headers())
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "web_url": result.get("webUrl"),
                    "success": True
                }
            else:
                return None
                
        except Exception as e:
            print(f"  ✗ Error getting folder info: {str(e)}")
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

    def create_subfolder(self, parent_folder_name, subfolder_name):
        """Create a subfolder inside a parent folder.
        
        Args:
            parent_folder_name: Name of the parent folder (e.g., "Claims_fraud")
            subfolder_name: Name of the subfolder to create
            
        Returns:
            Tuple of (folder_id, folder_path) or (None, None) if failed
        """
        try:
            # First ensure parent folder exists
            parent_id = self._create_folder_if_not_exists(parent_folder_name)
            
            if not parent_id:
                raise Exception(f"Could not access or create parent folder '{parent_folder_name}'")
            
            # Check if subfolder already exists
            subfolder_path = f"{parent_folder_name}/{subfolder_name}"
            subfolder_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{subfolder_path}"
            
            response = self._request("GET", subfolder_url, headers=self._get_headers())
            
            if response.status_code == 200:
                # Subfolder exists
                result = response.json()
                print(f"  ✓ Subfolder already exists: {subfolder_path}")
                return result.get("id"), subfolder_path
            
            # Create subfolder inside parent
            create_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/items/{parent_id}/children"
            
            data = {
                "name": subfolder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename"
            }
            
            response = self._request("POST", create_url, headers=self._get_headers(), json=data)
            response.raise_for_status()
            
            result = response.json()
            print(f"  ✓ Created subfolder: {subfolder_path}")
            return result.get("id"), subfolder_path
            
        except Exception as e:
            print(f"  ✗ Error creating subfolder: {str(e)}")
            return None, None

    def upload_file_to_path(self, local_file_path, onedrive_folder_path):
        """Upload a file to a specific OneDrive folder path (including subfolders).
        
        Args:
            local_file_path: Path to the local file to upload
            onedrive_folder_path: Full OneDrive path (e.g., "Claims_fraud/P123_2026-01-27")
        
        Returns:
            Dictionary with upload info or None if failed
        """
        try:
            file_name = os.path.basename(local_file_path)
            
            # Upload the file using direct path
            upload_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{onedrive_folder_path}/{file_name}:/content"
            
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
            print(f"  ✗ Error uploading file to path: {str(e)}")
            return None

    def move_file_to_path(self, file_id, destination_folder_path):
        """Move a file to a specific OneDrive folder path (including subfolders).
        
        Args:
            file_id: The ID of the file to move
            destination_folder_path: Full OneDrive path (e.g., "Claims_fraud/P123_2026-01-27")
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the folder ID for the destination path
            folder_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{destination_folder_path}"
            response = requests.get(folder_url, headers=self._get_headers())
            
            if response.status_code != 200:
                raise Exception(f"Destination folder not found: {destination_folder_path}")
            
            folder_id = response.json().get("id")
            
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
            raise Exception(f"Failed to move file to path: {str(e)}")

    def create_url_shortcut(self, folder_path, shortcut_name, url):
        """Create a .url shortcut file in a OneDrive folder.
        
        Args:
            folder_path: Full OneDrive path for the folder (e.g., "Claims_fraud/P123_2026-01-27")
            shortcut_name: Name for the shortcut file (without .url extension)
            url: The URL to link to
            
        Returns:
            Dictionary with upload info or None if failed
        """
        try:
            # Create .url file content (Windows shortcut format)
            url_content = f"[InternetShortcut]\nURL={url}\n"
            
            # Upload as .url file
            file_name = f"{shortcut_name}.url"
            upload_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{folder_path}/{file_name}:/content"
            
            headers = self._get_headers()
            headers["Content-Type"] = "text/plain"
            
            response = requests.put(upload_url, headers=headers, data=url_content.encode('utf-8'))
            response.raise_for_status()
            
            result = response.json()
            print(f"  ✓ Created URL shortcut: {file_name}")
            
            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "web_url": result.get("webUrl"),
                "success": True
            }
            
        except Exception as e:
            print(f"  ✗ Error creating URL shortcut: {str(e)}")
            return None

    def get_subfolder_info(self, folder_path):
        """Get folder information for a full folder path including web URL.
        
        Args:
            folder_path: Full OneDrive path (e.g., "Claims_fraud/P123_2026-01-27")
        
        Returns:
            Dictionary with folder info including web_url, or None if failed
        """
        try:
            folder_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{folder_path}"
            response = requests.get(folder_url, headers=self._get_headers())
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "web_url": result.get("webUrl"),
                    "success": True
                }
            else:
                return None
                
        except Exception as e:
            print(f"  ✗ Error getting folder info: {str(e)}")
            return None

    def list_files_in_subfolder(self, folder_path):
        """List all files in a specific OneDrive subfolder path.

        Args:
            folder_path: Full OneDrive path (e.g., "Claims_fraud/CN_7738446180")

        Returns:
            List of file info dicts with id, name, size, modified, web_url
        """
        try:
            children_url = (
                f"https://graph.microsoft.com/v1.0/users/{self.user_email}"
                f"/drive/root:/{folder_path}:/children"
            )
            response = requests.get(children_url, headers=self._get_headers())
            response.raise_for_status()

            items = response.json().get("value", [])
            files = []
            for item in items:
                if "file" in item:
                    files.append({
                        "id": item["id"],
                        "name": item["name"],
                        "size": item.get("size", 0),
                        "modified": item.get("lastModifiedDateTime", ""),
                        "web_url": item.get("webUrl", ""),
                    })
            return files

        except Exception as e:
            raise Exception(f"Failed to list files in subfolder '{folder_path}': {str(e)}")



    def get_file_info(self, file_path):
        """Get file information for a full file path including web URL.
        
        Args:
            file_path: Full OneDrive path to file (e.g., "Claims_fraud/P123_2026-01-27/report.pdf")
        
        Returns:
            Dictionary with file info including webUrl, or None if failed
        """
        try:
            file_url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/drive/root:/{file_path}"
            response = requests.get(file_url, headers=self._get_headers())
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "webUrl": result.get("webUrl"),
                    "size": result.get("size"),
                    "success": True
                }
            else:
                return None
                
        except Exception as e:
            print(f"  ✗ Error getting file info: {str(e)}")
            return None


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
