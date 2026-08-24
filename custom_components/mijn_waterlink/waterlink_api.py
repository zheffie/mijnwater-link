import requests
import hashlib
import base64
import secrets
import re
import logging

_LOGGER = logging.getLogger(__name__)

class WaterlinkClient:
    def __init__(self, username, password, client_id, meter_id):
        self.username = username
        self.password = password
        self.client_id = client_id
        self.meter_id = meter_id
        self.session = requests.Session()
        self.token = None

    def _generate_pkce(self):
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        return verifier, challenge

    def authenticate(self):
        verifier, challenge = self._generate_pkce()
        redirect = "https://portaaldigitalemeters.water-link.be"
        self.session = requests.Session()
        self.session.get(redirect)
        state = secrets.token_hex(16)

        authorize_url = (
            f"https://a5xhcq3r8.accounts.ondemand.com/oauth2/authorize"
            f"?client_id={self.client_id}&redirect_uri={redirect}&response_type=code"
            f"&scope=openid&state={state}&code_challenge={challenge}"
            f"&code_challenge_method=S256&response_mode=query"
        )

        resp = self.session.get(authorize_url)

        def extract(field, text, regex):
            match = re.search(regex, text)
            if not match:
                raise ValueError(f"Missing {field} in auth form")
            return match.group(1)

        token = extract("authenticity_token", resp.text, r'name="authenticity_token" value="([^"]+)"')
        xsrf = extract("xsrfProtection", resp.text, r'name="xsrfProtection" value="([^"]+)"')
        relaystate = extract("RelayState", resp.text, r'name="RelayState" value="([^"]+)"')
        spid = extract("spId", resp.text, r"name='spId' type='hidden' value='([^']+)'")
        target_url = extract("targetUrl", resp.text, r"name='targetUrl' type='hidden' value='([^']+)'")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0"
        }

        post_resp = self.session.post(authorize_url, data={
            "j_username": self.username,
            "j_password": self.password,
            "authenticity_token": token,
            "xsrfProtection": xsrf,
            "RelayState": relaystate,
            "spId": spid,
            "targetUrl": target_url,
            "method": "GET",
            "idpSSOEndpoint": authorize_url,
            "sp": "DIP Front-end",
            "spName": "DIP Front-end",
            "sourceUrl": "",
            "org": "",
            "mobileSSOToken": "",
            "tfaToken": "",
            "css": "",
            "passwordlessAuthnSelected": "",
            "utf8": "✓"
        }, headers=headers, allow_redirects=False)

        _LOGGER.debug(f"Login POST status: {post_resp.status_code}")
        _LOGGER.debug(f"Login POST headers: {post_resp.headers}")

        location = post_resp.headers.get("Location")
        if not location:
            _LOGGER.debug(post_resp.text)  # useful to see error page
            raise ValueError("No redirect location with authorization code")
        match = re.search(r"code=([^&]+)", location)
        if not match:
            raise ValueError("Authorization code not found in redirect")
        code = match.group(1)

        token_resp = self.session.post("https://a5xhcq3r8.accounts.ondemand.com/oauth2/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "client_id": self.client_id
        }, headers=headers)

        token_data = token_resp.json()
        self.token = token_data.get("access_token")
        if not self.token:
            raise ValueError("Failed to retrieve access token")

    def get_meter_data(self):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "Mozilla/5.0"
        }
        url = f"https://portaaldigitalemeters.water-link.be/api/meters/{self.meter_id}"
        resp = self.session.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_daily_measurements(self, from_date):
        """Fetch the daily usage measurements starting at from_date (a date object)."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "Mozilla/5.0"
        }
        url = "https://portaaldigitalemeters.water-link.be/api/measurements/day"
        params = {
            "from": from_date.isoformat(),
            "meterNumber": self.meter_id,
        }
        resp = self.session.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()
