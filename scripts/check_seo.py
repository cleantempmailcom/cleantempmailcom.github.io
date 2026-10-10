#!/usr/bin/env python3
"""Validate the static site's SEO metadata and crawlable links without dependencies."""
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import json
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://cleantempmailcom.github.io/'
NS = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9',
      'x': 'http://www.w3.org/1999/xhtml'}


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.captures = {'title': [], 'h1': [], 'json': []}
        self.active = None
        self.buffer = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.tags.append((tag, attrs))
        if tag in ('title', 'h1') or (tag == 'script' and attrs.get('type') == 'application/ld+json'):
            self.active = 'json' if tag == 'script' else tag
            self.buffer = []
        elif tag == 'br' and self.active == 'h1':
            self.buffer.append(' ')

    def handle_data(self, value):
        if self.active:
            self.buffer.append(value)

    def handle_endtag(self, tag):
        if tag == self.active or (tag == 'script' and self.active == 'json'):
            self.captures[self.active].append(''.join(self.buffer).strip())
            self.active = None

    def select(self, tag, **attrs):
        return [a for t, a in self.tags if t == tag and all(a.get(k) == v for k, v in attrs.items())]

    def metadata(self, key):
        attr = 'property' if key.startswith('og:') else 'name'
        return [a.get('content', '') for a in self.select('meta', **{attr: key})]


def canonical_for(path):
    relative = path.relative_to(ROOT).as_posix()
    return BASE + (relative[:-10] if relative.endswith('index.html') else relative)


