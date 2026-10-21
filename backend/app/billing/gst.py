"""G3: GST on an invoice (India).

    split(subtotal, buyer_country, buyer_state, seller_state) -> Tax
    valid_gstin(gstin) / state_of(gstin)

18% GST on software services (SAC 998314). A buyer in the seller's state
pays CGST 9% + SGST 9%; a buyer in another Indian state pays IGST 18%; a
buyer outside India is an export of services, zero-rated (0%, under a
letter of undertaking, which the seller must file: SETUP_NEEDED.md).
Amounts are rounded to the paisa; the halves of an intra-state tax are
equal and add up to the whole.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RATE = 0.18
SAC = "998314"
_GSTIN = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# GST state codes (the first two digits of a GSTIN).
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}


@dataclass(frozen=True)
class Tax:
    subtotal: float
    cgst: float
    sgst: float
    igst: float
    total: float
    kind: str              # intra | inter | export

    @property
    def tax(self) -> float:
        return round(self.cgst + self.sgst + self.igst, 2)


def valid_gstin(gstin: str) -> bool:
    gstin = (gstin or "").strip().upper()
    return bool(_GSTIN.match(gstin)) and gstin[:2] in STATES


def state_of(gstin: str) -> str | None:
    gstin = (gstin or "").strip().upper()
    return gstin[:2] if valid_gstin(gstin) else None


def split(subtotal: float, buyer_country: str | None, buyer_state: str | None, seller_state: str) -> Tax:
    subtotal = round(float(subtotal), 2)
    if (buyer_country or "").upper() != "IN":
        return Tax(subtotal, 0.0, 0.0, 0.0, subtotal, "export")
    whole = round(subtotal * RATE, 2)
    if buyer_state and buyer_state == seller_state:
        half = round(whole / 2, 2)
        return Tax(subtotal, half, round(whole - half, 2), 0.0, round(subtotal + whole, 2), "intra")
    return Tax(subtotal, 0.0, 0.0, whole, round(subtotal + whole, 2), "inter")
