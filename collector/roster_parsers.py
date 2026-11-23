"""Parse verified public directory formats. Keep role and topic evidence distinct."""

from dataclasses import dataclass, field
import re
from urllib.parse import urljoin, urlparse


@dataclass
class Entry:
    name: str
    title: str = ""
    research: str = ""
    profile: str = ""
    homepage: str = ""
    topics: list = field(default_factory=list)


TOPICS = {
    "complex": re.compile(r"complex (?:differential |algebraic )?geometr|k[äa]hler|hyperk[äa]hler|复几何", re.I),
    "differential": re.compile(r"differential geometr|riemannian geometr|geometric analys|ricci flow|scalar curvature|geometric flows?|gauge theory|微分几何|几何分析", re.I),
    "algebraic": re.compile(r"algebraic geometr|birational geometr|enumerative geometr|higher dimensional geometr|algebraic varieties|algebraic (?:surface|cycles)|hodge theory|derived algebraic|schemes and stacks|代数几何|双有理", re.I),
}
ADJACENT = re.compile(r"symplectic|contact geometry|several complex variables|complex analysis|geometric topology|geometry|geometrie|辛几何|多复变", re.I)


def clean(value):
    return " ".join(value.split())


def contents(element):
    return clean(" ".join(element.itertext()))


def urls(element, base):
    for link in element.xpath(".//a[@href]"):
        href = urljoin(base, link.get("href"))
        parsed = urlparse(href)
        if parsed.scheme in ("https", "http") and not parsed.username and not parsed.password:
            yield contents(link), href


def class_token(value):
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {value} ')"


def text_at(element, xpath):
    return " ".join(contents(node) for node in element.xpath(xpath)).strip()


def matched_fields(research):
    return sorted(key for key, keyword in TOPICS.items() if keyword.search(research))


def split_role(title):
    if re.search(r"emerit|retired|荣休", title, re.I):
        return "emeritus"
    if re.search(r"visiting|visitor|adjunct|courtesy|affiliated|访问|兼职", title, re.I):
        return "associated"
    if re.search(r"postdoc|instructor|lecturer|fellow|博士后", title, re.I):
        return "other"
    if re.search(r"\bprofessor\b|prof\. dr\.|研究员|教授", title, re.I):
        return "faculty"
    return "unverified"


def parse_stanford(document, base):
    records = []
    cards = document.xpath(f"//div[{class_token('hb-card__content')}]")
    for card in cards:
        links = card.xpath(f".//div[{class_token('hb-card__title')}]//a[contains(@href,'/people/')]")
        if not links:
            continue
        link = links[0]
        categories = card.xpath(f".//div[{class_token('hb-card__category')}]//a")
        records.append(Entry(
            contents(link), text_at(card, f".//div[{class_token('hb-card__subtitle')}]"),
            " / ".join(contents(category) for category in categories),
            urljoin(base, link.get("href")),
        ))
    return records


def parse_stonybrook(document, base):
    records = []
    for panel in document.xpath("//div[big and table]"):
        name = text_at(panel, "./big")
        if not name:
            continue
        details = panel.xpath("./table//tr[1]/td[last()]")
        detail = details[0] if details else panel
        role = next((clean(line) for line in detail.xpath("text()") if line.strip()), "")
        topical = re.search(r"Research Interests?\s*:\s*(.*?)(?:Awards?\s*:|Selected Publications?\s*:|$)", contents(detail), re.I)
        homepage = next((url for _, url in urls(panel.xpath("./big")[0], base)), "")
        records.append(Entry(name, role, topical[1][:700] if topical else "", homepage=homepage))
    return records


def parse_stonybrook_group(document, base):
    records = []
    for heading in document.xpath("//h3[normalize-space()='Core faculty' or normalize-space()='Faculty in related areas']"):
        for item in heading.getparent().xpath(f".//li[{class_token('table-row')}]"):
            group = contents(heading)
            name = text_at(item, f"./ul/li[{class_token('name')}]")
            description = text_at(item, f"./ul/li[not({class_token('name')})]")
            homepage = next((url for _, url in urls(item, base)), "")
            explicit = "Algebraic Geometry. " if group == "Core faculty" else ""
            if name:
                records.append(Entry(name, research=explicit + description, homepage=homepage))
    return records


def parse_bonn(document, base):
    records = []
    for heading in document.xpath(f"//h4[ancestor::div[{class_token('tile-content')}]]"):
        paragraph = heading.getparent().xpath("./p")
        if not paragraph:
            continue
        p = paragraph[0]
        parts = [clean(part) for part in p.xpath("text()") if clean(part)]
        homepage = next((url for label, url in urls(p, base) if label.lower() in ("website", "homepage", "webseite")), "")
        name = contents(heading)
        if name and parts:
            role, *descriptions = parts
            research = next((part for part in descriptions if not re.search(r"@|Room|Mathematics Center|Endenicher|\d\.\d\d", part)), "")
            records.append(Entry(name, role, research, homepage=homepage))
    return records


