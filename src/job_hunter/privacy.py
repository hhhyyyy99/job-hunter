import re
from pathlib import Path
from typing import Any

PII_PLACEHOLDERS = {
    "name": "[Name]",
    "phone": "[Phone]",
    "email": "[Email]",
    "wechat": "[WeChat]",
    "age": "[Age]",
    "birthday": "[Birthday]",
}

GENERIC_PII_PATTERNS = [
    (re.compile(r'1[3-9]\d{9}'), '[Phone]'),
    (re.compile(r'\b[\w.-]+@[\w.-]+\.\w+\b'), '[Email]'),
    (re.compile(r'微信[:：]\s*\S+'), '微信: [WeChat]'),
]


def mask_resume_fields(text: str, fields: list[str]) -> str:
    for field in fields:
        placeholder = PII_PLACEHOLDERS.get(field, f"[{field}]")
        pattern = re.compile(rf'{field}[:：]\s*\S+', re.IGNORECASE)
        text = pattern.sub(f'{field}: {placeholder}', text)
    return text


def mask_chat_text(text: str, mask_fields: list[str] | None = None) -> str:
    for pattern, replacement in GENERIC_PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def unmask_text(text: str, original_values: dict[str, str]) -> str:
    for field, value in original_values.items():
        placeholder = PII_PLACEHOLDERS.get(field, f"[{field}]")
        text = text.replace(placeholder, value)
    return text


def extract_pii_values(resume_text: str) -> dict[str, str]:
    values = {}
    for field in PII_PLACEHOLDERS:
        match = re.search(rf'{field}[:：]\s*(\S+)', resume_text, re.IGNORECASE)
        if match:
            values[field] = match.group(1)
    return values
