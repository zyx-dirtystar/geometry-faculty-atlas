"""Parse verified public directory formats. Keep role and topic evidence distinct."""

from dataclasses import dataclass, field
from html import unescape
import json
import re
from urllib.parse import quote, urljoin, urlparse


@dataclass
class Entry:
    name: str
    title: str = ""
    research: str = ""
    profile: str = ""
    homepage: str = ""
    topics: list = field(default_factory=list)


TOPICS = {
    "complex": re.compile(r"complex (?:differential |algebraic )?geometr|k[äa]hler|hyperk[äa]hler|géométrie complexe|geometr[ií]a comple[jx]a|komplexe geometrie|複素(?:微分)?幾何|ケーラー|复几何|\bCR\s*几何", re.I),
    "differential": re.compile(r"differential geometr|riemannian (?:geometr|(?:sub)?manifolds)|submanifold geometry|hyperbolic geometry|lorentzian geometry|(?<!asymptotic )geometric analys|ricci flow|mean curvature flow|scalar curvature|geometric flows?|gauge theory|géométrie (?:différentielle|riemannienne)|analyse géométrique|geometr[ií]a (?:differenziale|diferencial|riemanniana)|an[aá]lisis geom[eé]trico|differentialgeometrie|微分幾何|幾何解析|平均曲率流|リッチフロー|微分几何|几何分析", re.I),
    "algebraic": re.compile(r"algebraic (?:(?:and|&) arithmetic )?geometr|arithmetic geometr|birational geometr|enumerative geometr|tropical (?:algebra and )?geometr|higher dimensional geometr|algebraic varieties|algebraic (?:surface|cycles)|hodge theory|derived algebraic|schemes and stacks|géométrie (?:algébrique|arithmétique|birationnelle)|geometr[ií]a (?:alg[eé]brica|algebrica|aritm[eé]tica|biracional)|algebraische geometrie|代[数數][幾几]何|算[术術][幾几]何|双有理", re.I),
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

def parse_structured_directory(document, base, layout):
    """Read the scoped person cards of a reviewed official directory."""
    def value(card, key):
        paths = layout.get(key, [])
        if isinstance(paths, str):
            paths = [paths]
        return clean(" ".join(
            contents(item) if hasattr(item, "itertext") else str(item)
            for path in paths for item in card.xpath(path)
        ))

    def link(card, key):
        target = value(card, key)
        if not target:
            return ""
        url = quote(urljoin(base, target), safe=":/?&=#%+@!$'()*;,[]")
        parsed = urlparse(url)
        if parsed.scheme == "http" and parsed.hostname == urlparse(base).hostname and urlparse(base).scheme == "https":
            url = parsed._replace(scheme="https").geturl()
        return url if parsed.scheme in ("http", "https") and not parsed.username and not parsed.password else ""

    rows = []
    linked = {}
    for card in document.xpath(layout["cards"]):
        name = value(card, "name")
        if not name:
            continue
        name = re.sub(r"^(?:Emeritus Professor\s+|Mrs?\.?\s+|Mx\.?\s+|Doctor\s+)", "", name, flags=re.I) if layout.get("strip_english_honorific") else name
        name = re.sub(r"^(?:(?:(?:Associate|Assistant) Professor|A/Prof|Prof|Professor|Dra?|Professeur)\.?\s+)+", "", name, flags=re.I).strip(" ,")
        if layout.get("split_han_alias"):
            name = re.sub(r"\s+[\u3400-\u9fff]+$", "", name)
        if layout.get("surname_first"):
            name = display_name(name)
        title = value(card, "title").strip(" :") or layout.get("default_title", "")
        research = value(card, "research") or layout.get("default_research", "")
        profile = link(card, "profile")
        homepage = link(card, "homepage")
        prior = linked.get((name, profile)) if profile else None
        if prior is not None:
            if research and research != prior.research:
                prior.research = " / ".join(dict.fromkeys(filter(None, [*prior.research.split(" / "), research])))
            continue
        row = Entry(name, title, research, profile, homepage)
        if profile:
            linked[name, profile] = row
        rows.append(row)
    return rows


def matched_fields(research):
    return sorted(key for key, keyword in TOPICS.items() if keyword.search(research))


def parse_science_tokyo(document, base):
    ranks = {"P": "Professor", "AP": "Associate Professor"}
    rows = []
    for row in document.xpath("//table[.//tr/td[3][contains(.,'Representation theory')]]//tr[td[3]]"):
        family, separator, given = text_at(row, "./td[1]").partition(",")
        name = f"{given.strip()} {family.title()}" if separator else family
        code = text_at(row, "./td[2]")
        topic = text_at(row, "./td[3]")
        homepage = next((url for _, url in urls(row, base)), "")
        if name and topic:
            rows.append(Entry(name, ranks.get(code, code), topic, homepage=homepage))
    return rows


def parse_cuhk_staff(document, base):
    rows = []
    for table in document.xpath("//table[caption/h3]"):
        title = text_at(table, "./caption/h3")
        for cell in table.xpath(".//tr/td[1][strong or .//a/strong]"):
            name = re.sub(r"^Prof\.\s+|\s*\([^()]+\)$", "", contents(cell))
            name = re.sub(r"\b[A-Z]{2,}\b", lambda match: match[0].title(), name)
            profile = next((url for _, url in urls(cell, base)), "")
            if name:
                rows.append(Entry(name, title, profile=profile))
    return rows


def parse_glasgow_staff(document, base):
    rows = []
    for label, forced_title in (("research-teachinglist", ""), ("honorary-visitinglist", "Honorary or visiting")):
        for row in document.xpath(f"//ul[@id='{label}']/li[a]"):
            link = row.xpath("./a[1]")[0]
            surname, sep, given = contents(link).partition(",")
            given = re.sub(r"^(?:\s*(?:Professor|Prof|Dr|Mr|Mrs|Ms|Miss)\.?\s+)+", "", given, flags=re.I)
            name = f"{given} {surname}".strip() if sep else surname
            title = forced_title or clean(" ".join(row.xpath("./text()"))).strip(" ()")
            rows.append(Entry(name, title, profile=profile_link(base, link.get("href"))))
    return rows


def parse_ucas_staff(document, base):
    rows = []
    for link in document.xpath("//div[contains(@class,'neirongarea_xm')]//div[@class='yp_ity']/a[@href]"):
        url = profile_link(base, link.get("href"))
        split = re.search(r"people\.ucas\.ac\.cn/(?:https?://people\.ucas\.ac\.cn/)?(~[\w-]+)$", url)
        if split:
            url = f"https://people.ucas.ac.cn/{split[1]}"
        if contents(link):
            rows.append(Entry(contents(link), profile=url))
    return rows


def parse_isi_kolkata(document, base):
    rows = []
    for cell in document.xpath("//tr/td[b and br][contains(.,'Research Interest')]"):
        name, separator, title = text_at(cell, "./b[1]").rpartition(",")
        if not separator or not name.strip():
            continue
        research = next((clean(value).split(":", 1)[-1].strip()
                         for value in cell.xpath("./text()") if re.search("research interest", value, re.I)), "")
        homepage = next((profile_link(base, link.get("href"))
                         for link in cell.xpath("./a[input[@value='Homepage'] and @href]")), "")
        rows.append(Entry(name.strip(), title.strip(), research, homepage=homepage))
    return rows


def parse_lse_staff(document, base):
    rows = []
    for section in document.xpath("//div[contains(@class,'accordion-item')][h3/button[normalize-space()='Academic Faculty' or starts-with(normalize-space(),'Academic Associates')]]"):
        for item in section.xpath(".//li[div[@class='item__content']]"):
            names = item.xpath("(.//p[strong])[1]/strong[1]")
            if not names:
                continue
            name = re.sub(r"^(?:Professor|Prof\.?|Dr\.?|Mr\.?|Ms\.?)\s+", "", contents(names[0]))
            details = [clean(part) for part in names[0].getparent().xpath("./text()") if clean(part)]
            title = details[0] if details and not re.match(r"(?:Room|Email)\b", details[0], re.I) else ""
            profile = next((url for label, url in urls(item, base) if label == "Profile page"), "")
            if name:
                rows.append(Entry(name, title, profile=profile))
    return rows


def parse_utm_staff(document, base):
    rows = []
    ranks = {"PROFESSORS": "Professor", "ASSOCIATE PROFESSORS": "Associate Professor",
             "SENIOR LECTURERS": "Senior Lecturer", "LECTURERS": "Lecturer"}
    for card in document.xpath("//div[contains(@class,'et_pb_team_member_description')][h4]"):
        heading = text_at(card, "./h4")
        rank = re.match(r"^((?:(?:Associate|Adjunct|Emeritus)\s+)?Professor|Assoc\.\s*Prof\.?)(\s*\(Retired\))?\s+", heading, re.I)
        name = heading[rank.end():] if rank else heading
        name = re.sub(r"^(?:(?:Ts|Dr|Ir|Sr|Mr|Mrs|Ms)\.?\s*)+(?=[A-Z])", "", name)
        position = text_at(card, "./p[contains(@class,'et_pb_member_position')]")
        title = rank[0].strip() if rank else ""
        if not title and re.search(r"\b(?:lecturer|professor|fellow)\b", position, re.I):
            title = position
        if not title:
            title = ranks.get(text_at(card, "preceding::h2[1]").upper(), "")
        detail = card.xpath("ancestor::div[contains(concat(' ',normalize-space(@class),' '),' et_pb_row ')][1]"
                            "//div[contains(concat(' ',normalize-space(@class),' '),' et_pb_text_inner ')]")
        research = ""
        homepage = ""
        for section in detail:
            match = re.search(r"\bResearch Area:\s*(.+?)(?=\s+(?:Email|Office|Tel|Website|Admin|Other Info)\s*[:/]|$)",
                              contents(section), re.I)
            if match:
                research = match[1].strip(" –—-")
            homepage = homepage or next((url for label, url in urls(section, base)
                                         if label.casefold() in ("website", "homepage") and urlparse(url).scheme in ("http", "https")), "")
        if name:
            rows.append(Entry(name, title, research, homepage=homepage))
    return rows


def parse_auckland_research(document, base):
    rows = []
    for heading in document.xpath("//h4[.//a[contains(@href,'profiles.auckland.ac.nz')]]"):
        link = heading.xpath(".//a[contains(@href,'profiles.auckland.ac.nz')]")[0]
        label = contents(link)
        rank = re.match(r"^((?:(?:Associate|Distinguished|Emeritus|Honorary) )?Professor|(?:Senior )?Lecturer|Dr\.?)\s+", label)
        if not rank:
            continue
        topic = text_at(heading, "./following-sibling::*[1][self::ul]/li")
        title = "" if rank[1].rstrip(".") == "Dr" else rank[1]
        rows.append(Entry(label[rank.end():], title, topic, profile=profile_link(base, link.get("href"))))
    return rows


def parse_iit_delhi_faculty(records, base):
    if not isinstance(records, list):
        return []
    rows = []
    for record in records:
        name = clean(record.get("name") or "")
        if not name:
            continue
        homepage = clean(record.get("webpage_url") or "")
        uri = urlparse(homepage)
        if uri.scheme not in ("https", "http") or not uri.hostname or uri.username or uri.password:
            homepage = ""
        rows.append(Entry(name, clean(record.get("title") or ""),
                          clean(record.get("research_areas") or ""), homepage=homepage))
    return rows


def split_role(title, region=None):
    title = title.strip(" ,;–—")
    if title.casefold().startswith("future appointment ("):
        return "other"
    if re.search(r"\b(?:J\.\s*J\.\s*Sylvester|Szeg[oöő]) Assistant Professor\b", title, re.I):
        return "other"
    if re.match(r"^(?:(?:postgraduate|graduate) teaching assistant|teaching assistant|teaching demonstrator)\b", title, re.I):
        return "other"
    if region == "英国" and re.fullmatch(r"Maclaurin Scholar", title, re.I):
        return "other"
    if region == "法国":
        if re.fullmatch(r"(?:direct(?:eur|rice)|charg[ée]e?) de recherche(?:\s+CNRS)?", title, re.I):
            return "faculty"
        if re.fullmatch(r"visit(?:eur|euse)|membre associ[ée]e?|chercheu(?:r|se) b[ée]n[ée]vole", title, re.I):
            return "associated"
        if re.fullmatch(r"PRAG|PRCE|ATER", title, re.I):
            return "other"
    if region == "波兰":
        if re.search(r"emeryt", title, re.I):
            return "emeritus"
        if re.search(r"\b(?:profesor|adiunkt)\b", title, re.I):
            return "faculty"
        if re.search(r"\b(?:doktorant|asystent)\b", title, re.I):
            return "other"
    if re.search(r"emerit|émérit|emérit|retired|in memoriam|honoraire|jubilad|\bi\.?\s*r\.|荣休", title, re.I):
        return "emeritus"
    if re.search(r"visiting|visitor|adjunct|courtesy|affiliate|gästprofessor|gastwissen|secondary appointment|^invit[ée]|^honorary|\bsênior\b|访问|兼职", title, re.I):
        return "associated"
    if region == "巴西" and re.search(r"\bprofessor[a]?\s+(?:associad[oa]|assistente|doutor[a]?|titular)", title, re.I):
        return "faculty"
    if re.search(r"\bteaching (?:track|professor)|professor of teaching|faculty lecturer", title, re.I):
        return "other"
    if re.search(r"\bprofesor(?:a)? (?:asociad[oa]|asistent[ea]|titular)", title, re.I):
        return "faculty" if region == "智利" or "titular" in title.casefold() else "associated"
    if region in {"英国", "澳大利亚", "新西兰", "马来西亚"} and re.match(r"^(?:senior )?lecturer\b", title, re.I):
        return "other" if re.search(r"teaching|education|placement", title, re.I) else "faculty"
    if re.search(r"post.?doc|postdoktor|instructor|lecturer|student|\bph\.?d\.? candidate\b|professional services staff|^former (?:faculty|scientific staff)$|^lecteur|\b(?:dottorand[oa]|doctorand[oa]?|doctorante?|doktorand(?:in)?)\b|^講師$|博士后", title, re.I):
        return "other"
    if re.search(r"\bprofessors?\b|\bprofesor de matemáticas\b|\bacademic faculty\b|\btenure-track researcher\b|\breader\b|universitetslektor|prof\. dr\.|univ\.-?prof\.|assoz\. prof\.|professeur|professor(?:e|essa) (?:ordinari[oa]|associat[oa])|\bprofesor[a]? ayudante doctor[a]?\b|catedr[aá]tic[ao]|titular de universidad|contratad[oa] doctor|ma[iî]tr(?:e|esse) de conf[ée]rences|研究员|教授|^助教$", title, re.I):
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
    fallback_title = "Professor" if "Directory: Professors" in text_at(document, "//main/h1") else ""
    for link in document.xpath("//main//div[@class='name']//a[contains(@href,'pid=')]"):
        name = display_name(contents(link))
        card = link.xpath("ancestor::div[@class='person'][1]")
        title = text_at(card[0], ".//div[@class='title']") if card else ""
        research = text_at(card[0], ".//div[@class='research']/p/em") if card else ""
        start = text_at(card[0], ".//div[@class='leave']") if card else ""
        if start.casefold().startswith("starting "):
            title = f"Future appointment ({start}): {title}"
        records.append(Entry(name, title or fallback_title, research, profile=profile_link(base, link.get("href"))))
    return records


def parse_mit_group(document, base):
    records = []
    for row in document.xpath("//main//li[a[contains(@href,'pid=')] and span[contains(@class,'light-ital')]]"):
        link = row.xpath("./a")[0]
        records.append(Entry(contents(link), research=text_at(row, "./span"), profile=profile_link(base, link.get("href"))))
    return records


def parse_nyu(document, base):
    records = []
    for heading in document.xpath("//h2[following-sibling::*[1][@class='people-grid']]"):
        grid = heading.xpath("./following-sibling::*[1]")[0]
        active = contents(heading).casefold() == "tenure / tenure-track"
        for card in grid.xpath("./a[div[@class='people-description'] or figure/div[@class='people-description']]"):
            info = card.xpath("./div[@class='people-description'] | ./figure/div[@class='people-description']")[0]
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
        name_link = next(iter(name_cell.xpath("./a[following-sibling::br][1]")), None) if not name else None
        if name_link is not None:
            name = contents(name_link)
        rank = re.match(r"^((?:Associate |Assistant )?)Prof(?:essor)?\.?\s+", name)
        title = rank[1] + "Professor" if rank else "Academic and Lecturing Staff"
        name = name[rank.end():] if rank else name
        profile = next((url for label,url in urls(name_cell,base) if label.casefold()=="ucl profile"),"")
        homepage = next((url for label,url in urls(row,base) if label.casefold() in {"website","personal website","homepage"}),"")
        if not homepage and name_link is not None:
            homepage = next((url for label, url in urls(name_cell, base) if label == contents(name_link)), "")
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


def parse_vienna(document, base):
    records = []
    for table in document.xpath("//div[contains(@class,'univiepersonal-list-container')]//table"):
        group = text_at(table,"preceding::h2[1]")
        for row in table.xpath(".//tr[td[1] and td[2]]"):
            name = text_at(row,"./td[1]")
            title = text_at(row,"./td[2]")
            link = next((url for _,url in urls(row.xpath("./td[1]")[0],base)),"")
            if name and group:
                records.append(Entry(name,title,group,link))
    return records


def parse_ustc(document, base):
    records = []
    for table in document.xpath("//div[@class='paging_content']/table"):
        title = ""
        for row in table.xpath("./tbody/tr[td]|./tr[td]"):
            cells = row.xpath("./td")
            if len(cells) == 1:
                label = contents(cells[0])
                if label in {"教授","副教授","讲师","特任副研究员","特任教授","特任副教授"}:
                    title = label
                continue
            name = text_at(row, "./td[1]")
            field = text_at(row, "./td[2]")
            href = next(iter(row.xpath("./td[1]//a/@href")),"")
            if title and name and clean(name).replace(" ","") != "姓名":
                records.append(Entry(re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])","",name),
                                     title,field,profile_link(base,href) if href else ""))
    return records