def parse_bicmr(document, base):
    records = []
    for panel in document.xpath(f"//dl[{class_token('people')}]/dd[h4]"):
        name = text_at(panel, "./h4")
        role = text_at(panel, f"./p[{class_token('zc')}]")
        research = next((contents(p).removeprefix("Research:").strip() for p in panel.xpath("./p") if contents(p).lower().startswith("research:")), "")
        homepage = next((url for _, url in urls(panel, base) if "/~" in urlparse(url).path or "sites.google.com" in urlparse(url).netloc), "")
        if name:
            records.append(Entry(name, role, research, homepage=homepage))
    return records


def parse_princeton(document, base):
    records = []
    for link in document.xpath(f"//a[{class_token('person-card__name')}]"):
        name = contents(link)
        role = text_at(link.getparent(), f"./div[{class_token('person-card__title')}]")
        if name:
            records.append(Entry(name, role, profile=urljoin(base, link.get("href"))))
    return records


def parse_princeton_group(document, base):
    records = []
    for block in document.xpath(f"//div[{class_token('view-content')}]"):
        heading = ""
        for item in block:
            if item.tag == "h3":
                heading = contents(item)
            elif item.tag == "div" and heading:
                link = next(iter(urls(item, base)), None)
                if link and link[0]:
                    records.append(Entry(link[0], research=heading, profile=link[1]))
    return records


def parse_pku_pure(document, base):
    records = []
    for heading in document.xpath("//h3"):
        block = next((parent for parent in list(heading.iterancestors())[:3] if "Interests" in contents(parent) and len(contents(parent)) < 1100), None)
        if block is None:
            continue
        name = contents(heading)
        if not name or len(name) > 80:
            continue
        inverted = re.fullmatch(r"([A-Z][A-Z-]+)\s+(.+)",name)
        if inverted:
            name = f"{inverted[2]} {inverted[1].title()}"
        research = re.split(r"Interests\s*[:：]",contents(block),maxsplit=1)[-1].strip()
        links = list(urls(block,base))
        parent = heading.getparent()
        if parent.tag == "a" and parent.get("href"):
            links.insert(0, (name, urljoin(base,parent.get("href"))))
        homepage = next((link for _,link in links), "")
        records.append(Entry(name, research=research[:600], homepage=homepage))
    return records


def parse_pending(document, base):
    # These official listings need a separate adapter before any completeness claim.
    return []


PARSERS = {
    "stanford": parse_stanford, "stonybrook": parse_stonybrook, "stonybrook_group": parse_stonybrook_group,
    "bonn": parse_bonn, "bicmr": parse_bicmr, "princeton": parse_princeton, "princeton_group": parse_princeton_group,
    "pku": parse_pending, "pku_pure":parse_pku_pure, "rutgers": parse_pending,
}


def profile_fields(document, base):
    """Extract titles and visible link labels from an official or directory-linked page."""
    main = (document.xpath("//main") or document.xpath("//body") or [document])[0]
    research = []
    for label in main.xpath("//h2|//h3|//h4|//dt|//div[not(*) and @class]"):
        title = contents(label).strip(":").lower()
        if title not in {"field of interest", "research field", "research interests", "research area(s)", "research interests and areas"}:
            continue
        next_el = label.getnext()
        if next_el is not None:
            value = contents(next_el)
            if value and len(value) <= 600:
                research.append(value)
    for block in main.xpath("//*[contains(@class,'person-field') or contains(@class,'research-interest') or contains(@class,'field--name-field-research')]"):
        value = contents(block)
        if value and len(value) < 500:
            research.append(value)
    homepage = cv = bibliography = ""
    for label, url in urls(main, base):
        low = label.lower()
        host = urlparse(url).hostname or ""
        if not homepage and low in {"home page", "homepage", "personal website", "personal homepage", "professional website", "website"}:
            if host not in {"linkedin.com", "www.linkedin.com", "zoom.us"} and not host.endswith(".zoom.us"):
                homepage = url
        if not cv and re.search(r"^(?:(?:my|short|brief|latest|full) )?(?:curriculum vit[æa]e|curriculum vitae|cv|vita|resume|résumé|简历)\b", low):
            cv = url
        if not bibliography and low in {"publications","papers","research papers","publications and preprints","research publications"}:
            bibliography = url
    return {"research":" / ".join(dict.fromkeys(research)), "homepage":homepage, "cv":cv, "publications":bibliography}
