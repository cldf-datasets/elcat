import re
import json
import pathlib
import subprocess
import collections

from cldfbench import Dataset as BaseDataset
from cldfbench import CLDFSpec
from pycldf.sources import Source
from clldutils.misc import nfilter
from clldutils.coordinates import Coordinates

from parse import iter_langs, SCORED_PARAMETERS, split, iter_other_sources

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
                "Number Speaker Other Languages": {"type": "string"},  # remove double quotes
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
                "Description": {"type": "string"},  # remove double quotes
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


class Dataset(BaseDataset):
    dir = pathlib.Path(__file__).parent
    id = "elcat"

    def cldf_specs(self):
        return CLDFSpec(module='StructureDataset', dir=self.cldf_dir)

    def cmd_download(self, args):
        """
        Download files to the raw/ directory. You can use helpers methods of `self.raw_dir`, e.g.

        >>> self.raw_dir.download(url, fname)
        """
        i = 0
        srcs = collections.defaultdict(list)
        for lid, t in iter_other_sources(self.raw_dir / 'html'):
            i += 1
            srcs[t].append(lid)
        for t, lids in sorted(srcs.items(), key=lambda i: i[0]):
            print(t)
            #break

    def cmd_makecldf(self, args):
        args.writer.cldf.add_component(
            'LanguageTable',
            {
                'name': 'classification',
                'dc:description': 'Top-level genealogical unit the language belongs to.',
            },
            {
                'name': 'endangerment',
                'dc:description': "ElCat's aggregated endangerment assessment.",
                'datatype': {
                    'base': 'string',
                    'format': 'at risk|awakening|critically endangered|dormant|endangered|endangerment|severely endangered|threatened|vulnerable'},
            },
            {
                'name': 'code_authorities',
                'dc:description': 'Other language catalogs which have assigned codes to the language.',
                'separator': '; ',
                'datatype': {'base': 'string', 'format': 'ISO 639-3|Glottolog|LINGUIST List'},
            },
            {
                'name': 'codes',
                'dc:description': 'Codes assigned to the language by other language catalogs.',
                'separator': '; ',
            },
            {
                'name': 'alt_names',
                'dc:description': 'Alternative names used for the language.',
                'separator': '; '},
        )
        args.writer.cldf.add_component('ParameterTable')
        args.writer.cldf.add_component('CodeTable')

        args.writer.objects['ParameterTable'].append(dict(
            ID='LEI',
            Name='Language Endangerment Index',
            Description='The level of endangerment presented for each language is not meant to be '
                        'the final word on the matter. The scores for individual languages will '
                        'change as more information becomes available. These scores are provided '
                        'for practical purposes, to give a quick but rough visual indication of a '
                        'language’s endangerment status. The level of certainty accompanying each '
                        'endangerment score shows the degree of confidence in that score; a label '
                        'of “uncertain” may indicate that the level is not yet known, or that the '
                        'score has been computed but further evaluation is needed. Detailed '
                        'information about how a language’s level of endangerment is calculated is '
                        'given at https://endangeredlanguages.com/about_catalogue/',
        ))

        for pid, desc, schema in COMPOSITE_PARAMETERS:
            args.writer.objects['ParameterTable'].append(dict(
                ID=pid,
                Name=pid,
                Description=desc,
                ColumnSpec=dict(datatype=dict(base='json', format=json.dumps(schema))),
            ))

        for pname, levels in SCORED_PARAMETERS.items():
            if isinstance(pname, tuple):
                pname = pname[1]
                pid = pname.lower().replace(' ', '_')
                args.writer.objects['ParameterTable'].append(dict(ID=pid, Name=pname))

                for score, level in enumerate(levels):
                    args.writer.objects['CodeTable'].append(dict(
                        ID='{}-{}'.format(pid, score),
                        Parameter_ID=pid,
                        Name=SCORED_PARAMETERS['Score'][score],
                        Description=level,
                    ))

        coords = {}
        iso2gc = {}
        for l in args.glottolog.api.languoids():
            if l.iso:
                iso2gc[l.iso] = l.id
            if l.latitude is not None:
                coords[l.id] = (l.latitude, l.longitude)
        # Read hand-curated, explicit mappings between ElCat and Glottolog (dialects):
        id2gc = {
            r['ID']: r['Glottocode'] for r in self.etc_dir.read_csv('languages.csv', dicts=True)}

        for obj in iter_langs(self.raw_dir / 'html'):
            if isinstance(obj, Source):
                args.writer.cldf.sources.add(obj)
                continue
            lang = obj
            iso_codes, glottocodes = [], []
            for code in lang.metadata.language_code:
                code = code.replace('\ufeff', '')
                if len(code) == 3 and (
                        ('ISO 639-3' in lang.metadata.code_authority) or
                        (not lang.metadata.code_authority)):
                    iso_codes.append(code)
                if len(code) == 8 and ('Glottolog' in lang.metadata.code_authority):
                    glottocodes.append(code)

            if iso_codes and not glottocodes:
                glottocodes = [iso2gc[iso] for iso in iso_codes if iso in iso2gc]

            if lang.id in id2gc:
                if glottocodes:
                    if [id2gc[lang.id]] != glottocodes:
                        assert lang.id == '2896'
                        glottocodes = [id2gc[lang.id]]
                else:
                    glottocodes = [id2gc[lang.id]]

            args.writer.objects['LanguageTable'].append(dict(
                ID=lang.id,
                Name=lang.name.strip(),
                Glottocode=glottocodes[0] if len(glottocodes) == 1 else None,
                ISO639P3code=iso_codes[0] if len(iso_codes) == 1 else None,
                classification=lang.classification,
                endangerment=lang.endangerment,
                code_authorities=lang.metadata.code_authority,
                codes=lang.metadata.language_code,
                alt_names=nfilter(lang.metadata.also_known_as),
            ))

            for param, _, _ in COMPOSITE_PARAMETERS:
                for i, (sid, d) in enumerate(getattr(lang, param), start=1):
                    comment = d.pop('Public Comment', None)
                    if 'Endangerment Level' in d:
                        args.writer.objects['ValueTable'].append(dict(
                            ID='{}-LEI-{}'.format(lang.id, i),
                            Language_ID=lang.id,
                            Parameter_ID='LEI',
                            Value=d['Endangerment Level'],
                            Source=[sid] if sid else [],
                            Comment=norm_text(comment.strip()) if comment else None,
                        ))
                        level, _, certainty = d.pop('Endangerment Level').partition('(')
                        d['Endangerment'] = dict(Level=level.strip().lower())
                        m = re.match('([0-9]+)', certainty)
                        if m:
                            d['Endangerment']['Certainty'] = float(m.groups()[0]) / 100
                    if "Places" in d:
                        d["Places"] = split(d["Places"])
                    for key in [
                        'Description',
                        'Speaker Number Text',
                        'Speaker Attitude',
                        'Second Language Speakers',
                        'Number Speaker Other Languages'
                    ]:
                        if key in d:
                            d[key] = norm_text(d[key])
                    if "Domains Other Langs" in d:
                        d["Domains Other Langs"] = [norm_text(x) for x in split(d["Domains Other Langs"])]
                    if 'Coordinates' in d:
                        d['Coordinates'] = norm_coords(d['Coordinates'])
                        if not d['Coordinates']:
                            del d['Coordinates']
                        else:
                            coords[lang.id] = d['Coordinates'][0]

                    for k, v in d.items():
                        levels = SCORED_PARAMETERS.get((param, k))
                        if levels:
                            if k == 'Speaker Number':
                                if v in levels:
                                    score = levels.index(v)
                                else:
                                    assert v == 'Awakening'
                                    continue
                            else:
                                score = int(v) - 10
                            args.writer.objects['ValueTable'].append(dict(
                                ID='{}-{}-{}'.format(lang.id, k.lower().replace(' ', '_'), i),
                                Language_ID=lang.id,
                                Parameter_ID=k.lower().replace(' ', '_'),
                                Value=score,
                                Code_ID='{}-{}'.format(k.lower().replace(' ', '_'), score),
                                Source=[sid] if sid else [],
                                Comment=norm_text(comment.strip()) if comment else None,
                            ))
                    for key in ['Speaker Number Trends', 'Transmission', 'Domains Of Use']:
                        if key in d:
                            try:
                                score = int(d[key]) - 10
                                d[key] = SCORED_PARAMETERS[('vitality', key)][score]
                            except ValueError:
                                del d[key]
                    if d:
                        args.writer.objects['ValueTable'].append(dict(
                            ID='{}-{}-{}'.format(lang.id, param, i),
                            Language_ID=lang.id,
                            Parameter_ID=param,
                            Value=json.dumps(d),
                            Source=[sid] if sid else [],
                            Comment=norm_text(comment.strip()) if comment else None,
                        ))

        for lang in args.writer.objects['LanguageTable']:
            if lang['ID'] in coords:
                lang['Latitude'], lang['Longitude'] = coords[lang['ID']]
            elif lang['Glottocode'] in coords:
                lang['Latitude'], lang['Longitude'] = coords[lang['Glottocode']]

    def cmd_readme(self, args):
        """
        cldfbench cldfviz.map --language-properties endangerment ../elcat/elcat/cldf --language-properties-colormaps '{"at risk":"green","threatened":"yellow","vulnerable":"yellow","endangered":"orange","severely endangered":"orange","critically endangered":"orange","awakening":"red","dormant":"black"}' --format png --output map.png --with-ocean --width 20 --height 10 --pacific-centered
        """
        #subprocess.check_call([
        #    'cldfbench',
        #    'cldfviz.map',
        #    str(self.cldf_specs().metadata_path),
        #    '--parameters', 'CLF',
        #    '--output', str(self.dir / 'map.jpg'),
        #    '--width', '20',
        #    '--height', '10',
        #    '--format', 'jpg',
        #    '--pacific-centered'])
        desc = [
            '\n![](map.png)\n'
        ]
        pre, head, post = super().cmd_readme(args).partition('## CLDF ')
        return pre + '\n'.join(desc) + head + post
