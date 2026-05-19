# authent/views.py
import uuid, hashlib, requests, random
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.permissions import AllowAny,IsAuthenticated
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
from .utility import encrypt_aes_ecb_base64
from Crypto.Cipher import AES
#from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import make_password, check_password

import base64
import threading
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiTypes,  OpenApiParameter
#from drf_spectacular.utils import extend_schema, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from .serializers import (
    SignupSerializer, VerifyEmailSerializer, LoginSerializer,
    SetTransactionPinSerializer, ForgotPasswordSerializer,
    ResetPasswordSerializer, TransferFundsSerializer,
    VerifyAccountSerializer, GetAccountBalanceSerializer
)

User = get_user_model()



#import requests, random, uuid
#from django.conf import settings
#from django.core.cache import cache
#from django.core.mail import send_mail
#from rest_framework.views import APIView
#from rest_framework.response import Response
#from rest_framework import status
#from rest_framework.permissions import AllowAny
#from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiTypes
#from .models import User
#from .serializers import SignupSerializer


import random
import uuid
import requests
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiTypes

from .serializers import SignupSerializer
from .models import User


class SignupAndOpenWallet(APIView):
    """
    Register a new user and open a customer wallet via WAAS API.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=SignupSerializer,
        responses={201: OpenApiResponse(OpenApiTypes.OBJECT, description="Signup success")}
    )
    def post(self, request):
        data = request.data
        phone = data.get("phone")
        email = data.get("email")
        password = data.get("password")

        # Check duplicates
        if User.objects.filter(email=email).exists():
            return Response({"error": "Email already exists"}, status=400)
        if User.objects.filter(phone=phone).exists():
            return Response({"error": "Phone already exists"}, status=400)

        # Ensure BVN or NIN is provided
        if not data.get("bvn") and not data.get("nin_user_id"):
            return Response({"error": "BVN or NIN is required"}, status=400)

        #Create user
        verification_code = str(random.randint(100000, 999999))
        user = User.objects.create_user(
            email=email,
            phone=phone,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            password=password,
            email_verification_code=verification_code,
        )
        cache.set(f"verification_code:{verification_code}", email, timeout=300)

        # 4️⃣ Authenticate with WAAS
        auth_url = "http://102.216.128.75:9090/waas/api/v1/authenticate"
        auth_payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            auth_resp = requests.post(auth_url, json=auth_payload, timeout=30)
            auth_resp.raise_for_status()
            access_token = auth_resp.json().get("accessToken")
        except Exception as e:
            return Response({"error": "Failed to connect to WAAS auth", "details": str(e)}, status=500)

        # 5️⃣ Prepare wallet payload
        wallet_payload = {
            "transactionTrackingRef": str(uuid.uuid4()),
            "lastName": user.last_name,
            "otherNames": user.first_name,
            "accountName": f"MONIEPLUG/{user.first_name} {user.last_name}",
            "phoneNo": user.phone,
            "gender": int(data.get("gender", 0)),
            "dateOfBirth": data.get("date_of_birth"),  # must be DD/MM/YYYY
            "address": data.get("address"),
            "email": user.email,
        }
        if data.get("bvn"):
            wallet_payload["bvn"] = data.get("bvn")
        if data.get("nin_user_id"):
            wallet_payload["nin"] = data.get("nin_user_id")

        wallet_url = "http://102.216.128.75:9090/waas/api/v1/open_wallet"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        # 6️⃣ Open wallet
        try:
            wallet_resp = requests.post(wallet_url, json=wallet_payload, headers=headers, timeout=30)
            wallet_resp.raise_for_status()
            wallet_data = wallet_resp.json()

            if wallet_data.get("status", "").upper() == "SUCCESS":
                account_info = wallet_data.get("data", {})
                # Use customerID if walletId is missing
                user.wallet_id = account_info.get("walletId") or account_info.get("customerID")
                user.wallet_account_number = account_info.get("accountNumber")
                user.save()
            else:
                return Response({"error": "Wallet creation failed", "waas_response": wallet_data}, status=400)
        except Exception as e:
            return Response({"error": "Failed to open wallet", "details": str(e)}, status=500)

        # 7️⃣ Send verification email
        subject = "Verify your email"
        message = (
            f"Hello {user.first_name},\n\n"
            f"Your verification code is {verification_code}.\n"
            f"It expires in 5 minutes.\n\n"
            f"Thanks."
        )
        try:
            def send_email():
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True)
            threading.Thread(target=send_email).start()
            #send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True)
        except Exception as e:
            print("Email error:", e)

        # 8️⃣ Return response
        return Response({
            "message": "Account created successfully. Please verify email.",
            "wallet_id": user.wallet_id,
            "account_number": user.wallet_account_number,
            "waas_response": wallet_data,
            "verification_code":verification_code
        }, status=201)


class VerifyEmail(APIView):
    """
    post:
    Verify a user’s email using a 6-digit code.

    Request body:
    {
        "code": "123456"
    }

    Response:
    {
        "message": "Email verified successfully"
    }
    """
    permission_classes = [AllowAny]
    @extend_schema(
        request=VerifyEmailSerializer,
        responses={201: None}
    )
    def post(self, request):
        code = request.data.get("code")

        # 1️⃣ Get email back from cache using the code
        email = cache.get(f"verification_code:{code}")
        if not email:
            return Response({"error": "Invalid or expired code"}, status=400)

        try:
            user = User.objects.get(email=email)
            user.is_active = True
            user.email_verification_code = None
            user.save()

            # 2️⃣ Remove code from cache after successful verification
            cache.delete(f"verification_code:{code}")

            return Response({"message": "Email verified successfully"})
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)




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
        short_ref = str(uuid.uuid4())[:25]  # max 25 chars
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
    "transactionType": "OTHER_BANKS"
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











class WalletEnquiryView(APIView):
    """
    Fetch wallet details using WAAS wallet enquiry API
    """
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

    def post(self, request):

        account_no = request.data.get("accountNo")

        if not account_no:
            return Response(
                {"error": "accountNo is required"},
                status=400
            )

        # 🔐 STEP 1: Get WAAS token
        token = self.get_waas_token()

        if not token:
            return Response(
                {"error": "Failed to authenticate with WAAS"},
                status=500
            )

        # 🔐 STEP 2: Call wallet enquiry WITH token
        url = "http://102.216.128.75:9090/waas/api/v1/wallet_enquiry"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "accountNo": str(account_no)
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            data = response.json()

            if data.get("status", "").upper() != "SUCCESS":
                return Response(
                    {
                        "status": data.get("status"),
                        "message": data.get("message"),
                        "data": data.get("data")
                    },
                    status=400
                )

            return Response(
                {
                    "status": data.get("status"),
                    "message": data.get("message"),
                    "account": data.get("data")
                },
                status=200
            )

        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "status": "FAILED",
                    "message": f"Network error: {str(e)}"
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
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


class WAASBanksView(APIView):
    """
    Fetch list of banks from WAAS API
    """

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

            try:
                data = resp.json()
            except ValueError:
                data = json.loads(resp.text)

            return data.get("accessToken")

        except Exception:
            return None

    def get(self, request):

        # 🔐 STEP 1: TOKEN
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

        url = "http://102.216.128.75:9090/waas/api/v1/get_banks"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)

            # 🔥 SAFE PARSE
            try:
                data = response.json()
            except ValueError:
                data = json.loads(response.text)

            # WAAS must succeed
            if str(data.get("status", "")).upper() != "SUCCESS":
                return Response(
                    {
                        "status": data.get("status"),
                        "message": data.get("message"),
                        "banks": []
                    },
                    status=400
                )

            # 🔥 SMART EXTRACTION (FIX FOR YOUR ERROR)
            raw_banks = (
                data.get("bankList") or
                (data.get("data", {}) if isinstance(data.get("data"), dict) else None) or
                data.get("data")
            )

            # If still string → decode
            if isinstance(raw_banks, str):
                try:
                    raw_banks = json.loads(raw_banks)
                except:
                    raw_banks = None

            # Final safety check
            if not isinstance(raw_banks, list):
                return Response(
                    {
                        "status": "FAILED",
                        "message": "WAAS returned unexpected bank format",
                        "raw_data": data
                    },
                    status=500
                )

            # 🔥 CLEAN OUTPUT
            banks = [
                {
                    "name": (b.get("bankName") or "").strip(),
                    "code": (b.get("bankCode") or "").strip(),
                    "nibss_code": (b.get("nibssBankCode") or "").strip(),
                }
                for b in raw_banks
                if isinstance(b, dict)
            ]

            return Response(
                {
                    "status": "SUCCESS",
                    "message": data.get("message", "Success"),
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