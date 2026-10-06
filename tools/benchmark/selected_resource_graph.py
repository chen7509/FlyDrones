"""Original XML reference discovery; no implied path resolution or runtime coverage."""
from __future__ import annotations

import xml.etree.ElementTree as ET


def references(data: bytes, format: str) -> list[dict]:
    """Return parsed XML values; callers retain original bytes for lexical spelling."""
    if type(data) is not bytes or format not in ('sdf', 'dae'):
        raise ValueError('explicit bytes and sdf/dae format required')
    # Decode before checking declarations, including UTF-16/32 input refusal.
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('only UTF-8 original XML supported') from exc
    if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('DTD/entity/non-UTF8 XML unsupported')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('invalid original XML') from exc

    def tag(node):
        return node.tag.rsplit('}', 1)[-1]

    if tag(root) != ('sdf' if format == 'sdf' else 'COLLADA'):
        raise ValueError('XML root does not match declared format')
    rows = []

    def emit(node, kind, position, value=None):
        if value is None:
            if len(node):
                raise ValueError('nested resource spelling unsupported')
            value = node.text
        if type(value) is not str or not value.strip():
            raise ValueError('empty resource reference')
        rows.append(dict(kind=kind, text=value, position=position))

    def visit(node, parents, position):
        name = tag(node)
        parent = parents[-1] if parents else ''
        if format == 'dae':
            for attribute, value in node.attrib.items():
                local = attribute.rsplit('}', 1)[-1]
                if (local in ('url', 'source', 'href')
                        or (local == 'target' and name == 'instance_material')):
                    if not value.strip().startswith('#'):
                        emit(node, 'unsupported', position + '/@' + attribute, value)
        if format == 'sdf':
            if name == 'plugin':
                if 'filename' not in node.attrib:
                    raise ValueError('missing plugin filename')
                emit(node, 'plugin', position + '/@filename', node.attrib['filename'])
            if name == 'uri':
                kind = {'include': 'include', 'mesh': 'mesh', 'script': 'script',
                        'heightmap': 'heightmap'}.get(parent, 'unsupported')
                emit(node, kind, position)
            elif name == 'name' and parent == 'script':
                emit(node, 'material-name', position)
            elif name == 'texture' and parent == 'projector':
                emit(node, 'unsupported', position)
            elif name.endswith('_map'):
                emit(node, 'texture' if 'pbr' in parents else 'unsupported', position)
        elif name == 'init_from':
            if parent == 'image':
                emit(node, 'collada-image', position)
            elif parent != 'surface':
                emit(node, 'unsupported', position)
        counts = {}
        for child in node:
            child_tag = tag(child)
            counts[child_tag] = counts.get(child_tag, 0) + 1
            visit(child, parents + [name], f'{position}/{child_tag}[{counts[child_tag]}]')

    visit(root, [], f'/{tag(root)}[1]')
    return rows
