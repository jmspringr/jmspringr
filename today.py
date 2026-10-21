"""
Builds dark_mode.svg and light_mode.svg: a neofetch-style GitHub profile card.

Layout and idea adapted from Andrew6rant/Andrew6rant (MIT License).

Edit the CONFIG block below to change what the card says.
Run by .github/workflows/build.yml daily. Locally: `python today.py --offline`
renders the card with placeholder stats and no network calls.
"""
import datetime
import hashlib
import io
import json
import os
import sys
from xml.sax.saxutils import escape

import requests
from dateutil import relativedelta
from PIL import Image, ImageDraw, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
# CONFIG: edit these lines to change the card
# --------------------------------------------------------------------------- #
USER_NAME = os.environ.get('USER_NAME', 'jmspringr')
TITLE = 'jacob@springer'
BIRTHDAY = datetime.datetime(1998, 1, 12)

INFO = [  # (key, value); None = blank spacer line
    ('OS', 'Windows, macOS'),
    ('Uptime', '{uptime}'),
    ('Host', 'PalmerHolland'),
    ('Kernel', 'Junior Application Developer'),
    ('IDE', 'Visual Studio, VS Code'),
    None,
    ('Languages.Programming', 'SQL, C#, Python, JavaScript'),
    ('Languages.Real', 'English'),
    ('Hobbies', 'PC Gaming, Reading'),
]
CONTACT = [
    ('Email', 'jakemspringer@gmail.com'),
    ('LinkedIn', 'in/jakemspringer'),
]

# Optional: put hand-made ASCII art in ascii.txt to override the avatar art.
ASCII_FILE = 'ascii.txt'
ASCII_COLS, ASCII_ROWS = 38, 19

# --------------------------------------------------------------------------- #
# Layout / theme
# --------------------------------------------------------------------------- #
LINE_W = 58            # characters per line in the right column
LEFT_X, RIGHT_X = 15, 395
TOP_Y, STEP = 30, 20
WIDTH = 985

THEMES = {
    'dark_mode.svg': dict(bg='#161b22', text='#c9d1d9', key='#ffa657', value='#a5d6ff',
                          cc='#616e7f', add='#3fb950', dele='#f85149', invert=False),
    'light_mode.svg': dict(bg='#f6f8fa', text='#24292f', key='#953800', value='#0a3069',
                           cc='#c2cfde', add='#1a7f37', dele='#cf222e', invert=False),
}
RAMP = ' .:-=+*#%@'
CACHE_FILE = 'cache/' + hashlib.sha256(USER_NAME.encode()).hexdigest() + '.json'
GQL = 'https://api.github.com/graphql'


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def uptime(birthday):
    d = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    p = lambda n, w: f'{n} {w}' + ('' if n == 1 else 's')
    cake = ' 🎂' if d.months == 0 and d.days == 0 else ''
    return f"{p(d.years, 'year')}, {p(d.months, 'month')}, {p(d.days, 'day')}{cake}"


def gql(query, variables):
    headers = {'Authorization': 'bearer ' + os.environ['ACCESS_TOKEN']}
    r = requests.post(GQL, json={'query': query, 'variables': variables}, headers=headers, timeout=60)
    if r.status_code != 200 or 'errors' in r.json():
        raise RuntimeError(f'GraphQL failed ({r.status_code}): {r.text[:500]}')
    return r.json()['data']


def fetch_user():
    q = '''query($login:String!){ user(login:$login){
        id avatarUrl(size:400) followers{totalCount}
        owned: repositories(first:100, ownerAffiliations:OWNER){ totalCount nodes{ stargazerCount } }
        all: repositories(first:1, ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){ totalCount }
    }}'''
    u = gql(q, {'login': USER_NAME})['user']
    return {
        'id': u['id'],
        'avatar': u['avatarUrl'],
        'followers': u['followers']['totalCount'],
        'repos': u['owned']['totalCount'],
        'stars': sum(n['stargazerCount'] for n in u['owned']['nodes']),
        'contrib': u['all']['totalCount'],
    }


