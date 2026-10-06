import pytest

from tools.benchmark.selected_resource_graph import references


def test_original_edges_keep_repeats_and_locations():
    data = b'''<sdf><model><include><uri>model://x</uri></include>
    <include><uri>model://x</uri></include><link><visual><geometry><mesh>
    <uri>model://x/a.dae</uri></mesh></geometry><material><script>
    <uri>file://media/materials/scripts/gazebo.material</uri><name>Gazebo/Grey</name>
    </script><pbr><metal><albedo_map>a.png</albedo_map><normal_map>n.png</normal_map>
    </metal></pbr></material></visual></link><plugin filename="gz-sim-physics-system" name="Physics"/>
    </model></sdf>'''
    rows = references(data, 'sdf')
    assert [r['kind'] for r in rows] == ['include', 'include', 'mesh', 'script', 'material-name', 'texture', 'texture', 'plugin']
    assert rows[0] == {'kind': 'include', 'text': 'model://x', 'position': '/sdf[1]/model[1]/include[1]/uri[1]'}
    assert rows[1]['position'].endswith('include[2]/uri[1]')
    assert rows[-1]['text'] == 'gz-sim-physics-system'
    assert rows[-1]['position'].endswith('plugin[1]/@filename')


def test_collada_image_is_external_but_surface_symbol_is_not():
    data = b'''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema">
    <library_images><image id="texture"><init_from>../textures/wood.png</init_from></image></library_images>
    <library_effects><effect><profile_COMMON><newparam><surface><init_from>texture</init_from>
    </surface></newparam></profile_COMMON></effect></library_effects></COLLADA>'''
    assert references(data, 'dae') == [dict(kind='collada-image', text='../textures/wood.png',
        position='/COLLADA[1]/library_images[1]/image[1]/init_from[1]')]


def test_unrecognized_uri_is_visible_not_silently_qualified():
    rows = references(b'<sdf><extension><uri>https://example.invalid/a</uri></extension></sdf>', 'sdf')
    assert rows == [dict(kind='unsupported', text='https://example.invalid/a', position='/sdf[1]/extension[1]/uri[1]')]


@pytest.mark.parametrize('data', [b'<sdf><include><uri/></include></sdf>', b'<sdf><plugin name="X"/></sdf>',
    b'<sdf><plugin filename=" "/></sdf>', b'<!DOCTYPE sdf [<!ENTITY x "abc">]><sdf/>', b'<sdf>',
    b'<COLLADA/>', b'<sdf><mesh><uri>a<bad/>b</uri></mesh></sdf>'])
def test_bad_sdf_refused(data):
    with pytest.raises(ValueError):
        references(data, 'sdf')


def test_whitespace_in_resource_spelling_is_preserved():
    assert references(b'<sdf><include><uri> model://x </uri></include></sdf>', 'sdf')[0]['text'] == ' model://x '


def test_collada_non_image_init_from_is_not_silently_assumed_internal():
    rows = references(b'<COLLADA><extra><init_from>other.dae</init_from></extra></COLLADA>', 'dae')
    assert rows[0]['kind'] == 'unsupported'


def test_format_is_explicit():
    with pytest.raises(ValueError):
        references(b'<sdf/>', 'xml')


@pytest.mark.parametrize('element,attribute', [('instance_node', 'url'), ('input', 'source'),
    ('instance_material', 'target'), ('extension', 'href')])
def test_collada_external_document_attributes_are_retained_as_unsupported(element, attribute):
    data = f'<COLLADA><{element} {attribute}="other.dae#node"/></COLLADA>'.encode()
    assert references(data, 'dae') == [dict(kind='unsupported', text='other.dae#node',
        position=f'/COLLADA[1]/{element}[1]/@{attribute}')]


def test_collada_local_fragment_attributes_are_internal():
    assert references(b'<COLLADA><instance_node url="#node"/></COLLADA>', 'dae') == []


def test_text_is_xml_value_with_original_bytes_kept_by_caller():
    rows = references(b'<sdf><mesh><uri>a&amp;b\r\nc</uri></mesh></sdf>', 'sdf')
    assert rows[0]['text'] == 'a&b\nc'
