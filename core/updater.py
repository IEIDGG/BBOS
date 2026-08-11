import io
import os
import re
import shutil
import zipfile
from typing import Tuple

import requests

from config.settings import CURRENT_VERSION


class UpdateManager:
    def __init__(self):
        self.github_repo = "IEIDGG/BBOS"
        self.branch = "FastAPI-Config"
        self.raw_base_url = (
            f"https://raw.githubusercontent.com/{self.github_repo}/{self.branch}"
        )
        self.zip_url = f"https://github.com/{self.github_repo}/archive/refs/heads/{self.branch}.zip"

    def check_for_updates(self) -> Tuple[bool, str]:
        try:
            settings_url = f"{self.raw_base_url}/config/settings.py"
            response = requests.get(settings_url, timeout=10)

            if response.status_code == 200:
                content = response.text
                match = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    remote_version = match.group(1)

                    if self._compare_versions(remote_version, CURRENT_VERSION):
                        return True, remote_version

            return False, CURRENT_VERSION

        except Exception as e:
            print(f"Error checking for updates: {str(e)}")
            return False, CURRENT_VERSION

    def _compare_versions(self, remote: str, local: str) -> bool:
        try:
            r_parts = [int(p) for p in remote.split(".")]
            l_parts = [int(p) for p in local.split(".")]
            return r_parts > l_parts
        except ValueError:
            return remote != local

    def perform_update(self) -> bool:
        try:
            print(f"\nDownloading update from {self.branch} branch...")
            response = requests.get(self.zip_url, stream=True)

            if response.status_code != 200:
                print(f"Failed to download update. Status code: {response.status_code}")
                return False

            extract_path = "temp_update"
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            os.makedirs(extract_path)

            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                z.extractall(extract_path)

            extracted_folder = os.path.join(extract_path, f"BBOS-{self.branch}")
            if not os.path.exists(extracted_folder):
                items = os.listdir(extract_path)
                for item in items:
                    item_path = os.path.join(extract_path, item)
                    if os.path.isdir(item_path):
                        extracted_folder = item_path
                        break

            if not os.path.exists(extracted_folder):
                print("Could not find extracted update files.")
                return False

            preserve_files = {
                os.path.join("config", "profiles.json"),
            }

            preserve_extensions = {".sqlite3", ".log"}

            print("Installing update...")

            for root, dirs, files in os.walk(extracted_folder):
                rel_path = os.path.relpath(root, extracted_folder)

                target_dir = rel_path
                if target_dir == ".":
                    target_dir = ""

                if target_dir and not os.path.exists(target_dir):
                    os.makedirs(target_dir)

                for file in files:
                    source_file = os.path.join(root, file)
                    dest_file = os.path.join(target_dir, file)

                    if dest_file in preserve_files and os.path.exists(dest_file):
                        print(f"Skipping preserved file: {dest_file}")
                        continue

                    _, ext = os.path.splitext(file)
                    if ext in preserve_extensions:
                        continue

                    try:
                        shutil.copy2(source_file, dest_file)
                    except PermissionError:
                        print(
                            f"Warning: Could not update {dest_file} (Permission denied). This might be because the file is in use."
                        )
                    except Exception as e:
                        print(f"Error updating {dest_file}: {str(e)}")

            shutil.rmtree(extract_path)

            print("\nUpdate installed successfully!")
            return True

        except Exception as e:
            print(f"\nError performing update: {str(e)}")
            if "extract_path" in locals() and os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            return False
