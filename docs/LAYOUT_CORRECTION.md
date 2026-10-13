# Premium layout correction

This correction supersedes the storefront width and card sizing decisions in LAYOUT_AUDIT.md. It preserves the earlier backend and portal functionality.

## Findings

The previous shared 1800px maximum widened the homepage's three flexible tracks to roughly 578px at 1920px. Their unconstrained 4:5 frames consequently approached 723px tall. Shop also had a four-column large-desktop override and separate 440px sparse-grid tracks, creating inconsistent card widths and heading/grid alignment. Featured supporting text was only 12px and its heading capped at 32px. Homepage mobile cards used two narrow columns at 390px while Shop used one.

The catalog and all local gallery assets were inspected read-only. apile and sapce have standalone print artwork, including their gallery images. Bramanda Oversized T-Shirt already selects its clothing photograph as its primary image, with artwork retained in its gallery. There is no alternative clothing photograph for the two artwork-only products. Image selection and records remain unchanged; no photograph was invented or substituted.

## Corrections

- Shared storefront maximum: 1440px instead of 1800px; responsive outer gutter remains 16?64px. At 1920px the centered collection has approximately 233px margins; at 1440px the fluid gutter is approximately 46px. These margins result from the requested maximum rather than an old narrow percentage container.
- Homepage and Shop: three columns above 1199px, two through tablet/small desktop, one at 480px and below. Shop filters, title and grid align to the same container. Small Shop collections retain normal sized tracks instead of stretching a single card.
- Product cards: about 461px wide at the maximum container; 28px horizontal gaps, 40px row gaps. Desktop/tablet image frames are 350?430px tall; mobile frames 300?370px. All cards within a row share the same image frame. contain preserves artwork and complete photographs with a 20px inset. The existing explicit cover opt-in remains available with no inset.
- Featured heading: 30?36px, supporting text 15px, product names 16px on Homepage and 16?17px on Shop. Prices remain 16px. Names, stock, prices and links stay beneath the frame.
- Minimal hover zoom (1.015), no whole-card lift. Links have a short underline instead of a second full-width divider.
- Homepage section spacing: 56px above / 64px below; mobile 40px / 48px. Editorial banner and full-width campaign hero are preserved.
- Product details: desktop gallery capped at 580px, with existing tablet/mobile aspect rules retained. Cart/checkout retain their separate 1440px purchase cap, customer pages 1200px, login/signup practical 540px cards. Owner/Staff sidebars, available-width tables and bounded form layouts remain unchanged after visual review.

## Files modified in this correction

- static/css/base.css ? storefront maximum.
- static/css/home.css ? Featured spacing, typography, grids and mobile columns.
- static/css/storefront.css ? controlled card frames, Shop grid consistency, hover/link typography and detail gallery cap.
- scripts/audit_layout_browser.py ? fixtures include all three actual image types; screenshots include three-product Homepage/Shop at every width; metrics include card/image bounds.
- scripts/check_product_grid_browser.py ? expectations reflect the controlled frame heights and consistent Shop tracks (source updated; this separate runner was not executed).
- docs/LAYOUT_CORRECTION.md ? this report.

## Verification

- Django system check: passed, zero issues.
- Full Django suite: 422 passed in 52.501s.
- Focused products, homepage, dashboard and authentication route suite: 128 passed in 4.608s.
- Python browser script compilation and scoped git diff whitespace check: passed.
- Complete isolated Chrome audit: 70 existing page states at 1920, 1440, 1024, 768 and 390px (350 combinations), no document overflow, broken images or tested control failures.
- Final card typography/link refinement: focused eight-state browser rerun at the same five widths. 40 combinations passed with no overflow, broken images or tested control failures. Final Homepage 1440px and Shop 390px screenshots were reviewed after this refinement. All measured card frames in both runs passed the stated height bounds. Results and final screenshots are stored separately below.
- Screenshots actually reviewed: three-product Homepage/Shop desktop and mobile, Homepage tablet/small desktop, plus representative product detail, cart, checkout, profile, login, customer order details, Owner overview/inventory/product form/activity, and Staff overview/order detail. Other existing page states received automated geometry/render checks.

Artifacts: C:/Users/prade/AppData/Local/Temp/bramanda-balanced and C:/Users/prade/AppData/Local/Temp/bramanda-balanced-refined.

Browser pages use Django-rendered isolated fixtures and the real local image assets, rather than mutating or submitting forms against the production catalog. Synthetic product names and orders appear in audit screenshots. Live provider pages, real devices, non-Chrome browsers, and every production-content variation were not visually verified. Django admin was excluded. No models, records, authentication, payment/order/inventory services or schema were changed. No commit, push or deployment was performed.
