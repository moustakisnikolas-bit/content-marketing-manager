import base64
import hashlib
import hmac

# WooCommerce (X-WC-Webhook-Signature) and Shopify (X-Shopify-Hmac-Sha256)
# both sign webhook bodies the same way: base64(HMAC-SHA256(raw_body,
# webhook_secret)). This is pure crypto with no external I/O, so unlike the
# rest of this module's provider integration it needs no stub — it's
# exercised for real, against real signatures, in every test and even
# against the stub StoreConnectorPort.


def compute_signature(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(raw_body: bytes, secret: str, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = compute_signature(raw_body, secret)
    return hmac.compare_digest(expected, signature_header)
