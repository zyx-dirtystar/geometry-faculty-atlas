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
    "complex": re.compile(r"complex (?:differential |algebraic )?geometr|k[äa]hler|hyperk[äa]hler|géométrie complexe|複素(?:微分)?幾何|ケーラー|复几何", re.I),
    "differential": re.compile(r"differential geometr|riemannian geometr|geometric analys|ricci flow|mean curvature flow|scalar curvature|geometric flows?|gauge theory|géométrie (?:différentielle|riemannienne)|analyse géométrique|微分幾何|幾何解析|平均曲率流|リッチフロー|微分几何|几何分析", re.I),
    "algebraic": re.compile(r"algebraic geometr|birational geometr|enumerative geometr|higher dimensional geometr|algebraic varieties|algebraic (?:surface|cycles)|hodge theory|derived algebraic|schemes and stacks|géométrie (?:algébrique|birationnelle)|代数幾何|代数几何|双有理", re.I),
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
    if re.search(r"emerit|retired|in memoriam|荣休", title, re.I):
        return "emeritus"
    if re.search(r"visiting|visitor|adjunct|courtesy|affiliate|访问|兼职", title, re.I):
        return "associated"
    if re.search(r"postdoc|instructor|lecturer|fellow|student|professional services staff|^講師$|博士后", title, re.I):
        return "other"
    if re.search(r"\bprofessor\b|\bacademic faculty\b|\breader\b|prof\. dr\.|研究员|教授|^助教$", title, re.I):
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


def profile_link(base, link):
    # Some older directories emit HTTP links for their own HTTPS profile pages.
    return urljoin(base, link).replace("http://" + urlparse(base).netloc + "/", "https://" + urlparse(base).netloc + "/", 1)


def display_name(name):
    family, comma, given = name.partition(",")
    return f"{given.strip()} {family}" if comma and given.strip() else name


def parse_mit(document, base):
    records = []
    title = "Professor" if "Directory: Professors" in text_at(document, "//main/h1") else ""
    for link in document.xpath("//main//div[@class='name']//a[contains(@href,'pid=')]"):
        name = display_name(contents(link))
        records.append(Entry(name, title, profile=profile_link(base, link.get("href"))))
    return records


def parse_mit_group(document, base):
    records = []
    for row in document.xpath("//main/h3[normalize-space()='Faculty']/following-sibling::ul[1]/li[a]"):
        link = row.xpath("./a")[0]
        records.append(Entry(contents(link), research=text_at(row, "./span"), profile=profile_link(base, link.get("href"))))
    return records


def parse_nyu(document, base):
    records = []
    for heading in document.xpath("//h2[following-sibling::*[1][@class='people-grid']]"):
        grid = heading.xpath("./following-sibling::*[1]")[0]
        active = contents(heading).casefold() == "tenure / tenure-track"
        for card in grid.xpath("./a[div[@class='people-description']]"):
            info = card.xpath("./div[@class='people-description']")[0]
            name = text_at(info, "./h2")
            title = text_at(info, "./h2/following-sibling::div[1]")
            status = title if active else f"{contents(heading)} · {title}"
            interests = next((contents(row).partition(":")[2].strip() for row in info.xpath("./div[strong]")
                              if text_at(row, "./strong").startswith("Research Interests")), "")
            records.append(Entry(name, status, interests, profile_link(base, card.get("href"))))
    return records


def parse_nyu_research(document, base):
    records = {}
    for section in document.xpath("//h2[.='Algebraic Geometry' or .='Geometry']"):
        for row in section.xpath("./following-sibling::ul[1]/li"):
            description, colon, _ = contents(row).partition(":")
            if not colon:
                continue
            for name, profile in urls(row, base):
                name = name.strip(" ,")
                topics = records.setdefault(name, Entry(name, profile=profile_link(base, profile)))
                topics.research = " / ".join(filter(None, (topics.research, description.strip())))
    return list(records.values())


def parse_berkeley(document, base):
    records = []
    for card in document.xpath(f"//div[{class_token('node-view--card')}]//a[h2]"):
        title = text_at(card, f".//div[{class_token('field-name-field-openberkeley-person-title')}]")
        research = text_at(card, f".//div[{class_token('field-name-field-openberkeley-person-dept')}]")
        records.append(Entry(text_at(card, "./h2"), title, research, profile_link(base, card.get("href"))))
    return records


def parse_eth(document, base):
    return [
        Entry(display_name(contents(link)), "Professor", profile=profile_link(base, link.get("href")))
        for link in document.xpath("//tr[@class='trSubtext']/td[1]/a[contains(@href,'?u=')]")
    ]


