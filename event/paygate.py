import uuid
import hashlib
import requests
from .utils import encrypt_account_number

def generate_signature(request_ref, app_secret):
    raw_signature = f"{request_ref};{app_secret}"
    hashed_signature = hashlib.md5(raw_signature.encode()).hexdigest()
    return hashed_signature

def transfer_from_wallet(user, amount_kobo, account_number, user_data):
    API_KEY = "iGFX9Yg2AypaiUKMVTYk_b1ea9221596642848af9bdf39a7efc6c"
    AES_KEY = "12345678901234567890123456789012"
    APP_SECRET =  "9dREG1FeyoE3Slxp"
    DEST_ACCOUNT = "your-platform-acct"
    DEST_BANK_CODE = "076"

    request_ref = str(uuid.uuid4())
    signature = generate_signature(request_ref, APP_SECRET)
    transaction_ref = str(uuid.uuid4())

    encrypted = encrypt_account_number(account_number, AES_KEY)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Signature": signature,
        "Content-Type": "application/json"
    }

    payload = {
        "request_ref": request_ref,
        "request_type": "transfer_funds",
        "auth": {
            "type": "bank.account",
            "secure": encrypted,
            "auth_provider": "Fidelity",
            "route_mode": None
        },
        "transaction": {
            "mock_mode": "Live",
            "transaction_ref": transaction_ref,
            "transaction_desc": "Ticket purchase",
            "amount": amount_kobo,
            "customer": {
                "customer_ref": str(user.id),
                "firstname": user_data["first_name"],
                "surname": user_data["last_name"],
                "email": user_data["email"],
                "mobile_no": user_data["phone"]
            },
            "meta": {
                "event": user_data["event"]
            },
            "details": {
                "destination_account": DEST_ACCOUNT,
                "destination_bank_code": DEST_BANK_CODE,
                "otp_override": True
            }
        }
    }

    res = requests.post("https://api.paygateplus.ng/v2/transact", json=payload, headers=headers)
    return res.json(), request_ref