def parse_sustech(document, base):
    return [
        Entry(text_at(row,"./td[1]/a"),text_at(row,"./td[2]"),profile=profile_link(base,row.xpath("./td[1]/a/@href")[0]))
        for row in document.xpath("//tr[td[1]/a[starts-with(@href,'/c/')] and td[2]]")
    ]


def parse_uppsala(document, base):
    records = []
    for link in document.xpath("//a[contains(@href,'/personal?query=')][normalize-space()]"):
        panel = link.getparent().getparent()
        title = text_at(panel,"./ul/li[1]")
        records.append(Entry(display_name(contents(link)),title,profile=profile_link(base,link.get("href"))))
    return records


def parse_pisa_geometry(document, base):
    return [
        Entry(contents(link),research="Geometry",homepage=profile_link(base,link.get("href")))
        for link in document.xpath("//a[@href and normalize-space()]")
        if " " in contents(link) and len(contents(link)) < 70
    ]


def parse_kuleuven(document, base):
    records = []
    topic = "Geometry" if "/meetkunde/" in urlparse(base).path else "Algebra and Geometry"
    for link in document.xpath("//a[contains(@href,'/person/') and normalize-space()]"):
        label = contents(link)
        if not label.startswith(("Prof.","Professor ")):
            continue
        url = profile_link(base,link.get("href")).replace("http://www.kuleuven.be/","https://www.kuleuven.be/",1)
        records.append(Entry(re.sub(r"^dr\.\s+","",untitled(label),flags=re.I),"Professor",topic,profile=url))
    return records


