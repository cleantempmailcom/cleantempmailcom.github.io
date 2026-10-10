// Regression coverage for URL-based language selection. No browser or npm packages required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'assets/language.js'), 'utf8');
let checks = 0;

function run(url, lang, dataset, stored) {
  const state = { redirected: null, cleaned: null, listeners: {} };
  const links = ['zh', 'en'].map(key => ({ href: new URL(dataset[key], url).href }));
  const location = { href: url, replace: target => { state.redirected = target; } };
  vm.runInNewContext(source, {
    URL,
    location,
    history: {
      state: { preserved: true },
      replaceState(value, unused, target) {
        assert.deepEqual(value, { preserved: true });
        state.cleaned = location.href = target;
      },
    },
    document: {
      currentScript: { dataset },
      documentElement: { lang },
      querySelectorAll: () => links,
    },
    localStorage: { getItem: () => stored, setItem() { throw new Error('Storage must not be required'); } },
    addEventListener: (event, listener) => { state.listeners[event] = listener; },
  });
  checks++;
  return { ...state, links, location };
}

// 404.html is the noindex GitHub Pages error page; it has no canonical or language switch.
const files = fs.readdirSync(root, { recursive: true }).filter(file => file.endsWith('.html') && path.basename(file) !== '404.html');
for (const file of files) {
  const html = fs.readFileSync(path.join(root, file), 'utf8');
  const lang = html.match(/<html lang="([^"]+)"/)[1];
  const current = lang === 'en' ? 'en' : 'zh';
  const other = current === 'en' ? 'zh' : 'en';
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)[1];
  const script = html.match(/<script src="[^"]*language\.js"[^>]*>/)[0];
  const dataset = Object.fromEntries(['zh', 'en'].map(key => [key, script.match(new RegExp(`data-${key}="([^"]+)"`))[1]]));
  const clean = run(canonical, lang, dataset, other);
  assert.equal(clean.redirected, null, `${file}: stored preference changed the language`);
  assert.equal(clean.cleaned, null);
  assert.equal(run(canonical, lang, dataset, null).redirected, null);

  const target = new URL(dataset[other], canonical);
  target.search = '?utm_source=test&campaign=a%26b';
  target.hash = '#main';
  const switched = run(canonical + '?lang=' + other + '&utm_source=test&campaign=a%26b#main', lang, dataset, current);
  assert.equal(switched.redirected, target.href, `${file}: explicit language redirect lost URL data`);
  const arrived = run(switched.redirected, other === 'en' ? 'en' : 'zh-CN', {}, current);
  assert.equal(arrived.redirected, null, `${file}: redirect loop`);

  const same = run(canonical + '?lang=' + current + '&utm_source=test#main', lang, dataset, other);
  assert.equal(same.redirected, null);
  assert.equal(same.cleaned, canonical + '?utm_source=test#main');
  assert(same.links.every(link => link.href.endsWith('?utm_source=test#main')));
  same.location.href = canonical + '?utm_source=test#new-section';
  same.listeners.hashchange();
  assert(same.links.every(link => link.href.endsWith('?utm_source=test#new-section')));

  const invalid = run(canonical + '?lang=invalid', lang, dataset, other);
  assert.equal(invalid.redirected, null, `${file}: invalid language triggered a redirect`);
  assert.equal(invalid.cleaned, null);
}

// Relative targets must also work under a preview origin and project subpath.
const preview = run('http://127.0.0.1:8080/?lang=en#faq', 'zh-CN', { zh: './', en: './en/' });
assert.equal(preview.redirected, 'http://127.0.0.1:8080/en/#faq');
console.log(`PASS: ${checks} language scenarios across ${files.length} pages; stable URLs, legacy links, query parameters and anchors.`);