def parse_eth_topic(document, base):
    records = []
    for link in document.xpath("//div[h2[.='Professors']]//ul/li/a"):
        # These pages mix PDE and geometry or symplectic topology and algebraic geometry.
        records.append(Entry(contents(link), research="Geometry", profile=profile_link(base, link.get("href"))))
    return records


def parse_ucla(document, base):
    records = []
    for row in document.xpath("//tr[td[1]//a[contains(@href,'/people/ladder/')]]"):
        link = row.xpath("./td[1]//a[contains(@href,'/people/ladder/')]")[0]
        name = display_name(contents(link))
        records.append(Entry(name, text_at(row, "./td[2]"), profile=profile_link(base, link.get("href"))))
    return records


def parse_ucla_geometry(document, base):
    return [
        Entry(contents(link), research="Geometry", homepage=profile_link(base, link.get("href")))
        for link in document.xpath(f"//a[{class_token('elementor-cta')} and @href]")
    ]


def parse_yale(document, base):
    records = []
    for link in document.xpath(f"//a[{class_token('directory-listing-card__heading-link')}]"):
        title = text_at(link.getparent().getparent(), f"./div[{class_token('directory-listing-card__subheading')}]")
        records.append(Entry(contents(link).removesuffix(", Ph.D."), title, profile=profile_link(base, link.get("href"))))
    return records


def parse_kyoto(document, base):
    records = []
    for heading in document.xpath("//h2[.='教授' or .='准教授' or .='講師' or .='助教']"):
        for person in heading.xpath("./following-sibling::div[1]//li"):
            links = person.xpath(".//div[contains(@class,'display-name')]//a[@href]")
            if not links:
                continue
            link = links[0]
            specialty = text_at(person, ".//div[contains(@class,'specialty-area')]")
            records.append(Entry(contents(link), contents(heading), specialty, profile_link(base, link.get("href"))))
    return records


def parse_epfl(document, base):
    records = []
    for link in document.xpath("//a[starts-with(@href,'https://people.epfl.ch/')][following-sibling::p[contains(.,'Professor')]]"):
        records.append(Entry(contents(link), text_at(link, "./following-sibling::p[1]"), profile=profile_link(base, link.get("href"))))
    return records


def parse_epfl_geometry(document, base):
    records = []
    for link in document.xpath("//div[@class='prof']/a"):
        parent = link.getparent()
        description = text_at(parent, "./preceding-sibling::div[@class='lab'][1] | ./following-sibling::div[@class='research_description'][1]")
        records.append(Entry(contents(link), research=description or "Geometry", homepage=profile_link(base, link.get("href"))))
    return records


def parse_warwick_ag(document, base):
    staff = document.xpath("//p[normalize-space()='Staff:']/following-sibling::ul[1]")
    return [
        Entry(untitled(name), research="Algebraic Geometry", profile=profile)
        for listing in staff for name, profile in urls(listing, base)
    ]


def untitled(name):
    name = re.sub(r"^(?:(?:Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?)\s+)+", "", name)
    return re.sub(r"\s*,?\s+(?:FRS|FRSE|FBA)(?:\s+(?:FRS|FRSE|FBA))*$", "", name)


def parse_oxford(document, base):
    records = []
    for panel in document.xpath(f"//div[{class_token('people-list')}]//div[{class_token('item-list')}][h3]"):
        title = text_at(panel, "./h3")
        for link in panel.xpath("./ul/li//a[starts-with(@href,'/people/')][normalize-space()]"):
            records.append(Entry(untitled(contents(link)), title, profile=profile_link(base, link.get("href"))))
    return records


def parse_oxford_geometry(document, base):
    return [
        Entry(untitled(contents(link)), research="Geometry", profile=profile_link(base, link.get("href")))
        for link in document.xpath("//a[starts-with(@href,'/people/')][normalize-space() and not(normalize-space()='Contact form')]")
        if link.get("href").count("/") == 2 and re.match(r"^(?:Prof\.|Dr\.) ", contents(link))
    ]


def parse_warwick(document, base):
    records = []
    for panel in document.xpath("//h2[normalize-space()='Academic and Teaching Staff']/following-sibling::div[1]"):
        for label, profile in urls(panel, base):
            if "/maths/people/staff/" not in profile or not label:
                continue
            title = "Professor" if label.startswith("Professor ") else "Academic and Teaching Staff"
            records.append(Entry(untitled(label), title, profile=profile))
    return records


