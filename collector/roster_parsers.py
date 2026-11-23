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
    "complex": re.compile(r"complex (?:differential |algebraic )?geometr|k[äa]hler|hyperk[äa]hler|géométrie complexe|geometr[ií]a comple[jx]a|komplexe geometrie|複素(?:微分)?幾何|ケーラー|复几何", re.I),
    "differential": re.compile(r"differential geometr|riemannian geometr|geometric analys|ricci flow|mean curvature flow|scalar curvature|geometric flows?|gauge theory|géométrie (?:différentielle|riemannienne)|analyse géométrique|geometr[ií]a (?:differenziale|diferencial|riemanniana)|an[aá]lisis geom[eé]trico|differentialgeometrie|微分幾何|幾何解析|平均曲率流|リッチフロー|微分几何|几何分析", re.I),
    "algebraic": re.compile(r"algebraic (?:(?:and|&) arithmetic )?geometr|arithmetic geometr|birational geometr|enumerative geometr|higher dimensional geometr|algebraic varieties|algebraic (?:surface|cycles)|hodge theory|derived algebraic|schemes and stacks|géométrie (?:algébrique|arithmétique|birationnelle)|geometr[ií]a (?:alg[eé]brica|algebrica|aritm[eé]tica|biracional)|algebraische geometrie|代数幾何|代数几何|双有理", re.I),
}
ADJACENT = re.compile(r"symplectic|contact geometry|several complex variables|complex analysis|geometric topology|geometry|g[ée]om[ée]trie|几何|幾何|多复变", re.I)


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
    if re.search(r"emerit|émérit|emérit|retired|in memoriam|honoraire|jubilad|荣休", title, re.I):
        return "emeritus"
    if re.search(r"visiting|visitor|adjunct|courtesy|affiliate|secondary appointment|profesor[ae]? asociad|^invit[ée]|访问|兼职", title, re.I):
        return "associated"
    if re.search(r"post.?doc|instructor|lecturer|student|professional services staff|^lecteur|^dottorand|^doctorand|^講師$|博士后", title, re.I):
        return "other"
    if re.search(r"\bprofessor\b|\bacademic faculty\b|\breader\b|prof\. dr\.|professeur|professore (?:ordinario|associato)|catedr[aá]tic[ao]|titular de universidad|contratad[oa] doctor|ma[iî]tr(?:e|esse) de conf[ée]rences|研究员|教授|^助教$", title, re.I):
        return "faculty"
    if re.search(r"\bfellow\b|research assistant", title, re.I):
        return "other"
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


def parse_tokyo(document, base):
    records = []
    for table in document.xpath("//table[@class='ichiran_gojyuon']"):
        name = table.xpath(".//tr[td[1][normalize-space()='Name']]/td[2]")
        if not name:
            continue
        label = contents(name[0])
        match = re.match(r"(.+?)\s*【([^】]+)】(.*)", label)
        if not match:
            continue
        profile = next((url for _, url in urls(name[0], base)), "")
        field_cell = table.xpath(".//tr[td[1][normalize-space()='Field of Interest']]/td[2]")
        for hidden in table.xpath(".//del | .//s | .//strike"):
            hidden.drop_tree()
        field = contents(field_cell[0]) if field_cell else ""
        records.append(Entry(display_name(match[1].title()), (match[2] + match[3]).strip(), field, profile))
    return records


def parse_tokyo_ipmu(document, base):
    records = []
    for row in document.xpath("//h4[.='Faculty Members']/following-sibling::table[1]//tr[td[1]//a and td[2]]"):
        if text_at(row, "./td[2]") != "Mathematics":
            continue
        link = row.xpath("./td[1]//a")[0]
        name = display_name(contents(link)).replace("Todor Eliseev Milanov", "Todor Milanov")
        records.append(Entry(name, "Academic Faculty", profile=profile_link(base, link.get("href"))))
    return records


