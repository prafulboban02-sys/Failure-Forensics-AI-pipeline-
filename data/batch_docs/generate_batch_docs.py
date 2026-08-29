"""
Phase 6: generates 50 documents for a realistic-scale demo run.

~39 "normal" documents across all 4 types (varied vendors/amounts/dates --
no deliberately injected issue, though as we've already measured, even
"clean" documents organically hallucinate at a real, non-trivial rate).

11 documents each engineered with a DIFFERENT failure mode from the
original 5 -- for genuine diversity of failure categories, not just more
copies of the same bug.

Run: python data/batch_docs/generate_batch_docs.py
"""

import os

VENDORS = [
    "Aster Manufacturing Co.", "Bramwell & Co.", "Coastline Retailers",
    "Delacroix Supply Chain", "Everwood Timber Ltd", "Falkner Industrial",
    "Greenridge Logistics", "Hanover Textiles", "Ironclad Fabrication",
    "Juniper Freight Services", "Kestrel Components", "Lattimore Wholesale",
]
BUYERS = [
    "Meridian Logistics Pvt Ltd", "Northfield Retail Group", "Oakhurst Trading Co.",
    "Pinecrest Distributors", "Quarrystone Holdings", "Riverside Import/Export",
    "Sable Point Retail", "Thornbury Supplies", "Underwood Partners",
    "Vantage Point Logistics", "Westgate Commerce", "Yellowbrook Traders",
]
ITEMS = [
    ("Industrial packaging units", 500, 42.00), ("Warehouse shelving units", 120, 185.50),
    ("Steel fasteners (bulk)", 2000, 0.85), ("Commercial refrigeration units", 8, 1450.00),
    ("Office furniture sets", 40, 320.00), ("Safety equipment kits", 150, 65.00),
    ("Conveyor belt segments", 25, 210.00), ("Loading dock pallets", 300, 18.50),
    ("Industrial cleaning supplies", 80, 44.00), ("Electrical wiring (bulk)", 1000, 2.10),
]
CURRENCIES = ["USD", "EUR", "GBP"]

_normal_count = 0


def _next_ref(prefix):
    global _normal_count
    _normal_count += 1
    return f"{prefix}-2026-{1000 + _normal_count}"


def normal_invoice(vendor, buyer, item, qty, price, currency, date):
    total = qty * price
    return f"""
INVOICE #{_next_ref('INV')}
Date: {date}
Bill To: {buyer}
From: {vendor}

Item: {item} x {qty}
Unit Price: {price:.2f}
Total Amount: {total:,.2f}
Currency: {currency}
Payment Terms: Net 30
""".strip()


def normal_contract(vendor, buyer, item, date):
    return f"""
SERVICE AGREEMENT #{_next_ref('CTR')}
Effective Date: {date}
Party A: {vendor}
Party B: {buyer}

This agreement governs the supply of {item} under standard commercial
terms, including delivery schedules, warranty obligations, and dispute
resolution procedures as set forth in Schedule A.

Term: 12 months, renewable.
""".strip()


def normal_receipt(vendor, buyer, amount, currency, date):
    return f"""
RECEIPT #{_next_ref('RCPT')}
Date: {date}
Received From: {buyer}
Paid To: {vendor}
Amount Paid: {amount:,.2f}
Currency: {currency}
Payment Method: Bank Transfer
""".strip()


def normal_purchase_order(vendor, buyer, item, qty, price, date):
    total = qty * price
    return f"""
PURCHASE ORDER #{_next_ref('PO')}
Date: {date}
Vendor: {vendor}
Ordered By: {buyer}

Item: {item}
Quantity: {qty}
Unit Price: {price:.2f}
Total: {total:,.2f}
Requested Delivery: within 21 days
""".strip()


# --- 11 documents, each a DIFFERENT failure mode (beyond the original 5) ---

