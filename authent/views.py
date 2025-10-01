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
import base64

User = get_user_model()

class SignupAndOpenVirtualAccount(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        phone = data.get("phone")
        email = data.get("email")
        password = data.get("password")

        # 🔎 Check duplicates
        if User.objects.filter(email=email).exists():
            return Response({"error": "Email already exists"}, status=400)
        if User.objects.filter(phone=phone).exists():
            return Response({"error": "Phone already exists"}, status=400)

        # 1️⃣ Create user (inactive until email verification)
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

        # 2️⃣ Open virtual account via Fidelity API
        request_ref = str(uuid.uuid4())
        transaction_ref = str(uuid.uuid4())
        app_secret = data.get("app_secret", "9dREG1FeyoE3Slxp")
        api_key = data.get("api_key", "iGFX9Yg2AypaiUKMVTYk_b1ea9221596642848af9bdf39a7efc6c")

        # Signature required by PayGatePlus
        signature_raw = f"{request_ref};{app_secret}"
        signature = hashlib.md5(signature_raw.encode()).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Signature": signature
        }

        payload = {
            "request_ref": request_ref,
            "request_type": "open_account",
            "auth": {
                "type": None,
                "secure": None,
                "auth_provider": "FidelityVirtual",
                "route_mode": None
            },
            "transaction": {
                "mock_mode": "Live",
                "transaction_ref": transaction_ref,
                "transaction_desc": "Open virtual account",
                "amount": 0,
                "customer": {
                    "customer_ref": phone,
                    "firstname": data.get("first_name"),
                    "surname": data.get("last_name"),
                    "email": email,
                    "mobile_no": phone
                },
                "details": {
                    "name_on_account": f"{data.get('first_name')} {data.get('last_name')}",
                    "middlename": data.get("middle_name", ""),
                    "dob": data.get("dob"),
                    "gender": data.get("gender"),
                    "title": data.get("title", "Mr"),
                    "address_line_1": data.get("address1"),
                    "address_line_2": data.get("address2", ""),
                    "city": data.get("city"),
                    "state": data.get("state"),
                    "country": data.get("country", "Nigeria")
                },
                "meta": data.get("meta", {})
            }
        }

        try:
            response = requests.post(
                "https://api.paygateplus.ng/v2/transact",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp_data = response.json()
            print("Fidelity API Response:", resp_data)  # Debug

            if response.status_code == 200 and resp_data.get("status") == "Successful":
                provider_resp = resp_data.get("data", {}).get("provider_response", {})
                acct_number = provider_resp.get("account_number")
                bank_name = provider_resp.get("bank_name")

                if acct_number and bank_name:
                    user.virtual_account_number = acct_number
                    user.bank_name = bank_name
                    user.save()
        except Exception as e:
            print("Error while creating Fidelity account:", str(e))

        # 3️⃣ Send email verification code
        subject = "Verify your email - YourApp"
        message = (
            f"Hello {user.first_name},\n\n"
            f"Your verification code is {verification_code}.\n"
            f"It expires in 5 minutes.\n\n"
            f"Thanks,\nYourApp Team"
        )
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

        return Response({
            "message": "Account created. Please verify email.",
            "verification_code": verification_code,   # ⚠️ Remove in production
            "virtual_account_number": user.virtual_account_number,
            "bank_name": user.bank_name
        })


class VerifyEmail(APIView):
    permission_classes = [AllowAny]
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
    permission_classes = [AllowAny]
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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        pin = request.data.get("pin")
        if not pin or len(pin) != 4:
            return Response({"error": "PIN must be 4 digits"}, status=400)
        user.transaction_pin = hashlib.sha256(pin.encode()).hexdigest()
        user.save()
        return Response({"message": "Transaction PIN set successfully"})



class ForgotPassword(APIView):
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
    def post(self, request):
        data = request.data

        # Required keys from settings
        api_key = data.get("api_key", "iGFX9Yg2AypaiUKMVTYk_b1ea9221596642848af9bdf39a7efc6c")
        app_secret = data.get("app_secret", "9dREG1FeyoE3Slxp")


        # Generate IDs
        request_ref = str(uuid.uuid4())
        transaction_ref = str(uuid.uuid4())

        # Signature = MD5(request_ref + ";" + app_secret)
        signature_raw = f"{request_ref};{app_secret}"
        signature = hashlib.md5(signature_raw.encode()).hexdigest()

        # Encrypt source account
        source_account = data.get("source_account")
        encrypted_source_account = encrypt_aes_ecb_base64(source_account, app_secret)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Signature": signature,
        }

        payload = {
            "request_ref": request_ref,
            "request_type": "transfer_funds",
            "auth": {
                "type": "bank.account",
                "secure": encrypted_source_account,
                "auth_provider": "Fidelity",
                "route_mode": None
            },
            "transaction": {
                "mock_mode": "Live",
                "transaction_ref": transaction_ref,
                "transaction_desc": data.get("description", "A random transaction"),
                "transaction_ref_parent": None,
                "amount": data.get("amount"),  # amount in kobo
                "customer": {
                    "customer_ref": data.get("customer_id"),
                    "firstname": data.get("firstname"),
                    "surname": data.get("surname"),
                    "email": data.get("email"),
                    "mobile_no": data.get("mobile_no")
                },
                "meta": data.get("meta", {}),
                "details": {
                    "destination_account": data.get("destination_account"),
                    "destination_bank_code": data.get("destination_bank_code"),
                    "otp_override": True
                }
            }
        }

        url = "https://api.paygateplus.ng/v2/transact"
        response = requests.post(url, json=payload, headers=headers)
        return Response(response.json(), status=response.status_code)






        #Verify Account

