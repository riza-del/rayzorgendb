"""
RayzorgenDB Encryption
Simple but effective XOR + HMAC stream cipher for data at rest.

This is not AES. For production security, use cryptography library.
For a self-contained solution without external dependencies,
this provides reasonable protection against casual inspection.
"""

import os
import hmac
import hashlib
import struct


class Cipher:
    """
    Stream cipher with HMAC authentication.

    Key is derived from a password using PBKDF2.
    Each encryption uses a random nonce.
    """

    NONCE_SIZE = 16
    HMAC_SIZE = 32

    def __init__(self, password: str, salt: bytes = None):
        if salt is None:
            salt = b"rayzorgen_salt_v1"
        self.salt = salt
        # Derive key from password
        self.key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations=100_000,
            dklen=32,
        )

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        """Generate keystream from nonce using SHA-256 counter mode."""
        output = bytearray()
        counter = 0
        while len(output) < length:
            data = nonce + struct.pack(">Q", counter)
            block = hmac.new(
                self.key, data, hashlib.sha256
            ).digest()
            output.extend(block)
            counter += 1
        return bytes(output[:length])

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext. Returns nonce + ciphertext + hmac."""
        nonce = os.urandom(self.NONCE_SIZE)
        keystream = self._keystream(nonce, len(plaintext))

        ciphertext = bytes(
            p ^ k for p, k in zip(plaintext, keystream)
        )

        # HMAC over nonce + ciphertext
        mac = hmac.new(
            self.key, nonce + ciphertext, hashlib.sha256
        ).digest()

        return nonce + ciphertext + mac

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data. Verifies HMAC."""
        if len(data) < self.NONCE_SIZE + self.HMAC_SIZE:
            raise ValueError("Ciphertext too short")

        nonce = data[:self.NONCE_SIZE]
        mac = data[-self.HMAC_SIZE:]
        ciphertext = data[
            self.NONCE_SIZE:-self.HMAC_SIZE
        ]

        # Verify HMAC
        expected = hmac.new(
            self.key, nonce + ciphertext, hashlib.sha256
        ).digest()

        if not hmac.compare_digest(mac, expected):
            raise ValueError(
                "HMAC verification failed. "
                "Data corrupted or wrong password."
            )

        keystream = self._keystream(nonce, len(ciphertext))
        plaintext = bytes(
            c ^ k for c, k in zip(ciphertext, keystream)
        )
        return plaintext


def encrypt_bytes(plaintext: bytes,
                  password: str) -> bytes:
    """Convenience function."""
    return Cipher(password).encrypt(plaintext)


def decrypt_bytes(ciphertext: bytes,
                  password: str) -> bytes:
    """Convenience function."""
    return Cipher(password).decrypt(ciphertext)