FAILURE_DOCS = {
    "dup_reference_numbers.txt": """
INVOICE #INV-2026-9001
Also referenced as Order Confirmation #PO-2026-4471 (see attached PO).
Date: June 3, 2026
Bill To: Sable Point Retail
From: Ironclad Fabrication

Item: Custom steel brackets x 300
Unit Price: 12.50
Total Amount: 3,750.00
Currency: USD
Note: Please quote invoice number INV-2026-9002 on all correspondence.
""".strip(),  # FAILURE: three different reference numbers for one document

    "math_error_total.txt": """
INVOICE #INV-2026-9002
Date: June 5, 2026
Bill To: Thornbury Supplies
From: Kestrel Components

Item: Precision bearings x 400
Unit Price: 3.75
Total Amount: 2,200.00
Currency: USD
Payment Terms: Net 15
""".strip(),  # FAILURE: 400 * 3.75 = 1500, not 2200 -- arithmetic doesn't match

    "contradictory_dates.txt": """
PURCHASE ORDER #PO-2026-9003
Order Date: July 20, 2026
Vendor: Lattimore Wholesale
Ordered By: Vantage Point Logistics

Item: Loading dock pallets x 250
Unit Price: 18.50
Total: 4,625.00
Requested Delivery Date: July 5, 2026
""".strip(),  # FAILURE: delivery date is BEFORE the order date

    "foreign_language_snippet.txt": """
INVOICE #INV-2026-9004
Date: August 1, 2026
Bill To: Westgate Commerce
From: Juniper Freight Services

Item: Freight handling services x 1
Unit Price: 5400.00
Total Amount: 5,400.00
Currency: EUR

Note: Livraison prevue sous 10 jours ouvres, sauf cas de force majeure.
Payment Terms: Net 30
""".strip(),  # FAILURE: a French note embedded in an otherwise English document

    "truncated_document.txt": """
PURCHASE ORDER #PO-2026-9005
Date: August 4, 2026
Vendor: Greenridge Logistics
Ordered By: Riverside Import/Export

Item: Commercial refrigeration units x 6
Unit Price: 1450
""".strip(),  # FAILURE: cuts off mid-document, no total, no delivery terms

    "extreme_amount.txt": """
INVOICE #INV-2026-9006
Date: August 6, 2026
Bill To: Oakhurst Trading Co.
From: Falkner Industrial

Item: Custom industrial equipment x 1
Unit Price: 9875000.00
Total Amount: 9,875,000.00
Currency: USD
Payment Terms: Net 60
""".strip(),  # FAILURE: suspiciously large amount, should be flagged as a risk

    "conflicting_type_signals.txt": """
INVOICE #DOC-2026-9007
Date: August 8, 2026

This Purchase Order is issued by Underwood Partners to procure the goods
described below from Hanover Textiles. Upon delivery and acceptance,
this document also serves as the binding receipt of payment.

Item: Commercial-grade textiles x 600
Unit Price: 8.20
Total: 4,920.00
Currency: USD
""".strip(),  # FAILURE: header says "INVOICE", body says "Purchase Order", also claims to be a receipt

    "missing_vendor_entirely.txt": """
INVOICE #INV-2026-9008
Date: August 10, 2026
Bill To: Pinecrest Distributors

Item: Assorted office supplies x 200
Unit Price: 6.50
Total Amount: 1,300.00
Currency: USD
Payment Terms: Net 30
""".strip(),  # FAILURE: no "From" / vendor field anywhere in the document

    "duplicate_line_items.txt": """
PURCHASE ORDER #PO-2026-9009
Date: August 12, 2026
Vendor: Everwood Timber Ltd
Ordered By: Quarrystone Holdings

Item: Warehouse shelving units x 120, Unit Price 185.50, Subtotal 22,260.00
Item: Warehouse shelving units x 120, Unit Price 178.00, Subtotal 21,360.00
Total: 22,260.00
""".strip(),  # FAILURE: same line item listed twice with two different prices

    "currency_symbol_only.txt": """
RECEIPT #RCPT-2026-9010
Date: August 14, 2026
Received From: Yellowbrook Traders
Paid To: Delacroix Supply Chain
Amount Paid: £4,850
Payment Method: Wire Transfer
""".strip(),  # FAILURE: currency given only as a symbol, no explicit currency code anywhere

    "negative_amount.txt": """
INVOICE #INV-2026-9011
Date: August 16, 2026
Bill To: Sable Point Retail
From: Coastline Retailers

Item: Return credit -- packaging units x 50
Unit Price: 42.00
Total Amount: -2,100.00
Currency: USD
Note: This is a credit memo against Invoice INV-2026-0417.
""".strip(),  # FAILURE: a negative total (credit memo) -- does the pipeline handle this sanely?
}


def generate_normal_docs():
    docs = {}
    date_pool = [
        "January 14, 2026", "February 3, 2026", "March 22, 2026", "April 9, 2026",
        "May 17, 2026", "June 28, 2026", "July 11, 2026", "August 2, 2026",
        "September 19, 2026", "October 5, 2026", "November 23, 2026", "December 8, 2026",
    ]
    idx = 0
    # 15 invoices
    for i in range(15):
        vendor = VENDORS[i % len(VENDORS)]
        buyer = BUYERS[i % len(BUYERS)]
        item, qty, price = ITEMS[i % len(ITEMS)]
        currency = CURRENCIES[i % len(CURRENCIES)]
        date = date_pool[i % len(date_pool)]
        docs[f"normal_invoice_{i+1:02d}.txt"] = normal_invoice(vendor, buyer, item, qty, price, currency, date)
        idx += 1
    # 8 contracts
    for i in range(8):
        vendor = VENDORS[(i + 3) % len(VENDORS)]
        buyer = BUYERS[(i + 3) % len(BUYERS)]
        item, _, _ = ITEMS[(i + 3) % len(ITEMS)]
        date = date_pool[(i + 3) % len(date_pool)]
        docs[f"normal_contract_{i+1:02d}.txt"] = normal_contract(vendor, buyer, item, date)
    # 8 receipts
    for i in range(8):
        vendor = VENDORS[(i + 6) % len(VENDORS)]
        buyer = BUYERS[(i + 6) % len(BUYERS)]
        _, qty, price = ITEMS[(i + 6) % len(ITEMS)]
        amount = qty * price
        currency = CURRENCIES[(i + 1) % len(CURRENCIES)]
        date = date_pool[(i + 6) % len(date_pool)]
        docs[f"normal_receipt_{i+1:02d}.txt"] = normal_receipt(vendor, buyer, amount, currency, date)
    # 8 purchase orders
    for i in range(8):
        vendor = VENDORS[(i + 9) % len(VENDORS)]
        buyer = BUYERS[(i + 9) % len(BUYERS)]
        item, qty, price = ITEMS[(i + 9) % len(ITEMS)]
        date = date_pool[(i + 9) % len(date_pool)]
        docs[f"normal_po_{i+1:02d}.txt"] = normal_purchase_order(vendor, buyer, item, qty, price, date)
    return docs


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    all_docs = {}
    all_docs.update(generate_normal_docs())
    all_docs.update(FAILURE_DOCS)

    for filename, content in all_docs.items():
        path = os.path.join(out_dir, filename)
        with open(path, "w") as f:
            f.write(content)

    print(f"Generated {len(all_docs)} documents in {out_dir}")
    print(f"  - {len(generate_normal_docs())} normal (varied across invoice/contract/receipt/PO)")
    print(f"  - {len(FAILURE_DOCS)} with a distinct engineered failure mode")


if __name__ == "__main__":
    main()
