# authent/views.py

import random
import uuid
import requests

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny,IsAuthenticated
from rest_framework import status

from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiTypes,
)

from .models import User

from .serializers import (
    SignupSerializer,
    VerifyEmailSerializer,
    VerifyIdentitySerializer,
    LoginSerializer,
    SetTransactionPinSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    TransferFundsSerializer,
    VerifyAccountSerializer,
    GetBalanceSerializer,
    UserSerializer,
    WalletTransactionHistorySerializer,
    WalletTransactionHistoryResponseSerializer,
    OtherBankEnquirySerializer,
    OtherBankEnquiryResponseSerializer,
    WalletDebitCreditSerializer,
)


# ============================================================
# WAAS CONFIGURATION
# ============================================================

WAAS_BASE_URL = "http://102.216.128.75:9090/waas/api/v1"


# ============================================================
# WAAS AUTHENTICATION
# ============================================================

def get_waas_token():

    url = f"{WAAS_BASE_URL}/authenticate"

    payload = {
        "username": settings.WAAS_USERNAME,
        "password": settings.WAAS_PASSWORD,
        "clientId": settings.WAAS_CLIENT_ID,
        "clientSecret": settings.WAAS_CLIENT_SECRET,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )

        try:
            data = response.json()

        except ValueError:
            data = {
                "message": response.text
            }

        if not response.ok:

            return None, data

        token = data.get("accessToken")

        if not token:

            return None, data

        return token, data

    except requests.RequestException as exc:

        return None, {
            "message": str(exc)
        }


# ============================================================
# OPEN WAAS WALLET
# ============================================================

