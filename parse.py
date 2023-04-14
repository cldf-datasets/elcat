# h2 -> name

# div.inner div p "critically endangered"

# section [*/h4 = Language metadata] table tbody
   # tr td label -> text
   #    td p -> text
   # or: td ul li p

# table#columns_header
# <th class="source_type source">Isbn</th>

# <tr class="source-row" data-source-id="96340">
  # td matching column  headers above!

import io
import re
import functools
import itertools
import collections

import attr
from lxml.etree import HTMLParser, parse
from pycldf.sources import Source as BaseSource

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
        return cls(**{k.lower().replace(' ', '_').replace('&', 'and'): v for k, v in iter_language_metadata(doc)})


@attr.s
class Language:
    id = attr.ib(validator=attr.validators.matches_re('[0-9]+'))
    name = attr.ib(validator=attr.validators.matches_re('.+'))
    metadata = attr.ib()
    classification = attr.ib(default=None, converter=lambda s: s.replace('Classification:', '').strip() or None if s else None)
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

    context = attr.ib(default=attr.Factory(list))
    speakers = attr.ib(default=attr.Factory(list))
    location = attr.ib(default=attr.Factory(list))
    vitality = attr.ib(default=attr.Factory(list))

    # Endangerment Level"": ""Vulnerable (100 percent certain, based on the evidence available)

    @classmethod
    def from_html(cls, id, doc):
        kw = dict(id=id, name=name(doc), metadata=Metadata.from_html(doc))
        cae = classification_and_endangerment(doc)
        if cae:
            kw.update(classification=cae[0], endangerment=cae[1])
        return cls(**kw)


class Source(BaseSource):
    @classmethod
    def from_dict(cls, sid, d):
        d = {k.lower().replace(' ', '_'): v for k, v in d.items() if v}
        if 'journal' in d:
            genre = 'article'
        elif 'booktitle' in d:
            genre = 'incollection'
        elif 'publisher' in d:
            genre = 'book'
        elif 'school' in d:
            if 'phd' in d.get('free_text_citation'.lower(), ''):
                genre = 'phdthesis'
            elif 'master' in d.get('free_text_citation'.lower(), ''):
                genre = 'mastersthesis'
            else:
                genre = 'misc'
        else:
            genre = 'misc'
        if not sid:
            assert not d
            return
        return BaseSource(genre, sid, **d)


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
            doc = parse(io.StringIO(p.read_text(encoding='utf8')), HTMLParser())
            if lid == '2679':  # A known problem.
                assert name(doc) is None
                continue
            lang = Language.from_html(lid, doc)
            for sid, data in iter_sources(doc):
                for k, items in itertools.groupby(
                    sorted(data.items(), key=lambda i: i[0][0]),
                    lambda i: i[0][0],
                ):
                    if k == 'source':
                        s = Source.from_dict(sid, {key[1]: v for key, v in items})
                        if s:
                            if sid not in sources:
                                yield s
                            else:
                                assert s == sources[sid], '{}\n===\n{}'.format(s.bibtex(), sources[sid].bibtex())
                            sources[sid] = s
                    else:
                        dd = {kk[1]: vv for kk, vv in items if vv}
                        if dd:
                            getattr(lang, k).append((sid or None, dd))
            yield lang
