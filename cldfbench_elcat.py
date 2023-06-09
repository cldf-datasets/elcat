import re
import json
import hashlib
import pathlib
import subprocess
import collections
import urllib.parse
import urllib.request

import requests
from cldfbench import Dataset as BaseDataset
from cldfbench import CLDFSpec
from clldutils.misc import nfilter
from csvw.metadata import URITemplate

from util import (
    iter_langs, SCORED_PARAMETERS, split, bibliography, get_doc, COMPOSITE_PARAMETERS,
    norm_text, norm_coords, Bib, norm_country, INVALID_LANGUAGE_IDS,
)


class Dataset(BaseDataset):
    dir = pathlib.Path(__file__).parent
    id = "elcat"

    def cldf_specs(self):
        return CLDFSpec(module='StructureDataset', dir=self.cldf_dir)

    def get(self, url, force=False):
        if url.startswith('/'):
            url = 'https://endangeredlanguages.com' + url
        parsed = urllib.parse.urlparse(url)
        p = self.raw_dir / 'html' / parsed.path[1:].replace('/', '_')
        if force or (not p.exists()):
            p.write_text(requests.get(url).text, encoding='utf8')
            print(p)
        return get_doc(p)

    def cmd_download(self, args):
        urllib.request.urlretrieve(
            "https://endangeredlanguages.com/userquery/download/",
            self.raw_dir / 'languages.csv')
        for row in self.raw_dir.read_csv('languages.csv'):
            if row[0] not in INVALID_LANGUAGE_IDS:
                self.get('/lang/{}'.format(row[0]))
                self.get('/lang/{}/bibliography'.format(row[0]))

    def cmd_makecldf(self, args):
        self.schema(args)

        # Add parameter descriptions:
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
        args.writer.objects['ParameterTable'].append(dict(
            ID='LEI',
            Name='Language Endangerment Index',
            Description='Language Endangerment Index computed per source. '
                        'The level of endangerment presented for each language is not meant to be '
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
        args.writer.objects['ParameterTable'].append(dict(
            ID='bib',
            Name='Bibliography',
            Description='Other sources about a language.',
        ))

        # Add languages:
        coords, iso2gc = {}, {}
        for l in args.glottolog.api.languoids():
            if l.iso:
                iso2gc[l.iso] = l.id
            if l.latitude is not None:
                coords[l.id] = (l.latitude, l.longitude)
        # Read hand-curated, explicit mappings between ElCat and Glottolog (dialects):
        id2gc = {
            r['ID']: r['Glottocode'] for r in self.etc_dir.read_csv('languages.csv', dicts=True)}

        cols = {9: 'Comment', 10: 'Countries', 11: 'ELCatMacroareas'}
        lmeta = {}
        countries = {}
        for row in self.raw_dir.read_csv('languages.csv'):
            lmeta[row[0]] = {n: split(row[i]) if i in {11, 10} else row[i] for i, n in cols.items()}
            lmeta[row[0]]['Countries'] = [norm_country(c, countries) for c in lmeta[row[0]]['Countries']]

        for c in sorted(countries.values(), key=lambda i: i['name']):
            args.writer.objects['countries.csv'].append(c)

        sources = []
        for obj in iter_langs(self.raw_dir / 'html'):
            if obj is None:
                continue
            if isinstance(obj, Bib):
                sources.append(obj)
                continue
            lang = obj

            # Determine a language's ISO and Glottocode prefering
            # 1. our hand-crated mappings over
            # 2. explicit ElCat mappings, via "code_authority"
            # 3. derived mappings from ElCat mappings to ISO 639-3.
            iso_codes, glottocodes = [], []
            for code in lang.metadata.language_code:
                code = code.replace('\ufeff', '')
                if len(code) == 3 and (
                        ('ISO 639-3' in lang.metadata.code_authority) or
                        (not lang.metadata.code_authority)):
                    iso_codes.append(code)
                if len(code) == 8 and ('Glottolog' in lang.metadata.code_authority):
                    glottocodes.append(code)

            if iso_codes and not glottocodes:  # Map ISO to Glottocode.
                glottocodes = [iso2gc[iso] for iso in iso_codes if iso in iso2gc]

            if lang.id in id2gc:  # Hand-curated mapping exists.
                if glottocodes:
                    if [id2gc[lang.id]] != glottocodes:
                        assert (lang.id in {'2896', '6029'}) or id2gc[lang.id] in glottocodes, str(lang.id)  # This is the only known discrepancy.
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
                **lmeta[lang.id],
            ))

            # Add values:
            for param, _, _ in COMPOSITE_PARAMETERS:
                for i, (sid, d) in enumerate(getattr(lang, param), start=1):
                    comment = norm_text(d.pop('Public Comment', '')) or None
                    if 'Endangerment Level' in d:
                        if sid == lang.preferred_source:
                            if lang.endangerment and (lang.endangerment != d['Endangerment Level'].split('(')[0].strip().lower()):
                                # 29 cases. What to do here?
                                args.log.warning('{}: {} vs {}'.format(
                                    lang.id, lang.endangerment, d['Endangerment Level'].split('(')[0].strip().lower()))
                        args.writer.objects['ValueTable'].append(dict(
                            ID='{}-LEI-{}'.format(lang.id, i),
                            Language_ID=lang.id,
                            Parameter_ID='LEI',
                            Value=d['Endangerment Level'],
                            Source=[sid] if sid else [],
                            Comment=comment,
                            preferred=sid == lang.preferred_source,
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
                        else:  # Pick the first coordinate as representative location of the language.
                            coords[lang.id] = d['Coordinates'][0]

                    for k, v in d.items():
                        levels = SCORED_PARAMETERS.get((param, k))
                        if levels:  # A value for a scored parameter.
                            if k == 'Speaker Number':  # Speaker Numbers are not given as 10,11,...
                                if v in levels:
                                    score = levels.index(v)
                                else:
                                    assert v == 'Awakening', 'Unknown Speaker Number value: {}'.format(v)
                                    continue
                            else:  # Scores given as 10, 11, 12, 13, 14, 15.
                                score = int(v) - 10
                            args.writer.objects['ValueTable'].append(dict(
                                ID='{}-{}-{}'.format(lang.id, k.lower().replace(' ', '_'), i),
                                Language_ID=lang.id,
                                Parameter_ID=k.lower().replace(' ', '_'),
                                Value=score,
                                Code_ID='{}-{}'.format(k.lower().replace(' ', '_'), score),
                                Source=[sid] if sid else [],
                                Comment=comment,
                                preferred=sid == lang.preferred_source,
                            ))
                    for key in ['Speaker Number Trends', 'Transmission', 'Domains Of Use']:
                        if key in d:
                            # Translate 10,11,12,... notation to score descriptions for the
                            # composite values.
                            try:
                                score = int(d[key]) - 10
                                d[key] = SCORED_PARAMETERS[('vitality', key)][score]
                            except ValueError:
                                del d[key]
                    if d or comment:
                        args.writer.objects['ValueTable'].append(dict(
                            ID='{}-{}-{}'.format(lang.id, param, i),
                            Language_ID=lang.id,
                            Parameter_ID=param,
                            Value=json.dumps(d),
                            Source=[sid] if sid else [],
                            Comment=comment,
                            preferred=sid == lang.preferred_source,
                        ))

        for src in bibliography(self.raw_dir / 'html'):
            if src:
                sources.append(src)

        lid2sids = collections.defaultdict(set)
        local_id2sid, sids = {}, set()
        for i, m in enumerate(Bib.iter_merged(sources), start=1):
            src = m.as_source(str(i))
            sid = hashlib.md5((src.get('local_ids') or src.bibtex()).encode('utf8')).hexdigest()
            src.id = sid
            assert sid not in sids
            sids.add(sid)
            args.writer.cldf.sources.add(m.as_source(sid))
            assert m.local_ids or m.language_ids, str(src.bibtex())
            for local_id in m.local_ids:
                local_id2sid[local_id] = sid
            for lid in m.language_ids:
                lid2sids[lid].add(sid)

        for val in args.writer.objects['ValueTable']:
            val['Source'] = [local_id2sid[sid] for sid in val['Source']]

        for lid, sources in lid2sids.items():
            args.writer.objects['ValueTable'].append(dict(
                ID='{}-bib'.format(lid),
                Language_ID=lid,
                Parameter_ID='bib',
                Value='See Source',
                Source=list(sorted(sources)),
            ))

        # Now we can assign locations to the languages, preferentially from ElCat data, as a
        # fallback from Glottolog data.
        for lang in args.writer.objects['LanguageTable']:
            if lang['ID'] in coords:
                lang['Latitude'], lang['Longitude'] = coords[lang['ID']]
            elif lang['Glottocode'] in coords:
                lang['Latitude'], lang['Longitude'] = coords[lang['Glottocode']]

    def schema(self, args):
        args.writer.cldf.add_component(
            'LanguageTable',
            {
                'name': 'Comment',
                'propertyUrl': 'http://cldf.clld.org/v1.0/terms.rdf#comment',
            },
            {
                'name': 'Countries',
                'separator': ' ',
                'dc:description':
                    'Countries a language is spoken in given by ISO 3166-1 alpha-2 code',
            },
            {
                'name': 'ELCatMacroareas',
                'separator': '; ',
            },
            {
                'name': 'classification',
                'dc:description': 'Top-level genealogical unit the language belongs to.',
            },
            {
                'name': 'endangerment',
                'dc:description':
                    "ElCat's aggregated endangerment assessment. Note that in a few cases this "
                    "endangerment assessment does **not** match the assessment in the preferred "
                    "source as given for parameter LEI in the ValueTable.",
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
        args.writer.cldf['LanguageTable', 'ID'].valueUrl = URITemplate(
            'https://endangeredlanguages.com/lang/{ID}')
        args.writer.cldf.add_component('ParameterTable')
        args.writer.cldf.add_component('CodeTable')
        args.writer.cldf.add_columns(
            'ValueTable',
            {
                'name': 'preferred',
                'dc:description':
                    'If ElCat contains multiple pieces of information pertaining to the same '
                    'aspects of a language, the one used to assess the overall endangerment index '
                    'is marked as *preferred* (based on its source).',
                'datatype': {'base': 'boolean', 'format': 'yes|no'}}
        )
        args.writer.cldf.add_table(
            'countries.csv',
            {
                'name': 'alpha_2',
                'propertyUrl': 'http://cldf.clld.org/v1.0/terms.rdf#id',
            },
            'alpha_3',
            {
                'name': 'name',
                'propertyUrl': 'http://cldf.clld.org/v1.0/terms.rdf#name',
            },
            'official_name',
        )
        args.writer.cldf.add_foreign_key('LanguageTable', 'Countries', 'countries.csv', 'alpha_2')

    def cmd_readme(self, args):
        subprocess.check_call([
            'cldfbench',
            'cldfviz.map',
            str(self.cldf_specs().metadata_path),
            '--language-properties', 'endangerment',
            '--language-properties-colormaps',
            '{"at risk":"#FFF7BC","threatened":"#FEE391","vulnerable":"#FEC44F","endangered":"#FB9A29","severely endangered":"#EC7014","critically endangered":"#CC4C02","awakening":"#993404","dormant":"#662506"}',
            '--output', str(self.dir / 'map.png'),
            '--width', '20',
            '--height', '10',
            '--format', 'png',
            '--with-ocean',
            '--pacific-centered'])
        desc = [
            '\n![](map.png)\n\n### Parameters\n',
            'This dataset contains three sets of [parameters](cldf/parameters.csv).',
            '- The four categories from which the Language Endangerment Index is derived.',
            '- The computed Language Endangerment Index.',
            '- Parameters with composite JSON values, aggregating information from a specific '
            'source on a particular topic. Below is a list of '
            '[JSON schemas](https://json-schema.org/) describing the values of these parameters.\n'
        ]
        for param in self.cldf_reader()['ParameterTable']:
            if param['ColumnSpec']:
                desc.append('#### {}\n'.format(param['Name']))
                desc.append('```json')
                schema = json.loads(param['ColumnSpec']['datatype']['format'])
                desc.extend(json.dumps(schema, indent=4).split('\n'))
                desc.append('```\n')
        pre, head, post = super().cmd_readme(args).partition('## CLDF ')
        return pre + '\n'.join(desc) + head + post