def list_repos():
    q = '''query($login:String!, $cursor:String){ user(login:$login){
        repositories(first:60, after:$cursor, ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){
            nodes{ nameWithOwner defaultBranchRef{ target{ oid } } }
            pageInfo{ endCursor hasNextPage } } } }'''
    repos, cursor = [], None
    while True:
        r = gql(q, {'login': USER_NAME, 'cursor': cursor})['user']['repositories']
        repos += r['nodes']
        if not r['pageInfo']['hasNextPage']:
            return repos
        cursor = r['pageInfo']['endCursor']


def repo_loc(name_with_owner, user_id):
    owner, name = name_with_owner.split('/')
    q = '''query($owner:String!, $name:String!, $id:ID!, $cursor:String){ repository(owner:$owner, name:$name){
        defaultBranchRef{ target{ ... on Commit{
            history(first:100, after:$cursor, author:{id:$id}){
                nodes{ additions deletions } pageInfo{ endCursor hasNextPage } } } } } } }'''
    commits = add = dele = 0
    cursor = None
    while True:
        h = gql(q, {'owner': owner, 'name': name, 'id': user_id, 'cursor': cursor})
        h = h['repository']['defaultBranchRef']['target']['history']
        for n in h['nodes']:
            commits += 1
            add += n['additions']
            dele += n['deletions']
        if not h['pageInfo']['hasNextPage']:
            return commits, add, dele
        cursor = h['pageInfo']['endCursor']


def loc_and_commits(user_id):
    """Only re-walks repos whose default-branch head changed since the last run."""
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    fresh = {}
    for repo in list_repos():
        key = repo['nameWithOwner']
        if not repo['defaultBranchRef']:
            continue  # empty repo
        oid = repo['defaultBranchRef']['target']['oid']
        if key in cache and cache[key]['oid'] == oid:
            fresh[key] = cache[key]
        else:
            c, a, d = repo_loc(key, user_id)
            fresh[key] = {'oid': oid, 'commits': c, 'add': a, 'del': d}
    os.makedirs('cache', exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(fresh, f, indent=1, sort_keys=True)
    t = lambda k: sum(v[k] for v in fresh.values())
    return t('commits'), t('add'), t('del')


# --------------------------------------------------------------------------- #
# ASCII art
# --------------------------------------------------------------------------- #
def placeholder_image():
    img = Image.new('L', (400, 400), 0)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 230)
    except OSError:
        font = ImageFont.load_default(size=230)
    draw.text((200, 200), 'JS', fill=255, font=font, anchor='mm')
    return img


def load_image(avatar_url):
    if avatar_url:
        try:
            r = requests.get(avatar_url, timeout=30)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert('L')
        except Exception as e:  # fall back rather than fail the whole build
            print('Avatar fetch failed, using placeholder:', e)
    return placeholder_image()


