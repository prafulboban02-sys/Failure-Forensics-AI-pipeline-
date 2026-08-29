"""
Generates a small set of synthetic business documents, each deliberately
engineered to trigger a specific, known failure mode. This is what makes
the demo credible: you know the ground-truth failure, so you can verify
the root-cause analyzer (Phase 3) actually finds it.

Run: python data/sample_docs/generate_samples.py
"""

import os

SAMPLES = {
    "clean_invoice.txt": """
INVOICE #INV-2026-0417
Date: March 12, 2026
Bill To: Meridian Logistics Pvt Ltd
From: Aster Manufacturing Co.

Item: Industrial packaging units x 500
Unit Price: $42.00
Total Amount: $21,000.00
Currency: USD
Payment Terms: Net 30
""".strip(),

    "missing_date_invoice.txt": """
INVOICE #INV-2026-0418
Bill To: Northfield Retail Group
From: Aster Manufacturing Co.

Item: Warehouse shelving units x 120
Unit Price: $185.50
Total Amount: $22,260.00
Currency: USD
Payment Terms: Net 45

Note: dispatch date to be confirmed post inspection.
""".strip(),  # FAILURE MODE: no clear invoice date -> extraction should flag empty dates[]

    "ambiguous_category_doc.txt": """
AGREEMENT & PURCHASE CONFIRMATION #DOC-9921

This document confirms the purchase order raised by Coastline Retailers for
Q3 stock, AND serves as the binding service contract governing delivery
penalties, warranty terms, and dispute resolution for the same order.

Total commitment: $58,400.00
Currency: USD
Effective Date: April 2, 2026
""".strip(),  # FAILURE MODE: reads as BOTH purchase_order and contract -> classification should be ambiguous

    "currency_mismatch_receipt.txt": """
RECEIPT #RCPT-77210
Date: 5 May 2026
Received From: Bramwell & Co.
Amount Paid: 15,000
Currency Symbol on Stamp: EUR
Amount in Words: Fifteen thousand US Dollars

Payment method: Wire Transfer
""".strip(),  # FAILURE MODE: currency symbol says EUR but amount-in-words says USD

    "garbled_scan_artifact.txt": """
P U R C H A S E   O R D E R
Ref: ###-INVALID-OCR-4471###

[unreadable header]  qty: ?? unit: ??  amt: 4,,200..00  curr: US D
Vendor:  <<name not captured>>
Delivery window: TBD // TBD // 2026
""".strip(),  # FAILURE MODE: OCR-like garbage -> should push extraction confidence very low
}


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    for filename, content in SAMPLES.items():
        path = os.path.join(out_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
