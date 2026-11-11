"""
pure_aes.py - tiny pure-Python AES (128/192/256) + RC4 for the PDF Password Tool.

Why this file exists:
Many bank PDFs (e.g. SBI statements) use AES encryption. pypdf needs an AES
library for that, but the phone build did not include one. This file provides
AES in plain Python, and install() makes pypdf use it by presenting itself as
the 'pycryptodome' package (modules Crypto.Cipher.AES, Crypto.Cipher.ARC4,
Crypto.Util.Padding). No native code, so it cannot fail to build.

It is a little slower than native AES, but fine for statement-size PDFs.
"""

import struct
import sys
import types

# ---------------- tables ----------------


def _build_tables():
    sbox = [0] * 256
    p = q = 1
    while True:
        # multiply p by 3
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        # divide q by 3
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        q &= 0xFF
        x = q ^ (((q << 1) | (q >> 7)) & 0xFF) ^ (((q << 2) | (q >> 6)) & 0xFF) \
            ^ (((q << 3) | (q >> 5)) & 0xFF) ^ (((q << 4) | (q >> 4)) & 0xFF)
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i

    def xt(a):
        a <<= 1
        if a & 0x100:
            a ^= 0x11B
        return a & 0xFF

    def mul(a, b):
        r = 0
        while b:
            if b & 1:
                r ^= a
            a = xt(a)
            b >>= 1
        return r

    te0, te1, te2, te3 = [], [], [], []
    td0, td1, td2, td3 = [], [], [], []
    for i in range(256):
        s = sbox[i]
        w = (mul(s, 2) << 24) | (s << 16) | (s << 8) | mul(s, 3)
        te0.append(w)
        te1.append(((w >> 8) | (w << 24)) & 0xFFFFFFFF)
        te2.append(((w >> 16) | (w << 16)) & 0xFFFFFFFF)
        te3.append(((w >> 24) | (w << 8)) & 0xFFFFFFFF)
        s = inv[i]
        w = (mul(s, 14) << 24) | (mul(s, 9) << 16) | (mul(s, 13) << 8) | mul(s, 11)
        td0.append(w)
        td1.append(((w >> 8) | (w << 24)) & 0xFFFFFFFF)
        td2.append(((w >> 16) | (w << 16)) & 0xFFFFFFFF)
        td3.append(((w >> 24) | (w << 8)) & 0xFFFFFFFF)
    return sbox, inv, (te0, te1, te2, te3), (td0, td1, td2, td3)


_SBOX, _INV, (_TE0, _TE1, _TE2, _TE3), (_TD0, _TD1, _TD2, _TD3) = _build_tables()


def _expand_key(key):
    nk = len(key) // 4
    if len(key) not in (16, 24, 32):
        raise ValueError("Incorrect AES key length (%d bytes)" % len(key))
    nr = nk + 6
    w = list(struct.unpack(">%dI" % nk, key))
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = w[i - 1]
        if i % nk == 0:
            t = ((t << 8) | (t >> 24)) & 0xFFFFFFFF
            t = (_SBOX[t >> 24] << 24) | (_SBOX[(t >> 16) & 255] << 16) | \
                (_SBOX[(t >> 8) & 255] << 8) | _SBOX[t & 255]
            t ^= rcon << 24
            rcon <<= 1
            if rcon & 0x100:
                rcon ^= 0x11B
        elif nk > 6 and i % nk == 4:
            t = (_SBOX[t >> 24] << 24) | (_SBOX[(t >> 16) & 255] << 16) | \
                (_SBOX[(t >> 8) & 255] << 8) | _SBOX[t & 255]
        w.append(w[i - nk] ^ t)
    return w, nr


def _dec_key(w, nr):
    """Round keys for the 'equivalent inverse cipher'."""
    dk = []
    for r in range(nr + 1):
        row = w[4 * (nr - r): 4 * (nr - r) + 4]
        if 0 < r < nr:
            row = [
                _TD0[_SBOX[x >> 24]] ^ _TD1[_SBOX[(x >> 16) & 255]] ^
                _TD2[_SBOX[(x >> 8) & 255]] ^ _TD3[_SBOX[x & 255]]
                for x in row
            ]
        dk.extend(row)
    return dk


