import base64
import binascii
from hashlib import md5

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import unpad, pad


KEY_LEN = 32
IV_LEN = 16
BLOCK_SIZE = 16
PREFIX = b"53616c7465645f5f"
PUBLIC_PASSPHRASE = (
    b"455a2c7834577451101b68527f7f520c644452732a33370f76005e020e2d41581156090a"
)


def bytes_to_key(password, salt, key_len, iv_len):
    """
    Derive the key and the IV from the given password and salt.
    """
    dtot = md5(password + salt).digest()
    d = [dtot]
    while len(dtot) < (iv_len + key_len):
        d.append(md5(d[-1] + password + salt).digest())
        dtot += d[-1]
    return dtot[:key_len], dtot[key_len : key_len + iv_len]


def decrypt(message: str):
    encrypted = base64.b64decode(message)
    salt = encrypted[8:16]
    cypher = encrypted[16:]
    passphrase = binascii.unhexlify(PUBLIC_PASSPHRASE)
    key, iv = bytes_to_key(passphrase, salt, KEY_LEN, IV_LEN)
    aes = AES.new(key, AES.MODE_CBC, iv)
    result = unpad(aes.decrypt(cypher), BLOCK_SIZE)
    return result


def encrypt(message: str):
    msg = message.encode("utf-8")
    salt = get_random_bytes(8)
    prefix = binascii.unhexlify(PREFIX)
    passphrase = binascii.unhexlify(PUBLIC_PASSPHRASE)
    key, iv = bytes_to_key(passphrase, salt, KEY_LEN, IV_LEN)
    aes = AES.new(key, AES.MODE_CBC, iv)
    return base64.b64encode(prefix + salt + aes.encrypt(pad(msg, BLOCK_SIZE)))
