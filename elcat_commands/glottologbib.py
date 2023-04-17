"""
Create a bib file enhanced with Glottolog's "lgcode" field.
"""
import collections

from cldfbench_elcat import Dataset


def run(args):
    cldf = Dataset().cldf_reader()
    sid2lid = collections.defaultdict(set)
    for val in cldf.iter_rows('ValueTable'):
        for sid in val['Source']:
            sid2lid[sid].add(val['Language_ID'])

    languages = {l['ID']: l for l in cldf.iter_rows('LanguageTable')}

    def format_lid(lid):
        lang = languages[lid]
        res = lang['Name']
        if lang['Glottocode']:
            res += ' [{}]'.format(lang['Glottocode'])
        elif lang['ISO639P3code']:
            res += ' [{}]'.format(lang['ISO639P3code'])
        return res

    for source in cldf.sources.items():
        if len(sid2lid[source.id]) < 100:
            source['lgcode'] = '; '.join(format_lid(lid) for lid in sid2lid[source.id])
        print(source.bibtex())
