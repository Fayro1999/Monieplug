import requests
import uuid
import hmac
import hashlib

from decimal import Decimal

from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from decimal import Decimal


class PaystackService:

    BASE_URL = "https://api.paystack.co"

    @classmethod
    def headers(cls):
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

    @classmethod
    def post(cls, endpoint, payload):

        url = f"{cls.BASE_URL}{endpoint}"

        response = requests.post(
            url,
            json=payload,
            headers=cls.headers(),
            timeout=60
        )

        return response.json()

    @classmethod
    def get(cls, endpoint):

        url = f"{cls.BASE_URL}{endpoint}"

        response = requests.get(
            url,
            headers=cls.headers(),
            timeout=60
        )

        return response.json()

            @classmethod
    def verify_signature(cls, request):

        signature = request.headers.get("x-paystack-signature")

        computed = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(),
            request.body,
            hashlib.sha512
        ).hexdigest()

        return signature == computed

            @classmethod
    def verify_payment(cls, reference):

        response = cls.get(
            f"/transaction/verify/{reference}"
        )

        return response

            @classmethod
    def generate_reference(cls):

        return f"TICKET-{uuid.uuid4().hex.upper()}"

        @classmethod
def create_virtual_account(cls, purchase):

    expires_at = (
        timezone.now() + timedelta(minutes=30)
    ).isoformat()

    payload = {

        "email": purchase.email,

        "amount": int(
            Decimal(purchase.total_price) * 100
        ),

        "reference": str(
            purchase.reference_id
        ),

        "bank_transfer": {

            "account_expires_at": expires_at

        }

    }

    return cls.post(
        "/charge",
        payload
    )