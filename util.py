import io
import re
import types
import functools
import itertools
import collections

from nameparser import HumanName
import attr
from lxml.etree import HTMLParser, parse
from pycldf.sources import Source as BaseSource
from clldutils.coordinates import Coordinates
from clldutils.misc import slug

INVALID_LANGUAGE_IDS = {'2679'}
SCORED_PARAMETERS = {
    'Score': [
        'Safe',
        'Vulnerable',
        'Threatened',
        'Endangered',
        'Severely Endangered',
        'Critically Endangered',
    ],
    ('speakers', 'Speaker Number'): [
        '100000',
        '10000-99999',
        '1000-9999',
        '100-999',
        '10-99',
        '1-9',
    ],
    ('vitality', 'Speaker Number Trends'): [
        'Almost all community members or members of the ethnic group speak the language, and speaker numbers are stable or increasing.',
        'Most members of the community or ethnic group speak the language. Speaker numbers may be decreasing, but very slowly.',
        'A majority of community members speak the language. Speaker numbers are gradually decreasing.',
        'Only about half of community members speak the language. Speaker numbers are decreasing steadily, but not at an accelerated pace.',
        'Less than half of the community speaks the language, and speaker numbers are decreasing at an accelerated pace.',
        'A small percentage of the community speaks the language, and speaker numbers are decreasing very rapidly.',
    ],
    ('vitality', 'Transmission'): [
        'All members of the community, including children, speak the language.',
        'Most adults and some children are speakers.',
        'Most adults in the community are speakers, but children generally are not.',
        'Some adults in the community are speakers, but the language is not spoken by children.',
        'Many of the grandparent generation speak the language, but younger people generally do not.',
        'There are only a few elderly speakers.',
    ],
    ('vitality', 'Domains Of Use'): [
        'Used in most domains, including official ones such as government, mass media, education, etc.',
        'Used in most domains, including official ones such as government, mass media, education, etc.',
        'Used in some non-official domains along with other languages, and remains the primary language used in the home for many community members.',
        'Used mainly just in the home and/or with family, but remains the primary language of these domains for many community members.',
        'Used mainly just in the home and/or with family, and may not be the primary language even in these domains for many community members.',
        'Used only in a few very specific domains, such as in ceremonies, songs, prayer, proverbs, or certain limited domestic activities.',
    ]
}
COMPOSITE_PARAMETERS = [
    (
        'context',
        "Composite information pertaining to the context a language is spoken in.",
        {
            "type": "object",
            "properties": {
                "Domains Other Langs": {"type": "array", "items": {"type": "string"}},
                "Government Support": {"type": "string"},
                "Institutional Support": {"type": "string"},
                "Number Speaker Other Languages": {"type": "string"},
                "Other Languages Used": {"type": "string"},
                "Speaker Attitude": {"type": "string"}}
        },
    ),
    (
        'location',
        "Composite information pertaining to the location(s) a language is spoken at.",
        {
            "type": "object",
            "properties": {
                "Coordinates": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "prefixItems": [
                            {
                                "title": "latitude",
                                "type": "number",
                                "minimum": -90,
                                "maximum": 90},
                            {
                                "title": "longitude",
                                "type": "number",
                                "minimum": -180,
                                "maximum": 180},
                        ]
                    }
                },
                "Description": {"type": "string"},
                "Places": {"type": "array", "items": {"type": "string"}},
            }
        },
    ),
    (
        'speakers',
        "Composite information pertaining to the speakers of a language.",
        {
            "type": "object",
            "properties": {
                "Speaker Number Text": {"type": "string"}, # 11174
                "Speaker Number": {"type": "string"}, # 10800
                "Elders": {"type": "string"}, # 121
                "Ethnic Population": {"type": "string"}, # 2180
                "Older Adults": {"type": "string"}, # 89
                "Second Language Speakers": {"type": "string"}, # 167
                "Semi Speakers": {"type": "string"}, # 292
                "Young Adults": {"type": "string"}, # 118
                "Date Of Info": {"type": "string"}, # 3927
            }
        },
    ),
    (
        'vitality',
        "Composite information pertaining to the vitality of a language.",
        {
            "type": "object",
            "properties": {
                "Endangerment": {
                    "type": "object",
                    "properties": {
                        "Level": {"enum": [
                            "safe",
                            "at risk",
                            "vulnerable",
                            "threatened",
                            "endangered",
                            "severely endangered",
                            "critically endangered",
                            "awakening",
                            "dormant",
                        ]},
                        "Certainty": {"type": "number", "minimum": 0, "maximum": 1}
                    }
                }, #  11386
                "Domains Of Use": {"type": "string"}, #  879
                "Speaker Number Trends": {"type": "string"}, #  1465
                "Transmission": {"type": "string"}, #  1794
            }
        },
    ),
]


