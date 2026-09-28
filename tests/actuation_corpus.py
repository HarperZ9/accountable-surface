"""Local fixture corpora for the actuation policy tests.

Every page here is a string. None references a remote script, stylesheet, image,
or frame source, so parsing or serving one reaches nothing off the machine.
The challenge pages imitate the markers a real challenge carries; the benign
pages are built to sit close to them (prose about robots, security settings,
the phrase "just a moment" in a paragraph) so a detector that matches too
loosely fails the false-stop budget.
"""

from __future__ import annotations


def page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


CHALLENGE_PAGES = [
    ("recaptcha-div", page("Sign up", "<form><div class='g-recaptcha' data-sitekey='fixture'></div><button>Go</button></form>"), 200, {}),
    ("hcaptcha-div", page("Log in", "<div class='h-captcha' data-sitekey='fixture'></div>"), 200, {}),
    ("turnstile-div", page("Comments", "<div class='cf-turnstile'></div><textarea name='c'></textarea>"), 200, {}),
    ("sitekey-only", page("Contact", "<div data-sitekey='fixture'></div>"), 200, {}),
    ("challenge-form-id", page("Loading", "<form id='challenge-form'></form>"), 200, {}),
    ("frame-title-recaptcha", page("Checkout", "<iframe title='reCAPTCHA' src='about:blank'></iframe>"), 200, {}),
    ("frame-title-challenge", page("Store", "<iframe title='Widget containing a security challenge' src='about:blank'></iframe>"), 200, {}),
    ("title-just-a-moment", page("Just a moment...", "<p>Please wait.</p>"), 200, {}),
    ("title-attention", page("Attention Required! | Example", "<p>Sorry.</p>"), 200, {}),
    ("text-verify-human", page("Example", "<h1>Verify you are human by completing the action below.</h1>"), 200, {}),
    ("text-curly-not-robot", page("Example", "<label>I’m not a robot</label>"), 200, {}),
    ("text-i-am-not-robot", page("Example", "<p>I am not a robot</p>"), 200, {}),
    ("text-are-you-robot", page("Example", "<h2>Are you a robot?</h2>"), 200, {}),
    ("text-press-hold", page("Example", "<p>Press and hold the button to confirm.</p>"), 200, {}),
    ("text-unusual-traffic", page("Sorry", "<p>Our systems have detected unusual traffic from your computer network.</p>"), 200, {}),
    ("text-security-check", page("Example", "<p>Please complete the security check to access example.test</p>"), 200, {}),
    ("text-checking-browser", page("Example", "<p>Checking your browser before accessing example.test.</p>"), 200, {}),
    ("text-prove-human", page("Example", "<p>Prove you're human</p>"), 200, {}),
    ("control-not-robot", page("Example", "<input type='checkbox' id='cb'><label for='cb'>I'm not a robot</label>"), 200, {}),
    ("input-named-captcha", page("Register", "<input name='captcha_answer'>"), 200, {}),
    ("class-captcha-image", page("Register", "<img class='captcha-image' alt=''>"), 200, {}),
    ("http-403-mitigated", page("", ""), 403, {"cf-mitigated": "challenge"}),
    ("http-503-moment", page("Just a moment...", "<noscript>Enable JavaScript</noscript>"), 503, {}),
    ("arkose-container", page("Sign in", "<div id='arkose-enforcement'></div>"), 200, {}),
    ("geetest-container", page("Sign in", "<div class='geetest_panel'></div>"), 200, {}),
    ("text-human-verification", page("Example", "<p>Human verification required</p>"), 200, {}),
    ("text-select-images", page("Example", "<p>Select all images with traffic lights</p>"), 200, {}),
]

_PROSE = [
    "Our new robot vacuum maps the living room in one pass.",
    "The robotics club meets on Thursday in room 204.",
    "I, Robot is a 2004 film loosely based on a story collection.",
    "A robots.txt file tells crawlers which paths to skip.",
    "Are you a robotics hobbyist? Join the forum.",
    "Human-centered design starts with interviews.",
    "Verify your email address to finish setting up the account.",
    "Security settings let you turn on two-step sign in.",
    "Check your browser version under Help, then About.",
    "Press the button and hold it for three seconds to reset the router.",
    "Traffic was unusual on the bridge this morning after the storm.",
    "Just a moment ago the team shipped the new release.",
    "Attention to detail is what separates a good edit from a great one.",
    "The challenge this quarter is shipping fewer, better features.",
    "Run a security check on your laptop once a month.",
    "Our bot answers questions about opening hours.",
    "The human resources team is hiring two recruiters.",
    "Images are resized to fit the gallery width.",
    "Select all the files you want to upload, then press Open.",
    "Captions are available for every video in the archive.",
    "The capture card records at sixty frames per second.",
    "Cloudflare and other CDNs cache static assets close to readers.",
    "The turnstile at the station takes contactless cards.",
    "Weekly notes: the migration finished and the dashboards are green.",
    "Recipe: two cups of flour, one egg, a pinch of salt.",
]
_LAYOUTS = [
    lambda i, p: page(f"Article {i}", f"<article><h1>Post {i}</h1><p>{p}</p></article>"),
    lambda i, p: page(f"Form {i}", f"<form action='/save'><label for='t{i}'>Title</label><input id='t{i}' name='title'>"
                                   f"<textarea name='body'></textarea><button>Save</button></form><p>{p}</p>"),
    lambda i, p: page(f"Nav {i}", f"<nav><a href='/'>Home</a><a href='/about'>About</a><a href='/help'>Help</a></nav><p>{p}</p>"),
    lambda i, p: page(f"Table {i}", f"<table><tr><th>Item</th><td>{p}</td></tr></table>"
                                    f"<input type='checkbox' id='k{i}'><label for='k{i}'>Remember me</label>"),
]
BENIGN_PAGES = [
    (f"benign-{li}-{pi}", layout(pi, prose), 200, {})
    for li, layout in enumerate(_LAYOUTS) for pi, prose in enumerate(_PROSE)
] + [
    ("benign-login", page("Sign in", "<form><label for='u'>Email</label><input id='u' type='email'>"
                                     "<label for='p'>Password</label><input id='p' type='password'><button>Sign in</button></form>"), 200, {}),
    ("benign-404", page("Not found", "<p>That page does not exist.</p>"), 404, {}),
    ("benign-403-plain", page("Forbidden", "<p>You do not have access to this folder.</p>"), 403, {}),
    ("benign-429-plain", page("Too many requests", "<p>Slow down and try again later.</p>"), 429, {}),
]
