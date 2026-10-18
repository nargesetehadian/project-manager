import re

from django.core.exceptions import ValidationError

# 09123456789 / 9123456789 / 989123456789 / +989123456789 / 00989123456789
IRAN_MOBILE_REGEX = re.compile(r"^(?:\+98|0098|98|0)?(9\d{9})$")


def normalize_phone_number(value):
    """Return phone as 09XXXXXXXXX or raise ValidationError."""
    if value is None:
        raise ValidationError("Phone number is required.")
    value = str(value).strip().replace(" ", "").replace("-", "")
    match = IRAN_MOBILE_REGEX.match(value)
    if not match:
        raise ValidationError("Enter a valid Iranian mobile number.")
    return "0" + match.group(1)