def norm_text(s):
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s or None


def norm_coords(s):
    s = s.strip()
    res = []
    if s in {
        'Canada',
        'Canada;',
        'USA',
        'Papua New Guinea; Indonesia',
        'Papua New Guinea',
    }:
        return res
    if s.count(',') == 0 and s.count(';') == 1:
        s = s.replace(';', ',')

    for point in s.split(';'):
        if point.strip():
            lat, lon = point.split(',')
            lat = lat.strip().replace('\u200e', '').replace(' ', '')
            lon = lon.strip().replace('\u200e', '').replace(' ', '').replace('23.40.37', '23.406')
            if '°' in point:
                c = Coordinates(
                    lat.replace("'", "\u2032").replace('"', "\u2033"),
                    lon.replace("'", "\u2032").replace('"', "\u2033"),
                    format='degminsec')
                lat, lon = c.latitude, c.longitude
            else:
                lat = float(lat)
                lon = float(lon)
            if lat < -90 or (lat > 90):
                lat, lon = lon, lat
            assert -90 < lat < 90, s
            assert -180 < lon < 180, s
            res.append((lat, lon))
    return res


def get_doc(p):
    return parse(io.StringIO(p.read_text(encoding='utf8')), HTMLParser())


def split(s, sep=';'):
    return [
        ss.strip()
        for ss in ((s or '').split(sep) if isinstance(sep, str) else sep.split(s or ''))
        if ss.strip()]


def norm_authority(s):
    s = split(s)
    return [{
        'ISO': 'ISO 639-3',
        'ISO639-3': 'ISO 639-3',
        'ISO 939-9': 'ISO 639-3',
        'ISO 69-3': 'ISO 639-3',
        'Glottocode': 'Glottolog',
        'Glottolog 4.3': 'Glottolog',
        'Glotolog 4.3': 'Glottolog',
        'Glottologcode': 'Glottolog',
        'LINGUIST List (?)': 'LINGUIST List',
    }.get(ss, ss) for ss in s]


def validate_authority(i, f, v):
    if not all(vv in {'ISO 639-3', 'LINGUIST List', 'Glottolog'} for vv in v):
        raise ValueError(v)


@attr.s
class Metadata:
    classification = attr.ib(default=None)
    code_authority = attr.ib(
        default=None,
        converter=norm_authority,
        validator=validate_authority)
    also_known_as = attr.ib(
        default='',
        converter=lambda s: [ss.strip().replace('"', '') for ss in s.split(',') if ss.strip()])
    language_code = attr.ib(default=None, converter=functools.partial(split, sep=re.compile('[,;]')))
    orthography = attr.ib(default=None)
    additional_comments = attr.ib(default=None)
    variants_and_dialects = attr.ib(default=None)

    @classmethod
    def from_html(cls, doc):
        return cls(**{
            k.lower().replace(' ', '_').replace('&', 'and'): v.replace('xkwkemb1250', 'xkw; kemb1250')
            for k, v in iter_language_metadata(doc)})


def norm_classification(s):
    s = (s or '').replace('Classification:', '').strip()
    m = {
        'Austroasiatic': 'Austro-Asiatic',
        'North Halmahera': 'North Halmaheran',
        'Sino-Tibetan > Trans-Himalayan > Gyalrong': 'Sino-Tibetan',
        'Trans–New Guinea': 'Trans-New Guinea',
        'Unclassified': None,
    }
    return m.get(s, s) or None


@attr.s
class Language:
    id = attr.ib(validator=attr.validators.matches_re('[0-9]+'))
    name = attr.ib(validator=attr.validators.matches_re('.+'))
    metadata = attr.ib()
    classification = attr.ib(default=None, converter=norm_classification)
    endangerment = attr.ib(
        default=None,
        validator=attr.validators.in_([
            None,
            'at risk',
            'vulnerable',
            'threatened',
            'endangered',
            'severely endangered',
            'critically endangered',
            'awakening',
            'dormant',
        ]),
        converter=lambda s: s.lower() if s else None)
    preferred_source = attr.ib(default=None)

    context = attr.ib(default=attr.Factory(list))
    speakers = attr.ib(default=attr.Factory(list))
    location = attr.ib(default=attr.Factory(list))
    vitality = attr.ib(default=attr.Factory(list))

    # Endangerment Level"": ""Vulnerable (100 percent certain, based on the evidence available)

    @classmethod
    def from_html(cls, id, doc):
        pref_source = doc.xpath('.//a[@href="#sources_popup_wrapper" and @data-source-id]')
        pref_source = pref_source[0].attrib['data-source-id'] if pref_source else None
        kw = dict(
            id=id,
            name=name(doc),
            metadata=Metadata.from_html(doc),
            preferred_source=pref_source,
        )
        cae = classification_and_endangerment(doc)
        if cae:
            kw.update(classification=cae[0], endangerment=cae[1])
        return cls(**kw)