def parse_cmls_geometry(document, base):
    records = []
    for heading in document.xpath("//h3[normalize-space()='Membres permanents']"):
        for row in heading.itersiblings():
            if row.tag in {"h2","h3"}:
                break
            name,sep,title = contents(row).partition(",")
            if row.tag != "p" or not sep or not name:
                continue
            parts = name.strip().rsplit(" ",1)
            name = " ".join([parts[0],parts[1].title()]) if len(parts)>1 and parts[-1].isupper() else name.strip()
            homepage = next((url for _,url in urls(row,base)),"")
            title = title.strip()
            if title.startswith("Prof."):
                title = title.replace("Prof.","Professor",1)
            records.append(Entry(name,title,"Geometry and Dynamics",homepage=homepage))
    return records


def parse_zurich_group(document, base):
    records = []
    for table in document.xpath("//table[.//tr[contains(.,', professor.')]]"):
        for cell in table.xpath(".//tr/td[2][contains(.,', professor.')]"):
            name,_,description = contents(cell).partition(", professor.")
            if name and description:
                records.append(Entry(name.strip(),"Professor",description.strip()[:500]))
    return records


def parse_sjtu_wucms(document, base):
    records = []
    for link in document.xpath("//ul[@class='zc_lb1']/li/a[.//h3 or .//h4]"):
        name = text_at(link,".//h3|.//h4")
        name = re.sub(r"\s*[（(][^()（）]+[）)]$","",name).strip()
        url = profile_link(base,link.get("href"))
        records.append(Entry(name,"Assistant Professor",profile=url))
    return records


