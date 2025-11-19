# FastAPI Integration - Complete Implementation Guide

## Overview

This implementation adds automatic submission of Best Buy order tracking numbers to a FastAPI backend service. The integration is seamlessly built into the continuous monitoring mode and can be toggled on/off through the settings menu.

## What Was Added

### 1. New `/api/` Folder Structure

```
api/
├── __init__.py              # Package initialization
├── submitter.py             # Main API submission logic
├── api_config.json          # Configuration file
└── README.md                # Detailed documentation
```

### 2. Core Components

#### CarrierDetector Class
Automatically detects shipping carriers based on tracking number patterns:
- **UPS**: 1Z + 16 alphanumeric characters
- **FedEx**: 12, 14, or 15 digit numbers
- **USPS**: 20-22 digits or starts with 92/93/94
- **Amazon**: TBA + 12 digits
- **Undetermined**: For unrecognized patterns

#### ZipCodeExtractor Class
Extracts ZIP codes from address strings using regex patterns.
Supports both 5-digit and ZIP+4 formats.

#### APIConfig Class
Manages configuration loading, saving, and retrieval:
- Loads settings from `api/api_config.json`
- Maps ZIP codes to buying groups
- Manages API URL and authentication
- Handles enable/disable state

#### OrderAPISubmitter Class
Handles order submission to the FastAPI backend:
- Prepares order payloads with all required fields
- Submits tracking numbers individually
- Handles multiple orders in batch
- Prevents duplicate submissions in same session
- Provides detailed success/failure feedback

### 3. Modified Files

#### continuous_monitor.py
**Changes:**
- Added API submitter import and initialization
- Created `_submit_shipped_orders_to_api()` method
- Integrated API submission into shipped email processing
- Only submits orders with tracking numbers
- Shows real-time submission feedback

**Flow:**
1. Monitor detects new shipped emails
2. Extracts order and tracking information
3. Checks if API submission is enabled
4. Submits orders with tracking to API
5. Displays submission results

#### main.py
**Changes:**
- Added Settings menu option (option 5)
- Created `show_settings_menu()` method
- Integrated API configuration toggle
- Added API status display

**New Menu Structure:**
```
1. Best Buy
2. Amazon
3. Both Services
4. Continuous Monitor
5. Settings  ← NEW
q. Cancel
```

**Settings Submenu:**
```
1. Toggle API Submission (Currently: ENABLED/DISABLED)
2. Configure API Settings
3. Back to Main Menu
```

#### email_processing/parsers/bb_parser.py
**Changes:**
- Modified `extract_shipping_address()` to return full state + ZIP
- Previously returned only state code (e.g., "CA")
- Now returns full string (e.g., "CA 90210")
- Enables ZIP code extraction for buying group mapping

#### requirements.txt
**Changes:**
- Added `requests>=2.31.0` for HTTP API calls

## Configuration

### api/api_config.json

```json
{
    "api_url": "http://localhost:8000",
    "api_key": "your-secret-api-key-here",
    "enabled": false,
    "zip_to_buying_group": {
        "10001": "BuyingGroup",
        "90001": "RiveeDeals"
    },
    "state_to_buying_group": {
        "NY": "BuyingGroup",
        "CA": "RiveeDeals"
    }
}
```

### Configuration Options

| Option | Description | Example |
|--------|-------------|---------|
| `api_url` | FastAPI backend base URL | `http://localhost:8000` |
| `api_key` | Authentication key | `your-secret-api-key` |
| `enabled` | Enable/disable submission | `true` or `false` |
| `zip_to_buying_group` | ZIP to group mappings (priority) | `{"10001": "BuyingGroup"}` |
| `state_to_buying_group` | State to group mappings (fallback) | `{"NY": "BuyingGroup"}` |

## How to Use

### Initial Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure API Settings**
   Edit `api/api_config.json`:
   - Set your `api_url` (FastAPI backend URL)
   - Set your `api_key` (must match backend)
   - Add ZIP code mappings to `zip_to_buying_group`

