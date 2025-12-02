## Amazon Order Email Integration Summary

### Overview
This document outlines the data that must be scraped from Amazon order confirmation emails and how to handle single-item and multi-item orders.

### Email Identification
- **From**: `auto-confirm@amazon.com`
- **Subject pattern**: Contains the word **"Ordered"**, typically in the form `Ordered: {COUNT} "{PRODUCT_TITLE}..."`.

### Data Extraction Requirements

#### 1. Email Metadata
- **Recipient Email**: The `To` address the email was sent to. This must be recorded for every processed email.

#### 2. Order-Level Information
- **Order Number**: Text following `Order #` in the header section (e.g., `111-3244578-8337005`).
- **Arrival Text**: Short status line such as `Arriving Monday`, `Arriving Tuesday`, etc.
- **Recipient/Location Line**: Full text inside the bolded line after the arrival text (e.g., `Rafid - New Castle, DE`).
- **Order Detail Link ("View or edit order")**: The `href` from the primary button link with visible text `View or edit order`. This is the canonical order-details URL (Amazon domain, with `order-details?orderID=...`).

#### 3. Item-Level Information (Single and Multiple Items)
For each product block associated with the order (there may be one or many):
- **Item Title**: Text content of the product title link (e.g., `Apple 2024 Mac mini Desktop Compu...`).
- **Item Page URL**: The `href` of the product title link (Amazon `dp` URL, possibly with tracking parameters).
- **Quantity**: Text in the `Quantity: {N}` line.
- **Item Price**: The item price displayed under the quantity (e.g., `$479.00`, `$429.99`), normalized to a numeric value and currency (USD).

Multi-item emails are represented by multiple repeated product sections that share the same order header (`Arriving {DAY}`, recipient/location line, and `Order #`). The parser must:
- Collect **all** such product sections for that header.
- Emit a separate line item record for each product, all tied to the same order number and email metadata.

#### 4. Price Summary
- **Grand Total**: The value from the row where the left cell text is `Grand Total:` and the right cell contains the bolded amount (e.g., `$1,437.00`). This should be parsed as a numeric amount and currency (USD).

### Handling Multiple Items Example
In emails where multiple items are listed under the same `Arriving {DAY}` and `Order #` block:
- Treat the shared header section (arrival text, recipient/location, order number, `View or edit order` link, and `Grand Total`) as order-level data.
- Iterate over each repeated product item block:
  - Extract that item's title, product URL, quantity, and price.
  - Associate each extracted item with the same order number and recipient email.

### Parsing Method (Python)

#### Input Shape
- Raw email object providing:
  - Headers: `From`, `To`, `Subject`
  - HTML body as a string
- Use `BeautifulSoup(html_body, "lxml")` or `"html.parser"` to build `soup`.

#### Email Metadata
- Recipient email: read directly from the `To` header, normalize to a single address string, and attach to every parsed record for this email.

#### Order-Level Parsing
- Order number:
  - Search the HTML for text containing `Order #`.
  - From the matching element, extract the text following `Order #` and normalize by stripping whitespace and non-order characters.
  - If not found in HTML, fall back to a regex on the subject line to capture the `ORDER-ID` pattern with dashes.
- Arrival text:
  - Locate the heading element in the header block whose text starts with `Arriving `.
  - Normalize whitespace and store the full string (for example `Arriving Monday`).
- Recipient/location line:
  - From the same header section, find the bold line immediately following the arrival text and read its full text content (for example `Rafid - New Castle, DE`).
- View or edit order link:
  - Find the `<a>` tag whose visible text, stripped of whitespace, equals `View or edit order`.
  - Read its `href` attribute and keep the full Amazon order-details URL.