def main():
    errors = []
    # 404.html is the GitHub Pages error page: noindex, no canonical, not in the sitemap.
    pages = {canonical_for(p): Page(p.read_text()) for p in sorted(ROOT.rglob('*.html')) if p.name != '404.html'}
    titles, descriptions = [], []
    link_count = 0

    def check(condition, message):
        if not condition:
            errors.append(message)

    def local_target(url):
        parts = urlsplit(url)
        if parts.netloc != urlsplit(BASE).netloc:
            return None
        base_path = urlsplit(BASE).path
        if not parts.path.startswith(base_path):
            return None
        relative = unquote(parts.path[len(base_path):])
        return ROOT / (relative + 'index.html' if parts.path.endswith('/') else relative)

    for url, page in pages.items():
        label = url.removeprefix(BASE) or '/'
        check(len(page.captures['title']) == 1 and bool(page.captures['title'][0]), f'{label}: needs one title')
        check(len(page.captures['h1']) == 1 and bool(page.captures['h1'][0]), f'{label}: needs one H1')
        titles.extend(page.captures['title'])
        descriptions.extend(page.metadata('description'))
        for key in ['description', 'robots', 'og:title', 'og:description', 'og:url', 'og:type',
                    'og:locale', 'og:locale:alternate', 'og:image', 'og:image:width', 'og:image:height',
                    'og:image:alt', 'twitter:card', 'twitter:title', 'twitter:description',
                    'twitter:image', 'twitter:image:alt']:
            values = page.metadata(key)
            check(len(values) == 1 and bool(values[0]), f'{label}: missing or duplicate {key}')
        check(not any('noindex' in x or x.strip() == 'none' for x in page.metadata('robots')), f'{label}: indexing blocked')
        check(page.metadata('og:title') == page.captures['title'], f'{label}: OG title differs')
        check(page.metadata('twitter:title') == page.captures['title'], f'{label}: Twitter title differs')
        check(page.metadata('og:description') == page.metadata('description'), f'{label}: OG description differs')
        check(page.metadata('twitter:description') == page.metadata('description'), f'{label}: Twitter description differs')
        check([a.get('href') for a in page.select('link', rel='canonical')] == [url], f'{label}: wrong canonical')
        check(page.metadata('og:url') == [url], f'{label}: wrong og:url')
        ids = [a['id'] for _, a in page.tags if 'id' in a]
        check(len(ids) == len(set(ids)), f'{label}: duplicate HTML IDs')
        english = label.startswith('en/')
        language = 'en' if english else 'zh-CN'
        check([a.get('lang') for a in page.select('html')] == [language], f'{label}: wrong HTML language')
        zh = BASE + label.removeprefix('en/') if english else url
        alternatives = {'zh-CN': zh, 'en': BASE + 'en/' + zh.removeprefix(BASE), 'x-default': zh}
        actual = page.select('link', rel='alternate')
        check(len(actual) == 3 and {a.get('hreflang'): a.get('href') for a in actual} == alternatives,
              f'{label}: hreflang must match both language canonicals and x-default')
        scripts = [a for a in page.select('script') if a.get('src', '').endswith('/language.js')]
        check(len(scripts) == 1 and 'defer' in scripts[0], f'{label}: language script must defer')
        for script in scripts:
            for key, lang in [('zh', 'zh-CN'), ('en', 'en')]:
                check(urljoin(url, script.get('data-' + key, '')) == alternatives[lang], f'{label}: wrong language script target')
        language_links = [a for a in page.select('a') if a.get('hreflang') in ('zh-CN', 'en')]
        check(len(language_links) == 2, f'{label}: missing language switch links')
        for link in language_links:
            check(urljoin(url, link.get('href', '')) == alternatives[link['hreflang']], f'{label}: noncanonical language switch')

        for tag, attrs in page.tags:
            ref = attrs.get('href') if tag in ('a', 'link') else attrs.get('src') if tag in ('script', 'img') else None
            if ref is None:
                continue
            resolved = urljoin(url, ref)
            target = local_target(resolved)
            if target is None:
                continue
            link_count += 1
            check(target.is_file(), f'{label}: missing target {ref}')
            if target.suffix == '.html' and target.is_file():
                canonical = canonical_for(target)
                parts = urlsplit(resolved)
                check(parts._replace(query='', fragment='').geturl() == canonical, f'{label}: noncanonical internal URL {ref}')
                check(not parts.query, f'{label}: parameterized internal URL {ref}')
                if parts.fragment:
                    target_ids = {a.get('id') for _, a in pages[canonical].tags}
                    check(unquote(parts.fragment) in target_ids, f'{label}: missing fragment {ref}')

        try:
            blocks = [json.loads(raw) for raw in page.captures['json']]
            check(len(blocks) == 1, f'{label}: needs one JSON-LD graph')
            graph = blocks[0]['@graph']
            webpage = [n for n in graph if n.get('@type') in ('WebPage', 'CollectionPage')]
            check(len(webpage) == 1 and webpage[0].get('url') == url, f'{label}: wrong schema page URL')
            for node in webpage:
                check(node.get('name') == page.captures['title'][0], f'{label}: schema title differs')
                check(node.get('description') == page.metadata('description')[0], f'{label}: schema description differs')
                check(node.get('inLanguage') == language, f'{label}: schema language differs')
            if '/guide/' in url:
                crumbs = [n for n in graph if n.get('@type') == 'BreadcrumbList']
                check(len(crumbs) == 1, f'{label}: missing schema breadcrumb')
                for crumb in crumbs:
                    trail = crumb['itemListElement']
                    check([n['position'] for n in trail] == list(range(1, len(trail) + 1)), f'{label}: breadcrumb order')
                    check(trail[-1]['item'] == url, f'{label}: breadcrumb current page differs')
                    check(all(n['item'] in pages for n in trail), f'{label}: breadcrumb target missing')
                if url.endswith('.html'):
                    articles = [n for n in graph if n.get('@type') == 'Article']
                    check(len(articles) == 1, f'{label}: missing Article')
                    for article in articles:
                        check(article['mainEntityOfPage'] == {'@id': url + '#webpage'}, f'{label}: wrong article page')
                        check(article['inLanguage'] == language, f'{label}: article language differs')
                        check(article['headline'].split() == page.captures['h1'][0].split() if english else
                              article['headline'].replace(' ', '') == page.captures['h1'][0].replace(' ', ''),
                              f'{label}: article headline differs from visible H1')
                        check(date.fromisoformat(article['datePublished']) <= date.fromisoformat(article['dateModified']),
                              f'{label}: invalid article dates')
        except (ValueError, KeyError, IndexError, TypeError) as error:
            check(False, f'{label}: invalid structured data: {error}')

    for values, field in [(titles, 'titles'), (descriptions, 'descriptions')]:
        check(not any(n > 1 for n in Counter(values).values()), f'Duplicate page {field}')
    entries = ET.parse(ROOT / 'sitemap.xml').getroot().findall('s:url', NS)
    locations = [node.findtext('s:loc', namespaces=NS) for node in entries]
    check(len(locations) == len(set(locations)) and set(locations) == set(pages), 'Sitemap must cover every canonical exactly once')
    for node in entries:
        url = node.findtext('s:loc', namespaces=NS)
        check(bool(node.findtext('s:lastmod', namespaces=NS)), f'{url}: missing sitemap lastmod')
        if url in pages:
            expected = {a['hreflang']: a['href'] for a in pages[url].select('link', rel='alternate')}
            check({n.get('hreflang'): n.get('href') for n in node.findall('x:link', NS)} == expected,
                  f'{url}: sitemap language alternatives differ from HTML')
    if errors:
        print('\n'.join('ERROR: ' + error for error in errors))
        return 1
    print(f'PASS: {len(pages)} pages; {link_count} internal links/assets; metadata, canonical, hreflang, sitemap and JSON-LD.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
