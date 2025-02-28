# BBOS - Best Buy Order Scraper

Advanced order management system for Best Buy order processing and analysis

## Features
- Profile-based configuration management
- Email integration for order tracking
- Modular processing pipeline
- SQLite database backend
- Output generation in multiple formats

## Installation
```bash
git clone https://github.com/your-repo/BBOS.git
cd BBOS
pip install -r requirements.txt
```

## Configuration
1. Copy `config/settings.example.py` to `config/settings.py`
2. Configure email settings in `config/settings.py`:
```python
EMAIL_CONFIG = {
    'server': 'imap.your-email-provider.com',
    'user': 'your@email.com',
    'password': 'your-app-password'
}
```

## Profile Management
```bash
# Create new profile
python profile_main.py --create-profile --name "Warehouse1"

# List profiles
python profile_main.py --list-profiles

# Update profile
python profile_main.py --update-profile --name "Warehouse1"
```

## Project Structure
```
├── config/              - Configuration settings
│   ├── __init__.py
│   └── settings.py
├── core/                - Core application logic
│   ├── database.py      - Database connection manager
│   ├── profile_manager.py - Profile configuration handler
│   └── utils.py         - Common utilities
├── email_processing/    - Email integration modules
│   ├── connector.py     - IMAP email client
│   ├── parsers/         - Order parsing implementations
│   └── processor.py     - Main processing pipeline
├── output/              - Output generation
│   └── file_handlers.py - File export implementations
├── requirements.txt     - Python dependencies
└── profile_main.py      - CLI entry point
```

## Dependencies
- Python 3.9+
- See requirements.txt for full package list

## Usage
```bash
# Run main processing pipeline
python profile_main.py --run --profile "Warehouse1"