def to_ascii(img, invert):
    img = ImageOps.autocontrast(img.resize((ASCII_COLS, ASCII_ROWS)))
    if invert:
        img = ImageOps.invert(img)
    px = img.load()
    rows = []
    for y in range(ASCII_ROWS):
        rows.append(''.join(RAMP[px[x, y] * (len(RAMP) - 1) // 255] for x in range(ASCII_COLS)).rstrip())
    return rows


def ascii_rows(avatar_url, invert):
    if os.path.exists(ASCII_FILE):
        with open(ASCII_FILE, encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f][:ASCII_ROWS]
    return to_ascii(load_image(avatar_url), invert)


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
def span(cls, text):
    return f'<tspan class="{cls}">{escape(text)}</tspan>'


def key_spans(key):
    return '.'.join(span('key', part) for part in key.split('.'))


def kv_line(key, value, width=LINE_W):
    """'. Key: ....... value' padded to width characters."""
    dots = max(1, width - 2 - len(key) - 1 - len(value) - 2)
    return (span('cc', '. ') + key_spans(key) + ':' +
            span('cc', ' ' + '.' * dots + ' ') + span('value', value))


def stat_pair(k1, v1, k2, v2):
    left_w = 33
    left = kv_line(k1, v1, left_w)
    right_w = LINE_W - left_w - 3
    dots = max(1, right_w - len(k2) - 1 - len(v2) - 2)
    right = key_spans(k2) + ':' + span('cc', ' ' + '.' * dots + ' ') + span('value', v2)
    return left + ' | ' + right


def header(text):
    return escape(text) + ' -' + '—' * (LINE_W - len(text) - 2)


def build_lines(stats):
    lines = [header(TITLE)]
    for item in INFO:
        if item is None:
            lines.append(span('cc', '. '))
        else:
            lines.append(kv_line(item[0], item[1].format(uptime=stats['uptime'])))
    lines.append('')
    lines.append(header('- Contact'))
    lines += [kv_line(k, v) for k, v in CONTACT]
    lines.append('')
    lines.append(header('- GitHub Stats'))

    f = lambda n: f'{n:,}'
    repos = f"{f(stats['repos'])} {{Contributed: {f(stats['contrib'])}}}"
    lines.append(stat_pair('Repos', repos, 'Stars', f(stats['stars'])))
    lines.append(stat_pair('Commits', f(stats['commits']), 'Followers', f(stats['followers'])))
    net = f(stats['add'] - stats['del'])
    tail = f" ( {f(stats['add'])}++, {f(stats['del'])}-- )"
    dots = max(1, LINE_W - 2 - len('Lines of Code') - 1 - len(net) - len(tail) - 2)
    lines.append(span('cc', '. ') + span('key', 'Lines of Code') + ':' +
                 span('cc', ' ' + '.' * dots + ' ') + span('value', net) + ' ( ' +
                 span('add', f(stats['add']) + '++') + ', ' + span('del', f(stats['del']) + '--') + ' )')
    return lines


def render(filename, theme, stats, art):
    lines = build_lines(stats)
    height = TOP_Y + STEP * (max(len(lines), len(art)) - 1) + 20
    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,Menlo,monospace" '
        f'width="{WIDTH}px" height="{height}px" font-size="16px">',
        '<style>',
        "@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback';"
        ' font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }',
        f".key {{fill: {theme['key']};}}",
        f".value {{fill: {theme['value']};}}",
        f".add {{fill: {theme['add']};}}",
        f".del {{fill: {theme['dele']};}}",
        f".cc {{fill: {theme['cc']};}}",
        'text, tspan {white-space: pre;}',
        '</style>',
        f'<rect width="{WIDTH}px" height="{height}px" fill="{theme["bg"]}" rx="15"/>',
        f'<text xml:space="preserve" x="{LEFT_X}" y="{TOP_Y}" fill="{theme["text"]}">',
    ]
    for i, row in enumerate(art):
        out.append(f'<tspan x="{LEFT_X}" y="{TOP_Y + i * STEP}">{escape(row)}</tspan>')
    out.append('</text>')
    out.append(f'<text xml:space="preserve" x="{RIGHT_X}" y="{TOP_Y}" fill="{theme["text"]}">')
    for i, line in enumerate(lines):
        out.append(f'<tspan x="{RIGHT_X}" y="{TOP_Y + i * STEP}">{line}</tspan>')
    out.append('</text>')
    out.append('</svg>')
    with open(filename, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')


def main():
    offline = '--offline' in sys.argv
    stats = {'uptime': uptime(BIRTHDAY)}
    if offline:
        stats.update(repos=0, contrib=0, stars=0, followers=0, commits=0, add=0)
        stats['del'] = 0
        avatar = None
    else:
        if not os.environ.get('ACCESS_TOKEN'):
            sys.exit('ACCESS_TOKEN secret is not set. Add it under Settings > Secrets and variables > Actions.')
        user = fetch_user()
        commits, add, dele = loc_and_commits(user['id'])
        stats.update(user, commits=commits, add=add)
        stats['del'] = dele
        avatar = user['avatar']
    for filename, theme in THEMES.items():
        render(filename, theme, stats, ascii_rows(avatar, theme['invert']))
    print('Rendered', ', '.join(THEMES), '|', {k: v for k, v in stats.items() if k not in ('id', 'avatar')})


if __name__ == '__main__':
    main()