def parse_duke(document, base):
    records = []
    is_research = "/research/" in urlparse(base).path
    for card in document.xpath(f"//main//div[{class_token('member-card')}]"):
        link = next(((name, url) for name, url in urls(card, base) if name and "/person/" in urlparse(url).path), None)
        if link is None:
            continue
        website = next((url for _, url in urls(card, base) if "/~" in urlparse(url).path), "")
        title = text_at(card.getparent(), f".//div[{class_token('h6')}][normalize-space()][1]")
        if not website:
            website = next((url for label, url in urls(card.getparent(), base) if label.casefold().strip("#") == "personal website"), "")
        records.append(Entry(link[0], title, "Geometry" if is_research else "", link[1], website))
    return records


def parse_uchicago(document, base):
    records = []
    for link in document.xpath(f"//a[div[{class_token('people_content')}]/h3/span]"):
        name = text_at(link, "./div/h3/span")
        title = text_at(link, "./div/h3/b")
        if title != "Graduate Student":
            records.append(Entry(name, title, profile=profile_link(base, link.get("href"))))
    return records


def parse_imperial(document, base):
    records = []
    for card in document.xpath("//div[h3 and a[starts-with(@href,'https://profiles.imperial.ac.uk/')]]"):
        link = card.xpath("./a[starts-with(@href,'https://profiles.imperial.ac.uk/')]")[0]
        name = text_at(card, "./h3")
        label = contents(card)
        title = label.removeprefix(name).strip().removeprefix(name).strip()
        records.append(Entry(untitled(name), title, profile=profile_link(base, link.get("href"))))
    return records


def parse_brown_geometry(document, base):
    return [
        Entry(contents(link), research="Geometry", profile=profile_link(base, link.get("href")))
        for link in document.xpath("//h3[@class='people_item_name']/a[@href]")
    ]


PARSERS = {
    "stanford": parse_stanford, "stonybrook": parse_stonybrook, "stonybrook_group": parse_stonybrook_group,
    "bonn": parse_bonn, "bicmr": parse_bicmr, "princeton": parse_princeton, "princeton_group": parse_princeton_group,
    "pku": parse_pending, "pku_pure":parse_pku_pure, "rutgers": parse_pending,
    "pending": parse_pending, "mit": parse_mit, "mit_group": parse_mit_group, "nyu": parse_nyu, "nyu_research": parse_nyu_research,
    "berkeley": parse_berkeley, "eth": parse_eth, "eth_topic": parse_eth_topic, "epfl": parse_epfl, "epfl_geometry": parse_epfl_geometry,
    "ucla": parse_ucla, "ucla_geometry": parse_ucla_geometry, "yale": parse_yale, "kyoto": parse_kyoto, "warwick_ag": parse_warwick_ag,
    "oxford": parse_oxford, "oxford_geometry": parse_oxford_geometry, "warwick": parse_warwick, "duke": parse_duke,
    "uchicago": parse_uchicago, "imperial": parse_imperial, "brown_geometry": parse_brown_geometry,
}


def profile_fields(document, base):
    """Extract titles and visible link labels from an official or directory-linked page."""
    main = (document.xpath("//main") or document.xpath("//body") or [document])[0]
    research = []
    for label in main.xpath(".//h2|.//h3|.//h4|.//dt|.//div[not(*) and @class]|.//strong|.//b"):
        title = contents(label).strip(":").lower()
        if title not in {"field of interest", "research field", "research interests", "research area", "research areas", "research area(s)", "research interests and areas", "research specialization", "専門分野"}:
            continue
        following = label.getnext()
        value = clean(label.tail or "") or (contents(following) if following is not None else "")
        if value and len(value) <= 600:
            research.append(value)
    for block in main.xpath(".//*[contains(@class,'person-field') or contains(@class,'research-interest') or contains(@class,'field--name-field-research') or contains(@class,'field--name-field-specialty')]"):
        value = contents(block)
        if value and len(value) < 500:
            research.append(value)
    homepage = cv = bibliography = ""
    for label, url in urls(main, base):
        low = label.lower()
        host = urlparse(url).hostname or ""
        if not homepage and low in {"home page", "homepage", "personal website", "personal homepage", "professional website", "website", "personal web page", "web site", "個人ホームページ"}:
            if host not in {"linkedin.com", "www.linkedin.com", "zoom.us"} and not host.endswith(".zoom.us"):
                homepage = url
        if not cv and re.search(r"^(?:(?:my|short|brief|latest|full) )?(?:curriculum vit[æa]e|curriculum vitae|cv|vita|resume|résumé|简历)\b", low):
            cv = url
        if not bibliography and low in {"publications","papers","research papers","publications and preprints","research publications"}:
            bibliography = url
    return {"research":" / ".join(dict.fromkeys(research)), "homepage":homepage, "cv":cv, "publications":bibliography}
