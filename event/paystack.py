# event/paystack.py

import hashlib
import hmac
import requests
import uuid

from decimal import Decimal
from django.conf import settings


PAYSTACK_BASE_URL = "https://api.paystack.co"


# ============================================================
# COMMON HEADERS
# ============================================================

def paystack_headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


# ============================================================
# PLATFORM FEE
# ============================================================

def calculate_platform_charge(amount: Decimal) -> Decimal:
    """
    Monieplug platform fee.

    < ₦10,000      = ₦150
    < ₦500,000     = ₦200
    >= ₦500,000    = ₦250
    """

    amount = Decimal(amount)

    if amount < Decimal("10000"):
        return Decimal("150")

    if amount < Decimal("500000"):
        return Decimal("200")

    return Decimal("250")


# ============================================================
# WEBHOOK SIGNATURE
# ============================================================

def verify_paystack_signature(request):
    """
    Verify Paystack webhook signature using HMAC-SHA512.
    """

    signature = request.headers.get(
        "x-paystack-signature"
    )

    if not signature:
        return False

    expected_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        request.body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(
        signature,
        expected_signature,
    )


# ============================================================
# CREATE GUEST PAY-WITH-TRANSFER CHARGE
# ============================================================

def create_paystack_guest_charge(
    email,
    amount,
    reference,
    expires_at,
    metadata=None,
):
    """
    Create a Paystack Pay-with-Transfer charge.

    amount is supplied in NGN.
    Paystack receives the amount in kobo.
    """

    payload = {
        "email": email,
        "amount": int(
            Decimal(amount) * Decimal("100")
        ),
        "currency": "NGN",
        "reference": reference,
        "bank_transfer": {
            "account_expires_at": expires_at,
        },
        "metadata": metadata or {},
    }

    try:

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/charge",
            json=payload,
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": (
                f"Paystack connection failed: {str(exc)}"
            ),
        }

    except ValueError:

        return {
            "success": False,
            "message": (
                "Invalid response received from Paystack."
            ),
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to create Paystack payment.",
            ),
            "response": data,
        }

    return {
        "success": True,
        "data": data.get("data", {}),
    }


# ============================================================
# VERIFY CUSTOMER PAYMENT
# ============================================================

def verify_paystack_transaction(reference):
    """
    Verify a Paystack customer transaction.
    """

    try:

        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": str(exc),
        }

    except ValueError:

        return {
            "success": False,
            "message": "Invalid response from Paystack.",
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to verify transaction.",
            ),
            "response": data,
        }

    return {
        "success": True,
        "data": data.get("data", {}),
    }


# ============================================================
# CREATE PAYSTACK TRANSFER RECIPIENT
# ============================================================

def create_paystack_recipient(
    name,
    account_number,
    bank_code,
):
    """
    Create a Paystack NUBAN transfer recipient.

    The returned recipient_code should be saved against
    the organizer and reused for future payouts.
    """

    payload = {
        "type": "nuban",
        "name": name,
        "account_number": str(account_number),
        "bank_code": str(bank_code),
        "currency": "NGN",
    }

    try:

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transferrecipient",
            json=payload,
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": (
                f"Paystack connection failed: {str(exc)}"
            ),
        }

    except ValueError:

        return {
            "success": False,
            "message": (
                "Invalid response from Paystack."
            ),
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to create Paystack recipient.",
            ),
            "response": data,
        }

    recipient_data = data.get("data") or {}

    return {
        "success": True,
        "data": recipient_data,
        "recipient_code": recipient_data.get(
            "recipient_code"
        ),
    }


# ============================================================
# FETCH PAYSTACK TRANSFER RECIPIENT
# ============================================================

def get_paystack_recipient(recipient_code):
    """
    Fetch an existing Paystack transfer recipient.
    """

    try:

        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transferrecipient/"
            f"{recipient_code}",
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": str(exc),
        }

    except ValueError:

        return {
            "success": False,
            "message": "Invalid response from Paystack.",
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to fetch Paystack recipient.",
            ),
            "response": data,
        }

    return {
        "success": True,
        "data": data.get("data", {}),
    }


# ============================================================
# CREATE ORGANIZER PAYOUT
# ============================================================

def create_paystack_transfer(
    recipient_code,
    amount,
    reference,
    reason,
):
    """
    Transfer money from Monieplug's Paystack balance
    to an organizer's Paystack recipient.

    amount is supplied in NGN.
    Paystack expects kobo.
    """

    amount = Decimal(amount)

    if amount <= Decimal("0"):
        return {
            "success": False,
            "message": "Transfer amount must be greater than zero.",
        }

    payload = {
        "source": "balance",
        "amount": int(
            amount * Decimal("100")
        ),
        "recipient": recipient_code,
        "reference": reference,
        "reason": str(reason)[:100],
        "currency": "NGN",
    }

    try:

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transfer",
            json=payload,
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": (
                f"Paystack transfer connection failed: {str(exc)}"
            ),
        }

    except ValueError:

        return {
            "success": False,
            "message": (
                "Invalid transfer response from Paystack."
            ),
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to initiate organizer payout.",
            ),
            "response": data,
        }

    transfer_data = data.get("data") or {}

    return {
        "success": True,
        "data": transfer_data,
        "transfer_reference": transfer_data.get(
            "reference",
            reference,
        ),
        "transfer_code": transfer_data.get(
            "transfer_code"
        ),
        "transfer_status": transfer_data.get(
            "status"
        ),
    }


# ============================================================
# VERIFY ORGANIZER PAYOUT
# ============================================================

def verify_paystack_transfer(reference):
    """
    Verify the current status of a Paystack transfer.
    """

    try:

        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transfer/verify/{reference}",
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": str(exc),
        }

    except ValueError:

        return {
            "success": False,
            "message": "Invalid transfer response from Paystack.",
        }

    if not response.ok or not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to verify Paystack transfer.",
            ),
            "response": data,
        }

    return {
        "success": True,
        "data": data.get("data", {}),
    }