from csvw.metadata import Column
from cldfbench import metadata


def test_valid(cldf_dataset, cldf_logger):
    value_cols = {}
    for param in cldf_dataset.iter_rows('ParameterTable'):
        if param['ColumnSpec'] and param['ColumnSpec'].get('datatype', {}).get('base') == 'json':
            value_cols[param['ID']] = Column.fromvalue(param['ColumnSpec'])
    for val in cldf_dataset.iter_rows('ValueTable'):
        if val['Parameter_ID'] in value_cols:
            value_cols[val['Parameter_ID']].read(val['Value'])
    assert cldf_dataset.validate(log=cldf_logger)
