# Quick Start: FastAPI Integration

## What This Does

Automatically submits Best Buy order tracking numbers to your FastAPI backend when new shipped orders are detected in continuous monitoring mode.

## Quick Setup (3 Steps)

### 1. Install Requirements
```bash
pip install -r requirements.txt
```

### 2. Configure API
Edit `api/api_config.json`:
```json
{
    "api_url": "http://localhost:8000",
    "api_key": "your-actual-api-key",
    "enabled": true,
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

**Important:** Replace `your-actual-api-key` with your real API key!

### 3. Enable in BBOS
```
python main.py
→ Select "5. Settings"
→ Select "1. Toggle API Submission"
→ Verify it shows "ENABLED"
→ Select "3. Back to Main Menu"
```

## Usage

Run continuous monitoring as normal:
```
python main.py
→ Select "4. Continuous Monitor"
→ Select your email profile
→ Select email folder
```

When new shipped orders are detected, tracking numbers will automatically submit to your API!

## What Gets Submitted

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
        "zip_code": "10001"
    }
}
```

## How It Works

1. **Continuous Monitor** detects shipped email
2. **Extracts** order number, tracking, date, price
3. **Detects Carrier** from tracking number pattern
4. **Maps Buying Group** from ZIP code
5. **Submits to API** at `/bestbuy/submit-order`
6. **Shows Result** in console

## Carrier Detection (Automatic)

- **UPS**: 1Z999AA10123456784
- **FedEx**: 123456789012
- **USPS**: 9400111899223344556677
- **Amazon**: TBA123456789012
- **Undetermined**: Unknown format

## Buying Group Mapping

The system uses a two-tier mapping system:

### ZIP Code Mapping (Priority)
```json
"zip_to_buying_group": {
    "10001": "BuyingGroup",
    "10002": "BuyingGroup",
    "90001": "RiveeDeals",
    "90002": "RiveeDeals"
}
```

### State Code Mapping (Fallback)
```json
"state_to_buying_group": {
    "NY": "BuyingGroup",
    "CA": "RiveeDeals",
    "TX": "BuyingGroup"
}
```

**Logic:**
- ZIP code is checked first
- If no ZIP match, state code is used as fallback
- If neither match, order is NOT submitted

## Console Output Example

```
🚚 FOUND 1 ORDER SHIPMENT(S)!
  📮 Order #BB123456 - SHIPPED (Tracking: 1Z999AA10123456784)

📡 Submitting 1 order(s) to API...
✅ API Submission: Submitted 1 tracking numbers from 1 orders
```

## Toggle On/Off Anytime

**Via Settings Menu:**
```
Main Menu → 5. Settings → 1. Toggle API Submission
```

**Via Config File:**
```json
"enabled": false
```

## Troubleshooting

### Not submitting?
- Check `enabled: true` in `api_config.json`
- Verify API key is correct
- Ensure FastAPI backend is running
- Check orders have tracking numbers

### Wrong buying group?
- Add ZIP code to `zip_to_buying_group` (takes priority)
- Add state code to `state_to_buying_group` (fallback)

### Orders not submitting?
- Check if ZIP or state is mapped in config
- Orders without a matching ZIP or state won't submit

### Connection errors?
- Verify `api_url` is correct
- Test: `curl http://localhost:8000/health`
- Check firewall settings

## Files Created

```
api/
├── __init__.py              # Package file
├── submitter.py             # Submission logic
├── api_config.json          # Your configuration
└── README.md                # Full documentation
```

## Documentation

- **Full Guide**: `docs/API_INTEGRATION.md`
- **API Module**: `api/README.md`
- **This Guide**: `docs/QUICK_START_API.md`

## Important Notes

1. Only orders with tracking numbers are submitted
2. Duplicate submissions are prevented per session
3. All orders default to website: "bestbuy"
4. Feature is optional - disable anytime
5. Works only in continuous monitoring mode
6. Requires FastAPI backend to be running

## Security

- Keep your API key secret
- Use HTTPS in production
- Don't commit `api_config.json` with real keys
- Restrict backend access by IP

## Need Help?

See full documentation: `api/README.md` or `docs/API_INTEGRATION.md`

