"""Census identifiers must not be rounded into a different raster zone."""
import numpy as np
import pandas as pd
import pytest
from decimal import Decimal, localcontext
from fractions import Fraction
import yaml
import rasterio

from core.pypoprf.config.settings import Settings
from core.pypoprf.utils.raster import validate_census
from core.pypoprf.algorithms.feature_extraction import FeatureExtractor
from core.pypoprf.preparation import _census
from core.pypoprf.utils.zone_ids import exact_zone_ids
from core.pypoprf.algorithms.model import Model
from core.pypoprf.algorithms.dasymetric import DasymetricMapper
from core.pypoprf.cli import main
from .test_settings import settings_inputs as settings_inputs


@pytest.mark.parametrize('text', ['9007199254740993.0', '-9007199254740993.0',
                                  '9007199254740992.1', '-9007199254740992.1',
                                  '1.0000000000000001', '1e-400'])
def test_api_exact_id_rejects_lexical_rounding(text):
    frame = pd.DataFrame({'zone_code': [text], 'people': [100]})
    with pytest.raises(ValueError, match='integer|representable'):
        Settings.validate_census_frame(frame, 'zone_code', ['people'])
    with pytest.raises(ValueError, match='integer|representable'):
        validate_census(frame, 'zone_code', 'people')


@pytest.mark.parametrize('text', ['9007199254740993.0', '-9007199254740993.0',
                                  '1.0000000000000001'])
def test_csv_settings_rejects_before_pandas_rounding(settings_inputs, text):
    from pathlib import Path
    source = Path(settings_inputs['work_dir']) / settings_inputs['data_dir'] / settings_inputs['census_data']
    payload = ('id,sum\n' + text + ',100\n').encode()
    source.write_bytes(payload)
    with pytest.raises(ValueError, match='integer|representable'):
        Settings(**settings_inputs)
    assert source.read_bytes() == payload


@pytest.mark.parametrize('text,expected', [('1.0',1),(' 0001.000 ',1),('1e0',1),
                                         ('9007199254740991.0',2**53-1),
                                         ('9007199254740992.0',2**53),
                                         ('-9007199254740992.0',-(2**53))])
def test_csv_valid_spellings_exact_and_other_columns_preserved(tmp_path, text, expected):
    path = tmp_path / 'custom.csv'
    payload = ('zone_code,people,other\n' + text + ',12.5,note\n').encode()
    path.write_bytes(payload)
    frame = Settings._read_csv(path, 'zone_code')
    assert int(frame['zone_code'].iloc[0]) == expected
    assert frame['people'].iloc[0] == 12.5 and frame['other'].iloc[0] == 'note'
    assert path.read_bytes() == payload


def test_feature_reader_keeps_exact_custom_mapping(settings_inputs, tmp_path):
    settings = Settings(**settings_inputs)
    path = tmp_path / 'custom.csv'
    path.write_text('id,sum\n9007199254740991.0,12.5\n', encoding='utf-8')
    frame = FeatureExtractor(settings).load_table(path)
    assert int(frame.id.iloc[0]) == 2**53-1


@pytest.mark.parametrize('text', ['9007199254740993.0','1.0000000000000001'])
def test_preparation_census_refuses_rounded_id(tmp_path,text):
    path = tmp_path / 'custom.csv'
    path.write_text(f'zone_code,people\n{text},12.5\n',encoding='utf-8')
    with pytest.raises(ValueError, match='integer|representable'):
        _census({'path':str(path),'id_column':'zone_code','population_column':'people'})


def test_age_sex_ids_cannot_alias_main_census(settings_inputs, tmp_path):
    path = tmp_path / 'ages.csv'
    path.write_text('id,f0\n1.0000000000000001,100\n',encoding='utf-8')
    with pytest.raises(ValueError, match='integer|representable'):
        Settings(**settings_inputs, agesex_data=str(path))


def test_api_float_and_integer_ids_keep_accepted_types():
    for values in [[1.0,2.0], np.array([1,2],dtype='int64')]:
        frame=pd.DataFrame({'id':values,'pop':[10,20]})
        validated=validate_census(frame,'id','pop')
        assert validated.id.dtype == frame.id.dtype
        pd.testing.assert_frame_equal(frame,pd.DataFrame({'id':values,'pop':[10,20]}))


