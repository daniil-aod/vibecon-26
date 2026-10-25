# Driver link landing page (/api/open/{tok}): Expo Go fallback button, Android intent fallback, noapp mode
import os
import re
from urllib.parse import unquote
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
# Host from the review request (alias routed to this same backend)
ALIAS_URL = "https://e38e91c9-2f90-4132-abe8-9e55b84b1985.preview.emergentagent.com"
TOK = "15fea12acebc17d44921caaad2101f5bd5b231f6"  # TEST-0001


def _href(html, testid):
    m = re.search(r'<a [^>]*data-testid="%s"[^>]*href="([^"]+)"' % testid, html)
    return m.group(1).replace("&amp;", "&") if m else None


def _js_var(html, name):
    m = re.search(r'%s="([^"]+)"' % name, html)
    return m.group(1) if m else None


@pytest.fixture(params=[BASE_URL, ALIAS_URL], ids=["own-host", "alias-host"])
def host(request):
    return request.param


class TestOpenPage:
    def test_valid_page_buttons(self, host):
        r = requests.get(f"{host}/api/open/{TOK}", timeout=20)
        assert r.status_code == 200
        h = r.text
        assert 'data-testid="open-app-button"' in h
        assert 'data-testid="open-expo-go-box"' in h
        assert 'data-testid="open-load-number">TEST-0001<' in h
        origin = host.rstrip("/")
        expo = _href(h, "open-expo-go-button")
        assert expo is not None
        assert expo.startswith("exps://load-locator-4.preview.emergentagent.com/--/d/" + TOK + "?api=")
        assert unquote(expo.split("?api=")[1]) == origin
        deep = _href(h, "open-app-button")
        assert deep.startswith(f"dockclock://d/{TOK}?api=")
        assert unquote(deep.split("?api=")[1]) == origin

    def test_intent_fallback_and_autoredirect(self, host):
        h = requests.get(f"{host}/api/open/{TOK}", timeout=20).text
        intent = _js_var(h, "intent")
        assert intent.startswith(f"intent://d/{TOK}?api=")
        assert "#Intent;scheme=dockclock;" in intent and intent.endswith(";end")
        fb = re.search(r"S\.browser_fallback_url=([^;]+);", intent).group(1)
        assert unquote(fb) == f"{host.rstrip('/')}/api/open/{TOK}?noapp=1"
        assert "setTimeout(function(){window.location.href=href},300)" in h

    def test_noapp_disables_autoredirect(self, host):
        r = requests.get(f"{host}/api/open/{TOK}?noapp=1", timeout=20)
        assert r.status_code == 200
        h = r.text
        assert "setTimeout" not in h
        assert 'data-testid="open-app-button"' in h
        assert 'data-testid="open-expo-go-button"' in h
        assert "getElementById('open-btn').href=href" in h

    def test_invalid_token_404(self, host):
        r = requests.get(f"{host}/api/open/notarealtoken000000000000", timeout=20)
        assert r.status_code == 404
        assert 'data-testid="open-invalid"' in r.text
        assert "open-expo-go" not in r.text
        assert "setTimeout" not in r.text
