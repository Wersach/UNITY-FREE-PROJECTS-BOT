import hashlib
import logging
from config import ROBOKASSA_LOGIN, ROBOKASSA_PASSWORD1, ROBOKASSA_PASSWORD2, ROBOKASSA_TEST

logger = logging.getLogger(__name__)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def generate_payment_url(inv_id: int, amount: int, description: str) -> str:
    sig = _md5(f"{ROBOKASSA_LOGIN}:{amount}:{inv_id}:{ROBOKASSA_PASSWORD1}")
    test = "1" if ROBOKASSA_TEST else "0"
    base = "https://auth.robokassa.ru/Merchant/Index.aspx"
    return (
        f"{base}?MerchantLogin={ROBOKASSA_LOGIN}"
        f"&OutSum={amount}"
        f"&InvId={inv_id}"
        f"&Description={description}"
        f"&SignatureValue={sig}"
        f"&IsTest={test}"
    )


def verify_payment(out_sum: str, inv_id: str, signature: str) -> bool:
    expected = _md5(f"{out_sum}:{inv_id}:{ROBOKASSA_PASSWORD2}")
    return expected.lower() == signature.lower()
