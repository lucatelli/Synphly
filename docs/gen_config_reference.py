#!/usr/bin/env python
"""
Generate docs/config_reference.md from the comments in configs/template.toml.

    python docs/gen_config_reference.py [TEMPLATE] [OUTPUT]

Defaults: configs/template.toml -> docs/config_reference.md (paths relative to the repository root).

Conventions read from the template:
- ``[section]`` starts a new table.
- A block of ``#`` comment lines directly above one or more ``key = value`` lines describes all of those keys
  (a blank line or a new comment block ends the group).
- Comment lines indented by two or more spaces after ``#`` are examples and are rendered as code.
- The comment block before the first section is the file header and is not rendered.
- Defaults are taken from the parsed TOML (tomllib), so they are exactly what the loader sees.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEY_RE = re.compile(r'^([A-Za-z0-9_]+)\s*=')
SECTION_RE = re.compile(r'^\[([A-Za-z0-9_.]+)\]\s*$')


def _fmt_default(value) -> str:
    if isinstance(value, bool):
        text = 'true' if value else 'false'
    elif isinstance(value, str):
        text = f'"{value}"'
    elif isinstance(value, dict):
        text = '{}' if not value else '{ ' + ', '.join(f'{k} = {_fmt_default(v)}' for k, v in value.items()) + ' }'
        return f'`{text}`'
    else:
        text = str(value)
    return f'`{text}`'


def _render_comment(lines: list) -> str:
    """Join comment lines into one Markdown cell; example lines become inline code."""
    parts = []
    for raw in lines:
        body = raw[1:] if raw.startswith('#') else raw
        if body.startswith('   ') or body.startswith('\t'):
            ex = body.strip()
            if ex:
                parts.append(f'`{ex}`')
        else:
            text = body.strip()
            if text:
                parts.append(text)
    text = ' '.join(parts)
    return text.replace('|', '\\|')


def parse(template_path: str):
    """Return [(section, [(key, description)])] in file order."""
    with open(template_path) as f:
        lines = f.read().splitlines()
    sections = []
    current = None
    comment = []        # pending comment block
    group_desc = None   # description of the current key group
    for line in lines:
        stripped = line.strip()
        m = SECTION_RE.match(stripped)
        if m:
            current = (m.group(1), [])
            sections.append(current)
            comment, group_desc = [], None
            continue
        if stripped == '':
            comment, group_desc = [], None
            continue
        if stripped.startswith('#'):
            if group_desc is not None:      # a comment after keys starts a new group
                group_desc = None
                comment = []
            comment.append(stripped)
            continue
        km = KEY_RE.match(stripped)
        if km and current is not None:
            if group_desc is None:
                group_desc = _render_comment(comment)
                comment = []
            current[1].append((km.group(1), group_desc))
    return sections


def generate(template_path: str) -> str:
    with open(template_path, 'rb') as f:
        values = tomllib.load(f)
    rel = os.path.relpath(template_path, ROOT)
    out = ['# Synphly configuration reference', '',
           f'Generated from [`{rel}`](../{rel}) by `docs/gen_config_reference.py`. Do not edit by hand: edit the',
           'template comments and re-run the script.', '',
           'A dataset config only needs the keys that differ from these defaults. Lists of fields can be written as a',
           'comma-separated string (`"0,2"`) or as a TOML array (`[0, 2]`). Unknown keys are an error.', '']
    sections = parse(template_path)
    out.append('Sections: ' + ', '.join(f'[`[{s}]`](#{s.replace(".", "")})' for s, _ in sections) + '.')
    out.append('')
    for sec, keys in sections:
        out += [f'## [{sec}]', '', '| Key | Default | Description |', '|---|---|---|']
        sec_values = values.get(sec, {})
        prev = None
        for key, desc in keys:
            default = _fmt_default(sec_values[key]) if key in sec_values else ''
            # keys of one comment group: the description is written once, on the first key
            cell = '(as above)' if prev is not None and desc is prev and desc else desc
            out.append(f'| `{key}` | {default} | {cell} |')
            prev = desc
        out.append('')
    return '\n'.join(out)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    template = argv[0] if len(argv) > 0 else os.path.join(ROOT, 'configs', 'template.toml')
    output = argv[1] if len(argv) > 1 else os.path.join(HERE, 'config_reference.md')
    text = generate(template)
    with open(output, 'w') as f:
        f.write(text)
    print(f'Wrote {output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
