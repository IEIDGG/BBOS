"""
Profile manager for handling user credentials and email service preferences.
"""

import json
import os
from typing import Dict, List, Optional, Any
from getpass import getpass
import re
from pathlib import Path


class ProfileManager:
    def __init__(self, profiles_file: str = 'profiles.json'):
        """Initialize profile manager with profile storage location."""
        self.profiles_file = Path(profiles_file)
        self.email_services = {
            '1': {'name': 'gmail', 'requires_email': True, 'display': 'Gmail'},
            '2': {'name': 'proton', 'requires_email': True, 'display': 'Proton Mail'},
            '3': {'name': 'icloud', 'requires_email': False, 'display': 'iCloud'}
        }
        # Initialize or load existing profiles
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> Dict[str, Dict[str, Any]]:
        """
        Load profiles from JSON file or create new profiles dictionary.
        Returns a dictionary with 'profiles' key containing profile data.
        """
        default_profiles = {"profiles": {}}

        if not self.profiles_file.exists():
            return default_profiles

        try:
            with open(self.profiles_file, 'r') as f:
                data = json.load(f)
                if not isinstance(data, dict) or 'profiles' not in data:
                    return default_profiles
                return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading profiles file: {e}")
            return default_profiles

    def _save_profiles(self) -> bool:
        """
        Save current profiles to JSON file.
        Returns True if successful, False otherwise.
        """
        try:
            # Ensure directory exists
            self.profiles_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.profiles_file, 'w') as f:
                json.dump(self.profiles, f, indent=4)
            return True
        except IOError as e:
            print(f"Error saving profiles: {e}")
            return False

    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        return bool(re.match(pattern, email))

    def _get_email_service(self) -> Optional[Dict[str, Any]]:
        """
        Interactively get email service selection from user.
        Returns service configuration dict or None if cancelled.
        """
        while True:
            print("\nSelect email service:")
            for key, service in self.email_services.items():
                print(f"{key}. {service['display']}")
            print("q. Cancel")

            choice = input("\nEnter choice (or 'q' to cancel): ").strip().lower()

            if choice == 'q':
                return None

            if choice in self.email_services:
                return self.email_services[choice]

            print("Invalid choice. Please try again.")

    def _get_credentials(self, service: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Get credentials from user based on service type.
        Returns dict with username/email and password or None if cancelled.
        """
        # Get username/email
        while True:
            if service['requires_email']:
                prompt = f"Enter {service['display']} email address: "
                username = input(prompt).strip()
                if not self._validate_email(username):
                    print("Invalid email format. Please try again.")
                    continue
            else:
                prompt = f"Enter {service['display']} Apple ID: "
                username = input(prompt).strip()
                if not username:
                    print("Apple ID cannot be empty.")
                    continue
            break

        # Get password
        while True:
            try:
                password = getpass("Enter password: ")
                if not password:
                    print("Password cannot be empty.")
                    continue

                confirm = getpass("Confirm password: ")
                if password != confirm:
                    print("Passwords don't match. Please try again.")
                    continue
                break
            except KeyboardInterrupt:
                return None

        return {
            "username": username,
            "password": password
        }

    def _get_profile_name(self) -> Optional[str]:
        """
        Get unique profile name from user.
        Returns profile name or None if cancelled.
        """
        while True:
            name = input("\nEnter profile name (or 'q' to cancel): ").strip()

            if name.lower() == 'q':
                return None

            if not name:
                print("Profile name cannot be empty.")
                continue

            if name in self.profiles["profiles"]:
                print("Profile already exists. Choose a different name.")
                continue

            return name

    def add_profile(self) -> bool:
        """
        Add a new profile interactively.
        Returns True if profile was added successfully, False otherwise.
        """
        print("\nAdding New Profile")
        print("=" * 20)

        # Get service type
        service = self._get_email_service()
        if not service:
            return False

        # Get credentials
        creds = self._get_credentials(service)
        if not creds:
            return False

        # Get profile name
        profile_name = self._get_profile_name()
        if not profile_name:
            return False

        try:
            # Create new profile
            new_profile = {
                "email": creds["username"],
                "username": creds["username"],
                "password": creds["password"],
                "service": service["name"]
            }

            # Add to profiles dictionary
            self.profiles["profiles"][profile_name] = new_profile

            # Save to file
            if not self._save_profiles():
                # If save fails, remove from memory
                del self.profiles["profiles"][profile_name]
                return False

            print(f"\nProfile '{profile_name}' added successfully!")
            return True

        except Exception as e:
            print(f"Error creating profile: {e}")
            # Clean up if profile was partially added
            if profile_name in self.profiles["profiles"]:
                del self.profiles["profiles"][profile_name]
            return False

    def list_profiles(self) -> List[str]:
        """Get list of profile names."""
        return list(self.profiles["profiles"].keys())

    def select_profile(self) -> Optional[Dict[str, Any]]:
        """
        Select a profile interactively.
        Returns complete profile data dict or None if cancelled.
        """
        profiles = self.list_profiles()

        if not profiles:
            print("\nNo profiles found. Please add a profile first.")
            return None

        print("\nAvailable Profiles:")
        print("=" * 20)
        for i, name in enumerate(profiles, 1):
            profile = self.profiles['profiles'][name]
            print(f"{i}. {name} ({profile['email']} - {profile['service'].title()})")

        print("\na. Add new profile")
        print("q. Cancel")

        while True:
            choice = input("\nSelect profile (enter choice): ").strip().lower()

            if choice == 'q':
                return None

            if choice == 'a':
                if self.add_profile():
                    return self.select_profile()
                return None

            try:
                idx = int(choice)
                if 1 <= idx <= len(profiles):
                    profile_name = profiles[idx - 1]
                    profile_data = self.profiles["profiles"][profile_name]
                    return {
                        "name": profile_name,
                        **profile_data
                    }
            except ValueError:
                pass

            print("Invalid choice. Please try again.")

    def delete_profile(self, profile_name: str) -> bool:
        """
        Delete a profile.
        Returns True if profile was deleted successfully, False otherwise.
        """
        if profile_name not in self.profiles["profiles"]:
            print(f"Profile '{profile_name}' not found.")
            return False

        try:
            # Remove from memory
            del self.profiles["profiles"][profile_name]

            # Save changes
            if not self._save_profiles():
                print("Error saving changes after deletion.")
                return False

            print(f"\nProfile '{profile_name}' deleted successfully!")
            return True

        except Exception as e:
            print(f"Error deleting profile: {e}")
            return False

    def manage_profiles(self) -> None:
        """Manage profiles interactively."""
        while True:
            print("\nProfile Management")
            print("=" * 20)
            print("1. List profiles")
            print("2. Add profile")
            print("3. Delete profile")
            print("4. Exit")

            choice = input("\nEnter choice (1-4): ").strip()

            if choice == '1':
                profiles = self.list_profiles()
                if profiles:
                    print("\nExisting Profiles:")
                    for name in profiles:
                        profile = self.profiles['profiles'][name]
                        print(f"- {name} ({profile['email']} - {profile['service'].title()})")
                else:
                    print("\nNo profiles found.")

            elif choice == '2':
                self.add_profile()

            elif choice == '3':
                profiles = self.list_profiles()
                if not profiles:
                    print("\nNo profiles to delete.")
                    continue

                print("\nSelect profile to delete:")
                for i, name in enumerate(profiles, 1):
                    print(f"{i}. {name}")
                print("q. Cancel")

                while True:
                    choice = input("\nEnter choice (or 'q' to cancel): ").strip().lower()
                    if choice == 'q':
                        break

                    try:
                        idx = int(choice)
                        if 1 <= idx <= len(profiles):
                            profile_name = profiles[idx - 1]
                            confirm = input(f"Are you sure you want to delete '{profile_name}'? (y/n): ")
                            if confirm.lower() == 'y':
                                self.delete_profile(profile_name)
                            break
                        else:
                            print("Invalid choice. Please try again.")
                    except ValueError:
                        print("Invalid input. Please enter a number or 'q'.")

            elif choice == '4':
                break

            else:
                print("Invalid choice. Please try again.")