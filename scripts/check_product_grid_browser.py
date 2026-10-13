"""Check rendered storefront grids with an in-memory database and headless Chrome."""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bramanda.settings")
import django
from django.conf import settings

settings.DATABASES["default"]["NAME"] = ":memory:"
settings.ALLOWED_HOSTS = ["testserver"]
django.setup()
from check_homepage_browser import DevTools
from django.core.management import call_command
from django.test import Client

from products.models import Category, Color, Product, ProductVariant, Size


def main():
    call_command("migrate", verbosity=0)
    category = Category.objects.create(name="Essentials")
    color = Color.objects.create(name="Black")
    size = Size.objects.create(name="M")
    pages = {}
    client = Client()
    for count in (0, 1, 2, 3, 4, 6):
        while Product.objects.count() < count:
            index = Product.objects.count()
            product = Product.objects.create(
                name=(
                    "Everyday essential"
                    if index % 2
                    else "A longer product name with several words"
                )
                + f" {index}",
                category=category,
                price=845 + index,
                featured=True,
                image=(
                    "products/l_death_note.png"
                    if index % 2
                    else "products/Screenshot_2026-10-07_123431.png"
                ),
            )
            ProductVariant.objects.create(
                product=product,
                color=color,
                size=size,
                sku=f"GRID-{index}",
                stock_quantity=index % 2,
            )
        for page, url in (("home", "/"), ("shop", "/shop/")):
            response = client.get(url)
            assert response.status_code == 200
            pages[f"/{page}-{count}"] = response.content

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def do_GET(self):
            if self.path in pages:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(pages[self.path])
            else:
                super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def handle_error(request, address):
        if not isinstance(sys.exception(), (ConnectionResetError, BrokenPipeError)):
            ThreadingHTTPServer.handle_error(server, request, address)

    server.handle_error = handle_error
    threading.Thread(target=server.serve_forever, daemon=True).start()
    artifacts = Path(tempfile.mkdtemp(prefix="bramanda-grid-"))
    chrome = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe"
    )
    process = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--remote-debugging-port=9226",
            f'--user-data-dir={artifacts / "chrome-profile"}',
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    browser = None
    try:
        for _ in range(50):
            try:
                targets = json.load(urlopen("http://127.0.0.1:9226/json", timeout=1))
                target = next(t for t in targets if t["type"] == "page")
                break
            except (OSError, StopIteration):
                time.sleep(0.2)
        else:
            raise RuntimeError(
                "Headless Chrome did not start; run with browser execution permissions."
            )
        browser = DevTools(target["webSocketDebuggerUrl"])
        browser.call("Page.enable")
        for width in (1440, 1024, 768, 390, 320):
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                dict(width=width, height=1000, deviceScaleFactor=1, mobile=False),
            )
            for count in (0, 1, 2, 3, 4, 6):
                for page in ("home", "shop"):
                    path = f"/{page}-{count}"
                    browser.call(
                        "Page.navigate",
                        {"url": f"http://127.0.0.1:{server.server_port}{path}"},
                    )
                    for _ in range(100):
                        if browser.evaluate(
                            f"location.pathname === '{path}' && document.readyState === 'complete'"
                        ):
                            break
                        time.sleep(0.05)
                    browser.evaluate(
                        "document.documentElement.style.scrollBehavior='auto'; document.querySelector('.home-edit, .product-grid').scrollIntoView(); document.querySelectorAll('img').forEach(i => i.loading = 'eager')"
                    )
                    browser.call(
                        "Input.dispatchMouseEvent",
                        {"type": "mouseMoved", "x": 0, "y": 0},
                    )
                    for _ in range(100):
                        if browser.evaluate(
                            "[...document.images].every(i=>i.complete && i.naturalWidth>0)"
                        ):
                            break
                        time.sleep(0.05)
                    metrics = browser.evaluate("""(() => {
                        const grid = document.querySelector('.home-products, .product-grid');
                        const cards = [...grid.querySelectorAll('.product-card')];
                        const rect = el => {const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
                        return {overflow:document.documentElement.scrollWidth > innerWidth,
                            columns:getComputedStyle(grid).gridTemplateColumns.split(' ').length,
                            gap:getComputedStyle(grid).gap, cards:cards.map(rect),
                            images:cards.map(c => rect(c.querySelector('.product-image'))),
                            loaded:[...document.images].every(i=>i.complete && i.naturalWidth>0)};
                    })()""")
                    assert not metrics["overflow"], (width, page, count, metrics)
                    assert metrics["loaded"], (width, page, count, metrics)
                    assert len(metrics["cards"]) == (
                        min(count, 4) if page == "home" else count
                    )
                    if page == "shop":
                        expected = 3 if width >= 1200 else 2 if width > 480 else 1
                        assert metrics["columns"] == expected, (width, count, metrics)
                    for card, image in zip(metrics["cards"], metrics["images"]):
                        assert abs(card["width"] - image["width"]) < 1
                        assert (
                            (300 <= image["height"] <= 370)
                            if width <= 480
                            else (350 <= image["height"] <= 430)
                        )
                    if page == "shop" and count == 3 and width == 1440:
                        assert (
                            max(c["y"] for c in metrics["cards"])
                            - min(c["y"] for c in metrics["cards"])
                            < 4
                        ), metrics
                    browser.evaluate(
                        "document.querySelector('.home-edit, .product-grid').scrollIntoView()"
                    )
                    screenshot = browser.call(
                        "Page.captureScreenshot", {"format": "png"}
                    )
                    (artifacts / f"{page}-{count}-{width}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )
            print(f"PASS {width}px: both pages, product counts 0, 1, 2, 3, 4, 6")
        print(f"Screenshots: {artifacts}")
    finally:
        if browser:
            browser.sock.close()
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()


if __name__ == "__main__":
    main()
