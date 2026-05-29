"""Tests for the privacy masking module."""
import pytest
from job_hunter.privacy import mask_chat_text, unmask_text, extract_pii_values


class TestMaskChatText:
    def test_phone_masking(self):
        text = "call me at 13812345678"
        result = mask_chat_text(text)
        assert "13812345678" not in result
        assert "[Phone]" in result

    def test_email_masking(self):
        text = "send to hr@company.com please"
        result = mask_chat_text(text)
        assert "hr@company.com" not in result
        assert "[Email]" in result

    def test_wechat_masking(self):
        text = "加我微信: hr_zhang123 详聊"
        result = mask_chat_text(text)
        assert "hr_zhang123" not in result
        assert "[WeChat]" in result

    def test_no_pii(self):
        text = "你好，简历已收到，请确认一下项目经验"
        result = mask_chat_text(text)
        assert result == text


class TestUnmaskText:
    def test_placeholder_restore(self):
        text = "你好 [Name]，感谢联系"
        orig = {"name": "张三"}
        result = unmask_text(text, orig)
        assert "[Name]" not in result
        assert "张三" in result


class TestExtractPII:
    def test_extract_from_resume_text(self):
        resume = "姓名: 张三\n手机: 13800138000\n邮箱: zhangsan@example.com"
        values = extract_pii_values(resume)
        assert values.get("name") == "张三"
        assert values.get("phone") == "13800138000"
        assert values.get("email") == "zhangsan@example.com"