def parse_kyoto_rims(document, base):
    records = []
    for link in document.xpath("//h3[.='Staff']/following-sibling::div[1]/p[@class='name-le']/a"):
        title = contents(link.getparent()).removeprefix(contents(link)).strip()
        name = display_name(contents(link).title())
        records.append(Entry(name, title, homepage=profile_link(base, link.get("href"))))
    return records


def parse_northwestern(document, base):
    records = []
    for card in document.xpath("//div[@class='people-content'][h3/a]"):
        link = card.xpath("./h3/a")[0]
        label = next((line for line in card.xpath(".//text()") if "Field(s) of Research:" in line), "")
        fields = label.partition("Field(s) of Research:")[2].strip()
        if not fields and label:
            fields = re.split(r"Phone number:|Office location:", contents(card).partition("Field(s) of Research:")[2], 1)[0].strip()
        records.append(Entry(contents(link), text_at(card, "./p[@class='title']"), fields, profile_link(base, link.get("href"))))
    return records


def parse_purdue(document, base):
    records = []
    for card in document.xpath("//div[@class='people-item'][p[@class='people-name']/a]"):
        link = card.xpath("./p[@class='people-name']/a")[0]
        title = text_at(card, "./p[@class='people-title']")
        field = text_at(card, "./p[@class='people-research']")
        records.append(Entry(contents(link), title, field, profile_link(base, link.get("href"))))
    return records


def parse_washington(document, base):
    records = []
    for card in document.xpath("//div[@class='details'][.//h3/a]"):
        link = card.xpath(".//h3/a")[0]
        title = text_at(card, ".//div[contains(@class,'field-job-title')]")
        field = text_at(card, ".//div[contains(@class,'field-interests')]//a")
        homepage = next((url for label, url in urls(card, base) if label.casefold() == "website"), "")
        records.append(Entry(contents(link), title, field, profile_link(base, link.get("href")), homepage))
    return records


def parse_cornell(document, base):
    records = []
    for card in document.xpath("//article[@class='person-card'][.//h2/a]"):
        link = card.xpath(".//h2/a")[0]
        title = text_at(card, ".//p[@class='person-title']")
        field = text_at(card, ".//p[@class='person-departments']")
        records.append(Entry(contents(link), title, field, profile_link(base, link.get("href"))))
    return records


def parse_waterloo(document, base):
    records = []
    for row in document.xpath("//main//tr[td[1]//strong and td[2]]"):
        name = text_at(row, "./td[1]//strong[1]")
        title = text_at(row, "./td[1]").removeprefix(name).strip()
        link = next((url for _, url in urls(row.xpath("./td[1]")[0], base)), "")
        records.append(Entry(name, title, text_at(row, "./td[2]").strip("\u200b "), link))
    return records


def parse_uci_catalog(document, base):
    return [
        Entry(text_at(block, "./span[@class='name']"), text_at(block, "./span[@class='title']"),
              text_at(block, "./span[@class='research']").strip("()"))
        for block in document.xpath("//div[@class='faculty'][span[@class='name']]")
    ]


def parse_tel_aviv(document, base):
    records = []
    for link in document.xpath("//td/a[contains(@href,'/profile/')]"):
        label = contents(link)
        title = "Professor" if label.startswith("Prof.") else "Academic Faculty"
        records.append(Entry(untitled(label), title, profile=profile_link(base, link.get("href"))))
    return records


def parse_hebrew(document, base):
    records = []
    for link in document.xpath("//h3/a[@href and normalize-space()]"):
        if "/people/" not in link.get("href"):
            continue
        label = contents(link)
        card = link.getparent().getparent()
        homepage = next((url for name, url in urls(card, base) if "personal website" in name.casefold()), "")
        title = "Professor" if label.startswith("Prof.") else "Academic Faculty"
        records.append(Entry(untitled(label), title, profile=profile_link(base, link.get("href")), homepage=homepage))
    return records