def name(doc):
    try:
        return doc.find('.//h2').text
    except AttributeError:
        return


def classification_and_endangerment(doc):
    clf = None
    for i, p in enumerate(doc.findall('.//div[@class="inner"]/div/p')):
        if i == 0:
            clf = p.text
        elif i == 1:
            return clf, p.text


def iter_language_metadata(doc):
    for sec in doc.findall('.//section'):
        if sec.xpath('.//h4[text()="Language metadata"]') is not None:
            for tr in sec.findall('.//tr'):
                tds = tr.findall('td')
                if len(tds) == 3:
                    label = tds[0].find('label').text
                    if label not in {'DOWNLOAD', 'MORE RESOURCES'}:
                        # if label == 'VARIANTS & DIALECTS' -> split text by \n ...
                        yield tds[0].find('label').text, ''.join(tds[2].itertext()).strip()


def iter_sources(doc):
    header = []
    for th in doc.find('.//table[@id="columns_header"]').findall('.//th'):
        header.append((th.attrib['class'].replace('source_type ', ''), th.text))

    for tr in doc.findall(".//thead/tr[@class='source-row']"):
        data = [''.join(td.itertext()).strip() for td in tr.findall('td')]
        yield tr.attrib['data-source-id'], collections.OrderedDict(zip(header, data))


def iter_langs(dir):
    sources = collections.defaultdict(dict)
    for p in dir.iterdir():
        m = re.fullmatch('lang_([0-9]+)', p.stem)
        if m:
            lid = m.groups()[0]
            doc = get_doc(p)
            if lid in INVALID_LANGUAGE_IDS:  # A known problem.
                assert name(doc) is None
                continue
            lang = Language.from_html(lid, doc)
            for sid, data in iter_sources(doc):
                for k, items in itertools.groupby(
                    sorted(data.items(), key=lambda i: i[0][0]),
                    lambda i: i[0][0],
                ):
                    if k == 'source':
                        s = Bib.source_from_dict(sid, {key[1]: v for key, v in items})
                        if s:
                            if sid not in sources:
                                yield s
                            #else:
                            #    assert s == sources[sid], '{}\n===\n{}'.format(s.bibtex(), sources[sid].bibtex())
                            sources[sid] = s
                    else:
                        dd = {kk[1]: vv for kk, vv in items if vv}
                        if dd:
                            getattr(lang, k).append((sid or None, dd))
            yield lang


