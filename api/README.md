# BBOS API Submission Module

This module enables automatic submission of order tracking numbers to a FastAPI backend service.

## Overview

The API submission module automatically sends tracking information for new orders to a centralized FastAPI backend. This is useful for sharing tracking data with buying groups or other systems that need real-time order updates.

## Features

- **Automatic Tracking Submission**: Submits new tracking numbers as they are detected
- **Carrier Detection**: Automatically determines carrier (UPS, FedEx, USPS, Amazon) from tracking number format
- **Buying Group Assignment**: Maps orders to buying groups based on ZIP code
- **Duplicate Prevention**: Tracks submitted orders to avoid duplicate submissions
- **Configurable**: Easy JSON-based configuration
- **Toggle On/Off**: Can be enabled/disabled through the main menu

## Configuration

Edit `api/api_config.json` to configure the module:

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

- **api_url**: The base URL of your FastAPI backend
- **api_key**: Your API authentication key (must match backend)
- **enabled**: Set to `true` to enable automatic submission, `false` to disable
- **zip_to_buying_group**: Map ZIP codes to buying group names (takes priority)
- **state_to_buying_group**: Map state codes to buying group names (fallback if no ZIP match)

## ZIP Code and State to Buying Group Mapping

The system uses a two-tier mapping system with ZIP code priority:

### ZIP Code Mapping (Priority 1)

Add entries to `zip_to_buying_group` to map ZIP codes to specific buying groups:

```json
"zip_to_buying_group": {
    "10001": "BuyingGroup",
    "10002": "BuyingGroup",
    "90001": "RiveeDeals",
    "90002": "RiveeDeals",
    "30301": "BuyingGroup"
}
```

Only the first 5 digits of the ZIP code are used for matching.

### State Code Mapping (Fallback)

Add entries to `state_to_buying_group` for state-level fallback when ZIP is unavailable:

```json
"state_to_buying_group": {
    "NY": "BuyingGroup",
    "CA": "RiveeDeals",
    "TX": "BuyingGroup",
    "FL": "RiveeDeals"
}
```

Use standard 2-letter state abbreviations (e.g., NY, CA, TX).

## Carrier Detection

The module automatically detects carriers based on tracking number patterns:

- **UPS**: 1Z followed by 16 alphanumeric characters
- **FedEx**: 12, 14, or 15 digit numbers
- **USPS**: 20 or 22 digit numbers, or starts with 92/93/94
- **Amazon**: Starts with TBA followed by 12 digits
- **Undetermined**: If pattern doesn't match known formats

## How It Works

1. **Continuous Monitor** detects new shipped orders with tracking numbers
2. **API Submitter** checks if API submission is enabled
3. **ZIP Code & State** are extracted from shipping address (state field)
4. **Buying Group** is determined from ZIP code mapping (priority) or state mapping (fallback)
5. **Skip if no match** - Orders without a matching ZIP or state are not submitted
6. **Carrier** is detected from tracking number format
7. **Order Data** is formatted and sent to FastAPI backend
8. **Duplicate Check** prevents resubmission in the same session

## Enabling/Disabling

### Method 1: Main Menu
1. Run BBOS application
2. Select "Settings" from the main menu
3. Toggle "Submit tracking numbers to API"

### Method 2: Configuration File
Edit `api/api_config.json` and set:
```json
"enabled": true
```

## API Endpoint

The module submits to the `/bestbuy/submit-order` endpoint with this payload:

```json
{
    "website": "bestbuy",
    "order_id": "BB123456789",
    "tracking_number": "1Z2232WW0359868400",
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

## Requirements

- `requests` library (install via `pip install requests`)
- Running FastAPI backend with valid API key
- Network connectivity to the API server

## Troubleshooting

### No Tracking Numbers Submitted
- Check that orders have tracking numbers (only shipped orders are submitted)
- Verify `enabled` is set to `true` in config
- Check that API key is correctly configured

### API Connection Errors
- Verify `api_url` is correct and accessible
- Check that FastAPI backend is running
- Ensure firewall allows connections to API server

### Wrong Buying Group Assignment
- Verify ZIP code and state code are being extracted (check logs)
- Add ZIP code mapping to `zip_to_buying_group` (takes priority)
- Add state code mapping to `state_to_buying_group` (fallback)

### Orders Not Being Submitted
- Check if orders have tracking numbers
- Verify ZIP or state code is mapped in configuration
- Orders without matching ZIP or state will NOT submit

## Security Notes

- Keep your `api_key` secret and secure
- Use HTTPS in production (`https://` URL)
- Restrict API access to trusted IP addresses
- Regularly rotate API keys

## Integration with Continuous Monitor

The API submission is integrated into the continuous monitoring mode. When enabled, tracking numbers are automatically submitted as soon as new shipped emails are detected.

You can monitor submissions in real-time through console output showing:
- Order number
- Tracking numbers submitted
- Buying group assigned
- Submission status

