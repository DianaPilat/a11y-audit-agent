"""A realistic sample audit of a fictional city portal, so reports can be made without a crawl.

`load_sample` writes it into a `FindingStore` through the normal store methods, so exporters read it
the same way they read a real audit. Every site and address here is fictional (.example is reserved).
"""

import json
from dataclasses import dataclass

from app.findings import Finding, FindingStore
from app.tickets import Ticket

SAMPLE_AUDIT_ID = "sample"
SAMPLE_SITE = "https://portal.riverton.example/"
SAMPLE_DATE = "2026-10-26 09:30:00"
_BASE = "https://portal.riverton.example"

PAGES = [
    "/", "/services", "/services/permits", "/services/permits/apply", "/pay", "/pay/parking-ticket",
    "/news", "/news/2026/budget-hearing", "/departments", "/departments/parks", "/events", "/contact",
    "/council/agendas", "/council/minutes",
]


@dataclass
class _Group:
    rule: str
    criterion: str
    severity: str
    confidence: str
    element: str
    explanation: str
    pages: list[int]  # indexes into PAGES
    statuses: list[str]  # cycled over the group's rows
    ticket: tuple[str, str, str, str] | None = None  # title, fix, before, after

    @property
    def source(self) -> str:
        return "ai-assessed" if self.rule.startswith("judgment-") else "axe-core"


A, P, R = "approved", "pending", "rejected"

