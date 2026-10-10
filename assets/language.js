(() => {
  const script = document.currentScript;
  const current = document.documentElement.lang === 'en' ? 'en' : 'zh';
  const url = new URL(location.href);
  const requested = url.searchParams.get('lang');
  const explicit = requested === 'en' || requested === 'zh' ? requested : null;

  // Each language has a stable URL. Only an explicit legacy ?lang= link redirects.
  if (explicit) {
    const path = script?.dataset[explicit];
    if (path && explicit !== current) {
      const target = new URL(path, url);
      target.search = url.search;
      target.searchParams.delete('lang');
      target.hash = url.hash;
      location.replace(target.href);
      return;
    }
    url.searchParams.delete('lang');
    history.replaceState(history.state, '', url.href);
  }

  // Static links work without JavaScript; retain campaign parameters and section links.
  const updateLinks = () => {
    const source = new URL(location.href);
    document.querySelectorAll('.language-switch a').forEach(link => {
      const target = new URL(link.href);
      target.search = source.search;
      target.searchParams.delete('lang');
      target.hash = source.hash;
      link.href = target.href;
    });
  };
  updateLinks();
  addEventListener('hashchange', updateLinks);
})();
