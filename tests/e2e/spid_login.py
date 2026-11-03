"""Login SPID end-to-end contro spid-saml-check (IdP demo), solo stdlib.

Emula il browser: /verifica/start → OIDC authorization → discovery → AuthnRequest
SAML all'IdP demo → login utente di test → SAMLResponse all'ACS → callback
/verifica (scambio code + userinfo lato config-api) → pagina risultato.

Gira in un container sulla rete interna dello stack (scripts/smoke-stack.sh,
SMOKE_E2E_SPID=true). Gli URL pubblici del proxy (https://<PROXY_HOSTNAME>)
vengono riscritti verso nginx; i cookie sono gestiti a mano, ignorando
l'attributo Secure (satosa_state è Secure, qui si parla HTTP).

Variabili: E2E_PUBLIC_BASE (https://localhost), E2E_NGINX (http://nginx:8080),
E2E_IDP_ENTITY (https://demo.spid.gov.it), E2E_USER / E2E_PASSWORD,
E2E_EXPECT (testo atteso nella pagina risultato, es. il codice fiscale),
E2E_SUBJECT (pf | pg), E2E_ALLOWED_HOSTS (host:porta ammessi, separati da virgola).
"""
import html.parser
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PUBLIC = os.environ.get("E2E_PUBLIC_BASE", "https://localhost").rstrip("/")
NGINX = os.environ.get("E2E_NGINX", "http://nginx:8080").rstrip("/")
IDP_ENTITY = os.environ.get("E2E_IDP_ENTITY", "https://demo.spid.gov.it")
USER = os.environ.get("E2E_USER", "ada")
PASSWORD = os.environ.get("E2E_PASSWORD", "password123")
EXPECT = os.environ.get("E2E_EXPECT", "")
SUBJECT = os.environ.get("E2E_SUBJECT", "pf")
MAX_STEPS = 40
# Host raggiungibili: il test non deve mai uscire dallo stack (es. verso il
# vero demo.spid.gov.it se il metadata dell'IdP fosse quello pubblico).
ALLOWED = {h for h in os.environ.get("E2E_ALLOWED_HOSTS", "").split(",") if h}

cookies: dict[str, dict[str, str]] = {}  # host → {name: value}


def log(msg: str) -> None:
    print(f"   {msg}", flush=True)


def fail(msg: str, body: str = "") -> None:
    print(f"::error::e2e SPID: {msg}", flush=True)
    if body:
        print(body[:3000], flush=True)
    sys.exit(1)


def rewrite(url: str) -> str:
    if url.startswith(PUBLIC + "/") or url == PUBLIC:
        return NGINX + url[len(PUBLIC):]
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)


def request(method: str, url: str, data: dict | None = None):
    url = rewrite(url)
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if ALLOWED and host not in ALLOWED:
        fail(f"richiesta verso host esterno allo stack: {url.split('?')[0]}")
    body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    jar = cookies.get(host, {})
    if jar:
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in jar.items()))
    try:
        resp = opener.open(req, timeout=30)
    except urllib.error.HTTPError as exc:
        resp = exc
    for header in resp.headers.get_all("Set-Cookie") or []:
        name, _, rest = header.partition("=")
        value = rest.split(";", 1)[0]
        cookies.setdefault(host, {})[name.strip()] = value
    text = resp.read().decode("utf-8", "replace")
    return resp.status, resp.headers.get("Location"), text, url


class Forms(html.parser.HTMLParser):
    """Raccoglie i form: action, method, campi (input/hidden/select/button)."""

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"action": a.get("action", ""), "method": (a.get("method") or "get").lower(),
                         "fields": [], "buttons": []}
            self.forms.append(self._cur)
        elif self._cur is not None and tag == "input" and a.get("name"):
            kind = (a.get("type") or "text").lower()
            if kind in ("submit", "button"):
                self._cur["buttons"].append((a["name"], a.get("value", "")))
            elif kind not in ("checkbox", "radio") or "checked" in a:
                self._cur["fields"].append((a["name"], a.get("value", "")))
        elif self._cur is not None and tag == "button" and a.get("name"):
            self._cur["buttons"].append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None


def forms_of(text: str) -> list[dict]:
    p = Forms()
    p.feed(text)
    return p.forms


def submit(form: dict, base_url: str, extra: dict | None = None, button: str | None = None):
    action = urllib.parse.urljoin(base_url, form["action"] or base_url)
    data = dict(form["fields"])
    if button:
        for name, value in form["buttons"]:
            if name == button or value == button:
                data[name] = value
    data.update(extra or {})
    if form["method"] == "post":
        return request("POST", action, data)
    sep = "&" if "?" in action else "?"
    return request("GET", action + sep + urllib.parse.urlencode(data))


def main() -> None:
    start = f"{PUBLIC}/verifica/start?level=2" + ("&subject=pg" if SUBJECT == "pg" else "")
    status, loc, text, url = request("GET", start)
    logged_in = False
    for step in range(MAX_STEPS):
        path = urllib.parse.urlsplit(url).path
        if status in (301, 302, 303, 307):
            if not loc:
                fail(f"redirect senza Location da {url}")
            nxt = urllib.parse.urljoin(url, loc)
            log(f"{status} → {nxt.split('?')[0]}")
            # Discovery: la pagina statica sceglie l'IdP e torna a "return" con
            # entityID; qui lo facciamo senza JavaScript.
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(nxt).query)
            if "/disco" in urllib.parse.urlsplit(nxt).path and "return" in q:
                ret = q["return"][0]
                param = q.get("returnIDParam", ["entityID"])[0]
                sep = "&" if "?" in ret else "?"
                nxt = ret + sep + urllib.parse.urlencode({param: IDP_ENTITY})
                log(f"discovery → {IDP_ENTITY}")
            status, loc, text, url = request("GET", nxt)
            continue
        if status >= 400:
            fail(f"HTTP {status} su {url}", text)

        if path.endswith("/verifica/callback"):
            if "token_exchange_failed" in text or "state_mismatch" in text:
                fail("pagina risultato con errore", text)
            if EXPECT and EXPECT not in text:
                fail(f"pagina risultato senza {EXPECT!r}", text)
            log("pagina risultato /verifica/callback OK")
            print("E2E SPID OK", flush=True)
            return

        forms = forms_of(text)
        if not forms:
            fail(f"pagina senza form né redirect: {url}", text)
        names = {n for f in forms for n, _ in f["fields"]}
        login_form = next((f for f in forms if f["action"].rstrip("/").endswith("/login")), None)
        if login_form and not logged_in:
            form = login_form
            log(f"login IdP demo come {USER}")
            logged_in = True
            status, loc, text, url = submit(form, url, {"username": USER, "password": PASSWORD})
            continue
        if "SAMLResponse" in names:
            form = next(f for f in forms if any(n == "SAMLResponse" for n, _ in f["fields"]))
            log(f"SAMLResponse → {form['action']}")
            status, loc, text, url = submit(form, url)
            continue
        # Altre pagine dell'IdP demo (caricamento, consenso): primo form, con il
        # pulsante di conferma se presente.
        form = forms[0]
        btn = next((n for n, v in form["buttons"] if "confirm" in (n + v).lower()), None)
        log(f"form → {form['action']}" + (f" ({btn})" if btn else ""))
        status, loc, text, url = submit(form, url, button=btn)
    fail(f"troppi passaggi, ultimo URL {url}", text)


if __name__ == "__main__":
    main()
