from Crypto.Cipher import AES
import base64

def pad(data: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    return data + bytes([pad_len]) * pad_len

def encrypt_aes_ecb_base64(plain_text, key):
    key_bytes = key.encode("utf-8")
    if len(key_bytes) not in (16, 24, 32):
        key_bytes = key_bytes.ljust(32, b"\0")[:32]
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    padded_text = pad(plain_text.encode("utf-8"))
    encrypted = cipher.encrypt(padded_text)
    return base64.b64encode(encrypted).decode("utf-8")
