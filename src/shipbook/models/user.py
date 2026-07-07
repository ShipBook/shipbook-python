from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    user_id: str
    user_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    additional_info: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"userId": self.user_id}
        if self.user_name is not None:
            d["userName"] = self.user_name
        if self.full_name is not None:
            d["fullName"] = self.full_name
        if self.email is not None:
            d["email"] = self.email
        if self.phone_number is not None:
            d["phoneNumber"] = self.phone_number
        if self.additional_info:
            d["additionalInfo"] = self.additional_info
        return d