3. **Enable API Submission**
   - Run BBOS: `python main.py`
   - Select option 5 (Settings)
   - Select option 1 (Toggle API Submission)
   - Confirm it shows "ENABLED"

### Running with API Submission

1. **Start Continuous Monitor**
   - Run BBOS: `python main.py`
   - Select option 4 (Continuous Monitor)
   - Select email profile and folder

2. **Monitor Operation**
   The monitor will automatically:
   - Detect new shipped emails
   - Extract order and tracking info
   - Submit to API if tracking exists
   - Display submission results

### Example Output

```
🚚 FOUND 2 ORDER SHIPMENT(S)!
  📮 Order #BB123456 - SHIPPED (Tracking: 1Z999AA10123456784)
  📮 Order #BB789012 - SHIPPED (Tracking: 9400111899223344556677)

📡 Submitting 2 order(s) to API...
✅ API Submission: Submitted 2 tracking numbers from 2 orders
```

## API Payload Format

Each tracking number is submitted individually:

```json
{
    "website": "bestbuy",
    "order_id": "BB123456789",
    "tracking_number": "1Z999AA10123456784",
    "carrier": "UPS",
    "purchase_datetime": "2024-01-15T10:30:00",
    "total_amount": 299.99,
    "buying_group": "BuyingGroup",
    "metadata": {
        "source": "bbos_continuous_monitor",
        "zip_code": "10001",
        "state_code": "NY"
    }
}
```

## Buying Group Assignment Logic

The system uses a two-tier priority system:

1. Extract ZIP code and state code from order's state field
2. **Check ZIP mapping first**: Look up ZIP code in `zip_to_buying_group`
   - If found, use that buying group
3. **Fallback to state mapping**: If no ZIP match, look up state code in `state_to_buying_group`
   - If found, use that buying group
4. **Skip submission**: If neither ZIP nor state match, order is NOT submitted

**Example 1 (ZIP Match - Priority):**
- Order ships to "CA 90210"
- ZIP extracted: "90210", State extracted: "CA"
- Config has: `"90210": "RiveeDeals"` in ZIP mapping
- Result: Buying group = "RiveeDeals" (ZIP takes priority)

**Example 2 (State Fallback):**
- Order ships to "NY 10999"
- ZIP extracted: "10999", State extracted: "NY"
- Config has: No ZIP match, but `"NY": "BuyingGroup"` in state mapping
- Result: Buying group = "BuyingGroup" (state fallback)

**Example 3 (No Match - Skip):**
- Order ships to "WA 98001"
- ZIP extracted: "98001", State extracted: "WA"
- Config has: No ZIP match, no state match
- Result: Order NOT submitted (no buying group assigned)

## Carrier Detection Logic

The system automatically detects carriers:

| Carrier | Pattern | Example |
|---------|---------|---------|
| UPS | 1Z + 16 chars | 1Z999AA10123456784 |
| FedEx | 12-15 digits | 123456789012 |
| USPS | 20-22 digits or 92/93/94 prefix | 9400111899223344556677 |
| Amazon | TBA + 12 digits | TBA123456789012 |
| Undetermined | No match | CUSTOM12345 |

## Features

### Duplicate Prevention
- Tracks submitted orders in session
- Prevents resubmission of same tracking number
- Key: `{order_number}_{tracking_number}`

### Error Handling
- Connection timeouts (10 seconds)
- HTTP error responses
- Invalid payloads
- Missing configuration

### Multi-Order Support
- Processes multiple orders in batch
- Individual tracking per request
- Aggregate success reporting

### Real-Time Feedback
- Shows submission status immediately
- Displays success/failure per order
- Shows total submitted count

## Troubleshooting

### Issue: API Submission Not Working

