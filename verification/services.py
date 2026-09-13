import requests

from django.conf import settings
from django.utils import timezone

from authent.models import User
from .models import Verification


class DojahService:

    BASE_URL = "https://sandbox.dojah.io"

    @classmethod
    def headers(cls):

        return {
            "AppId": settings.DOJAH_APP_ID,
            "Authorization": settings.DOJAH_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def fetch_verification(cls, reference_id):

        url = f"{cls.BASE_URL}/api/v1/kyc/verification"

        print("URL:", url)
        print("Headers:", cls.headers())
        print("Reference ID:", reference_id)

        response = requests.get(
            url,
            headers=cls.headers(),
            params={
                "reference_id": reference_id
            },
            timeout=30,
        )

        print("Status:", response.status_code)
        print("Response:", response.text)

        response.raise_for_status()

        return response.json()
    @classmethod
    def update_verification(cls, reference_id):

        verification = Verification.objects.get(
            reference_id=reference_id
        )

        response = cls.fetch_verification(reference_id)

        verification.raw_response = response

        verification.verification_status = response.get(
            "verification_status",
            "Pending",
        )

        verification.verification_mode = response.get(
            "verification_mode"
        )

        verification.verification_type = response.get(
            "verification_type"
        )

        verification.verification_value = response.get(
            "verification_value"
        )

        verification.selfie_url = response.get(
            "selfie_url"
        )

        verification.id_url = response.get(
            "id_url"
        )

        verification.completed_at = timezone.now()

        verification.save()

        user = verification.user

        user.verification_status = verification.verification_status
        user.verification_mode = verification.verification_mode
        user.dojah_reference_id = reference_id

        if verification.verification_status == "Completed":

            user.is_identity_verified = True
            user.identity_verified_at = timezone.now()

        user.save()

        return verification



def create_verification(user, reference_id):

    verification, created = Verification.objects.get_or_create(

        reference_id=reference_id,

        defaults={

            "user": user,

            "verification_status": "Pending",

        }

    )

    return verification