def parse_sissa(document, base):
    records = []
    for item in document.xpath("//h2[.='Faculty']/following-sibling::*[1]//li"):
        link = item.xpath(".//a[strong]")
        if not link:
            continue
        a = link[0]
        title = contents(item).removeprefix(contents(a)).strip(" ,")
        records.append(Entry(contents(a), title, "Geometry", profile_link(base, a.get("href"))))
    return records


def parse_strasbourg(document, base):
    records = []
    subject = "Algebraic Geometry" if "géométrie algébrique" in text_at(document, "//h1").casefold() else "Geometry"
    for row in document.xpath("//h3[.='Membres permanents']/following-sibling::ul[1]/li"):
        name, _, title = contents(row).partition(",")
        if not title.strip():
            continue
        url = next((url for _, url in urls(row, base)), "")
        records.append(Entry(name.strip(), title.strip(), subject, homepage=url))
    return records


def parse_maryland(document, base):
    records = []
    for heading in document.xpath(f"//h3[{class_token('tm-title')}]"):
        card = heading.getparent()
        title = next((clean(line) for line in heading.xpath("following-sibling::text()") if clean(line)), "")
        homepage = next((url for label, url in urls(card, base) if label.casefold() == "website"), "")
        records.append(Entry(display_name(contents(heading)), title, homepage=homepage))
    return records


def parse_caltech(document, base):
    records = []
    for heading in document.xpath("//nav/h2[.='Professorial Faculty' or .='Emeritus Faculty' or .='Teaching Faculty']"):
        title = {
            "Professorial Faculty": "Academic Faculty", "Emeritus Faculty": "Professor Emeritus",
            "Teaching Faculty": "Instructor",
        }[contents(heading)]
        for link in heading.getparent().xpath("./ul/li/a[starts-with(@href,'/people/')]"):
            profile = profile_link(base, link.get("href")).split("?", 1)[0]
            records.append(Entry(contents(link), title, profile=profile))
    return records


def parse_illinois(document, base):
    records = []
    for card in document.xpath(f"//article[{class_token('profile-card')}]"):
        link = card.xpath(f"./a[{class_token('profile-card__link')}]")
        if not link:
            continue
        title = text_at(card, ".//div[contains(@class,'field-dircore-appt-title-local')]")
        records.append(Entry(contents(link[0]), title, profile=profile_link(base, link[0].get("href"))))
    return records


def parse_manchester(document, base):
    records = []
    for row in document.xpath("//h2[.='Academic staff']/following-sibling::ul[1]/li"):
        for name, profile in urls(row, base):
            title = contents(row).removeprefix(name).strip(" –-")
            records.append(Entry(name, title, profile=profile))
    return records


def parse_georgia_tech(document, base):
    records = {}
    for heading in document.xpath("//h3[normalize-space()]"):
        field = contents(heading)
        for listing in heading.xpath("./following-sibling::ul[1]"):
            for name, link in urls(listing, base):
                if "/people/" not in urlparse(link).path:
                    continue
                person = records.setdefault(name, Entry(name, profile=profile_link(base, link)))
                # These groups cover several specialties. The individual’s profile must identify the field.
                description = field.replace("Algebra, Number Theory, and Algebraic Geometry", "Algebra / number theory / geometry group")
                person.research = " / ".join(filter(None, (person.research, description)))
    return list(records.values())


def parse_technion(document, base):
    records = []
    for link in document.xpath("//h2[@class='member-name']/a[@href]"):
        name = contents(link)
        panel = link.getparent().getparent()
        title = text_at(panel, "./div[@class='a-title']")
        records.append(Entry(name, title, profile=profile_link(base, link.get("href"))))
    return records


def parse_regensburg(document, base):
    records = []
    for heading in document.xpath("//h3[@class='contact__title']"):
        text = contents(heading)
        title = "Professor Emeritus" if re.search(r"emerit|\bi\.\s*r\.", text, re.I) else "Professor"
        link_section = heading.getparent().xpath("./div[@class='contact__links']")
        page = next((url for div in link_section for label, url in urls(div, base) if label.startswith("Weitere Infos")), "")
        if text.startswith(("Prof.", "Professor")):
            records.append(Entry(untitled(text), title, homepage=page))
    return records