def open_waas_wallet(
    user,
    waas_token,
    transaction_ref,
):

    wallet_url = f"{WAAS_BASE_URL}/open_wallet"

    # --------------------------------------------------------
    # BASE PAYLOAD
    # --------------------------------------------------------

    wallet_payload = {
        "transactionTrackingRef": transaction_ref,

        "lastName": user.last_name,

        "otherNames": user.first_name,

        "accountName": (
            f"MONIEPLUG/"
            f"{user.first_name} "
            f"{user.last_name}"
        ),

        "phoneNo": user.phone,

        "gender": int(user.gender),

        "dateOfBirth": user.date_of_birth.strftime(
            "%d/%m/%Y"
        ),

        "address": user.address,

        "email": user.email,
    }

    # --------------------------------------------------------
    # IDENTITY
    # --------------------------------------------------------

    if user.nin:

        wallet_payload["nationalIdentityNo"] = (
            str(user.nin).strip()
        )

    if user.nin_user_id:

        wallet_payload["ninUserId"] = (
            str(user.nin_user_id).strip()
        )

    if user.bvn:

        wallet_payload["bvn"] = (
            str(user.bvn).strip()
        )

    # --------------------------------------------------------
    # NEXT OF KIN
    # --------------------------------------------------------

    if user.next_of_kin_name:

        wallet_payload["nextOfKinName"] = (
            user.next_of_kin_name
        )

    if user.next_of_kin_phone:

        wallet_payload["nextOfKinPhoneNo"] = (
            user.next_of_kin_phone
        )

    # --------------------------------------------------------
    # REFERRAL
    # --------------------------------------------------------

    if user.referral_name:

        wallet_payload["referralName"] = (
            user.referral_name
        )

    if user.referral_phone:

        wallet_payload["referralPhoneNo"] = (
            user.referral_phone
        )

    headers = {
        "Authorization": f"Bearer {waas_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # --------------------------------------------------------
    # CALL WAAS
    # --------------------------------------------------------

    try:

        response = requests.post(
            wallet_url,
            json=wallet_payload,
            headers=headers,
            timeout=60,
        )

        try:

            wallet_data = response.json()

        except ValueError:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Invalid response received "
                        "from WAAS wallet service."
                    ),
                    "waas_response": response.text,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

    except requests.RequestException as exc:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "Unable to connect to WAAS "
                    "wallet service."
                ),
                "details": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # --------------------------------------------------------
    # CHECK WAAS STATUS
    # --------------------------------------------------------

    if (
        str(
            wallet_data.get("status", "")
        ).upper()
        != "SUCCESS"
    ):

        return Response(
            {
                "status": "FAILED",
                "message": wallet_data.get(
                    "message",
                    "WAAS wallet creation failed.",
                ),
                "waas_response": wallet_data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------------------
    # EXTRACT ACCOUNT
    # --------------------------------------------------------

    account_info = wallet_data.get(
        "data",
        {}
    )

    wallet_id = (
        account_info.get("walletId")
        or account_info.get("customerID")
    )

    account_number = account_info.get(
        "accountNumber"
    )

    wallet_name = (
        account_info.get("accountName")
        or account_info.get("fullName")
        or (
            f"MONIEPLUG/"
            f"{user.first_name} "
            f"{user.last_name}"
        )
    )

    # --------------------------------------------------------
    # SUCCESS WITHOUT ACCOUNT NUMBER
    # --------------------------------------------------------

    if not account_number:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "WAAS reported success but "
                    "no account number was returned."
                ),
                "waas_response": wallet_data,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # --------------------------------------------------------
    # SAVE WALLET
    # --------------------------------------------------------

    user.wallet_id = wallet_id

    user.wallet_account_number = account_number

    user.wallet_name = wallet_name

    user.is_identity_verified = True

    user.verification_status = "Completed"

    user.identity_verified_at = timezone.now()

    # Facial image is no longer needed after
    # successful identity verification and wallet opening.
    user.facial_image = None

    user.save(
        update_fields=[
            "wallet_id",
            "wallet_account_number",
            "wallet_name",
            "is_identity_verified",
            "verification_status",
            "identity_verified_at",
            "facial_image",
        ]
    )

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return Response(
        {
            "status": "SUCCESS",
            "message": (
                "Identity verified and wallet "
                "created successfully."
            ),
            "wallet_id": wallet_id,
            "account_number": account_number,
            "wallet_name": wallet_name,
            "verification_status": "Completed",
        },
        status=status.HTTP_201_CREATED,
    )


# ============================================================
# SIGNUP
# ============================================================

class SignupAndOpenWallet(APIView):

    permission_classes = [AllowAny]

    @extend_schema(
        request=SignupSerializer,
        responses={
            201: OpenApiResponse(
                OpenApiTypes.OBJECT,
                description=(
                    "Signup created and email "
                    "verification sent."
                ),
            ),
        },
        tags=["Authentication"],
    )
    def post(self, request):

        serializer = SignupSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        data = serializer.validated_data

        email = data["email"].strip().lower()

        phone = data["phone"].strip()

        # ----------------------------------------------------
        # DUPLICATE EMAIL
        # ----------------------------------------------------

        existing_email = User.objects.filter(
            email=email
        ).first()

        if existing_email:

            if not existing_email.is_active:

                return Response(
                    {
                        "status": "PENDING",
                        "message": (
                            "An account with this email "
                            "already exists and is awaiting "
                            "email verification."
                        ),
                        "next_step": "verify_email",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "An account with this email "
                        "already exists."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # DUPLICATE PHONE
        # ----------------------------------------------------

        if User.objects.filter(
            phone=phone
        ).exists():

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "An account with this phone "
                        "number already exists."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # EMAIL VERIFICATION CODE
        # ----------------------------------------------------

        verification_code = str(
            random.randint(100000, 999999)
        )

        # ----------------------------------------------------
        # CREATE USER
        #
        # IMPORTANT:
        #
        # BVN/NIN ARE NOT COLLECTED HERE.
        #
        # OTP/FACIAL ARE NOT SELECTED HERE.
        #
        # WAAS IS NOT CALLED HERE.
        # ----------------------------------------------------

        try:

            with transaction.atomic():

                user = User.objects.create_user(

                    email=email,

                    phone=phone,

                    password=data["password"],

                    first_name=data["first_name"],

                    last_name=data["last_name"],

                    date_of_birth=data["date_of_birth"],

                    gender=data["gender"],

                    address=data["address"],

                    # ------------------------------------------------
                    # DO NOT PASS BVN/NIN HERE
                    # ------------------------------------------------

                    next_of_kin_name=data.get(
                        "next_of_kin_name"
                    ),

                    next_of_kin_phone=data.get(
                        "next_of_kin_phone"
                    ),

                    referral_name=data.get(
                        "referral_name"
                    ),

                    referral_phone=data.get(
                        "referral_phone"
                    ),

                    email_verification_code=(
                        verification_code
                    ),

                    is_active=False,

                    is_identity_verified=False,

                    verification_status="Pending",

                    # Identity method has NOT been selected yet.
                    verification_mode=None,

                    # Facial image has NOT been submitted yet.
                    facial_image=None,

                    city=data.get("city"),

                    state=data.get("state"),

                    country=data.get("country"),
                )

        except Exception as exc:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Unable to create account."
                    ),
                    "details": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ----------------------------------------------------
        # CACHE EMAIL CODE
        # ----------------------------------------------------

        cache.set(
            f"email_verification:{user.id}",
            verification_code,
            timeout=600,
        )

        # ----------------------------------------------------
        # SEND EMAIL
        # ----------------------------------------------------

        try:

            send_mail(

                subject="Verify your Monieplug account",

                message=(
                    f"Hello {user.first_name},\n\n"
                    f"Your Monieplug verification "
                    f"code is:\n\n"
                    f"{verification_code}\n\n"
                    "This code expires in 10 minutes.\n\n"
                    "Do not share this code with anyone."
                ),

                from_email=settings.DEFAULT_FROM_EMAIL,

                recipient_list=[
                    user.email
                ],

                fail_silently=False,
            )

        except Exception as exc:

            user.delete()

            cache.delete(
                f"email_verification:{user.id}"
            )

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Email verification could "
                        "not be sent."
                    ),
                    "details": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        return Response(
            {
                "status": "PENDING",

                "message": (
                    "Account created. Please verify "
                    "your email."
                ),

                "user_id": str(user.id),

                "email": user.email,

                "next_step": "verify_email",
            },
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# VERIFY EMAIL
# ============================================================

class VerifyEmail(APIView):

    permission_classes = [AllowAny]

    @extend_schema(
        request=VerifyEmailSerializer,
        responses={
            200: OpenApiResponse(
                OpenApiTypes.OBJECT,
                description=(
                    "Email verified. User must now "
                    "choose BVN or NIN."
                ),
            ),
            400: OpenApiResponse(
                description="Invalid verification code."
            ),
        },
        tags=["Authentication"],
    )
    def post(self, request):

        serializer = VerifyEmailSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        code = serializer.validated_data["code"]

        # ----------------------------------------------------
        # FIND PENDING USER
        # ----------------------------------------------------

        user = User.objects.filter(
            email_verification_code=code,
            is_active=False,
        ).first()

        if not user:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Invalid or expired "
                        "email verification code."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CHECK CACHE
        # ----------------------------------------------------

        cached_code = cache.get(
            f"email_verification:{user.id}"
        )

        if cached_code != code:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Verification code "
                        "has expired."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # MARK EMAIL VERIFIED
        # ----------------------------------------------------

        user.is_active = True

        user.email_verification_code = None

        user.verification_status = "Email Verified"

        user.save(
            update_fields=[
                "is_active",
                "email_verification_code",
                "verification_status",
            ]
        )

        cache.delete(
            f"email_verification:{user.id}"
        )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # DO NOT CALL WAAS HERE.
        #
        # THE USER MUST FIRST CHOOSE:
        #
        # 1. BVN OR NIN
        #
        # 2. OTP OR FACIAL
        # ----------------------------------------------------

        return Response(
            {
                "status": "SUCCESS",

                "message": (
                    "Email verified successfully. "
                    "Please choose your identity "
                    "verification method."
                ),

                "user_id": str(user.id),

                "next_step": "choose_identity_method",

                "options": {
                    "identity": [
                        "BVN",
                        "NIN",
                    ],
                    "verification": [
                        "OTP",
                        "FACIAL",
                    ],
                },
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# CHOOSE BVN/NIN AND OTP/FACIAL
# ============================================================

class InitiateIdentityVerification(APIView):

    permission_classes = [AllowAny]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiResponse(
                OpenApiTypes.OBJECT,
                description=(
                    "WAAS identity verification "
                    "initiated."
                ),
            ),
        },
        tags=["Authentication"],
    )
    def post(self, request):

        # ----------------------------------------------------
        # REQUIRED FIELDS
        # ----------------------------------------------------

        user_id = request.data.get(
            "user_id"
        )

        identity_type = str(
            request.data.get(
                "identity_type",
                ""
            )
        ).upper().strip()

        verification_type = str(
            request.data.get(
                "verification_type",
                ""
            )
        ).upper().strip()

        identity_number = str(
            request.data.get(
                "identity_number",
                ""
            )
        ).strip()

        facial_image = request.data.get(
            "image"
        )

        # ----------------------------------------------------
        # VALIDATE USER ID
        # ----------------------------------------------------

        if not user_id:

            return Response(
                {
                    "status": "FAILED",
                    "message": "user_id is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            user = User.objects.get(
                id=user_id
            )

        except (User.DoesNotExist, ValueError):

            return Response(
                {
                    "status": "FAILED",
                    "message": "User not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ----------------------------------------------------
        # EMAIL MUST BE VERIFIED
        # ----------------------------------------------------

        if not user.is_active:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Please verify your email "
                        "before identity verification."
                    ),
                    "next_step": "verify_email",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # ALREADY VERIFIED
        # ----------------------------------------------------

        if user.is_identity_verified:

            return Response(
                {
                    "status": "SUCCESS",
                    "message": (
                        "Identity has already "
                        "been verified."
                    ),
                    "wallet_id": user.wallet_id,
                    "account_number": (
                        user.wallet_account_number
                    ),
                    "next_step": "completed",
                },
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # VALIDATE IDENTITY TYPE
        # ====================================================

        if identity_type not in [
            "BVN",
            "NIN",
        ]:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "identity_type must be "
                        "either BVN or NIN."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ====================================================
        # VALIDATE VERIFICATION TYPE
        # ====================================================

        if verification_type not in [
            "OTP",
            "FACIAL",
        ]:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "verification_type must be "
                        "either OTP or FACIAL."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ====================================================
        # IDENTITY NUMBER REQUIRED
        # ====================================================

        if not identity_number:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        f"{identity_type} is required."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ====================================================
        # SAVE BVN/NIN
        # ====================================================

        if identity_type == "BVN":

            user.bvn = identity_number

            # Clear the other identity if necessary.
            user.nin = None

        elif identity_type == "NIN":

            user.nin = identity_number

            # Clear the other identity if necessary.
            user.bvn = None

        # ====================================================
        # SAVE VERIFICATION METHOD
        # ====================================================

        user.verification_mode = verification_type

        # ====================================================
        # FACIAL IMAGE
        # ====================================================

        if verification_type == "FACIAL":

            if not facial_image:

                return Response(
                    {
                        "status": "FAILED",
                        "message": (
                            "Facial image is required "
                            "for facial verification."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user.facial_image = facial_image

        else:

            # OTP does not need a facial image.
            user.facial_image = None

        user.verification_status = "Ongoing"

        user.save(
            update_fields=[
                "bvn",
                "nin",
                "verification_mode",
                "facial_image",
                "verification_status",
            ]
        )

        # ----------------------------------------------------
        # START WAAS
        # ----------------------------------------------------

        return initiate_waas_identity(
            user
        )


# ============================================================
# INITIATE WAAS IDENTITY VERIFICATION
# ============================================================

def initiate_waas_identity(user):

    # --------------------------------------------------------
    # CHECK REQUIRED USER DATA
    # --------------------------------------------------------

    if not user.bvn and not user.nin:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "BVN or NIN must be selected "
                    "before WAAS identity verification."
                ),
                "next_step": "choose_identity_method",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not user.verification_mode:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "OTP or FACIAL must be selected "
                    "before WAAS identity verification."
                ),
                "next_step": "choose_identity_method",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------------------
    # WAAS AUTHENTICATION
    # --------------------------------------------------------

    waas_token, auth_response = get_waas_token()

    if not waas_token:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "Email verified, but WAAS "
                    "authentication failed."
                ),
                "waas_response": auth_response,
                "next_step": (
                    "retry_identity_verification"
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # --------------------------------------------------------
    # UNIQUE TRANSACTION REFERENCE
    # --------------------------------------------------------

    transaction_ref = uuid.uuid4().hex[:15].upper()

    verification_type = (
        user.verification_mode
        or "OTP"
    )

    # --------------------------------------------------------
    # WAAS IDENTITY INITIATE
    # --------------------------------------------------------

    url = (
        f"{WAAS_BASE_URL}/identity/initiate"
    )

    payload = {
        "transactionRef": transaction_ref,

        "phoneNo": user.phone,

        "type": verification_type,
    }

    # --------------------------------------------------------
    # ADD SELECTED IDENTITY ONLY
    # --------------------------------------------------------

    if user.bvn:

        payload["bvn"] = str(
            user.bvn
        ).strip()

    elif user.nin:

        payload["nin"] = str(
            user.nin
        ).strip()

    # --------------------------------------------------------
    # FACIAL VERIFICATION
    # --------------------------------------------------------

    if verification_type == "FACIAL":

        if not user.facial_image:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Facial verification image "
                        "is missing."
                    ),
                    "next_step": (
                        "submit_facial_image"
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload["image"] = user.facial_image

    # --------------------------------------------------------
    # HEADERS
    # --------------------------------------------------------

    headers = {
        "Authorization": (
            f"Bearer {waas_token}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # --------------------------------------------------------
    # DEBUG
    # --------------------------------------------------------

    print(
        "======================================"
    )

    print(
        "WAAS IDENTITY INITIATE"
    )

    print(
        "URL:",
        url
    )

    print(
        "TRANSACTION REF:",
        transaction_ref
    )

    print(
        "PHONE:",
        user.phone
    )

    print(
        "IDENTITY:",
        "BVN" if user.bvn else "NIN"
    )

    print(
        "VERIFICATION TYPE:",
        verification_type
    )

    print(
        "BVN PRESENT:",
        bool(user.bvn)
    )

    print(
        "NIN PRESENT:",
        bool(user.nin)
    )

    print(
        "FACIAL IMAGE PRESENT:",
        bool(user.facial_image)
    )

    if verification_type == "FACIAL":

        print(
            "FACIAL IMAGE LENGTH:",
            len(user.facial_image or "")
        )

    print(
        "======================================"
    )

    # --------------------------------------------------------
    # CALL WAAS
    # --------------------------------------------------------

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60,
        )

        print(
            "======================================"
        )

        print(
            "WAAS HTTP STATUS:",
            response.status_code
        )

        print(
            "WAAS RAW RESPONSE:",
            response.text
        )

        print("BVN PRESENT:", bool(user.bvn))
        print("BVN VALUE:", user.bvn)
        print("NIN VALUE:", user.nin)
        print("ACTUAL WAAS PAYLOAD:", payload)

        print(
            "======================================"
        )

        try:

            waas_data = response.json()

        except ValueError:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Invalid response "
                        "received from WAAS."
                    ),
                    "waas_response": (
                        response.text
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

    except requests.RequestException as exc:

        return Response(
            {
                "status": "FAILED",
                "message": (
                    "Unable to connect to "
                    "WAAS identity service."
                ),
                "details": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # --------------------------------------------------------
    # CHECK WAAS STATUS
    # --------------------------------------------------------

    waas_status = str(
        waas_data.get(
            "status",
            ""
        )
    ).upper()

    if waas_status not in [
        "SUCCESS",
        "PENDING",
    ]:

        user.verification_status = "Failed"

        user.save(
            update_fields=[
                "verification_status"
            ]
        )

        return Response(
            {
                "status": "FAILED",

                "message": waas_data.get(
                    "message",
                    (
                        "WAAS identity "
                        "verification failed."
                    ),
                ),

                "waas_response": waas_data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------------------
    # GET TRANSACTION REFERENCE
    # --------------------------------------------------------

    transaction_ref = (
        waas_data.get(
            "transactionRef"
        )

        or waas_data.get(
            "data",
            {}
        ).get(
            "transactionRef"
        )

        or transaction_ref
    )

    # --------------------------------------------------------
    # SAVE TRANSACTION REFERENCE
    # --------------------------------------------------------

    user.identity_transaction_ref = (
        transaction_ref
    )

    user.verification_status = (
        "Completed"
        if waas_status == "SUCCESS"
        else "Ongoing"
    )

    user.save(
        update_fields=[
            "identity_transaction_ref",
            "verification_status",
        ]
    )

    # --------------------------------------------------------
    # FACIAL SUCCESS
    #
    # If WAAS immediately completes facial
    # verification, open wallet.
    # --------------------------------------------------------

    if (
        verification_type == "FACIAL"
        and waas_status == "SUCCESS"
    ):

        return open_waas_wallet(
            user=user,

            waas_token=waas_token,

            transaction_ref=transaction_ref,
        )

    # --------------------------------------------------------
    # OTP
    # --------------------------------------------------------

    if verification_type == "OTP":

        return Response(
            {
                "status": "PENDING",

                "message": waas_data.get(
                    "message",
                    (
                        "OTP sent successfully. "
                        "Please enter the OTP."
                    ),
                ),

                "user_id": str(
                    user.id
                ),

                "transaction_ref": (
                    transaction_ref
                ),

                "verification_type": (
                    verification_type
                ),

                "next_step": (
                    "verify_identity"
                ),

                "waas_response": (
                    waas_data
                ),
            },
            status=status.HTTP_200_OK,
        )

    # --------------------------------------------------------
    # FACIAL PENDING
    # --------------------------------------------------------

    return Response(
        {
            "status": "PENDING",

            "message": waas_data.get(
                "message",
                (
                    "Facial identity verification "
                    "has been initiated."
                ),
            ),

            "user_id": str(
                user.id
            ),

            "transaction_ref": (
                transaction_ref
            ),

            "verification_type": (
                verification_type
            ),

            "next_step": (
                "identity_verification"
            ),

            "waas_response": (
                waas_data
            ),
        },
        status=status.HTTP_200_OK,
    )


# ============================================================
# VERIFY WAAS IDENTITY OTP
# ============================================================

class VerifyIdentityView(APIView):

    permission_classes = [AllowAny]

    @extend_schema(
        request=VerifyIdentitySerializer,
        responses={
            201: OpenApiResponse(
                OpenApiTypes.OBJECT,
                description=(
                    "Identity verified and wallet created."
                ),
            ),
            400: OpenApiResponse(
                description="Invalid OTP."
            ),
            404: OpenApiResponse(
                description=(
                    "Identity transaction not found."
                ),
            ),
            502: OpenApiResponse(
                description="WAAS unavailable."
            ),
        },
        tags=["Authentication"],
    )
    def post(self, request):

        serializer = VerifyIdentitySerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        transaction_ref = (
            serializer.validated_data[
                "transaction_ref"
            ]
        )

        otp = (
            serializer.validated_data[
                "otp"
            ]
        )

        # ----------------------------------------------------
        # FIND USER
        # ----------------------------------------------------

        try:

            user = User.objects.get(
                identity_transaction_ref=(
                    transaction_ref
                )
            )

        except User.DoesNotExist:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Identity verification "
                        "transaction was not found."
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ----------------------------------------------------
        # EMAIL MUST BE VERIFIED
        # ----------------------------------------------------

        if not user.is_active:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "Email verification is "
                        "required first."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # MUST BE OTP VERIFICATION
        # ----------------------------------------------------

        if (
            str(
                user.verification_mode
            ).upper()
            != "OTP"
        ):

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "This identity verification "
                        "was not initiated using OTP."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # ALREADY COMPLETED
        # ----------------------------------------------------

        if user.is_identity_verified:

            return Response(
                {
                    "status": "SUCCESS",

                    "message": (
                        "Identity has already been "
                        "verified and wallet created."
                    ),

                    "wallet_id": (
                        user.wallet_id
                    ),

                    "account_number": (
                        user.wallet_account_number
                    ),

                    "next_step": "completed",
                },
                status=status.HTTP_200_OK,
            )

        # ----------------------------------------------------
        # WAAS AUTH
        # ----------------------------------------------------

        waas_token, auth_response = (
            get_waas_token()
        )

        if not waas_token:

            return Response(
                {
                    "status": "FAILED",

                    "message": (
                        "Unable to authenticate "
                        "with WAAS."
                    ),

                    "waas_response": (
                        auth_response
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # VERIFY OTP
        # ----------------------------------------------------

        verify_url = (
            f"{WAAS_BASE_URL}/identity/verify-otp"
        )

        payload = {
            "transactionRef": (
                transaction_ref
            ),

            "otp": otp,
        }

        # ----------------------------------------------------
        # SEND THE SELECTED IDENTITY
        # ----------------------------------------------------

        if user.bvn:

            payload["bvn"] = str(
                user.bvn
            ).strip()

        elif user.nin:

            payload["nin"] = str(
                user.nin
            ).strip()

        else:

            return Response(
                {
                    "status": "FAILED",
                    "message": (
                        "No BVN or NIN was found "
                        "for this verification."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = {
            "Authorization": (
                f"Bearer {waas_token}"
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # ----------------------------------------------------
        # DEBUG
        # ----------------------------------------------------

        print(
            "======================================"
        )

        print(
            "WAAS IDENTITY VERIFY OTP"
        )

        print(
            "URL:",
            verify_url
        )

        print(
            "TRANSACTION REF:",
            transaction_ref
        )

        print(
            "OTP:",
            otp
        )

        print(
            "IDENTITY:",
            "BVN" if user.bvn else "NIN"
        )

        print(
            "PAYLOAD:",
            payload
        )

        print(
            "======================================"
        )

        # ----------------------------------------------------
        # CALL WAAS
        # ----------------------------------------------------

        try:

            response = requests.post(
                verify_url,
                json=payload,
                headers=headers,
                timeout=60,
            )

            print(
                "======================================"
            )

            print(
                "WAAS VERIFY HTTP STATUS:",
                response.status_code
            )

            print(
                "WAAS VERIFY RAW RESPONSE:",
                response.text
            )

            print(
                "======================================"
            )

            try:

                waas_data = response.json()

            except ValueError:

                return Response(
                    {
                        "status": "FAILED",

                        "message": (
                            "Invalid response "
                            "received from WAAS."
                        ),

                        "waas_response": (
                            response.text
                        ),
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        except requests.RequestException as exc:

            return Response(
                {
                    "status": "FAILED",

                    "message": (
                        "Unable to connect to "
                        "WAAS identity service."
                    ),

                    "details": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # OTP FAILED
        # ----------------------------------------------------

        if (
            str(
                waas_data.get(
                    "status",
                    ""
                )
            ).upper()
            != "SUCCESS"
        ):

            user.verification_status = "Failed"

            user.save(
                update_fields=[
                    "verification_status"
                ]
            )

            return Response(
                {
                    "status": "FAILED",

                    "message": waas_data.get(
                        "message",
                        (
                            "Identity OTP "
                            "verification failed."
                        ),
                    ),

                    "waas_response": (
                        waas_data
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # OTP SUCCESS
        #
        # NOW OPEN WALLET
        # ----------------------------------------------------

        return open_waas_wallet(
            user=user,

            waas_token=waas_token,

            transaction_ref=transaction_ref,
        )

#User = get_user_model()

class Login(APIView):
    """
    post:
    Authenticate a user with phone and password.

    Request body:
    {
        "phone": "08123456789",
        "password": "securepassword"
    }

    Response:
    {
        "token": "abc123xyz",
        "user": {
            "id": "1",
            "email": "john@example.com",
            "phone": "08123456789",
            "virtual_account": "1234567890",
            "bank": "Fidelity Bank"
        }
    }
    """
    permission_classes = [AllowAny]
    @extend_schema(
        request=LoginSerializer,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Login success")}
    )
    def post(self, request):
        phone = request.data.get("phone")
        password = request.data.get("password")

        if not phone or not password:
            return Response({"error": "Phone and password are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, phone=phone, password=password)

        if not user:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            return Response({"error": "Email not verified"}, status=status.HTTP_403_FORBIDDEN)

        token, created = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "phone": user.phone,
                "wallet_id": user.wallet_id,
                "account_number": user.wallet_account_number,
            }
        }, status=status.HTTP_200_OK)


class SetTransactionPin(APIView):
    """
    post:
    Set a 4-digit transaction PIN for the authenticated user.

    Request body:
    {
        "pin": "1234"
    }

    Response:
    {
        "message": "Transaction PIN set successfully"
    }
    """
    permission_classes = [IsAuthenticated]
    @extend_schema(
        request=SetTransactionPinSerializer,
        responses={201: None}
    )
    def post(self, request):
        user = request.user
        pin = request.data.get("pin")
        if not pin or len(pin) != 4:
            return Response({"error": "PIN must be 4 digits"}, status=400)
        user.transaction_pin = make_password(pin)
        user.save()
        return Response({"message": "Transaction PIN set successfully"})



class CheckTransactionPin(APIView):
    """
    get:
    Check if the authenticated user has a transaction PIN set.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        user = request.user

        pin_set = bool(user.transaction_pin)

        return Response({
            "pin_set": pin_set
        })



class ForgotPassword(APIView):
    @extend_schema(
        request=ForgotPasswordSerializer,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Forgot password result")}
    )
    def post(self, request):
        email = request.data.get("email")
        try:
            user = User.objects.get(email=email)
            reset_code = str(random.randint(100000, 999999))
            user.email_verification_code = reset_code
            user.save()
            print(f"Password reset code for {email}: {reset_code}")
            return Response({"message": "Reset code sent to email"})
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

class ResetPassword(APIView):
    @extend_schema(
        request= ResetPasswordSerializer,
        responses={201: None}
    )
    def post(self, request):
        email = request.data.get("email")
        code = request.data.get("code")
        new_password = request.data.get("new_password")
        try:
            user = User.objects.get(email=email, email_verification_code=code)
            user.set_password(new_password)
            user.email_verification_code = None
            user.save()
            return Response({"message": "Password reset successful"})
        except User.DoesNotExist:
            return Response({"error": "Invalid reset code"}, status=400)



            # Fund Transfer

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiResponse
from django.conf import settings
from django.contrib.auth.hashers import check_password
import requests
import uuid
from datetime import datetime

class TransferFundsView(APIView):
    """
    Transfer funds from user wallet to another bank using WAAS API
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Transfer result")}
    )
    def post(self, request):
        user = request.user
        data = request.data

        # 1️⃣ Check transaction PIN
        if not user.transaction_pin:
            return Response(
                {"detail": "Set a transaction PIN first."},
                status=status.HTTP_403_FORBIDDEN
            )

        pin = data.get("transaction_pin")
        if not pin:
            return Response({"detail": "Transaction PIN is required."}, status=status.HTTP_400_BAD_REQUEST)

        if not check_password(pin, user.transaction_pin):
            return Response({"detail": "Invalid transaction PIN."}, status=status.HTTP_403_FORBIDDEN)

        # 2️⃣ Validate required fields
        required_fields = ["destinationAccount", "destinationBankCode", "amount"]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return Response({"detail": f"Missing fields: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure amount is numeric
        try:
            amount = float(data["amount"])
        except (ValueError, TypeError):
            return Response({"detail": "Amount must be a number"}, status=status.HTTP_400_BAD_REQUEST)

        # 3️⃣ Authenticate WAAS
        try:
            auth_resp = requests.post(
                "http://102.216.128.75:9090/waas/api/v1/authenticate",
                json={
                    "username": settings.WAAS_USERNAME,
                    "password": settings.WAAS_PASSWORD,
                    "clientId": settings.WAAS_CLIENT_ID,
                    "clientSecret": settings.WAAS_CLIENT_SECRET,
                },
                timeout=30
            )
            auth_resp.raise_for_status()
            access_token = auth_resp.json().get("accessToken")
        except Exception as e:
            return Response({"error": "WAAS authentication failed", "details": str(e)}, status=500)

        # 4️⃣ Prepare WAAS payload
        short_ref = uuid.uuid4().hex[:15].upper()  # max 25 chars
        short_name = f"{user.first_name} {user.last_name}"[:25]
        narration = data.get("narration", "Payment transfer")[:25]

        payload = {
    "customer": {
        "account": {
            "bank": data["destinationBankCode"],
            "number": data["destinationAccount"],
            "senderaccountnumber": user.wallet_account_number,
            "name": f"{user.first_name} {user.last_name}",
            "sendername": f"{user.first_name} {user.last_name}"
        }
    },
    "order": {
        "amount": str(int(amount)),  # MUST be string
        "currency": "NGN",
        "description": narration,
        "country": "NG"
    },
    "narration": narration,
    "transaction": {
        "reference": short_ref
    },
    "transactionType": "INTRA_BANK",
    "merchant": {
  "isFee": True,
  "merchantFeeAccount": "1100015137",
  "merchantFeeAmount": "9.25"
}
}

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        # 5️⃣ Call WAAS transfer API
        try:
            waas_resp = requests.post(
                "http://102.216.128.75:9090/waas/api/v1/wallet_other_banks",
                json=payload,
                headers=headers,
                timeout=30
            )
            waas_data = waas_resp.json()

            if waas_data.get("status", "").upper() == "SUCCESS":
                return Response({
                    "message": "Transfer successful",
                    "reference": short_ref,
                    "amount": amount,
                    "waas_response": waas_data
                }, status=200)
            else:
                return Response({"error": "Transfer failed", "waas_response": waas_data}, status=400)

        except Exception as e:
            return Response({"error": "Transfer request failed", "details": str(e)}, status=500)


        #Verify Account

class VerifyAccountView(APIView):
    """
    Verify a recipient's account name using Rova BaaS Name Enquiry API.

    Request body:
    {
        "account_number": "2483520014",
        "bank_code": "000003"
    }

    Response:
    {
        "status": "SUCCESS",
        "data": {
            "status": "SUCCESSFUL",
            "message": "success",
            "accountName": "NNOROM UZOMA CHUKWUDI",
            "bankCode": "000003"
        },
        "message": "success"
    }
    """
    @extend_schema(
        request=VerifyAccountSerializer,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Account verification result")}
    )
    def post(self, request):
        data = request.data
        account_number = data.get("account_number")
        bank_code = data.get("bank_code")

        if not account_number or not bank_code:
            return Response({"error": "Account number and bank code are required."}, status=400)

        # Rova BaaS API URL
        url = "https://baas.dev.getrova.co.uk/transfer/name-query"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}"
        }

        payload = {
            "accountNumber": account_number,
            "institutionCode": bank_code
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response_data = response.json()
            return Response(response_data, status=response.status_code)
        except requests.exceptions.RequestException as e:
            return Response(
                {"detail": f"Name enquiry failed due to network error: {str(e)}"},
                status=503
            )











from .serializers import GetBalanceSerializer, WalletEnquiryResponseSerializer

class WalletEnquiryView(APIView):
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()
            return data.get("accessToken")
        except Exception:
            return None

    @extend_schema(
        request=GetBalanceSerializer,   # 🔥 FIX HERE
        responses=WalletEnquiryResponseSerializer
    )
    def post(self, request):

        account_no = request.data.get("accountNo")

        if not account_no:
            return Response(
                {"status": "FAILED", "message": "accountNo is required"},
                status=400
            )

        token = self.get_waas_token()

        if not token:
            return Response(
                {"status": "FAILED", "message": "Failed to authenticate with WAAS"},
                status=500
            )

        url = "http://102.216.128.75:9090/waas/api/v1/wallet_enquiry"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {"accountNo": str(account_no)}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            data = response.json()

            if data.get("status", "").upper() != "SUCCESS":
                return Response(
                    {
                        "status": data.get("status"),
                        "message": data.get("message"),
                        "account": data.get("data")
                    },
                    status=400
                )

            return Response(
                {
                    "status": "SUCCESS",
                    "message": data.get("message"),
                    "account": data.get("data")
                },
                status=200
            )

        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "status": "FAILED",
                    "message": str(e)
                },
                status=503
            )







class PaymentWebhookView(APIView):

    authentication_classes = []
    permission_classes = []

    # =========================
    # BASIC AUTH
    # =========================
    def _is_valid_basic_auth(self, request):
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Basic "):
            return False

        try:
            encoded = auth_header.split(" ")[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":")
        except Exception:
            return False

        return (
            username == settings.WEBHOOK_USERNAME and
            password == settings.WEBHOOK_PASSWORD
        )

    # =========================
    # MAIN WEBHOOK ENTRY
    # =========================
    def post(self, request):

        # AUTH CHECK
        if not self._is_valid_basic_auth(request):
            return Response({
                "success": False,
                "code": "01",
                "status": "FAILED",
                "message": "Unauthorized"
            }, status=403)

        event = (request.query_params.get("event") or "").strip().lower()
        data = request.data

        if event == "transfer":
            return self.handle_transfer(data)

        elif event == "account-upgrade":
            return self.handle_account_upgrade(data)

        return Response({
            "success": False,
            "code": "02",
            "status": "FAILED",
            "message": "Invalid event type"
        }, status=400)

    # =========================
    # TRANSFER HANDLER
    # =========================
    def handle_transfer(self, data):

        transaction_ref = data.get("transactionref")

        try:
            account_number = data.get("accountnumber")  # FIXED TYPO
            amount = Decimal(str(data.get("amount", "0")))
            narration = data.get("narration")
            sender_name = data.get("sendername")

            # prevent duplicate credit
            if Transaction.objects.filter(reference=transaction_ref).exists():
                return self.success_response(transaction_ref)

            user = User.objects.get(wallet_account_number=account_number)

            with db_transaction.atomic():

                # ⚠️ IMPORTANT:
                # You currently do NOT have a balance field
                # So we only store transaction history

                Transaction.objects.create(
                    user=user,
                    amount=amount,
                    transaction_type="credit",
                    reference=transaction_ref,
                    narration=narration,
                    sender_name=sender_name,
                    status="successful"
                )

            return self.success_response(transaction_ref)

        except User.DoesNotExist:
            return self.success_response(transaction_ref)

        except Exception as e:
            print("Webhook error:", str(e))
            return self.success_response(transaction_ref)

    # =========================
    # ACCOUNT UPGRADE HANDLER
    # =========================
    def handle_account_upgrade(self, data):

        account_number = data.get("accountNumber")
        status = data.get("status")
        message = data.get("message")

        try:
            user = User.objects.get(wallet_account_number=account_number)

            # Example logic (you can expand this later)
            if status.lower() == "approved":
                user.is_active = True
                user.save()

        except User.DoesNotExist:
            pass

        return self.success_response()

    # =========================
    # SUCCESS RESPONSE
    # =========================
    def success_response(self, transaction_ref=None):

        response = {
            "message": "Acknowledged",
            "status": "SUCCESS",
            "success": True,
            "code": "00",
        }

        if transaction_ref:
            response["transactionRef"] = transaction_ref

        return Response(response, status=200)





import json
import requests
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


import json
import requests

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated


class WAASBanksView(APIView):
    """
    Fetch list of banks from WAAS API
    """
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        auth_url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            response = requests.post(
                auth_url,
                json=payload,
                timeout=30
            )

            try:
                data = response.json()
            except ValueError:
                data = json.loads(response.text)

            return data.get("accessToken")

        except Exception:
            return None

    def get(self, request):

        # STEP 1: Authenticate with WAAS
        token = self.get_waas_token()

        if not token:
            return Response(
                {
                    "status": "FAILED",
                    "message": "WAAS authentication failed",
                    "banks": []
                },
                status=500
            )

        # STEP 2: Fetch banks
        banks_url = "http://102.216.128.75:9090/waas/api/v1/get_banks"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(
                banks_url,
                headers=headers,
                timeout=30
            )

            # SAFE JSON PARSE
            try:
                data = response.json()
            except ValueError:
                data = json.loads(response.text)

            # STEP 3: Validate WAAS response
            if str(data.get("status", "")).upper() != "SUCCESS":
                return Response(
                    {
                        "status": data.get("status"),
                        "message": data.get("message"),
                        "banks": []
                    },
                    status=400
                )

            # STEP 4: Extract bank list correctly
            raw_banks = (
                data.get("data", {}).get("bankList", [])
            )

            # FINAL SAFETY CHECK
            if not isinstance(raw_banks, list):
                return Response(
                    {
                        "status": "FAILED",
                        "message": "Invalid bank list format",
                        "banks": []
                    },
                    status=500
                )

            # STEP 5: Clean bank data
            banks = [
                {
                    "name": (bank.get("bankName") or "").strip(),
                    "code": (bank.get("bankCode") or "").strip(),
                    "nibss_code": (bank.get("nibssBankCode") or "").strip(),
                }
                for bank in raw_banks
                if isinstance(bank, dict)
            ]

            # STEP 6: Success response
            return Response(
                {
                    "status": "SUCCESS",
                    "message": data.get(
                        "message",
                        "Banks fetched successfully"
                    ),
                    "banks": banks
                },
                status=200
            )

        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "status": "FAILED",
                    "message": f"Network error: {str(e)}",
                    "banks": []
                },
                status=503
            )

        except Exception as e:
            return Response(
                {
                    "status": "FAILED",
                    "message": str(e),
                    "banks": []
                },
                status=500
            )





  #from rest_framework.permissions import IsAuthenticated
#from .serializers import UserSerializer


class GetUsersView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request):
        users = User.objects.all().order_by("-id")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=200)


class GetSingleUserView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request, id):
        try:
            user = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=404
            )

        serializer = UserSerializer(user)
        return Response(serializer.data, status=200) 





class WalletTransactionHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            return resp.json().get("accessToken")
        except Exception:
            return None

    @extend_schema(
        request=WalletTransactionHistorySerializer,
        responses=WalletTransactionHistoryResponseSerializer
    )
    def post(self, request):

        accountNumber = request.data.get("accountNumber")
        fromDate = request.data.get("fromDate")
        toDate = request.data.get("toDate")
        numberOfItems = request.data.get("numberOfItems")

        # validation
        if not all([accountNumber, fromDate, toDate, numberOfItems]):
            return Response({
                "status": "FAILED",
                "message": "All fields are required"
            }, status=400)

        token = self.get_waas_token()

        if not token:
            return Response({
                "status": "FAILED",
                "message": "Authentication failed"
            }, status=500)

        url = "http://102.216.128.75:9090/waas/api/v1/wallet_transactions"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "accountNumber": accountNumber,
            "fromDate": fromDate,
            "toDate": toDate,
            "numberOfItems": numberOfItems
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            data = resp.json()

            if data.get("status", "").upper() != "SUCCESS":
                return Response({
                    "status": data.get("status"),
                    "message": data.get("message"),
                    "data": data.get("data")
                }, status=400)

            return Response({
                "status": "SUCCESS",
                "message": data.get("message"),
                "data": data.get("data")
            }, status=200)

        except requests.exceptions.RequestException as e:
            return Response({
                "status": "FAILED",
                "message": str(e)
            }, status=503)        



import requests
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema

from .serializers import (
    OtherBankEnquirySerializer,
    OtherBankEnquiryResponseSerializer,
)


class OtherBankAccountEnquiryView(APIView):
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()

            data = resp.json()
            return data.get("accessToken")

        except requests.RequestException:
            return None

    @extend_schema(
        request=OtherBankEnquirySerializer,
        responses=OtherBankEnquiryResponseSerializer
    )
    def post(self, request):

        serializer = OtherBankEnquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer_data = serializer.validated_data["customer"]

        # Get WAAS token
        token = self.get_waas_token()

        if not token:
            return Response({
                "status": "FAILED",
                "message": "Authentication failed",
                "data": None
            }, status=401)

        url = "http://102.216.128.75:9090/waas/api/v1/other_banks_enquiry"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Convert Django request → WAAS format
        payload = {
            "customer": {
                "account": {
                    "bank": customer_data["bankCode"],
                    "number": customer_data["accountNumber"]
                }
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            print("=== WAAS REQUEST ===")
            print(payload)

            print("=== WAAS STATUS CODE ===")
            print(resp.status_code)

            print("=== WAAS RESPONSE ===")
            print(resp.text)

            # Safe JSON parsing
            try:
                data = resp.json()
            except ValueError:
                return Response({
                    "status": "FAILED",
                    "message": "Invalid response from WAAS",
                    "data": None
                }, status=502)

            # WAAS success logic (VERY IMPORTANT)
            message = (data.get("message") or "").lower()
            code = data.get("code")

            is_success = (
                resp.ok and (
                    code == "00" or
                    "success" in message or
                    "approved" in message
                )
            )

            return Response({
                "status": "SUCCESS" if is_success else "FAILED",
                "message": data.get("message"),
                "data": data.get("data") or data
            }, status=200 if is_success else 400)

        except requests.RequestException as e:
            return Response({
                "status": "FAILED",
                "message": str(e),
                "data": None
            }, status=503)



class WalletDebitView(APIView):
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=30
            )

            resp.raise_for_status()

            data = resp.json()
            return data.get("accessToken")

        except requests.RequestException:
            return None

    @extend_schema(
        request=WalletDebitCreditSerializer
    )
    def post(self, request):

        user = request.user

        if not user.wallet_account_number:
            return Response({
                "status": "FAILED",
                "message": "User does not have a wallet account.",
                "data": None
            }, status=400)

        serializer = WalletDebitCreditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        amount = data["amount"]
        narration = data["narration"]
        transaction_id = data["transaction_id"]

        # Get WAAS token
        token = self.get_waas_token()

        if not token:
            return Response({
                "status": "FAILED",
                "message": "Authentication failed",
                "data": None
            }, status=401)

        # Correct WAAS endpoint
        url = "http://102.216.128.75:9090/waas/api/v1/debit/transfer"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # WAAS debit payload
        payload = {
            "accountNo": user.wallet_account_number,
            "totalAmount": str(amount),
            "transactionId": transaction_id,
            "narration": narration,
            "merchant": {
                "isFee": False
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            print("=== WAAS DEBIT REQUEST ===")
            print(payload)

            print("=== WAAS DEBIT STATUS CODE ===")
            print(resp.status_code)

            print("=== WAAS DEBIT RESPONSE ===")
            print(resp.text)

            try:
                waas_data = resp.json()
            except ValueError:
                return Response({
                    "status": "FAILED",
                    "message": "Invalid response from WAAS",
                    "data": None
                }, status=502)

            # WAAS documentation says status is the primary
            # field for determining success or failure.
            waas_status = (waas_data.get("status") or "").upper()

            is_success = (
                resp.ok and
                waas_status == "SUCCESS"
            )

            return Response({
                "status": "SUCCESS" if is_success else "FAILED",
                "message": waas_data.get("message"),
                "data": waas_data.get("data") or waas_data
            }, status=200 if is_success else 400)

        except requests.RequestException as e:

            return Response({
                "status": "FAILED",
                "message": str(e),
                "data": None
            }, status=503)

class WalletCreditView(APIView):
    permission_classes = [IsAuthenticated]

    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=30
            )

            resp.raise_for_status()

            data = resp.json()
            return data.get("accessToken")

        except requests.RequestException:
            return None

    @extend_schema(
        request=WalletDebitCreditSerializer
    )
    def post(self, request):

        user = request.user

        if not user.wallet_account_number:
            return Response({
                "status": "FAILED",
                "message": "User does not have a wallet account.",
                "data": None
            }, status=400)

        serializer = WalletDebitCreditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        amount = data["amount"]
        narration = data["narration"]
        transaction_id = data["transaction_id"]

        # Get WAAS token
        token = self.get_waas_token()

        if not token:
            return Response({
                "status": "FAILED",
                "message": "Authentication failed",
                "data": None
            }, status=401)

        url = "http://102.216.128.75:9090/waas/api/v1/credit/transfer"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "accountNo": user.wallet_account_number,
            "totalAmount": str(amount),
            "transactionId": transaction_id,
            "narration": narration,
            "merchant": {
                "isFee": False
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            print("=== WAAS CREDIT REQUEST ===")
            print(payload)

            print("=== WAAS CREDIT STATUS CODE ===")
            print(resp.status_code)

            print("=== WAAS CREDIT RESPONSE ===")
            print(resp.text)

            try:
                waas_data = resp.json()
            except ValueError:
                return Response({
                    "status": "FAILED",
                    "message": "Invalid response from WAAS",
                    "data": None
                }, status=502)

            waas_status = (waas_data.get("status") or "").upper()

            is_success = (
                resp.ok and
                waas_status == "SUCCESS"
            )

            return Response({
                "status": "SUCCESS" if is_success else "FAILED",
                "message": waas_data.get("message"),
                "data": waas_data.get("data") or waas_data
            }, status=200 if is_success else 400)

        except requests.RequestException as e:

            return Response({
                "status": "FAILED",
                "message": str(e),
                "data": None
            }, status=503)