GROUPS = [
    _Group("image-alt", "1.1.1", "critical", "high", "img.dept-photo",
           "Images on these pages have no text alternative, so screen reader users hear only a file name or nothing. "
           "Add alt text that describes what the photo shows, or empty alt if it is decoration.",
           [0, 8, 9, 10], [A],
           ("Add alt text to department photos", "Give each informative image an alt attribute describing its content.",
            '<img class="dept-photo" src="/img/parks-crew.jpg">',
            '<img class="dept-photo" src="/img/parks-crew.jpg" alt="Parks crew planting trees along River Street">')),
    _Group("judgment-alt-text", "1.1.1", "moderate", "medium", "img.news-thumb",
           "The alt text reads 'image' or repeats the file name, so it tells people using screen readers nothing about the picture. "
           "Replace it with a short description of what the image conveys.",
           [6, 7, 10], [A, A, R]),
    _Group("color-contrast", "1.4.3", "serious", "high", ".btn-secondary",
           "Light grey text on a white background is hard to read for people with low vision or in bright light. "
           "Darken the text to at least a 4.5 to 1 contrast ratio.",
           [0, 1, 2, 3, 4, 5, 8, 11, 12], [A],
           ("Raise contrast of secondary buttons", "Change the secondary button text colour to meet 4.5:1 against its background.",
            ".btn-secondary { color: #8a8a8a; background: #fff; }", ".btn-secondary { color: #595959; background: #fff; }")),
    _Group("label", "1.3.1", "critical", "high", "#permit-address",
           "Form fields on the permit application have no programmatic label, so screen reader users cannot tell what to enter. "
           "Connect a visible label to each field with for and id.",
           [2, 3, 11], [A],
           ("Label the permit application fields", "Associate a label element with each input.",
            '<input id="permit-address" type="text">',
            '<label for="permit-address">Property address</label>\n<input id="permit-address" type="text">')),
    _Group("judgment-form-label", "3.3.2", "moderate", "low", "#parking-plate",
           "The only instruction for this field is placeholder text that disappears as soon as someone types. "
           "Add a visible label that stays on screen.",
           [5, 4], [P]),
    _Group("link-name", "2.4.4", "serious", "high", "a.social-icon",
           "Icon-only links have no accessible name, so a screen reader announces just 'link'. "
           "Add visually hidden text or an aria-label.",
           [0, 11], [A],
           ("Name the social media icon links", "Add an aria-label naming each destination.",
            '<a class="social-icon" href="https://social.example/riverton"><svg>...</svg></a>',
            '<a class="social-icon" href="https://social.example/riverton" aria-label="Riverton on Social">'
            '<svg aria-hidden="true">...</svg></a>')),
    _Group("judgment-link-text", "2.4.4", "moderate", "medium", "a.read-more",
           "Several links say only 'Read more', so out of context people using a screen reader's link list cannot tell where "
           "each goes. Make the link text name its target.",
           [1, 6, 7, 8, 9, 10, 12, 13], [A, A, A, A, P, A, A, A],
           ("Replace 'Read more' link text", "Use descriptive link text, or add visually hidden context after the visible words.",
            '<a class="read-more" href="/news/2026/budget-hearing">Read more</a>',
            '<a class="read-more" href="/news/2026/budget-hearing">Read more'
            '<span class="visually-hidden"> about the 2026 budget hearing</span></a>')),
    _Group("html-has-lang", "3.1.1", "serious", "high", "html",
           "These legacy pages do not declare a language, so screen readers may read them with the wrong pronunciation. "
           "Add lang='en' to the html element.",
           [11, 12, 13, 3, 5], [A]),
    _Group("button-name", "4.1.2", "critical", "high", "button.menu-toggle",
           "The menu button contains only an icon and has no name, so assistive technology cannot say what it does. "
           "Give it an accessible name.",
           [0, 1, 4], [A],
           ("Name the mobile menu button", "Add aria-label and aria-expanded to the toggle.",
            '<button class="menu-toggle"><span class="icon-bars"></span></button>',
            '<button class="menu-toggle" aria-label="Menu" aria-expanded="false">'
            '<span class="icon-bars" aria-hidden="true"></span></button>')),
    _Group("aria-required-attr", "4.1.2", "serious", "medium", "div[role='combobox']",
           "The search box uses a combobox role without the attributes that role requires, so its state is not announced.",
           [0], [R]),
    _Group("judgment-heading-structure", "1.3.1", "moderate", "medium", "h4.card-title",
           "Headings jump from level 2 to level 4, which breaks the outline people use to move around the page. "
           "Use heading levels in order.",
           [1, 8, 9, 10, 12, 13], [A, A, P, A, P, A]),
    _Group("frame-title", "4.1.2", "serious", "high", "iframe.map-embed",
           "The embedded map frame has no title, so screen reader users cannot tell what it contains. "
           "Add a descriptive title attribute.",
           [11], [A],
           ("Add a title to the map iframe", "Give the iframe a title describing its content.",
            '<iframe class="map-embed" src="https://maps.example/city-hall"></iframe>',
            '<iframe class="map-embed" src="https://maps.example/city-hall" '
            'title="Map showing the location of City Hall"></iframe>')),
    _Group("scrollable-region-focusable", "2.1.1", "serious", "high", "div.agenda-scroll",
           "A scrolling agenda panel cannot be reached with the keyboard, so keyboard-only users cannot read its full "
           "content. Make it focusable.",
           [12, 13], [P]),
    _Group("meta-viewport", "1.4.4", "critical", "high", "meta[name='viewport']",
           "Pinch zoom is disabled on every page, which blocks people with low vision from enlarging text. "
           "Remove user-scalable=no and maximum-scale.",
           [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [A],
           ("Allow zooming on all pages", "Remove the zoom restrictions from the viewport meta tag in the shared layout.",
            '<meta name="viewport" content="width=device-width, user-scalable=no, maximum-scale=1">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">')),
    _Group("bypass", "2.4.1", "serious", "medium", "body",
           "There is no way to skip the long navigation menu and go straight to the main content, which makes every page "
           "slow for keyboard users.",
           [0], [A]),
]


def load_sample(store: FindingStore, audit_id: str = SAMPLE_AUDIT_ID) -> str:
    """Write the sample audit into `store` and return its audit id."""
    store.create_audit(audit_id, SAMPLE_SITE, 20, created_at=SAMPLE_DATE)
    store.update_audit(
        audit_id, status="done", phase="done", pages_total=len(PAGES), pages_done=len(PAGES),
        pages=json.dumps([_BASE + p for p in PAGES]),
    )
    for g in GROUPS:
        ids = []
        for i, page in enumerate(g.pages):
            finding_id, _ = store.save(audit_id, Finding(
                url=_BASE + PAGES[page], rule_id=g.rule, wcag_criterion=g.criterion, severity=g.severity,
                element=g.element, explanation=g.explanation, source=g.source, confidence=g.confidence,
            ))
            store.set_review_status(audit_id, finding_id, g.statuses[i % len(g.statuses)])
            ids.append(finding_id)
        if g.ticket:
            title, fix, before, after = g.ticket
            store.save_ticket(audit_id, Ticket(
                finding_ids=ids, title=title, fix_description=fix, code_before=before, code_after=after,
            ))
    return audit_id