**Check:**
1. Is API enabled? (Settings menu shows "ENABLED")
2. Is API URL correct in `api_config.json`?
3. Is API key set correctly?
4. Is FastAPI backend running?
5. Do orders have tracking numbers?

### Issue: Wrong Buying Group

**Check:**
1. Are ZIP and state codes being extracted? (Check console output)
2. Add ZIP code mapping to `zip_to_buying_group` (takes priority)
3. Add state code mapping to `state_to_buying_group` (fallback)
4. Remember: ZIP takes priority over state

### Issue: Orders Not Being Submitted

**Check:**
1. Do orders have tracking numbers? (Only shipped orders are submitted)
2. Is ZIP or state code mapped in configuration?
3. Orders without matching ZIP or state will NOT submit

### Issue: Carrier Shows "Undetermined"

**Reason:**
- Tracking number doesn't match known patterns
- This is normal for custom carriers

**Solution:**
- Orders still submit successfully
- Backend can handle "Undetermined" carrier

### Issue: Connection Errors

**Check:**
1. Is backend accessible? (Try: `curl http://localhost:8000/health`)
2. Is firewall blocking connections?
3. Is URL using correct protocol (http/https)?

## Security Considerations

1. **API Key Protection**
   - Keep `api_config.json` secure
   - Don't commit API key to version control
   - Use environment variables in production

2. **Network Security**
   - Use HTTPS in production
   - Restrict API access by IP
   - Implement rate limiting

3. **Data Privacy**
   - Only tracking numbers are submitted
   - Personal info stays local
   - Backend should encrypt data

## Advanced Usage

### Custom ZIP Mappings

Add specific ZIP ranges to different groups:

```json
"zip_to_buying_group": {
    "10001": "GroupNYC",
    "10002": "GroupNYC",
    "90001": "GroupLA",
    "90002": "GroupLA",
    "30301": "GroupATL"
}
```

### Multiple Backend URLs

To switch backends, just change `api_url`:

```json
"api_url": "https://production-api.example.com"
```

### Temporary Disable

Quick disable without losing config:

```json
"enabled": false
```

## Technical Details

### Dependencies
- `requests>=2.31.0`: HTTP client for API calls
- Python 3.7+: Required for type hints and dataclasses

### API Endpoint
- Method: `POST`
- Endpoint: `/bestbuy/submit-order`
- Headers: `X-API-Key`, `Content-Type: application/json`
- Timeout: 10 seconds

### Session Tracking
- Submitted orders stored in memory
- Cleared when application restarts
- Prevents duplicate submissions per session

## Integration Points

### 1. Continuous Monitor → API
- `continuous_monitor.py` calls API submission
- Only for shipped orders with tracking
- Happens automatically in monitoring loop

### 2. Settings Menu → Configuration
- `main.py` provides UI for toggling
- Reads/writes `api_config.json`
- Shows current status

### 3. Parser → ZIP Extraction
- `bb_parser.py` extracts state + ZIP
- Returns full string for parsing
- Enables buying group mapping

## Future Enhancements

Possible future additions:
- Amazon order support
- Retry failed submissions
- Submission history log
- Multiple buying group per order
- Custom carrier mappings
- Webhook notifications
- Submission queue with persistence

## Support

For issues or questions:
1. Check `api/README.md` for detailed documentation
2. Review console output for error messages
3. Verify configuration in `api_config.json`
4. Test API connectivity manually with curl
5. Check FastAPI backend logs

## Summary

This implementation provides seamless integration with your FastAPI backend, automatically submitting tracking numbers as they're detected. The system is:

- **Automatic**: Works in continuous monitoring mode
- **Configurable**: Easy JSON-based configuration
- **Smart**: Detects carriers and maps buying groups
- **Reliable**: Handles errors and prevents duplicates
- **User-Friendly**: Toggle on/off via settings menu
- **Documented**: Comprehensive README and guides

The feature is designed to be optional and non-intrusive - it can be easily enabled or disabled without affecting the rest of the application.

