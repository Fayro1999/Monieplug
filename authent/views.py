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


class SignupAndOpenVirtualAccount(APIView):
    """
    post:
    Register a new user and open a Rova BaaS static virtual account.

    Steps:
    1. Create a user (inactive until verified).
    2. Call Rova BaaS API to open a static virtual account.
    3. Send a verification code to user's email.
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

        # 🔎 1️⃣ Check duplicates
        if User.objects.filter(email=email).exists():
            return Response({"error": "Email already exists"}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(phone=phone).exists():
            return Response({"error": "Phone already exists"}, status=status.HTTP_400_BAD_REQUEST)

        # 2️⃣ Create user (inactive until email verification)
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

        # 3️⃣ Call Rova BaaS API to open virtual account
        rova_url = "https://baas.dev.getrova.co.uk/virtual-account/static"
        headers = {
            "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",  # store your token in settings or env
            "Content-Type": "application/json",
        }
        payload = {
            "email": email,
            "firstName": data.get("first_name"),
            "lastName": data.get("last_name"),
            "phone": phone
        }

        try:
            response = requests.post(rova_url, json=payload, headers=headers, timeout=30)
            resp_data = response.json()
            print("Rova API Response:", resp_data)  # Debug

            if response.status_code == 200 and resp_data.get("status") == "SUCCESS":
                success_list = resp_data.get("data", {}).get("successfulVirtualAccounts", [])
                if success_list:
                    acct_info = success_list[0]
                    user.virtual_account_number = acct_info.get("virtualAccountNumber")
                    user.bank_name = "Rova BaaS"
                    user.save()
            else:
                print("Rova API error:", resp_data)
        except Exception as e:
            print("Error while creating Rova virtual account:", str(e))

        # 4️⃣ Send email verification code
        subject = "Verify your email - YourApp"
        message = (
            f"Hello {user.first_name},\n\n"
            f"Your verification code is {verification_code}.\n"
            f"It expires in 5 minutes.\n\n"
            f"Thanks,\nYourApp Team"
        )
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

        # 5️⃣ Return response
        return Response({
            "message": "Account created. Please verify email.",
            "verification_code": verification_code,  # ⚠️ Remove in production
            "virtual_account_number": user.virtual_account_number,
            "bank_name": user.bank_name
        }, status=status.HTTP_201_CREATED)


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
                "virtual_account": user.virtual_account_number,
                "bank": user.bank_name,
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

class TransferFundsView(APIView):
    """
    post:
    Transfer funds to another bank account using Rova BaaS API.

    Request body:
    {
        "destinationAccount": "4000027790",
        "destinationBankCode": "000003",
        "amount": "1000.50",
        "narration": "Internal Transfer",
        "transaction_pin": "1234"
    }

    Response:
    {
        "status": "SUCCESS",
        "data": {
            "status": "SUCCESSFUL",
            "reference": "2323211334232",
            "message": "Approved or Completed Successfully",
            "code": "SUCCESS"
        },
        "message": "success"
    }
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TransferFundsSerializer,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Transfer result")}
    )
    def post(self, request):
        user = request.user
        data = request.data

        # 1️⃣ Check if transaction PIN is set
        if not user.transaction_pin:
            return Response(
                {"detail": "You need to set a transaction PIN before making transfers."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2️⃣ Verify transaction PIN
        pin = data.get("transaction_pin")
        if not pin:
            return Response(
                {"detail": "Transaction PIN is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not check_password(pin, user.transaction_pin):
            return Response(
                {"detail": "Invalid transaction PIN."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 3️⃣ Validate required fields
        required_fields = ["destinationAccount", "destinationBankCode", "amount"]
        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return Response(
                {"detail": f"Missing fields: {', '.join(missing_fields)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4️⃣ Prepare transfer data
        payload = {
            "destinationAccount": data["destinationAccount"],
            "destinationBankCode": data["destinationBankCode"],
            "amount": data["amount"],
            "clientReference": str(uuid.uuid4()),
            "narration": data.get("narration", "Internal Transfer"),
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",  # defined in settings.py
        }

        # 5️⃣ Send request to Rova API
        try:
            response = requests.post(
                "https://baas.dev.getrova.co.uk/transfer",
                json=payload,
                headers=headers,
                timeout=30,
            )
            response_data = response.json()

            if response.status_code == 200 and response_data.get("status") == "SUCCESS":
                return Response(response_data, status=status.HTTP_200_OK)
            else:
                return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

        except requests.exceptions.RequestException as e:
            return Response(
                {"detail": f"Transfer failed due to network error: {str(e)}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )






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






class GetAccountBalance(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="account_number",
                description="Virtual account number to check balance",
                required=True,
                type=str
            )
        ],
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Account balance details")}
    )
    def get(self, request):
        account_number = request.query_params.get("account_number")
        if not account_number:
            return Response({"error": "Account number is required"}, status=400)

        url = f"https://baas.dev.getrova.co.uk/virtual-account/static/{account_number}"
        headers = {
            "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)

            if not response.text.strip():
                return Response({"error": "Empty response from Rova API"}, status=502)

            try:
                data = response.json()
            except ValueError:
                return Response({
                    "error": "Invalid JSON response from Rova API",
                    "raw_response": response.text
                }, status=502)

            if response.status_code != 200 or data.get("status") != "SUCCESS":
                return Response(data, status=response.status_code)

            result = {
                "account_id": data["data"].get("virtualAccountId"),
                "account_name": data["data"].get("virtualAccountName"),
                "bank_name": data["data"].get("bankName"),
                "balance": data["data"].get("transactionAmount"),
                "status": data.get("status"),
                "message": data.get("message"),
            }

            return Response(result, status=200)

        except requests.exceptions.RequestException as e:
            return Response({"error": f"Network error: {str(e)}"}, status=503)





        

class PaymentWebhookView(APIView):
    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Webhook event processed")}
    )
    def post(self, request):
        data = request.data

        

        # ✅ Verify Signature
        request_ref = data.get("request_ref")
        signature_header = request.headers.get("Signature")
        app_secret = "9dREG1FeyoE3Slxp"

        expected_signature = hashlib.md5(f"{request_ref};{app_secret}".encode()).hexdigest()
        if signature_header != expected_signature:
            return Response({"error": "Invalid signature"}, status=403)

        # ✅ Process only successful credits
        details = data.get("details", {})
        if details.get("status") != "Successful":
            return Response({"status": "Ignored non-success transaction"}, status=200)

        # ✅ Extract transaction details
        amount = details.get("amount")
        account = details.get("meta", {}).get("cr_account")
        sender_name = details.get("meta", {}).get("originator_account_name")
        narration = details.get("meta", {}).get("narration")

        # TODO: match this cr_account to a user in your system
        # TODO: update their wallet balance or trigger related service

        return Response({"status": "Payment processed"}, status=200)




class BanksListView(APIView):
    """
    Get the list of banks from CollectionBaaS API
    """
    permission_classes = [AllowAny]  
    def get(self, request):
        url = "https://baas.dev.getrova.co.uk/banks"
        headers = {
            "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "SUCCESS":
                return Response({"status": "success", "banks": data.get("data", [])}, status=200)
            else:
                return Response({"status": "error", "message": data}, status=400)

        except requests.RequestException as e:
            return Response({"status": "error", "message": f"Network error: {str(e)}"}, status=503)