def parse_fau(document, base):
    records = []
    for section in document.xpath("//section[@class='format-compact-container'][.//h1/a]"):
        link = section.xpath(".//h1/a")[0]
        specialty = text_at(section, ".//p[@class='organisation_name']")
        title = text_at(section, ".//p[@class='jobtitle']")
        if title == "Professors":
            title = "Professor"
        records.append(Entry(untitled(contents(link)), title, specialty, profile_link(base, link.get("href"))))
    return records


def parse_grenoble(document, base):
    return [
        Entry(name, research="Geometry", homepage=url)
        for panel in document.xpath("//p[strong[normalize-space()='Membres permanents']]/following-sibling::p[1]")
        for name, url in urls(panel, base)
    ]


def parse_bielefeld_ag(document, base):
    return [
        Entry(untitled(name), "Professor", "Algebraic and Arithmetic Geometry", homepage=profile_link(base, url))
        for panel in document.xpath("//h3[.='Professors']/following-sibling::ul[1]")
        for name, url in urls(panel, base)
    ]


def parse_muenster_crc(document, base):
    records = []
    for link in document.xpath("//tr[td[2]]/td[1]/a[contains(@href,'show_perspage.shtml')]"):
        parts = [part.strip() for part in contents(link).split(",")]
        name = display_name(", ".join(parts[:2]))
        title = parts[2] if len(parts) > 2 else ""
        records.append(Entry(name, title, "Geometry", profile_link(base, link.get("href"))))
    return records


def parse_tsinghua(document, base):
    records = []
    for card in document.xpath(f"//li/a[{class_token('gp-flex')}][.//div[{class_token('name')}]]"):
        info = card.xpath(f".//div[{class_token('name')}][span]")
        if not info:
            continue
        name = clean(" ".join(info[0].xpath("./text()")))
        title = text_at(info[0], "./span")
        field = text_at(card, f".//div[{class_token('area')}]").removeprefix("研究领域：").strip()
        if name and title:
            records.append(Entry(name, title, field, profile_link(base, card.get("href"))))
    return records


def parse_edinburgh_hodge(document, base):
    records = []
    for link in document.xpath("//table[.//th[normalize-space()='Faculty']]//tr/td[2]/a[normalize-space()]"):
        row = link.getparent().getparent()
        if len(contents(link.getparent())) > 80:
            continue
        research = text_at(row, "./following-sibling::tr[1]/td[2]")
        name = contents(link)
        homepage = profile_link(base, link.get("href"))
        records.append(Entry(name, "Academic Faculty", research, homepage=homepage))
    return records


def parse_tsinghua_ymsc(document, base):
    title = text_at(document, "//title").split("-", 1)[0].strip()
    if title not in ("教授","副教授","助理教授"):
        return []
    records = []
    for link in document.xpath("//div[@class='teacher_text']/a[@href]"):
        name = text_at(link, ".//div[@class='t_main_right']/h4")
        research = text_at(link, ".//div[@class='t_main_right']/p")
        if name:
            records.append(Entry(name, title, research, profile_link(base, link.get("href"))))
    return records


def parse_usc(document, base):
    records = []
    for card in document.xpath("//div[@class='text-container'][h3 and div[contains(@class,'f--description')]]"):
        heading = card.xpath("./h3")[0]
        bio = text_at(card, "./div[contains(@class,'f--description')]/p[1]")
        title = re.split(r"\b(?:Email|Phone|Office|Website)\s*:", bio, 1, flags=re.I)[0].strip()
        title = title if len(title) <= 150 else ""
        url = next((link for _, link in urls(heading, base)), "")
        records.append(Entry(display_name(contents(heading)), title, profile=url))
    return records