#### Item-Level Parsing
- Identify product blocks by locating the product title anchors linking to Amazon product pages:
  - Search for `<a>` tags whose `href` contains `/dp/` and which are inside the main order content area.
  - For each such anchor:
    - Item title: use the anchor text, normalized (strip whitespace and trailing ellipsis handling as configured).
    - Item page URL: store the full `href` value.
    - Quantity: from the nearby text row containing `Quantity:`, extract the integer that follows.
    - Item price: from the nearby price row in the same item block, extract the amount string, strip currency symbols and commas, and convert to a numeric value.
- Treat each detected product block as one line item; in multi-item emails, iterate over all such blocks in the order section.

#### Price Summary Parsing
- Grand total:
  - Search for a `<td>` element whose text, normalized, equals `Grand Total:`.
  - From the same table row, take the sibling `<td>` on the right side that holds the bolded amount.
  - Clean the string by removing currency symbols, spaces, and thousand separators, then convert to a numeric type while storing `"USD"` as the currency.

#### Record Construction
- Build an order object containing:
  - Recipient email, order number, arrival text, recipient/location, view-or-edit-order URL, and grand total.
- Build one item object per product block containing:
  - Item title, item URL, quantity, item price, and a foreign key reference to the order number (and recipient email if needed).
- Ensure that for multi-item emails all item objects share the same order-level fields derived from the header and price summary sections.

### Cancelled Order Emails

#### Email Identification
- **From**: `qla@amazon.com`, `order-update@amazon.com`
- **Subject pattern**: May include the order number and cancellation wording (for example, `Your Amazon.com order 111-7348074-5996208 was canceled`). The order ID can appear in either the subject or the body.

#### Data Extraction Requirements
- **Recipient Email ("sent to")**: The `To` address for the email. This is the primary identity field for who the cancellation applies to.
- **Order Number**:
  - First, attempt to extract from the subject line using a regex that matches Amazon-style order IDs.
  - If not present in the subject, search the HTML/text body using a regex.
  - Use a pattern that matches IDs like `111-7348074-5996208`, for example:

```python
order_id_pattern = r"\b\d{3}-\d{7}-\d{7}\b"
```

#### Record Construction
- For cancelled-order emails, record at minimum:
  - Recipient email (`To`)
  - Order number (from subject or body via regex)
- Optionally attach additional metadata such as cancellation timestamp or subject text, but no item-level details are required.

### Shipped Order Emails

#### Email Identification
- **From**: `shipment-tracking@amazon.com`
- **Subject pattern**: Standard Amazon shipment notifications (for example, variations of "Your package is arriving" or "Your Amazon.com order has shipped").

#### Data Extraction Requirements

##### 1. Email Metadata
- **Recipient Email ("sent to")**: The `To` address. This must be stored for every shipped-order email.

##### 2. Order-Level Information
- **Arrival Text**: The status line such as `Arriving tomorrow`, taken from the heading block near the top of the email.
- **Recipient/Location Line**: The bolded line directly under the arrival text (for example, `Rafid - Nashua, NH`).
- **Order Number**: Text following `Order #` in the same block (for example, `112-5277767-5017059`). Normalize by stripping whitespace.
- **Track Package Link**: The `href` of the primary button with visible text `Track package`. This is the canonical tracking/progress URL.

##### 3. Item-Level Information
For each product block under the shipped-order section:
- **Item Title**: Text content of the product title link.
- **Item Page URL**: The `href` of the title link (Amazon `dp` URL).
- **Quantity**: Text such as `Quantity: 2` in the item block, parsed to an integer.
- **Item Price**: Monetary amount shown under the quantity, normalized to a numeric value and currency (USD).

##### 4. Price Summary
- **Total**: From the summary row where the left cell text is `Total` and the right cell contains the bolded total amount (for example, `$1,395.00`). Strip currency symbols and separators and store as a numeric value with `"USD"` currency.

#### Record Construction
- Build a shipped-order object containing:
  - Recipient email, order number, arrival text, recipient/location, track-package URL, and total.
- Build one shipped-item object per product block containing:
  - Item title, item URL, quantity, item price, and a foreign key reference to the shipped-order record.
- Ensure that for multi-item shipments, all item objects share the same order-level fields.


