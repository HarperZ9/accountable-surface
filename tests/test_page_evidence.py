"""Page evidence: the structure the policy check reads, parsed from HTML only."""

from __future__ import annotations

import http.server
import socketserver
import threading

import pytest

from accountable_surface.http_driver import parse_html
from accountable_surface.page_evidence import capture, origin_of, parse_page

FORM = (
    "<html><head><title> Checkout </title><script>var secret = 'x';</script></head><body>"
    "<form action='/pay'><label for='cn'>Card number</label>"
    "<input id='cn' name='cardnumber' autocomplete='cc-number'>"
    "<input type='hidden' name='csrf' value='t'>"
    "<input type='password' name='pw'>"
    "<button>Pay now</button><button type='button'>Cancel</button>"
    "<input type='submit' value='Place order'></form>"
    "<a href='/help'>Help</a><iframe src='about:blank' title='frame'></iframe>"
    "<div class='g-recaptcha big' id='w1' data-sitekey='k'></div><p>Hello  there</p></body></html>"
)


def test_controls_carry_role_name_type_and_form_membership():
    ev = parse_page("http://127.0.0.1:9/checkout", FORM)
    got = [(c.role, c.name, c.input_type, c.in_form) for c in ev.controls]
    assert got == [
        ("textbox", "Card number", "", True),
        ("textbox", "pw", "password", True),
        ("button", "Pay now", "submit", True),
        ("button", "Cancel", "button", True),
        ("button", "Place order", "submit", True),
        ("link", "Help", "", False),
    ]
    assert ev.controls[0].attr("autocomplete") == "cc-number"
    assert ev.title == "Checkout" and "secret" not in ev.text and "Hello there" in ev.text
    assert ev.frames == (("about:blank", "frame"),)
    assert {"g-recaptcha", "big", "w1", "data-sitekey"} <= set(ev.markers)


def test_field_names_match_the_driver_that_fills_them():
    ev = parse_page("http://127.0.0.1:9/checkout", FORM)
    driver_fields = parse_html("http://127.0.0.1:9/checkout", FORM)["fields"]
    textboxes = {c.name for c in ev.controls if c.role == "textbox"}
    assert textboxes <= set(driver_fields)


def test_find_by_ref_or_unique_name_and_ambiguity_settles_nothing():
    ev = parse_page("http://127.0.0.1:9/x", "<button>Go</button><button>Go</button><a href='/a'>Home</a>")
    assert ev.find({"name": "Home", "role": "link"}).role == "link"
    assert ev.find({"name": "Go"}) is None
    assert ev.find({"ref": ev.controls[1].ref}) is ev.controls[1]
    assert ev.find(None) is None


def test_digest_moves_with_the_page_and_redactor_runs_on_text():
    a = parse_page("http://127.0.0.1:9/x", "<p>one</p>")
    b = parse_page("http://127.0.0.1:9/x", "<p>two</p>")
    assert a.digest != b.digest and a.digest.startswith("sha256:")
    red = parse_page("http://127.0.0.1:9/x", "<p>code 1234</p>", redactor=lambda t: (t.replace("1234", "[r]"), 1))
    assert red.text == "code [r]" and red.redactions == 1


def test_origin_is_scheme_and_host():
    assert origin_of("http://127.0.0.1:8765/form?a=1") == "http://127.0.0.1:8765"
    assert origin_of("not a url") == ""


@pytest.fixture
def server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/blocked":
                self.send_response(403)
                self.send_header("cf-mitigated", "challenge")
                self.end_headers()
                self.wfile.write(b"<title>Just a moment...</title>")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<title>Ok</title><input name='q'>")

        def log_message(self, *args):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_capture_reads_a_local_page_and_keeps_an_error_status(server):
    ok = capture(server + "/")
    assert (ok.http_status, ok.title, ok.channel) == (200, "Ok", "http-get")
    blocked = capture(server + "/blocked")
    assert blocked.http_status == 403 and blocked.header("cf-mitigated") == "challenge"


def test_capture_refuses_a_non_http_scheme():
    with pytest.raises(ValueError):
        capture("file:///etc/passwd")