def parse_usc_group(document, base):
    return [
        Entry(display_name(name), research="Algebra and geometry research group", homepage=link)
        for section in document.xpath("//h4[.='Tenured and Tenure-Track Faculty']/following-sibling::ul[1]")
        for name, link in urls(section, base)
    ]


def parse_columbia(document, base):
    records = []
    for row in document.xpath(f"//div[{class_token('cn-list-row')}][.//h3/a]"):
        link = row.xpath(".//h3/a")[0]
        title = text_at(row, f".//span[{class_token('title')}]")
        if not title and {"senior-faculty","junior-faculty"}.intersection(row.get("class","").split()):
            title = "Academic Faculty"
        homepage = next((url for label,url in urls(row,base) if label.casefold() in {"website","homepage","personal website"}),"")
        records.append(Entry(contents(link),title,profile=profile_link(base,link.get("href")),homepage=homepage))
    return records


def parse_ucsd(document, base):
    records = []
    for row in document.xpath("//tr[td[6] and td[5]/a[@href]]"):
        name = text_at(row, "./td[position()<=2]")
        title = text_at(row, "./td[6]")
        url = profile_link(base, row.xpath("./td[5]/a/@href")[0])
        if name and title and name != "First Name Last Name":
            records.append(Entry(name,title,homepage=url))
    return records


def parse_psu(document, base):
    records = []
    for link in document.xpath("//div[contains(@class,'views-field-field-name')]//a[contains(@href,'/math/people/')]"):
        panel = next((e for e in link.iterancestors() if "faculty-card" in e.get("class","").split()), link.getparent().getparent())
        title = text_at(panel, ".//div[contains(@class,'views-field-field-staff-title')]/div")
        research = text_at(panel, ".//div[contains(@class,'views-field-field-res')]/div")
        records.append(Entry(contents(link),title,research,profile_link(base,link.get("href"))))
    return records


def parse_complutense(document, base):
    records = []
    for cell in document.xpath("//tr/td[1][p[1][contains(.,',')] and p[2]]"):
        name = text_at(cell,"./p[1]")
        last, _, given = name.partition(",")
        title = contents(cell).removeprefix(name).strip()
        role = split_role(title)
        if name and role != "unverified":
            records.append(Entry(f"{given.strip()} {last.title()}", title, "Geometría y Topología"))
    return records


def parse_granada(document, base):
    records = []
    for row in document.xpath("//div[@class='personal']/div[@class='persona']"):
        links = row.xpath(".//div[@class='nombre']/a[starts-with(@href,'/personal/')]")
        if links:
            link = links[0]
            records.append(Entry(contents(link),text_at(row,".//div[@class='cargo']"),"Geometría y Topología",profile_link(base,link.get("href"))))
    return records


def parse_jyvaskyla(document, base):
    records = []
    for link in document.xpath(f"//a[{class_token('liftup--person')} and starts-with(@href,'/en/people/')]"):
        title = text_at(link, ".//div[contains(@class,'field--name-field-person-title')]")
        if split_role(title) in ("faculty","emeritus","associated"):
            records.append(Entry(text_at(link,f".//span[{class_token('heading')}]"),title,profile=profile_link(base,link.get("href"))))
    return records


def parse_polyu(document, base):
    records = []
    for row in document.xpath("//div[@class='ppl-detail-blk'][.//span[contains(@class,'ppl-detail-blk__name')]]"):
        title = text_at(row, ".//p[contains(@class,'ppl-detail-blk__title')]")
        label = text_at(row, ".//span[contains(@class,'ppl-detail-blk__name')]")
        profile = next((url for _,url in urls(row,base) if "/ama/people/academic-staff/" in urlparse(url).path),"")
        homepage = next((url for name,url in urls(row,base) if name.casefold() in {"personal website","website"}),"")
        records.append(Entry(untitled(label),title,profile=profile,homepage=homepage))
    return records


