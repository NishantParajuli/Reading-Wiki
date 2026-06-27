"""Multi-user authentication: accounts, sessions, OAuth, email verification.

Session model: an opaque random token lives in an httpOnly+Secure cookie; only its
SHA-256 hash is stored server-side in the `sessions` table, so logout/ban revokes
access immediately. See deps.py for the FastAPI dependencies that gate routes.
"""
