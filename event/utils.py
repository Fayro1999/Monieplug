# utils.py
from Crypto.Cipher import AES
import base64

def encrypt_account_number(account_number, aes_key):
    key = aes_key.encode('utf-8')[:32]
    cipher = AES.new(key, AES.MODE_ECB)

    pad = lambda s: s + (16 - len(s) % 16) * chr(16 - len(s) % 16)
    padded = pad(account_number)

    encrypted = cipher.encrypt(padded.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')