def parse_hit(document, base):
    records = []
    for row in document.xpath("//div[@class='wp_entry']//tr[count(td)>=7]"):
        name = text_at(row,"./td[1]")
        if not name or name == "姓名":
            continue
        title = "副教授" if "/fjs/" in urlparse(base).path else "教授"
        records.append(Entry(name,title,text_at(row,"./td[7]")))
    return records


def parse_lmo(payload, base):
    records = []
    for item in payload.get("data",[]):
        name = clean(item.get("nom") or "")
        title = clean(item.get("fonction_feminine") or item.get("fonction") or "")
        team = clean(item.get("equipe") or "")
        href = item.get("url") or ""
        site = item.get("site") or ""
        if not name or not href.startswith(("/fr/membres/","/en/people/")):
            continue
        if urlparse(site).scheme not in {"https","http"}:
            site = ""
        records.append(Entry(name,title,team,profile_link(base,href),site))
    return records


def parse_zjnu(document, base):
    return [
        Entry(text_at(row,"./td[3]"),text_at(row,"./td[4]"))
        for row in document.xpath("//div[contains(@class,'wp_articlecontent')]//tr[td[1] and td[3] and td[4]]")
        if text_at(row,"./td[1]").isdigit() and text_at(row,"./td[3]")
    ]


def parse_sydney_profiles(document, base):
    records = []
    for link in document.xpath("//main//a[contains(@href,'?nsh')][normalize-space()]"):
        label = contents(link)
        if len(label.split()) < 2:
            continue
        match = re.match(r"^(?P<title>Emeritus Professor|Associate Professor|Assistant Professor|Professor)\s+",label)
        name = label[match.end():] if match else untitled(label)
        records.append(Entry(name,match["title"] if match else "",profile=profile_link(base,link.get("href")).split("?")[0]))
    return records


def parse_tamu(payload, base):
    records = []
    for item in payload:
        categories = set(item.get("tag") or [])
        if "mathematics" not in categories:
            continue
        title = " / ".join(item.get("titles") or [])
        if {"Emeritus Faculty","Retired Faculty"} & categories:
            title = "Professor Emeritus"
        elif "Visiting Faculty" in categories:
            title = "Visiting Professor"
        elif "Faculty" not in categories:
            continue
        research = " / ".join((item.get("researchAreas") or []) + (item.get("interests") or []))
        href = item.get("link") or ""
        name = clean(item.get("name") or "")
        if name and href.startswith("/mathematics/contact/profiles/"):
            records.append(Entry(name,title or "Academic Faculty",research,profile_link(base,href)))
    return records


def parse_wisconsin(payload, base):
    role_labels = {20:"Professor",21:"Associate Professor",22:"Assistant Professor",52:"Affiliated Professor"}
    records = []
    for item in payload:
        title = item.get("title") or {}
        name = clean(unescape(re.sub(r"<[^>]*>"," ",title.get("rendered",""))))
        roles = item.get("uw_staff_type") or []
        role = next((role_labels[n] for n in roles if n in role_labels and n != 52),"")
        if not role and 52 in roles:
            role = role_labels[52]
        href = item.get("link") or ""
        if name and role and href:
            records.append(Entry(display_name(name),role,profile=profile_link(base,href)))
    return records


def parse_psau_profiles(document, base):
    return [
        Entry(contents(link).title(),profile=profile_link(base,link.get("href")))
        for link in document.xpath("//h3[@class='title']/a[contains(@href,'/en/persons/')][normalize-space()]")
    ]