class VerifyAccountView(APIView):
    def post(self, request):
        data = request.data

        account_number = data.get("account_number")
        bank_code = data.get("bank_code")

        if not account_number or not bank_code:
            return Response({"error": "Account number and bank code are required."}, status=400)

        api_key = data.get("api_key", "iGFX9Yg2AypaiUKMVTYk_b1ea9221596642848af9bdf39a7efc6c")
        app_secret = data.get("app_secret", "9dREG1FeyoE3Slxp")


        request_ref = str(uuid.uuid4())
        transaction_ref = str(uuid.uuid4())
        signature = hashlib.md5(f"{request_ref};{app_secret}".encode()).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Signature": signature
        }

        payload = {
            "request_ref": request_ref,
            "request_type": "verify_account_number",
            "auth": {
                "type": None,
                "secure": None,
                "auth_provider": "FidelityVirtual",
                "route_mode": None
            },
            "transaction": {
                "mock_mode": "Live",
                "transaction_ref": transaction_ref,
                "transaction_desc": "Verify recipient account name",
                "amount": 0,
                "customer": {
                    "customer_ref": account_number,
                    "firstname": "",
                    "surname": "",
                    "email": "",
                    "mobile_no": ""
                },
                "details": {
                    "destination_account": account_number,
                    "destination_bank_code": bank_code
                }
            }
        }

        url = "https://api.paygateplus.ng/v2/transact"
        response = requests.post(url, headers=headers, json=payload)
        return Response(response.json(), status=response.status_code)







class GetAccountBalance(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        app_secret = data.get("app_secret", "9dREG1FeyoE3Slxp")
        api_key = data.get("api_key", "iGFX9Yg2AypaiUKMVTYk_b1ea9221596642848af9bdf39a7efc6c")


        request_ref = str(uuid.uuid4())
        transaction_ref = str(uuid.uuid4())
        encrypted_account = encrypt_aes_ecb_base64(data["account_number"], app_secret)

        signature_raw = f"{request_ref};{app_secret}"
        signature = hashlib.md5(signature_raw.encode()).hexdigest().upper()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Signature": signature
        }

        payload = {
            "request_ref": request_ref,
            "request_type": "get_balance",
            "auth": {
                "type": "bank.account",
                "secure": encrypted_account,
                "auth_provider": "FidelityVirtual",
                "route_mode": None
            },
            "transaction": {
                "mock_mode": "Live",
                "transaction_ref": transaction_ref,
                "transaction_desc": "Get account balance",
                "transaction_ref_parent": None,
                "amount": 0,
                "customer": {
                    "customer_ref": data["customer_ref"],
                    "firstname": data.get("first_name", ""),
                    "surname": data.get("last_name", ""),
                    "email": data.get("email", ""),
                    "mobile_no": data.get("mobile_no", "")
                },
                "meta": {
                    "a_key": "value_a",
                    "b_key": "value_b"
                },
                "details": None
            }
        }

        response = requests.post("https://api.paygateplus.ng/v2/transact", headers=headers, json=payload)
        return Response(response.json(), status=response.status_code)





        

class PaymentWebhookView(APIView):
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



