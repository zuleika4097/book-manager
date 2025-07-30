import base64
import binascii
from hashlib import md5
import itertools

import jwt
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import unpad, pad


KEY_LEN = 32
IV_LEN = 16
BLOCK_SIZE = 16
PREFIX = b"53616c7465645f5f"
BOREALIS_CODE = b"1c1d383d0562361a241b6b7a253d715965585b71053e171d26742c460d2211022b100000"
ORION_CODE = b"6c767276555072795230334a6e754733332b6a304c6b4370644744716269646359773d3d"


def shuffle(x: bytes, y: bytes) -> bytes:
    r = bytes(v ^ y[i % len(y)] for i, v in enumerate(x))
    return r


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


def passcode_from_token(auth_token: str):
    jwt_content = jwt.decode(auth_token, algorithms=["RS256"], options={"verify_signature": False})
    secret_token = jwt_content["token"].encode()
    digest = SHA256.new(secret_token).hexdigest()

    borealis_code = binascii.unhexlify(BOREALIS_CODE)
    orion_code = binascii.unhexlify(ORION_CODE)
    star_code = shuffle(borealis_code, orion_code)
    digest_code = bytes(
        [int.from_bytes(b, byteorder="little") for b in itertools.batched(digest.encode("utf-16-le"), 2)]
    )
    passcode = shuffle(star_code, digest_code)
    return passcode


def decrypt(auth_token: str, message: str):
    passcode = passcode_from_token(auth_token)
    encrypted = base64.b64decode(message)
    salt = encrypted[8:16]
    cypher = encrypted[16:]
    key, iv = bytes_to_key(passcode, salt, KEY_LEN, IV_LEN)
    aes = AES.new(key, AES.MODE_CBC, iv)
    result = unpad(aes.decrypt(cypher), BLOCK_SIZE)
    return result


def encrypt(auth_token: str, message: str):
    passcode = passcode_from_token(auth_token)
    msg = message.encode("utf-8")
    salt = get_random_bytes(8)
    prefix = binascii.unhexlify(PREFIX)
    key, iv = bytes_to_key(passcode, salt, KEY_LEN, IV_LEN)
    aes = AES.new(key, AES.MODE_CBC, iv)
    return base64.b64encode(prefix + salt + aes.encrypt(pad(msg, BLOCK_SIZE)))
