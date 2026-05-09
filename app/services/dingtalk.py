import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from typing import List

class DingTalkClient:
    def _sign(self, secret: str):
        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return timestamp, sign

    def send_markdown(self, title: str, text: str, webhook_url: str, secret: str, access_token: str, at_mobiles: List[str] = None, at_all: bool = False):
        if not webhook_url or not secret or not access_token:
             return {"errcode": -1, "errmsg": "DingTalk configuration missing"}

        # If webhook_url already contains access_token (common mistake), strip it or handle it
        # But we assume standard format: https://oapi.dingtalk.com/robot/send
        
        timestamp, sign = self._sign(secret)
        
        # Check if webhook_url already has query params
        separator = "&" if "?" in webhook_url else "?"
        
        # If access_token is NOT in webhook_url, append it. 
        # Some users might paste the full URL into webhook_url field.
        # But our UI asks for access_token separately.
        # Let's assume standard behavior:
        # If user puts full URL in webhook_url, we might duplicate access_token parameter, which DingTalk might ignore or error.
        # Safe bet: Construct URL from base.
        
        # Logic update:
        # If webhook_url has access_token, use it as base but still append sign/timestamp
        # But we specifically ask for access_token in config. 
        # So we should probably strip it from URL if present, or just trust the separate field.
        
        # Let's construct strictly:
        base_url = webhook_url.split("?")[0]
        url = f"{base_url}?access_token={access_token}&timestamp={timestamp}&sign={sign}"
        
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            },
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all
            }
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return {"response": response.json(), "request_payload": payload}
        except Exception as e:
            import logging
            logging.getLogger('dingwatch').error(f"Error sending DingTalk message: {e}")
            return {"errcode": -1, "errmsg": str(e), "request_payload": payload}

    def send_text(self, text: str, webhook_url: str, secret: str, access_token: str, at_mobiles: List[str] = None):
        if not webhook_url or not secret or not access_token:
            return {"errcode": -1, "errmsg": "DingTalk configuration missing"}
        timestamp, sign = self._sign(secret)
        base_url = webhook_url.split("?")[0]
        url = f"{base_url}?access_token={access_token}&timestamp={timestamp}&sign={sign}"
        payload = {
            "msgtype": "text",
            "text": {
                "content": text
            },
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": False
            }
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return {"response": response.json(), "request_payload": payload}
        except Exception as e:
            import logging
            logging.getLogger('dingwatch').error(f"Error sending DingTalk text message: {e}")
            return {"errcode": -1, "errmsg": str(e), "request_payload": payload}

dingtalk_client = DingTalkClient()