@pytest.mark.parametrize('value', [True, np.bool_(True), complex(1,0), float('nan'),
                                  float('inf'), '-Infinity', 'NaN', '1e999999', '-1e999999', '1_0'])
def test_invalid_scalar_ids_are_explicit(value):
    with pytest.raises(ValueError):
        exact_zone_ids([value])


def test_exact_decimal_context_and_integer_spellings():
    with localcontext() as context:
        context.prec = 2
        assert exact_zone_ids(['0','-99','9007199254740991.0',Decimal('-9007199254740992')]) == [0,-99,2**53-1,-(2**53)]
        with pytest.raises(ValueError):
            exact_zone_ids([Decimal('9007199254740992.1')])


@pytest.mark.parametrize('number', [2**31,2**53,-(2**53)])
@pytest.mark.parametrize('dtype',[np.float32,np.float64,np.longdouble])
def test_numpy_real_id_uses_numeric_value_not_shortest_display(number,dtype):
    value=dtype(number)
    assert exact_zone_ids([value]) == [number]
    assert int(Settings.validate_census_frame(pd.DataFrame({'id':np.array([value],dtype=dtype),'pop':[100]}),'id',['pop'])[0]) == number


@pytest.mark.parametrize('value',[np.float32(1.5),np.float64(1.0000000000000002),Fraction(3,2)])
def test_native_real_fraction_rejected_without_decimal_display(value):
    with pytest.raises(ValueError,match='integer'):
        exact_zone_ids([value])


def test_extended_real_fraction_not_rounded_to_python_float():
    if np.finfo(np.longdouble).eps >= np.finfo(float).eps:
        pytest.skip('Platform longdouble has no extended precision')
    value=np.longdouble('1.000000000000000001')
    assert value != 1 and float(value)==1
    with pytest.raises(ValueError,match='integer'):
        exact_zone_ids([value])


def test_duplicate_numeric_spellings_rejected_without_source_mutation():
    frame=pd.DataFrame({'id':['1','1.0'],'pop':[10,20]})
    original=frame.copy()
    with pytest.raises(ValueError,match='duplicate|Duplicate'):
        validate_census(frame,'id','pop')
    with pytest.raises(ValueError,match='duplicate|Duplicate'):
        Settings.validate_census_frame(frame,'id',['pop'])
    pd.testing.assert_frame_equal(frame,original)


def test_cli_original_misallocation_repro_is_rejected_before_run(settings_inputs, tmp_path):
    from pathlib import Path
    from .test_settings import write_raster
    write_raster(Path(settings_inputs['mastergrid']), np.full((32,32),2**53,dtype='int64'))
    census=Path(settings_inputs['census_data'])
    payload=b'id,sum\n9007199254740993.0,100\n'
    census.write_bytes(payload)
    config=tmp_path/'config.yaml'
    config.write_text(yaml.safe_dump(settings_inputs),encoding='utf-8')
    output=tmp_path/'explicit-run'
    assert main(['--config',str(config),'--output-dir',str(output)]) == 1
    assert not output.exists()
    assert census.read_bytes()==payload


def test_model_and_mapper_api_valid_large_decimal_keeps_exact_zone(settings_inputs, tmp_path):
    from pathlib import Path
    from .test_settings import write_raster
    write_raster(Path(settings_inputs['mastergrid']),np.full((32,32),2**53-1,dtype='int64'))
    Path(settings_inputs['census_data']).write_text('id,sum\n9007199254740991.0,100\n',encoding='utf-8')
    settings=Settings(**{**settings_inputs, 'n_estimators':2, 'cv_strategy':'spatial'})
    data=pd.DataFrame({'id':['9007199254740991.0'],'sum':[100.],
                       'dens':[100./1024], 'x_avg':[1.]})
    model=Model(settings)
    model.train(data,save_model=False)
    assert int(model.cv_zone_geometry.zone_id.iloc[0]) == 2**53-1
    prediction=model.predict()
    result=DasymetricMapper(settings).map(prediction)
    with rasterio.open(result['unconstrained']) as source:
        assert float(source.read(1,masked=True).sum())==pytest.approx(100)