def parse_aix(document, base):
    records = []
    for row in document.xpath(f"//div[{class_token('lab_clickable_user')}]"):
        name = text_at(row,"./div[@class='lab_directory_table_row_name']")
        title = text_at(row,"./div[@class='lab_directory_table_row_function']")
        topic = text_at(row,"./div[@class='lab_directory_table_row_group']")
        if name and title:
            parts = name.split()
            cut = next((i for i,p in enumerate(parts) if not p.isupper()), 0)
            if cut:
                name = " ".join(parts[cut:] + [p.title() for p in parts[:cut]])
            records.append(Entry(name,title,topic))
    return records


def parse_padua_group(document, base):
    return [
        Entry(display_name(label), research="Algebraic and arithmetic geometry research group", homepage=profile_link(base,url))
        for label,url in urls(document,base)
        if "," in label and "/~" in url.replace("%7E","~").replace("%7e","~")
    ]


def parse_imj_tga(document, base, employer):
    records = []
    for modal in document.xpath("//div[@class='modal-content'][.//h4[@class='modal-title']]"):
        body = modal.xpath(".//div[@class='modal-body']")
        if not body:
            continue
        labels = [clean(t) for t in body[0].xpath("./text()") if clean(t)]
        if employer not in labels or "Permanents" not in labels:
            continue
        index = labels.index("Permanents")
        if len(labels) <= index+1:
            continue
        name = text_at(modal,".//h4[@class='modal-title']")
        parts = name.split()
        prefix = [p for p in parts if not p.isupper()]
        suffix = [p.title() for p in parts if p.isupper()]
        name = " ".join(prefix + suffix)
        page = next((url for _,url in urls(body[0],base)),"")
        records.append(Entry(name,labels[index+1],"IMJ-PRG geometry and topology group",homepage=page))
    return records


def parse_imj_sorbonne(document,base):
    return parse_imj_tga(document,base,"Sorbonne Université")


def parse_imj_paris_cite(document,base):
    return parse_imj_tga(document,base,"UPC")


def parse_china_faculty_portal(document, base):
    records = []
    for link in document.xpath(f"//a[{class_token('lib_title')} and @href and normalize-space()]"):
        panel = link.getparent()
        title = text_at(panel, f"./a/div[{class_token('unit')}][1]")
        records.append(Entry(contents(link),title,profile=profile_link(base,link.get("href"))))
    for card in document.xpath("//div[contains(@class,'result-wz')][h2]"):
        name = text_at(card,"./h2")
        href = next((url for _,url in urls(card.getparent(),base) if urlparse(url).path.endswith((".htm",".html"))),"")
        if name:
            records.append(Entry(name,profile=href))
    return records


def parse_ut_group(document,base):
    records = []
    for link in document.xpath("//main//a[starts-with(@href,'/directory/')][normalize-space()]"):
        name=contents(link)
        if len(name.split())>1:
            records.append(Entry(name,research="Geometry or algebra research group",profile=profile_link(base,link.get("href"))))
    return records


def parse_toronto_mississauga(document, base):
    records = []
    for heading in document.xpath("//h2[normalize-space()='Faculty - Mathematics']"):
        lists = heading.xpath("./following-sibling::*[1][contains(@class,'people-list')]")
        for panel in lists:
            for card in panel.xpath(f".//div[{class_token('people-primary-details')}]"):
                links = card.xpath(f"./div[{class_token('people-name')}]/a[@href]")
                title = text_at(card, f"./span[{class_token('people-position')}]").removeprefix("Title/Position ")
                if links and "(MATH)" in title:
                    link = links[0]
                    records.append(Entry(contents(link), title, profile=profile_link(base, link.get("href"))))
    return records


def parse_kth_members(document, base):
    records = []
    for row in document.xpath("//tr[td[@class='lastname']/a]"):
        surname = row.xpath("./td[@class='lastname']/a")[0]
        first = text_at(row, "./td[@class='firstname']")
        title = text_at(row, "./td[@class='title']")
        if first and title:
            records.append(Entry(f"{first} {contents(surname)}", title, profile=profile_link(base, surname.get("href"))))
    return records


def parse_kth_algebraic(document, base):
    records = []
    for card in document.xpath(f"//div[{class_token('contact-info__wrapper')}]"):
        name = text_at(card, ".//span[@property='name']")
        link = card.xpath(".//a[@property='url' and @href]")
        if name and link:
            records.append(Entry(name, research="Geometry and commutative algebra research group",
                                 profile=profile_link(base, link[0].get("href"))))
    return records


def parse_michigan(document, base):
    records = []
    for card in document.xpath(f"//div[{class_token('person')} and {class_token('row')}]"):
        links = card.xpath(f"./div/a[{class_token('name')} and @href]")
        if not links:
            continue
        link = links[0]
        title = text_at(link.getparent(), f"./span[{class_token('title')}]")
        tags = text_at(card, f"./div[{class_token('col-sm-4')}]").replace(
            "Algebra and Algebraic Geometry", "Algebra and geometry research group",
        )
        if title:
            records.append(Entry(contents(link), title, tags, profile_link(base, link.get("href"))))
    return records


def parse_rutgers_directory(document, base):
    records = []
    for card in document.xpath(f"//div[{class_token('newsinfo')}]"):
        links = card.xpath("./h2/a[@href and normalize-space()]")
        if not links:
            continue
        link = links[0]
        title = text_at(card, f"./dl/dd/span[{class_token('detail_jfield_12')}]")
        tags = text_at(card, f"./dl/dd/span[{class_token('detail_jfield_76')}]")
        tags = re.sub(r"(?:Number Theory|Algebra) and Algebraic Geometry", "Algebra and geometry research group", tags)
        focus = text_at(card, f"./dl/dd/span[{class_token('detail_jfield_77')}]")
        records.append(Entry(contents(link), title, " / ".join(filter(None, (tags, focus))),
                             profile_link(base, link.get("href"))))
    return records


def parse_uab(document, base):
    records = []
    for anchor in document.xpath("//a[contains(@onclick,'pop_ex_nou.php?id=')]"):
        route = re.search(r"'(pop_ex_nou\.php\?id=\d+&lang=eng)'", anchor.get("onclick"))
        raw_name = text_at(anchor.getparent().getparent(), "./div[1]")
        surname, separator, first = raw_name.partition(",")
        if route and separator and first.strip():
            records.append(Entry(f"{first.strip()} {surname}", profile=profile_link(base, route[1])))
    return records