def parse_weizmann(document, base):
    records = []
    for row in document.xpath("//div[@class='person-wrap'][div[@class='second-side']/h2[contains(@class,'font-22')]]"):
        research = text_at(row,"./div[@class='second-side']/div[@class='person-position']")
        homepage = next((url for label,url in urls(row,base) if label.casefold() in {"homepage","home page"}),"")
        name = text_at(row,"./div[@class='second-side']/h2")
        if name:
            records.append(Entry(name,"Academic Faculty",research,homepage=homepage))
    return records


def parse_ucl(document, base):
    records = []
    for row in document.xpath("//table[.//strong[.='Name']]//tr[td[3] and not(.//strong[.='Name'])]"):
        name_cell = row.xpath("./td[1]")[0]
        name = next((clean(t) for t in name_cell.xpath("./text()") if clean(t)), "")
        title = "Professor" if re.match(r"^Prof(?:essor)?\.? ",name) else "Academic and Lecturing Staff"
        profile = next((url for label,url in urls(name_cell,base) if label.casefold()=="ucl profile"),"")
        homepage = next((url for label,url in urls(row,base) if label.casefold() in {"website","personal website","homepage"}),"")
        if name:
            records.append(Entry(untitled(name),title,text_at(row,"./td[2]"),profile,homepage))
    return records


def parse_polimi(document, base):
    records = []
    for heading in document.xpath("//h2[.='Full Professors' or .='Associate Professors' or .='Assistant Professors']"):
        section = heading.getparent()
        for listing in section.itersiblings():
            if listing.xpath(".//h2"):
                break
            if listing.get("class") != "personale":
                continue
            row = listing.xpath("./li")[0]
            links = row.xpath("./a[contains(@href,'?id=') and span[normalize-space()]]")
            if not links:
                continue
            link = links[0]
            homepage = next((url for label,url in urls(row,base) if "visita la pagina personale" in label.casefold()),"")
            records.append(Entry(text_at(link,"./span[last()]"),contents(heading).removesuffix("s"),profile=profile_link(base,link.get("href")),homepage=homepage))
    return records


def parse_sapienza(document, base):
    records = []
    for row in document.xpath("//tr[td[5] and td[last()]/a[contains(@href,'/lecturer/')]]"):
        title = text_at(row,"./td[5]")
        name = text_at(row,"./td[2]") + " " + text_at(row,"./td[1]")
        records.append(Entry(clean(name),title,profile=profile_link(base,row.xpath("./td[last()]/a/@href")[0])))
    return records


def parse_sns(document, base):
    return [
        Entry(contents(link),"Mathematics Teaching Staff",profile=profile_link(base,link.get("href")))
        for link in document.xpath("//article[.//h2[.='Docenti']]//a[starts-with(@href,'/it/persona/')]")
    ]


def parse_ubc(document, base):
    records = []
    for link in document.xpath("//td[contains(@class,'views-field-field-full-name')]/a[starts-with(@href,'/user/')]"):
        name = contents(link)
        if name and not name.startswith("["):
            records.append(Entry(display_name(name),profile=profile_link(base,link.get("href"))))
    return records


def parse_ens(document, base):
    records = []
    for panel in document.xpath("//div[@class='awsm-personal-info'][h3 and span]"):
        title = text_at(panel,"./span")
        name = text_at(panel,"./h3")
        if name and title:
            records.append(Entry(name,title))
    return records


