"""No evasion code anywhere on the actuation path.

The CAPTCHA and bot-detection audit found no bypass feature in this repository, so
there was nothing to delete here. These tests keep it that way. They read the
source, not the behaviour, because evasion code can sit unused and still ship.

Each scan is a plain function that the negative controls at the bottom run
against planted source text, so a scan that silently matches nothing fails.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "accountable_surface"

DRIVER_MODULES = (
    "playwright_driver.py", "http_driver.py", "browser_effector.py", "web_effector.py",
    "uia_transport.py", "uia_effector.py", "native_control_effector.py", "os_effector.py",
    "api_transport.py", "api_effector.py", "page_evidence.py",
)
EVASION_STRINGS = (
    "automationcontrolled", "disable-blink-features", "navigator.webdriver", "add_init_script",
    "user_agent", "useragent", "user-agent-override", "stealth", "fingerprint_diversif",
    "humaniz", "captcha_solve", "solve_captcha", "recaptcha_token",
)
EVASION_PARAMS = frozenset({
    "user_agent", "proxy", "proxies", "headers", "cookies", "fingerprint", "stealth",
    "impersonate", "captcha", "solver", "jitter", "humanize",
})
EVASION_PACKAGES = (
    "curl_cffi", "curl-cffi", "undetected", "playwright-stealth", "playwright_stealth",
    "selenium-stealth", "selenium_stealth", "puppeteer-extra", "cloudscraper", "tls_client",
    "tls-client", "2captcha", "twocaptcha", "anticaptcha", "anti-captcha", "capsolver",
    "capmonster", "deathbycaptcha", "gather.backends_stealth",
)


def launch_violations(source: str) -> list[str]:
    """Browser launch calls may pass `headless` and nothing else."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("launch", "launch_persistent_context"):
            extra = [kw.arg for kw in node.keywords if kw.arg != "headless"]
            if node.args or extra:
                out.append(f"launch with {extra or 'positional args'}")
    return out


def _docstring_ids(tree) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def string_violations(source: str) -> list[str]:
    """Code only: string constants and identifiers. Docstrings and comments are
    skipped, because the refusal code documents the verbs it refuses."""
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    words = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            words.append(node.value)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        elif isinstance(node, ast.arg):
            words.append(node.arg)
    lowered = " ".join(words).lower()
    return [s for s in EVASION_STRINGS if s in lowered]


# The API transport seam takes the request headers the effector builds from one
# declared service (the credential header read by require_secret). The agent hands
# in an intent and cannot set a header, so this one parameter is not a caller knob.
ALLOWED_PARAMS = frozenset({"request(headers)"})


def param_violations(source: str, allowed: frozenset = frozenset()) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [a.arg for a in node.args.args + node.args.kwonlyargs]
            out += [f"{node.name}({n})" for n in names if n in EVASION_PARAMS]
    return [v for v in out if v not in allowed]


def jitter_violations(source: str) -> list[str]:
    """No random module, and no sleep whose duration is computed at run time."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            out += [f"import {n}" for n in names if n.split(".")[0] == "random"]
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "sleep":
            if node.args and not isinstance(node.args[0], ast.Constant):
                out.append("sleep with a computed duration")
    return out


def package_violations(text: str) -> list[str]:
    lowered = text.lower()
    return [pkg for pkg in EVASION_PACKAGES if pkg in lowered]


def _driver_sources():
    return {name: (SRC / name).read_text(encoding="utf-8") for name in DRIVER_MODULES}


def test_browser_launch_carries_no_stealth_arguments():
    source = (SRC / "playwright_driver.py").read_text(encoding="utf-8")
    assert "chromium.launch(" in source, "the launch call moved; point this test at it"
    assert launch_violations(source) == []


def test_driver_modules_carry_no_evasion_strings():
    assert {n: string_violations(s) for n, s in _driver_sources().items() if string_violations(s)} == {}


def test_no_user_agent_proxy_or_header_parameters_on_driver_callables():
    def allowed(name):
        return ALLOWED_PARAMS if name in ("api_transport.py", "api_effector.py") else frozenset()
    found = {n: param_violations(s, allowed(n)) for n, s in _driver_sources().items()}
    assert {n: v for n, v in found.items() if v} == {}
    # the allowance is narrow: the browser and web drivers get none of it
    assert param_violations("def request(self, method, url, headers, body): pass") == ["request(headers)"]


def test_no_random_delays_in_drivers():
    assert {n: jitter_violations(s) for n, s in _driver_sources().items() if jitter_violations(s)} == {}


def test_no_solver_or_stealth_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = list(project.get("dependencies", []))
    pins += [p for deps in project.get("optional-dependencies", {}).values() for p in deps]
    assert package_violations("\n".join(pins)) == []
    imports = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
    assert package_violations("\n".join(imports)) == []


# --- negative controls: each scan must catch a planted violation -------------

PLANTED_LAUNCH = (
    "async def go(p):\n"
    "    b = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])\n"
)
PLANTED_DRIVER = (
    "import random\nimport time\n"
    "def fetch(url, user_agent=None, proxy=None):\n"
    "    time.sleep(random.uniform(0.2, 1.1))\n"
    "    page.add_init_script('Object.defineProperty(navigator, \"webdriver\", {get: () => undefined})')\n"
)


def test_planted_launch_argument_is_caught():
    assert launch_violations(PLANTED_LAUNCH) == ["launch with ['args']"]
    assert "automationcontrolled" in string_violations(PLANTED_LAUNCH)


def test_planted_driver_evasion_is_caught():
    assert param_violations(PLANTED_DRIVER) == ["fetch(user_agent)", "fetch(proxy)"]
    assert jitter_violations(PLANTED_DRIVER) == ["import random", "sleep with a computed duration"]
    assert "add_init_script" in string_violations(PLANTED_DRIVER)


def test_planted_dependency_is_caught():
    assert package_violations('curl_cffi>=0.7\nplaywright-stealth\n2captcha-python') == [
        "curl_cffi", "playwright-stealth", "2captcha"]
    assert re.search("gather.backends_stealth", "from gather.backends_stealth import x")
    assert package_violations("from gather.backends_stealth import x") == ["gather.backends_stealth"]
