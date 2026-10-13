# Homepage editorial refresh

Uses the supplied homepage mockup as its visual reference: slim brand announcement,
wide hero, left-aligned headline, understated four-part value strip, product/edit
composition and two lower editorial panels. No fictional discounts, shipping
guarantees, collections, products or material specifications were added.

The homepage uses its own CSS, loaded through the base template's extra_css block.
Other pages retain their existing styles. Existing navigation, search link,
mobile menu, account links, cart count and footer links remain functional.

## Images

Only one live clothing photograph currently exists in the local catalog:
`media/products/Screenshot_2026-10-07_123431.png`. The view selects a real displayed
product photograph dynamically, not by that filename. The photograph supplies the
clothing-focused hero fallback and editorial detail panels. Empty catalogs or
products without images use neutral CSS backgrounds and existing placeholders.
The attached full-page mockup is a design reference, not a storefront image asset.

For the mountain/model composition, supply an approved, licensed BRAMANDA campaign
image at `static/images/home/hero-editorial.webp`. The view detects this optional
asset automatically. Recommended dimensions: approximately 2400 × 1100 pixels,
subject on the right and quiet landscape/negative space on the left. It must also
crop cleanly on mobile. A separate landscape/model photograph would improve the
New Perspective panel; its current visual is intentionally a neutral CSS treatment.
No new images were scraped, generated or fabricated.

## Data and checks

Featured active products lead the showcase. Remaining slots are filled by other
active real products, up to four, without duplicates. Category activity, variant
stock availability, database prices, images and product-detail routes are retained.
Zero through four products have explicit layout support. No schema migration or
payment/order/authentication service changes were required.

The full Django suite passed 398 tests. Existing notification/payment JavaScript
tests passed 14 tests. System and migration consistency checks passed. The former
featured-only homepage test was updated to expect the new real-product fallback.

Headless Chrome checked the live anonymous homepage at 1440, 1024, 768, 390 and
320 pixels: no horizontal overflow, loaded images, and functional mobile menu /
Escape dismissal. Desktop and mobile screenshots were inspected. Four-product
data cases are covered by Django tests; local screenshots use the current one-product
catalog. Real Google consent and eSewa transactions were not performed.

## Local preview

```powershell
Set-Location C:\Users\prade\Documents\bramanda
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/ and hard-refresh if an older stylesheet is cached.
For repeatable browser checks, run Django on port 8008 and then run
`.\venv\Scripts\python.exe scripts/check_homepage_browser.py` in a second terminal.
That script requires locally installed Chrome and creates a disposable browser
profile and screenshots in the system temporary directory. It only browses the
public homepage; it does not modify customers, orders, products or payments.
