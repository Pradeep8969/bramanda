"""Render existing pages in an isolated in-memory DB and audit six Chrome widths.

No production database, OAuth, payment network, or form submissions are used.
Run with --output PATH; --screenshots writes representative full-page captures.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bramanda.settings")
import django
from django.conf import settings

settings.DATABASES["default"]["NAME"] = ":memory:"
settings.ALLOWED_HOSTS = ["testserver", "127.0.0.1"]
settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
django.setup()
from check_homepage_browser import DevTools
from django import forms
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from cart.models import Cart, CartItem
from dashboard.models import StaffActivity
from orders.models import Order, OrderItem
from payments.models import Payment
from products.models import Category, Color, Product, ProductVariant, Size


def fixture_pages():
    call_command("migrate", verbosity=0)
    users = get_user_model().objects
    owner = users.create_user(username="layout-owner", role="OWNER")
    staff = users.create_user(username="layout-staff", role="STAFF")
    customer = users.create_user(
        username="layout-customer",
        first_name="Asha",
        last_name="Rai",
        email="asha@example.com",
        phone_number="9800000001",
        address="Kathmandu",
    )
    category = Category.objects.create(name="Essentials")
    color = Color.objects.create(name="Black")
    size = Size.objects.create(name="M")
    products, variants = [], []
    for n in range(8):
        product = Product.objects.create(
            name=f"Everyday essential {n + 1}",
            category=category,
            price=845,
            featured=True,
            description="Premium everyday comfort. Independent direction.",
            image=[
                "products/l_death_note.png",
                "products/1.png",
                "products/Screenshot_2026-10-07_123431.png",
            ][n % 3],
        )
        products.append(product)
        variants.append(
            ProductVariant.objects.create(
                product=product,
                color=color,
                size=size,
                sku=f"LAYOUT-{n + 1}",
                stock_quantity=12,
            )
        )
    order = Order.objects.create(
        customer=customer,
        first_name="Asha",
        last_name="Rai",
        email=customer.email,
        phone_number=customer.phone_number,
        shipping_address=customer.address,
        subtotal=845,
        shipping_cost=100,
        grand_total=945,
        payment_method="ESEWA",
        payment_status="PAID",
    )
    OrderItem.objects.create(
        order=order,
        product=products[0],
        variant=variants[0],
        product_name=products[0].name,
        color_name="Black",
        size_name="M",
        sku=variants[0].sku,
        quantity=1,
        unit_price=845,
        subtotal=845,
    )
    payment = Payment.objects.create(
        order=order, payment_method="ESEWA", status="PAID", amount=945
    )
    for action in StaffActivity.Action.values:
        StaffActivity.objects.create(
            staff=staff,
            action=action,
            reference=order.order_number,
            description="Layout fixture: stock, fulfillment and delivery activity.",
        )
    pages, manifest = {}, []
    client = Client()

    def add(name, url, expected=200):
        response = client.get(url)
        if response.status_code != expected:
            raise AssertionError((name, url, response.status_code))
        pages["/audit/" + name] = response.content
        manifest.append({"page": name, "url": url, "status": response.status_code})

    for name, url in [
        ("home", "/"),
        ("shop", "/shop/"),
        ("search", "/shop/?q=Everyday"),
        ("new-arrivals", "/shop/?sort=newest"),
        ("shop-empty", "/shop/?q=not-found"),
        ("login", "/login/"),
        ("registration", "/register/"),
        ("allauth-login", "/accounts/login/"),
        ("allauth-registration", "/accounts/signup/"),
        ("product", reverse("products:detail", args=[products[0].slug])),
    ]:
        add(name, url)
    # Small collections: preserve their real image proportions without giant cards.
    for count in (0, 1, 2, 3):
        Product.objects.all().update(is_active=False)
        Product.objects.filter(pk__in=[p.pk for p in products[:count]]).update(
            is_active=True
        )
        add(f"home-{count}", "/")
        add(f"shop-{count}", "/shop/")
    Product.objects.all().update(is_active=True)
    client.force_login(customer)
    add("cart-empty", "/cart/")
    cart, _ = Cart.objects.get_or_create(user=customer)
    CartItem.objects.create(cart=cart, variant=variants[0], quantity=2)
    CartItem.objects.create(cart=cart, variant=variants[1], quantity=1)
    for name, url in [
        ("cart", "/cart/"),
        ("checkout", "/checkout/"),
        ("profile", "/profile/"),
        ("my-orders", "/orders/"),
        ("order-detail", reverse("orders:detail", args=[order.order_number])),
        ("confirmation", reverse("orders:success", args=[order.order_number])),
    ]:
        add(name, url)
    add("payment-result", reverse("payments:result", args=[payment.transaction_uuid]))
    add("invoice", reverse("payments:invoice", args=[order.order_number]))
    add("receipt", reverse("payments:receipt", args=[order.order_number]))
    order.payment_status = "PENDING"
    order.save()
    payment.status = "PENDING"
    payment.save()
    add("payment-pay", reverse("payments:pay", args=[payment.transaction_uuid]))
    order.payment_status = "PAID"
    order.save()
    payment.status = "PAID"
    payment.save()
    request = client.get("/profile/").wsgi_request

    class SocialSignupFixture(forms.Form):
        email = forms.EmailField()
        username = forms.CharField()

    pages["/audit/social-signup"] = render_to_string(
        "socialaccount/signup.html", {"form": SocialSignupFixture()}, request=request
    ).encode()
    manifest.append(
        {"page": "social-signup", "url": "(social signup template)", "status": 200}
    )
    pages["/audit/payment-error"] = render_to_string(
        "payments/error.html",
        {"error": "Payment verification unavailable."},
        request=request,
    ).encode()
    manifest.append({"page": "payment-error", "url": "(error template)", "status": 400})
    for role, user in [("owner", owner), ("staff", staff)]:
        client.force_login(user)
        prefix = "/owner" if role == "owner" else "/staff"
        routes = [
            ("", "dashboard"),
            ("/inventory/", "inventory"),
            ("/orders/", "orders"),
            ("/customers/", "customers"),
            (f"/orders/{order.order_number}/", "order-detail"),
        ]
        if role == "owner":
            routes += [
                ("/reports/", "reports"),
                ("/staff/", "staff"),
                ("/staff/add/", "staff-add"),
                (f"/staff/{staff.pk}/edit/", "staff-edit"),
                ("/payments/", "payments"),
                ("/activity/", "activity"),
            ]
            for kind, obj in [
                ("products", products[0]),
                ("categories", category),
                ("colors", color),
                ("sizes", size),
                ("variants", variants[0]),
            ]:
                routes += [
                    (f"/{kind}/", kind),
                    (f"/{kind}/add/", kind + "-add"),
                    (f"/{kind}/{obj.pk}/edit/", kind + "-edit"),
                ]
        for path, name in routes:
            add(f"{role}-{name}", prefix + (path or "/"))
        add(f"{role}-inventory-empty", prefix + "/inventory/?q=not-found")
        add(f"{role}-orders-empty", prefix + "/orders/?q=not-found")
    # Empty order history, without deleting any fixture records.
    empty_user = users.create_user(username="layout-empty")
    client.force_login(empty_user)
    add("orders-empty", "/orders/")
    return pages, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument(
        "--widths", nargs="+", type=int, default=[1920, 1440, 1024, 768, 390, 320]
    )
    parser.add_argument(
        "--pages", nargs="+", help="Optional rendered page names for focused rechecks"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pages, manifest = fixture_pages()
    if args.pages:
        manifest = [item for item in manifest if item["page"] in args.pages]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path in pages:
                data, content_type = pages[path], "text/html; charset=utf-8"
            elif path.startswith(("/static/", "/media/")):
                asset = (ROOT / path.lstrip("/")).resolve()
                allowed = (
                    ROOT / ("static" if path.startswith("/static/") else "media")
                ).resolve()
                if not asset.is_relative_to(allowed) or not asset.is_file():
                    self.send_error(404)
                    return
                import mimetypes

                data, content_type = (
                    asset.read_bytes(),
                    mimetypes.guess_type(asset)[0] or "application/octet-stream",
                )
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    chrome = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe"
    )
    profile = tempfile.TemporaryDirectory(prefix="bramanda-layout-chrome-")
    process = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--remote-debugging-port=9227",
            f"--user-data-dir={profile.name}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    browser, results = None, []
    try:
        for _ in range(50):
            try:
                targets = json.load(urlopen("http://127.0.0.1:9227/json", timeout=1))
                target = next(t for t in targets if t["type"] == "page")
                break
            except (OSError, StopIteration):
                time.sleep(0.2)
        else:
            raise RuntimeError("Headless Chrome could not start.")
        browser = DevTools(target["webSocketDebuggerUrl"])
        browser.call("Page.enable")
        browser.call("Network.enable")
        browser.call(
            "Network.setBlockedURLs", {"urls": ["https://*", "http://*.esewa.com.np/*"]}
        )
        for width in args.widths:
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                dict(width=width, height=1000, deviceScaleFactor=1, mobile=False),
            )
            for item in manifest:
                page = item["page"]
                path = "/audit/" + page
                browser.call(
                    "Page.navigate",
                    {"url": f"http://127.0.0.1:{server.server_port}{path}"},
                )
                for _ in range(100):
                    if browser.evaluate(
                        f"location.pathname === '{path}' && document.readyState === 'complete'"
                    ):
                        break
                    time.sleep(0.02)
                browser.evaluate(
                    "document.documentElement.style.scrollBehavior='auto'; document.querySelectorAll('img').forEach(i=>i.loading='eager')"
                )
                for _ in range(50):
                    if browser.evaluate("[...document.images].every(i=>i.complete)"):
                        break
                    time.sleep(0.02)
                # Wait for navigation drawer entrance styles to reach their settled state.
                time.sleep(0.28)
                metrics = browser.evaluate("""(() => {
                    const rect = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
                    const container = document.querySelector('.dashboard-content, main > section, .home-edit');
                    const grids = [...document.querySelectorAll('.product-grid, .home-products, .stats-grid, .staff-columns, .account-layout, .checkout-layout')];
                    const overflowing = [...document.querySelectorAll('main *')].filter(e => {
                        const r=e.getBoundingClientRect();
                        return r.width > 0 && (r.right > innerWidth + 1 || r.left < -1)
                          && !e.closest('.table-scroll, .owner-sidebar, #main-navigation')
                          && getComputedStyle(e).position !== 'absolute' && getComputedStyle(e).position !== 'fixed';
                    }).slice(0,8).map(e=>({tag:e.tagName,classes:e.className,...rect(e)}));
                    return {width:innerWidth, documentWidth:document.documentElement.scrollWidth,
                        height:document.documentElement.scrollHeight, container:container?rect(container):null,
                        overflowing, grids:grids.map(e=>({classes:e.className,columns:getComputedStyle(e).gridTemplateColumns,gap:getComputedStyle(e).gap,...rect(e)})),
                        tableScroll:[...document.querySelectorAll('.table-scroll')].map(e=>({width:e.clientWidth,scrollWidth:e.scrollWidth})),
                        cards:[...document.querySelectorAll('.product-card')].map(e=>({card:rect(e),image:rect(e.querySelector('.product-image'))})),
                        forms:document.forms.length, links:document.links.length,
                        inventoryInputWidth:document.querySelector('.inventory-quantity')?.getBoundingClientRect().width ?? null,
                        brokenImages:[...document.images].filter(e=>e.complete && !e.naturalWidth).map(e=>e.src)};
                })()""")
                metrics["interactions"] = {}
                if page in ("owner-inventory", "staff-inventory"):
                    metrics["interactions"]["inventory"] = browser.evaluate("""(() => {
                        const row=document.querySelector('[data-stock-row]'), input=row.querySelector('[name=quantity]'), button=row.querySelector('button');
                        const original=input.value, disabledBefore=button.disabled;
                        input.value=Number(original)+1; input.dispatchEvent(new Event('input', {bubbles:true}));
                        const changedEnabled=!button.disabled;
                        input.value=original; input.dispatchEvent(new Event('input', {bubbles:true}));
                        return disabledBefore && changedEnabled && button.disabled;
                    })()""")
                if page == "owner-dashboard" and width <= 1024:
                    metrics["interactions"]["ownerMenu"] = browser.evaluate("""(() => {
                        const toggle=document.querySelector('.owner-menu-toggle'); toggle.click();
                        const open=toggle.getAttribute('aria-expanded')==='true' && !document.querySelector('.owner-sidebar').inert;
                        document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                        return open && toggle.getAttribute('aria-expanded')==='false';
                    })()""")
                    time.sleep(0.28)
                if page == "shop" and width < 1200:
                    metrics["interactions"]["publicMenu"] = browser.evaluate("""(() => {
                        const toggle=document.querySelector('.menu-toggle'); toggle.click();
                        const open=toggle.getAttribute('aria-expanded')==='true';
                        document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                        return open && toggle.getAttribute('aria-expanded')==='false';
                    })()""")
                    time.sleep(0.28)
                results.append({"page": page, **metrics})
                if args.screenshots and (
                    width in (1440, 320)
                    or page
                    in {
                        "home",
                        "home-1",
                        "home-3",
                        "shop",
                        "shop-1",
                        "shop-3",
                        "product",
                        "login",
                        "registration",
                        "profile",
                        "cart",
                        "checkout",
                        "order-detail",
                        "owner-dashboard",
                        "owner-inventory",
                        "owner-products-add",
                        "owner-activity",
                        "staff-dashboard",
                        "staff-order-detail",
                        "payment-result",
                        "social-signup",
                    }
                ):
                    screenshot = browser.call(
                        "Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": True},
                    )
                    (args.output / f"{page}-{width}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )
            print(f"Checked {len(manifest)} pages at {width}px", flush=True)
        (args.output / "metrics.json").write_text(json.dumps(results, indent=2))
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        overflow = [r for r in results if r["documentWidth"] > r["width"]]
        failures = [
            (r["page"], r["width"], key)
            for r in results
            for key, value in r["interactions"].items()
            if not value
        ]
        broken = [
            (r["page"], r["width"], r["brokenImages"])
            for r in results
            if r["brokenImages"]
        ]
        print(
            json.dumps(
                {
                    "interactionFailures": failures,
                    "brokenImages": broken,
                    "pages": len(manifest),
                    "checks": len(results),
                    "overflow": [
                        (r["page"], r["width"], r["documentWidth"]) for r in overflow
                    ],
                    "output": str(args.output),
                }
            ),
            flush=True,
        )
        if overflow or failures or broken:
            raise AssertionError(
                "Layout audit found overflow, broken images or failed controls; see metrics.json"
            )
    finally:
        if browser:
            browser.sock.close()
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        try:
            profile.cleanup()
        except PermissionError:
            pass


if __name__ == "__main__":
    main()