def _encrypt_block(rk, nr, block):
    te0, te1, te2, te3, sb = _TE0, _TE1, _TE2, _TE3, _SBOX
    s0, s1, s2, s3 = struct.unpack(">4I", block)
    s0 ^= rk[0]
    s1 ^= rk[1]
    s2 ^= rk[2]
    s3 ^= rk[3]
    k = 4
    for _ in range(nr - 1):
        t0 = te0[s0 >> 24] ^ te1[(s1 >> 16) & 255] ^ te2[(s2 >> 8) & 255] ^ te3[s3 & 255] ^ rk[k]
        t1 = te0[s1 >> 24] ^ te1[(s2 >> 16) & 255] ^ te2[(s3 >> 8) & 255] ^ te3[s0 & 255] ^ rk[k + 1]
        t2 = te0[s2 >> 24] ^ te1[(s3 >> 16) & 255] ^ te2[(s0 >> 8) & 255] ^ te3[s1 & 255] ^ rk[k + 2]
        t3 = te0[s3 >> 24] ^ te1[(s0 >> 16) & 255] ^ te2[(s1 >> 8) & 255] ^ te3[s2 & 255] ^ rk[k + 3]
        s0, s1, s2, s3 = t0, t1, t2, t3
        k += 4
    o0 = ((sb[s0 >> 24] << 24) | (sb[(s1 >> 16) & 255] << 16) | (sb[(s2 >> 8) & 255] << 8) | sb[s3 & 255]) ^ rk[k]
    o1 = ((sb[s1 >> 24] << 24) | (sb[(s2 >> 16) & 255] << 16) | (sb[(s3 >> 8) & 255] << 8) | sb[s0 & 255]) ^ rk[k + 1]
    o2 = ((sb[s2 >> 24] << 24) | (sb[(s3 >> 16) & 255] << 16) | (sb[(s0 >> 8) & 255] << 8) | sb[s1 & 255]) ^ rk[k + 2]
    o3 = ((sb[s3 >> 24] << 24) | (sb[(s0 >> 16) & 255] << 16) | (sb[(s1 >> 8) & 255] << 8) | sb[s2 & 255]) ^ rk[k + 3]
    return struct.pack(">4I", o0, o1, o2, o3)


def _decrypt_block(dk, nr, block):
    td0, td1, td2, td3, ib = _TD0, _TD1, _TD2, _TD3, _INV
    s0, s1, s2, s3 = struct.unpack(">4I", block)
    s0 ^= dk[0]
    s1 ^= dk[1]
    s2 ^= dk[2]
    s3 ^= dk[3]
    k = 4
    for _ in range(nr - 1):
        t0 = td0[s0 >> 24] ^ td1[(s3 >> 16) & 255] ^ td2[(s2 >> 8) & 255] ^ td3[s1 & 255] ^ dk[k]
        t1 = td0[s1 >> 24] ^ td1[(s0 >> 16) & 255] ^ td2[(s3 >> 8) & 255] ^ td3[s2 & 255] ^ dk[k + 1]
        t2 = td0[s2 >> 24] ^ td1[(s1 >> 16) & 255] ^ td2[(s0 >> 8) & 255] ^ td3[s3 & 255] ^ dk[k + 2]
        t3 = td0[s3 >> 24] ^ td1[(s2 >> 16) & 255] ^ td2[(s1 >> 8) & 255] ^ td3[s0 & 255] ^ dk[k + 3]
        s0, s1, s2, s3 = t0, t1, t2, t3
        k += 4
    o0 = ((ib[s0 >> 24] << 24) | (ib[(s3 >> 16) & 255] << 16) | (ib[(s2 >> 8) & 255] << 8) | ib[s1 & 255]) ^ dk[k]
    o1 = ((ib[s1 >> 24] << 24) | (ib[(s0 >> 16) & 255] << 16) | (ib[(s3 >> 8) & 255] << 8) | ib[s2 & 255]) ^ dk[k + 1]
    o2 = ((ib[s2 >> 24] << 24) | (ib[(s1 >> 16) & 255] << 16) | (ib[(s0 >> 8) & 255] << 8) | ib[s3 & 255]) ^ dk[k + 2]
    o3 = ((ib[s3 >> 24] << 24) | (ib[(s2 >> 16) & 255] << 16) | (ib[(s1 >> 8) & 255] << 8) | ib[s0 & 255]) ^ dk[k + 3]
    return struct.pack(">4I", o0, o1, o2, o3)


