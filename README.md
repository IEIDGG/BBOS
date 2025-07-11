# BBOS - Best Buy Order Scraper

Advanced email processing system for Best Buy order management and promotional code extraction

## Features
- **Email Processing**: Automated parsing of Best Buy order confirmation and promotional emails
- **Multiple Parsers**: Dedicated parsers for different email types (orders, Xbox codes, etc.)
- **Profile Management**: Profile-based configuration for different use cases
- **Database Integration**: SQLite backend for data storage and retrieval
- **Code Extraction**: Specialized extraction of promotional codes (Xbox Game Pass, etc.)
- **Flexible Output**: Multiple export formats and file handling options

## Installation
```bash
git clone https://github.com/IEIDGG/BBOS.git
cd BBOS
pip install -r requirements.txt
```

## Usage

### Main Application
```bash
# Run the main processing pipeline
python main.py
```

### Profile Management
```bash
# Create new profile
python core/profile_manager.py
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
│   ├── handlers.py      - Email processing handlers
│   ├── processor.py     - Main processing pipeline
│   └── parsers/         - Email parsing implementations
│       ├── bb_parser.py - Best Buy order parser
│       ├── xbox_parser.py - Xbox promotional code parser
│       └── html_selectors.json - Parser configuration
├── output/              - Output generation
│   └── file_handlers.py - File export implementations
├── main.py              - Main CLI entry point
└── requirements.txt     - Python dependencies
```

## Email Parsers

### Best Buy Order Parser
- Extracts order details from Best Buy confirmation emails
- Parses product information, quantities, and pricing
- Handles multiple order formats and layouts

### Xbox Code Parser
- Specialized extraction of Xbox Game Pass promotional codes
- Intelligent filtering to distinguish Xbox codes from other promotional offers
- Supports multiple Xbox/Game Pass email formats

## Configuration

The system uses `html_selectors.json` for parser configuration, allowing flexible adaptation to different email formats without code changes.

## Dependencies
- Python 3.9+
- beautifulsoup4 - HTML parsing
- sqlite3 - Database operations
- Other dependencies listed in requirements.txt

## Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License
See LICENSE file for details