PARSERS = {
    "stanford": parse_stanford, "stonybrook": parse_stonybrook, "stonybrook_group": parse_stonybrook_group,
    "bonn": parse_bonn, "bicmr": parse_bicmr, "princeton": parse_princeton, "princeton_group": parse_princeton_group,
    "pku": parse_pending, "pku_pure":parse_pku_pure, "rutgers": parse_pending,
    "pending": parse_pending, "mit": parse_mit, "mit_group": parse_mit_group, "nyu": parse_nyu, "nyu_research": parse_nyu_research,
    "berkeley": parse_berkeley, "eth": parse_eth, "eth_topic": parse_eth_topic, "epfl": parse_epfl, "epfl_geometry": parse_epfl_geometry,
    "ucla": parse_ucla, "ucla_geometry": parse_ucla_geometry, "yale": parse_yale, "kyoto": parse_kyoto, "warwick_ag": parse_warwick_ag,
    "oxford": parse_oxford, "oxford_geometry": parse_oxford_geometry, "warwick": parse_warwick, "duke": parse_duke,
    "uchicago": parse_uchicago, "imperial": parse_imperial, "brown_geometry": parse_brown_geometry,
    "tokyo": parse_tokyo, "tokyo_ipmu": parse_tokyo_ipmu, "kyoto_rims": parse_kyoto_rims, "northwestern": parse_northwestern, "purdue": parse_purdue,
    "washington": parse_washington, "cornell": parse_cornell, "waterloo": parse_waterloo, "uci_catalog": parse_uci_catalog,
    "tel_aviv": parse_tel_aviv, "hebrew": parse_hebrew, "sissa": parse_sissa, "strasbourg": parse_strasbourg,
    "maryland": parse_maryland, "caltech": parse_caltech, "illinois": parse_illinois,
    "manchester": parse_manchester, "georgia_tech": parse_georgia_tech,
    "technion": parse_technion, "regensburg": parse_regensburg, "fau": parse_fau,
    "grenoble": parse_grenoble, "bielefeld_ag": parse_bielefeld_ag, "muenster_crc": parse_muenster_crc,
    "tsinghua": parse_tsinghua, "tsinghua_ymsc": parse_tsinghua_ymsc, "edinburgh_hodge": parse_edinburgh_hodge,
    "usc":parse_usc, "usc_group":parse_usc_group, "columbia":parse_columbia, "ucsd":parse_ucsd, "psu":parse_psu,
    "complutense":parse_complutense, "granada":parse_granada, "jyvaskyla":parse_jyvaskyla, "polyu":parse_polyu,
    "weizmann":parse_weizmann, "ucl":parse_ucl, "polimi":parse_polimi, "sapienza":parse_sapienza, "sns":parse_sns,
    "ubc":parse_ubc, "ens":parse_ens,
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
    for row in main.xpath(".//tr[td[1][normalize-space()='Field of Interest' or normalize-space()='Research Interests']]/td[2]"):
        value = contents(row)
        if value and len(value) < 600:
            research.append(value)
    homepage = cv = bibliography = ""
    for label, url in urls(main, base):
        low = label.lower()
        host = urlparse(url).hostname or ""
        if not homepage and low in {"home page", "my home page", "homepage", "personal website", "my personal website", "personal homepage", "professional website", "website", "personal web page", "web site", "個人ホームページ"}:
            if host not in {"linkedin.com", "www.linkedin.com", "zoom.us"} and not host.endswith(".zoom.us"):
                homepage = url
        if not cv and re.search(r"^(?:(?:my|short|brief|latest|full) )?(?:(?:curriculum|cv|vita|lebenslauf|résumé|resume)\b|简历|履歴書|略歴)", low):
            cv = url
        if not bibliography and low in {"publications","papers","research papers","publications and preprints","research publications"}:
            bibliography = url
    if not cv:
        for link in main.xpath(".//a[@href]"):
            href = profile_link(base, link.get("href"))
            target = urlparse(href)
            if target.scheme != "https" or target.username or target.password:
                continue
            if not re.search(r"(?:^|[-_./])(?:cv|vita|curriculum-vitae)(?:[-_.]|$)", target.path, re.I):
                continue
            context = contents(link.getparent())
            if len(context) < 220 and re.search(r"curriculum vitae|\bCV\b", context, re.I):
                cv = href
                break
    return {"research":" / ".join(dict.fromkeys(research)), "homepage":homepage, "cv":cv, "publications":bibliography}