def parse_uab_arithmetic(document, base):
    records = []
    directory_names = {
        "Francesc Bars": "Francesc Bars Cortina",
        "Marc Masdeu": "Marc Masdeu Sabaté",
        "Joaquim Roé": "Joaquim Roé i Vellvé",
        "Xavier Xarles": "Francesc Xavier Xarles Ribas",
    }
    for row in document.xpath("//tr[td[2][contains(.,'UAB (')]]"):
        links = row.xpath("./td[1]/a[@href]")
        rank = re.search(r"UAB \(([^)]+)\)", text_at(row, "./td[2]"))
        if not links or not rank:
            continue
        link = links[0]
        name = contents(link)
        homepage = next((url for label, url in urls(row, base) if label == "Personal page"), "")
        records.append(Entry(directory_names.get(name, name), rank[1], "Arithmetic geometry",
                             profile_link(base, link.get("href")), homepage))
    return records


def parse_waseda_japanese(document, base):
    rows = []
    for card in document.xpath("//table[.//tr[td[contains(.,'専門分野')]] and not(.//table)]"):
        cells = card.xpath(".//td")
        if len(cells) < 3:
            continue
        name, _, title = contents(cells[1]).rpartition(" ")
        if not name:
            continue
        homepage = next((url for label, url in urls(card, base) if label == "個人サイト"), "")
        rows.append(Entry(name, title, re.sub(r"^専門分野[：:]\s*", "", contents(cells[2])), homepage=homepage))
    return rows


def parse_usp_staff(document, base):
    for script in document.xpath("//script[contains(.,'const dados')]/text()"):
        match = re.search(r"const dados\s*=\s*(\[.*?\]);", script, re.S)
        if not match:
            continue
        try:
            cards = json.loads(match[1])
        except json.JSONDecodeError:
            continue
        return [
            Entry(card["nome"], card["funcao"], homepage=profile_link(base, card.get("perfil", "") or ""))
            for card in cards if card.get("exibir") is True and card.get("nome") and card.get("funcao")
        ]
    return []


def parse_usp_geometry(document, base):
    names = {
        "Daniel Tausk": "Daniel Victor Tausk",
        "Marcos M. Alexandrino": "Marcos Martins Alexandrino da Silva",
    }
    rows = []
    for card in document.xpath("//tr[starts-with(normalize-space(.),'Prof:')]"):
        name = contents(card).removeprefix("Prof:").strip()
        next_row = card.getnext()
        if next_row is None:
            continue
        topic = contents(next_row).removeprefix("Research Interests:").strip()
        if len(topic) < 10 or len(topic) > 500:
            continue
        rows.append(Entry(names.get(name, name), research=topic))
    return rows


def parse_durham_geometry(document, base):
    rows = []
    cards = document.xpath("//div[contains(@class,'landing-page-section--grid-cards')]//div[contains(@class,'card-body') and h3/a and p]")
    for card in cards:
        heading = card.xpath("./h3/a")[0]
        name, topic = contents(heading), text_at(card, "./p")
        if len(name.split()) > 4 or not topic:
            continue
        if "retired from" in topic:
            title = "Retired faculty"
        elif "teaching track" in topic:
            title = "Teaching track"
        else:
            title = "Academic Faculty"
        target = profile_link(base, heading.get("href"))
        rows.append(Entry(name, title, topic, target))
    return rows


def parse_sustech_graduate(document, base):
    rows = []
    for card in document.xpath("//div[contains(@class,'posFosterBottom')]/div[@class='tabRow'][span[@class='name']/a]"):
        link = card.xpath("./span[@class='name']/a")[0]
        summary = text_at(card, "./p")
        title = re.match(r"^(?:讲席|特聘|教学)?(?:助理|副)?教授", summary)
        topic = text_at(card, "./span[2]")
        explicit_interest = re.search(r"(?:研究方向|研究领域|主要科研方向|研究专长|研究兴趣)(?:为|是|在|包括|[：:])([^。]{3,230})", summary)
        if explicit_interest:
            topic = "；".join(filter(None, [topic, explicit_interest[1]]))
        if title:
            rows.append(Entry(contents(link), title[0], topic, profile_link(base, link.get("href"))))
    return rows


def parse_kit_geometry(document, base):
    rows = []
    for link in document.xpath("//table[contains(@class,'collapseTable')]//a[@itemprop='name']"):
        label = contents(link)
        title = re.match(r"^(?:Prof\. Dr\.|Dr\.)", label)
        name = display_name(re.sub(r",?\s+M\.Sc\.?$", "", label.removeprefix(title[0]).strip() if title else label))
        role = title[0] if title else ""
        rows.append(Entry(name, role, "Differential geometry research group", profile_link(base,link.get("href"))))
    return rows


def parse_heidelberg_algebra(document, base):
    rows = []
    for card in document.xpath("//main//a[h3 or .//h3][.//div[contains(@class,'DateLine_')]]"):
        heading = text_at(card, ".//h3")
        rank = re.match(r"^(?:Jun\.\s*)?Prof\.\s+(?:Dr\.\s+)?", heading)
        if rank is None:
            continue
        area = text_at(card, ".//div[contains(@class,'DateLine_')]")
        if re.search(r"arithmetische geometrie|arithmetic geometry", area, re.I):
            area += " / Arithmetic geometry"
        rows.append(Entry(heading[rank.end():], rank[0].strip(), area, homepage=profile_link(base, card.get("href"))))
    return rows


def parse_ufrj_department(document, base):
    rows = []
    for item in document.xpath("//div[@class='entry-content']/ul/li"):
        name, _, details = contents(item).partition(" – ")
        if not name:
            continue
        _, _, research = details.partition("Área de pesquisa:")
        target = next(iter(item.xpath("./a[1]/@href")), "")
        rows.append(Entry(name, "", research.strip(), "", profile_link(base, target) if target else ""))
    return rows


def parse_ufrj_graduate(document, base):
    rows = []
    for card in document.xpath("//div[contains(@class,'panel-group')]//div[div[@class='panel-heading'] and .//div[@class='panel-body']]"):
        name = text_at(card, "./div[@class='panel-heading']")
        research = []
        for label in card.xpath(".//strong[contains(.,'Área de pesquisa') or contains(.,'Research Area')]"):
            following = label.getnext()
            value = clean(label.tail or "")
            if not value and following is not None and following.tag == "a":
                value = contents(following)
            if value:
                research.append(value)
        homepage = next((url for label,url in urls(card,base) if label == "Homepage"), "")
        if name:
            rows.append(Entry(name, research=" / ".join(dict.fromkeys(research)), homepage=homepage))
    return rows