# ---------------- pycryptodome-like classes ----------------

MODE_ECB = 1
MODE_CBC = 2


class _AESCipher:
    block_size = 16

    def __init__(self, key, mode, iv=None):
        if mode not in (MODE_ECB, MODE_CBC):
            raise ValueError("Only ECB and CBC are supported")
        self._rk, self._nr = _expand_key(bytes(key))
        self._dk = None
        self._mode = mode
        if mode == MODE_CBC:
            iv = bytes(iv if iv is not None else b"\x00" * 16)
            if len(iv) != 16:
                raise ValueError("Incorrect IV length")
        self._iv_enc = iv
        self._iv_dec = iv

    def encrypt(self, data):
        data = bytes(data)
        if len(data) % 16:
            raise ValueError("Data must be aligned to block boundary")
        out = []
        prev = self._iv_enc
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            if self._mode == MODE_CBC:
                blk = (int.from_bytes(blk, "big") ^ int.from_bytes(prev, "big")).to_bytes(16, "big")
            prev = _encrypt_block(self._rk, self._nr, blk)
            out.append(prev)
        self._iv_enc = prev
        return b"".join(out)

    def decrypt(self, data):
        data = bytes(data)
        if len(data) % 16:
            raise ValueError("Data must be aligned to block boundary")
        if self._dk is None:
            self._dk = _dec_key(self._rk, self._nr)
        out = []
        prev = self._iv_dec
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            plain = _decrypt_block(self._dk, self._nr, blk)
            if self._mode == MODE_CBC:
                plain = (int.from_bytes(plain, "big") ^ int.from_bytes(prev, "big")).to_bytes(16, "big")
                prev = blk
            out.append(plain)
        self._iv_dec = prev
        return b"".join(out)


def _aes_new(key, mode, *args, **kwargs):
    iv = kwargs.get("iv")
    if iv is None and args:
        iv = args[0]
    return _AESCipher(key, mode, iv)


class _ARC4Cipher:
    def __init__(self, key, *args, **kwargs):
        key = bytes(key)
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) & 255
            s[i], s[j] = s[j], s[i]
        self._s = s
        self._i = 0
        self._j = 0

    def _crypt(self, data):
        s, i, j = self._s, self._i, self._j
        out = bytearray(len(data))
        for n, b in enumerate(bytes(data)):
            i = (i + 1) & 255
            j = (j + s[i]) & 255
            s[i], s[j] = s[j], s[i]
            out[n] = b ^ s[(s[i] + s[j]) & 255]
        self._i, self._j = i, j
        return bytes(out)

    encrypt = _crypt
    decrypt = _crypt


def _pad(data, block_size, style="pkcs7"):
    n = block_size - (len(data) % block_size)
    return bytes(data) + bytes([n]) * n


# ---------------- install as the 'Crypto' package ----------------


def install():
    """Make 'from Crypto.Cipher import AES, ARC4' work using this file.
    Does nothing if a real Crypto package is already available."""
    try:
        from Crypto.Cipher import AES  # noqa: F401
        return False
    except Exception:
        pass

    crypto = types.ModuleType("Crypto")
    crypto.__version__ = "3.20.0"
    crypto.__path__ = []

    cipher = types.ModuleType("Crypto.Cipher")
    cipher.__path__ = []
    aes = types.ModuleType("Crypto.Cipher.AES")
    aes.new = _aes_new
    aes.MODE_ECB = MODE_ECB
    aes.MODE_CBC = MODE_CBC
    aes.block_size = 16
    arc4 = types.ModuleType("Crypto.Cipher.ARC4")
    arc4.ARC4Cipher = _ARC4Cipher
    arc4.new = lambda key, *a, **k: _ARC4Cipher(key)
    cipher.AES = aes
    cipher.ARC4 = arc4

    util = types.ModuleType("Crypto.Util")
    util.__path__ = []
    padding = types.ModuleType("Crypto.Util.Padding")
    padding.pad = _pad
    util.Padding = padding

    crypto.Cipher = cipher
    crypto.Util = util
    sys.modules.update({
        "Crypto": crypto,
        "Crypto.Cipher": cipher,
        "Crypto.Cipher.AES": aes,
        "Crypto.Cipher.ARC4": arc4,
        "Crypto.Util": util,
        "Crypto.Util.Padding": padding,
    })
    return True
