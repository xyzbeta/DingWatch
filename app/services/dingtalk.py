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

    def send_text(self, text: str, webhook_url: str, secret: str, access_token: str, at_mobiles: List[str] = None, at_all: bool = False):
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
                "isAtAll": at_all
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