PARSERS = {
    "science_tokyo": parse_science_tokyo, "glasgow_staff": parse_glasgow_staff, "ucas_staff": parse_ucas_staff,
    "cuhk_staff": parse_cuhk_staff,
    "isi_kolkata": parse_isi_kolkata, "lse_staff": parse_lse_staff, "utm_staff": parse_utm_staff,
    "auckland_research": parse_auckland_research,
    "iit_delhi_faculty": parse_iit_delhi_faculty,
    "stanford": parse_stanford, "stonybrook": parse_stonybrook, "stonybrook_group": parse_stonybrook_group,
    "bonn": parse_bonn, "bicmr": parse_bicmr, "princeton": parse_princeton, "princeton_group": parse_princeton_group,
    "pku": parse_pending, "pku_pure":parse_pku_pure, "rutgers": parse_rutgers_directory,
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
    "vienna":parse_vienna, "ustc":parse_ustc, "sustech":parse_sustech, "uppsala":parse_uppsala,
    "pisa_geometry":parse_pisa_geometry, "kuleuven":parse_kuleuven, "cmls_geometry":parse_cmls_geometry,
    "zurich_group":parse_zurich_group,"sjtu_wucms":parse_sjtu_wucms,"hit":parse_hit,
    "lmo":parse_lmo,"zjnu":parse_zjnu,"sydney_profiles":parse_sydney_profiles,
    "tamu":parse_tamu,"wisconsin":parse_wisconsin,"psau_profiles":parse_psau_profiles,
    "aix":parse_aix,"padua_group":parse_padua_group,
    "imj_sorbonne":parse_imj_sorbonne,"imj_paris_cite":parse_imj_paris_cite,
    "china_faculty_portal":parse_china_faculty_portal, "ut_group":parse_ut_group,
    "toronto_mississauga":parse_toronto_mississauga,
    "kth_members":parse_kth_members, "kth_algebraic":parse_kth_algebraic,
    "michigan":parse_michigan, "uab":parse_uab, "uab_arithmetic":parse_uab_arithmetic,
    "waseda_japanese":parse_waseda_japanese, "usp_staff":parse_usp_staff,
    "usp_geometry":parse_usp_geometry, "durham_geometry":parse_durham_geometry,
    "sustech_graduate":parse_sustech_graduate,
    "kit_geometry":parse_kit_geometry, "heidelberg_algebra":parse_heidelberg_algebra,
    "ufrj_department":parse_ufrj_department, "ufrj_graduate":parse_ufrj_graduate,
}