@attr.s
class Bib:
    citation = attr.ib(default=None)
    local_ids = attr.ib(default=attr.Factory(set))
    language_ids = attr.ib(default=attr.Factory(set))

    title = attr.ib(default='', converter=lambda s: s.strip())
    pages = attr.ib(default='', converter=lambda s: s.replace(')', '').replace('pp.', '').strip())
    author = attr.ib(default='', converter=lambda s: s.strip())
    year = attr.ib(default='', converter=lambda s: s.strip())
    booktitle = attr.ib(default='', converter=lambda s: s.strip())
    publisher = attr.ib(default='', converter=lambda s: s.strip())
    address = attr.ib(default='', converter=lambda s: s.strip())
    journal = attr.ib(default='', converter=lambda s: s.strip())
    volume = attr.ib(default='', converter=lambda s: s.replace('Vol.', '').strip())
    number = attr.ib(default='', converter=lambda s: s.strip())
    editor = attr.ib(default='', converter=lambda s: s.strip())
    edition = attr.ib(default='', converter=lambda s: s.strip())
    series = attr.ib(default='', converter=lambda s: s.strip())
    url = attr.ib(default='', converter=lambda s: s.strip())
    school = attr.ib(default='', converter=lambda s: s.strip())
    copied_from = attr.ib(default='', converter=lambda s: s.strip())
    isbn = attr.ib(default='', converter=lambda s: s.strip())
    institution = attr.ib(default='', converter=lambda s: s.strip())
    howpublished = attr.ib(default='', converter=lambda s: s.strip())
    note = attr.ib(default='', converter=lambda s: s.strip())
    num = attr.ib(default='', converter=lambda s: s.strip())
    month = attr.ib(default='', converter=lambda s: s.strip())
    chapter = attr.ib(default='', converter=lambda s: s.strip())
    translator = attr.ib(default='', converter=lambda s: s.strip())

    def __attrs_post_init__(self):
        for f, repls in {
            'title': [
                ('Indıgenas', 'Indígenas'),
                ('morfologija', 'Morfologia'),
                ('Dicionário', 'dictionário'),
                ('and its Cultural COntext', 'in its Cultural Context'),
                ('A Dumugat (Casiguran)', 'A Dumagat (Casiguran)'),
                ('Resıgaro', 'Resígaro'),
                ('Lehrbuch des saamischen (lappischen) Sprache', 'Lehrbuch der saamischen (lappischen) Sprache'),
                ('lıngua', 'língua'),
            ],
            'author': [
                ('Anonymous,', ''),
                ('N/A', ''),
                ('(', ''),
                (')', ''),
            ],
        }.items():
            for from_, to_ in repls:
                setattr(self, f, getattr(self, f, '').replace(from_, to_).strip())

        if self.address and not self.publisher:
            self.publisher, self.address = self.address, ''
        if self.author.startswith('http'):
            self.url, self.author = self.author, ''
        if ': ' in self.publisher and not self.address:
            self.address, _, self.publisher = self.publisher.partition(': ')

        for f in {'address', 'series', 'journal'}:  # Extract booktitle.
            if getattr(self, f).startswith('In ') and not self.booktitle:
                self.booktitle = ' '.join(self.series.split()[1:])
                setattr(self, f, '')

        for f in {'booktitle', 'author', 'publisher', 'journal', 'isbn'}:  # Extract URL.
            val = getattr(self, f)
            m = re.search(r'(?P<url>http(s)?://[^\s]+)$', val)
            if m:
                self.url = m.group('url')
                setattr(self, f, val[:m.start()].strip())

        if self.url and self.url.endswith('Ethnologue: Languages of the World, 17th Edition (2013)'):
            assert self.title == 'Ethnologue: Languages of the World, 17th Edition (2013)'
            self.title = 'Ethnologue: Languages of the World, 17th Edition'
            self.year = '2013'
            self.url = self.url.split('\n')[0]
        if '\n' in self.url:
            for candidate in self.url.split('\n'):
                if 'doi' in candidate:
                    self.url = candidate
                    break
                if 'handle' in candidate:
                    self.url = candidate
                    break
            else:
                self.url = candidate
        for f in self.regular_fields():
            if '\n' in getattr(self, f, ''):
                setattr(self, f, getattr(self, f).replace('\n', ' '))

    @classmethod
    def regular_fields(cls):
        return [f.name for f in attr.fields(cls) if f.name not in {'citation', 'local_ids', 'language_ids'}]

    @property
    def sortkey(self):
        return (
            HumanName(self.author).last,
            slug(self.title),
            self.year,
            self.url,
            'a' if self.local_ids else 'z'
        )

    @property
    def hashkey(self):
        return (
            HumanName(self.author).last or self.url,
            slug(self.title)[:12],
            self.year[:4],
        )

    def __iadd__(self, other):
        for att in {'local_ids', 'language_ids'}:
            setattr(self, att, getattr(self, att) | getattr(other, att))
        for f in self.regular_fields():
            if getattr(other, f) and not getattr(self, f):
                setattr(self, f, getattr(other, f))
        return self

    def as_source(self, id):
        if self.journal:
            genre = 'article'
        elif self.booktitle:
            genre = 'incollection'
        elif self.publisher or self.series:
            genre = 'book'
        elif self.school:
            txt = (self.citation or '').lower()
            if 'phd' in txt:
                genre = 'phdthesis'
            elif 'master' in txt:
                genre = 'mastersthesis'
            else:
                genre = 'misc'
        else:
            genre = 'misc'
        return BaseSource(
            genre,
            id,
            local_ids=' '.join(self.local_ids),
            **{f: getattr(self, f) for f in self.regular_fields() if getattr(self, f)})

    @staticmethod
    def iter_merged(recs):
        for key, items in itertools.groupby(sorted(recs, key=lambda r: r.sortkey), lambda r: r.hashkey):
            if not all(key):  # Insufficient data to identify items.
                yield from items
            else:
                pick = None
                for item in items:
                    if not pick:
                        pick = item
                    else:
                        if slug(item.title).startswith(slug(pick.title)):
                            # pick's title is a prefix of item's title
                            pick.title = item.title
                            pick += item
                        else:
                            yield pick
                            pick = item
                yield pick

    @classmethod
    def source_from_dict(cls, sid, d):
        def fix(s):
            for x, y in {
                "Lyle Campbell (Principal Investigator)": "Lyle Campbell",
                "Julien Meyer. (2014. ": "Julien Meyer. (2014). ",
                "o Maranungku (Northern Australia": "o Maranungku (Northern Australia)",
            }.items():
                s = s.replace(x, y)
            return s

        d = {k.lower().replace(' ', '_'): fix(v) for k, v in d.items() if v}
        if not sid:
            assert not d
            return
        if 'free_text_citation' in d:
            d['citation'] = d.pop('free_text_citation')

        if set(d.keys()) == {'citation'}:
            d['howpublished'] = d.pop('citation')
        d['local_ids'] = {sid}
        return cls(**d)

    @classmethod
    def from_other_sources(cls, s, lids):
        def is_publisher(s):
            return any(kw in s.lower() for kw in {'lincom', 'gruyter', 'gryuter', 'press', 'köppe', '&', 'publish', 'verlag', 'brill'})

        rec = types.SimpleNamespace()

        if not s.strip():
            return
        title_and_pages, _, rem = s.partition(' . ')
        if not rem:
            title_and_pages, rem = None, s

        if title_and_pages:
            rec.title, _, rec.pages = title_and_pages.partition(' ( ')

        assert rem
        author_and_year, _, rem = rem.partition(' ·')

        yearp = re.compile(r'\(([0-9\-/, \[\]sx?]+|forthcoming|no date|n\.\s*d\.?)\)$')
        m = yearp.search(author_and_year.strip())
        if m:
            rec.author = author_and_year[:m.start()].strip()
            rec.year = m.groups()[0]
        else:
            rec.author = author_and_year.split('(')[0].strip()
        rem = rem.strip()
        if rem:
            rem = [p.strip() for p in rem.split(' ·') if p.strip()]
            incollp = re.compile('In\s+(?P<booktitle>.+?)\s+edited by\s+(?P<editor>.+)')
            m = incollp.match(rem[0])
            if m:
                rec.booktitle, rec.editor = m.group('booktitle'), m.group('editor')
            else:
                jvnp = re.compile('(?P<journal>.+?)\.\s*(?P<volume>[0-9VXI]+)\s*(\((?P<number>[0-9]+)\))?')
                m = jvnp.match(rem[0])
                if m:
                    rec.journal = m.group('journal')
                    rec.volume = m.group('volume')
                    if m.group('number'):
                        rec.number = m.group('number')
                else:
                    for i, r in enumerate(rem):
                        if r.startswith('edited by'):
                            rec.editor = r.replace('edited by', '').strip()
                            del rem[i]
                            break
                    for i, r in enumerate(rem):
                        if r.strip().startswith('http://') or r.strip().startswith('https://'):
                            rec.url = r
                            del rem[i]
                            break

                    if len(rem) == 1:
                        if ':' in rem[0] and '://' not in rem[0]:
                            rec.address, _, rec.publisher = rem[0].partition(':')
                        elif is_publisher(rem[0]):
                            rec.publisher = rem[0]
                        elif not rem[0].lower().startswith('in '):
                            rec.publisher = rem[0]
                        else:
                            rec.booktitle = ' '.join(rem[0].split()[1:]).strip()
                    elif len(rem) == 3 and rem[1].startswith('Vol.'):
                        rec.series, rec.volume, rec.publisher = rem
                    elif len(rem) == 2 and ':' in rem[1] and '://' not in rem[1]:
                        rec.series, publisher = rem
                        rec.address, _, rec.publisher = publisher.partition(':')
                    elif len(rem) == 2 and is_publisher(rem[1]):
                        rec.series, rec.publisher = rem
                    elif len(rem) == 2 and rem[1].startswith('Vol.'):
                        rec.series, rec.volume = rem
                    elif len(rem) == 2:
                        rec.series, rec.publisher = rem
                    else:
                        assert not rem
                    # series: #[0-9]+ -> volume
        return cls(citation=s, language_ids=lids, **{k: v for k, v in rec.__dict__.items() if v and v.strip()})


def bibliography(dir):
    res = collections.defaultdict(list)
    for p in dir.glob('lang_*_bibliography'):
        lid = p.stem.split('_')[1]
        doc = parse(io.StringIO(p.read_text(encoding='utf8')), HTMLParser())
        for para in doc.findall('.//ul[@id="other_sources"]/li'):
            res[re.sub(r'\s+', ' ', ''.join(para.itertext()).strip())].append(lid)

    for line, lids in res.items():
        yield Bib.from_other_sources(line, {lid for lid in lids if lid not in INVALID_LANGUAGE_IDS})