def profile_fields(document, base):
    """Extract titles and visible link labels from an official or directory-linked page."""
    main = (document.xpath("//main") or document.xpath("//body") or [document])[0]
    research = []
    official_title = ""
    official_name = ""
    target = urlparse(base)
    if target.hostname in {"dur.ac.uk", "www.durham.ac.uk"} and re.fullmatch(r"/staff/[^/]+/?", target.path):
        heading = main.xpath(".//h2[@class='h h2'][following-sibling::p[1]["
                             + class_token("u-font-bold") + " and " + class_token("u-text-large") + "]]")
        if len(heading) == 1:
            official_name = untitled(contents(heading[0]))
            official_title = text_at(heading[0], "following-sibling::p[1]")
    qmul_profile = (target.hostname == "www.qmul.ac.uk"
                    and re.fullmatch(r"/maths/profiles/[^/]+\.html", target.path))
    centre_profile = (target.hostname == "www.seresearch.qmul.ac.uk"
                      and re.fullmatch(r"/(?:ccant|cgag)/people/[^/]+/?", target.path))
    if centre_profile:
        keywords = text_at(main, ".//div[@id='research']/p[" + class_token("keyicon") + "]")
        if keywords:
            research.append(keywords)
    if target.hostname == "www.math.ubc.ca" and re.fullmatch(r"/user/\d+", target.path):
        name = main.xpath(".//h2[" + class_token("profile-title") + "]")
        if len(name) == 1:
            official_name = contents(name[0])
            official_title = text_at(name[0], "following-sibling::h2[1][" + class_token("h5") + "]")
            if official_title == "Faculty":
                official_title = "Academic Faculty"
        for paragraph in main.xpath(".//p"):
            focus = re.search(
                r"\b(?:my|his|her|their) (?:current |general )?research "
                r"(?:interests|focus|lies|examines|investigates|studies|is in).*?(?:\.(?=\s|$)|$)",
                contents(paragraph), re.I,
            )
            if focus and 20 <= len(focus[0]) <= 360:
                research.append(focus[0])
    if target.hostname == "vitdirectory.vit.ac.in" and re.fullmatch(r"/page/faculty/\d+/?", target.path):
        official_name = untitled(text_at(main, "(.//h1)[1]"))
        designation = main.xpath(".//strong[normalize-space()='Designation :']")
        if len(designation) == 1:
            official_title = clean(designation[0].tail or "")
        specializations = main.xpath(
            ".//div[normalize-space()='Areas of Specialization']/following-sibling::ul[1]/li"
        )
        research.extend(contents(item) for item in specializations if 3 <= len(contents(item)) <= 140)
    if target.hostname == "math.nyu.edu" and re.fullmatch(r"/people/profiles/[^/]+\.html", target.path):
        headings = main.xpath(".//h1[normalize-space(.) != 'Faculty Profile']")
        titles = main.xpath(f".//div[{class_token('title')}]")
        if len(headings) == 1 and len(titles) == 1:
            official_name = contents(headings[0])
            official_title = contents(titles[0])
    if target.hostname == "math.qau.edu.pk" and re.fullmatch(r"/faculty/[^/]+/?", target.path):
        official_name = re.sub(r"^(?:Prof\.?\s+)?Dr\.?\s+", "", text_at(main, "(.//h1)[1]"), flags=re.I)
        titles = main.xpath(".//tr[td[1][normalize-space(.)='Designation:']]/td[2]")
        if len(titles) == 1:
            official_title = contents(titles[0])
    if target.hostname == "mat.uab.cat" and target.path == "/departament/uab/pop_ex_nou.php":
        heading = text_at(main, "(.//h2)[1]")
        match = re.match(r"((?:Full |Associate |Assistant |Emeritus )?Professor|Lecturer)\b", heading, re.I)
        if match:
            official_title = match[1]
            specialization = re.search(r"\(([^()]{6,90})\)\s*$", heading)
            if specialization:
                research.append(specialization[1])
    if target.hostname == "math.utexas.edu" and target.path.startswith("/directory/"):
        for heading in main.xpath(".//h2[normalize-space()='Research']"):
            paragraphs = heading.xpath("./following-sibling::*[1][self::p or self::div]")
            if paragraphs:
                value = contents(paragraphs[0])
                if 20 <= len(value) <= 650:
                    research.append(value)
    research_labels = {
        "expertise", "key expertise", "research topics", "field of interest", "research field",
        "research interests", "research area", "research areas", "research area(s)",
        "research interests and areas", "research specialization", "専門分野", "研究方向",
        "研究兴趣", "研究領域", "研究领域", "科研方向", "主要研究方向", "thèmes de recherche",
        "domaines de recherche", "axes de recherche", "intérêts de recherche", "forschungsinteressen",
        "forschungsschwerpunkte", "forskningsintressen", "líneas de investigación",
        "áreas de investigación", "intereses de investigación", "áreas de pesquisa",
        "área de pesquisa", "temas de pesquisa", "interessi di ricerca", "temi di ricerca",
        "научные интересы", "область научных интересов", "область исследований", "направления исследований",
        "연구분야", "전공분야", "研究分野", "研究テーマ",
    }
    headings = {"h1", "h2", "h3", "h4", "h5", "h6"}
    for label in main.xpath(".//h2|.//h3|.//h4|.//h5|.//dt|.//th|.//td[1]|.//div[not(*) and @class]|.//strong|.//b"):
        text = contents(label)
        title, _, inline = re.split(r"([:：])", text, maxsplit=1) if re.search(r"[:：]", text) else (text, "", "")
        title = title.strip().lower()
        if title not in research_labels:
            continue
        following = label.getnext()
        if following is None and label.tag in {"strong", "b"}:
            parent = label.getparent()
            if parent is not None and parent.tag in {"p", "div"} and contents(parent) == text:
                following = parent.getnext()
        value = clean(inline or label.tail or "")
        if not value and following is not None and following.tag not in headings:
            if not following.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6"):
                value = contents(following)
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
    for paragraph in main.xpath(".//p"):
        text = contents(paragraph)
        if len(text) <= 450 and re.match(r"^(?:my research (?:interests|focus|is in|deals)|research interests\s*[:：]|我(?:的)?主要研究方向|研究方向\s*[:：])", text, re.I):
            research.append(text)
    if qmul_profile:
        research = [value for value in research if not re.match(
            r"^(?:see .+?['’]?s? research profile pages?\b|my research interests are:?$)",
            value, re.I,
        )]
        overview = main.xpath(".//div[@id='second']//p")
        for paragraph in overview:
            value = contents(paragraph)
            if 20 <= len(value) <= 600 and re.search(
                r"research (?:is in|focus(?:es|ed)?|interests? (?:are|lie)|involves|covers|spans)|"
                r"\b(?:I (?:work|study|specialise|specialize) in|I am interested in)\b",
                value, re.I,
            ):
                research.append(value)
    homepage = cv = bibliography = ""
    orcids = set()
    for label, url in urls(main, base):
        low = label.lower()
        host = urlparse(url).hostname or ""
        if not homepage and low in {"home page", "my home page", "homepage", "personal website", "my personal website", "personal homepage", "professional website", "faculty website", "visit website", "website", "personal web page", "web site", "research website", "個人ホームページ", "个人主页", "個人網頁", "page personnelle", "site personnel", "página personal", "página pessoal", "persönliche webseite", "personal webpage"}:
            if host not in {"linkedin.com", "www.linkedin.com", "zoom.us"} and not host.endswith(".zoom.us"):
                homepage = url
        if (not cv and not re.search(r"/faq(?:\.php|/|$)", urlparse(url).path, re.I)
                and re.search(r"^(?:(?:view|download|my|short|brief|latest|full|pdf) )*(?:(?:curriculum|cv|vita|lebenslauf|résumé|resume)\b|(?:个人|学术)?简历|履歴書|略歴)", low)):
            cv = url
        if (not bibliography and not (centre_profile and urlparse(url).path in {"/ccant/publications/", "/cgag/publications/"})
                and low in {"publications","papers","research papers","publications and preprints","research publications","preprints and publications","发表论文","学术成果","研究成果","publikationen","publicações","publicaciones","論文"}):
            bibliography = url
        if host in {"orcid.org", "www.orcid.org"}:
            identifier = urlparse(url).path.strip("/")
            if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", identifier):
                orcids.add(identifier)
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
    fields = {"research":" / ".join(dict.fromkeys(research)), "homepage":homepage, "cv":cv, "publications":bibliography}
    if official_title:
        fields["official_title"] = official_title
        if official_name:
            fields["official_name"] = official_name
    if len(orcids) == 1:
        fields["orcid"] = next(iter(orcids))
    person_path = urlparse(base).path.rstrip("/")
    if re.search(r"/persons/[^/]+$", person_path):
        publication_path = person_path + "/publications"
        counts = []
        for label, url in urls(main, base):
            parsed = urlparse(url)
            if parsed.hostname != urlparse(base).hostname or parsed.path.rstrip("/") != publication_path:
                continue
            total = re.fullmatch(r"View all ([\d,]+) research outputs?", label, re.I)
            if total:
                counts.append({"value":int(total[1].replace(",", "")),
                               "scope":"机构 Pure 档案的 Research output 总数", "url":url})
                fields["publications"] = fields["publications"] or url
        for link in main.xpath(".//a[contains(@class,'increment-counter')][@href and @aria-label]"):
            count = re.fullmatch(r"\s*([\d,]+)\s+Article\s*", link.get("aria-label"), re.I)
            url = profile_link(base, link.get("href"))
            parsed = urlparse(url)
            if (count and parsed.hostname == urlparse(base).hostname and parsed.path.rstrip("/") == publication_path
                    and "researchoutputtypes%2Fcontributiontojournal%2Farticle" in parsed.query):
                counts.append({"value":int(count[1].replace(",", "")),
                               "scope":"机构 Pure 档案的 Article 分类", "url":url})
        if counts:
            fields["publication_counts"] = counts
    return fields
