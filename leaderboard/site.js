/* Progressive enhancement: the complete catalog remains readable without JS. */
(() => {
  const revealAnchor = () => {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); }
    catch { return; }
    if (!target) return;
    const details = target.closest('details');
    if (details) details.open = true;
  };
  revealAnchor();
  window.addEventListener('hashchange', revealAnchor);
  document.querySelectorAll('a[href="#protocol-fit"]').forEach(link => {
    link.addEventListener('click', () => {
      const panel = document.getElementById('protocol-fit');
      if (panel) panel.open = true;
    });
  });
  const controls = document.getElementById('library-controls');
  if (!controls) return;
  const search = document.getElementById('benchmark-search');
  const cards = [...document.querySelectorAll('[data-benchmark]')];
  const count = document.getElementById('benchmark-count');
  const empty = document.getElementById('search-empty');
  const filter = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const stage = controls.querySelector('input[name="stage"]:checked').value;
    let visible = 0;
    cards.forEach(card => {
      const matches = (stage === 'all' || card.dataset.stage === stage)
        && card.textContent.toLocaleLowerCase().includes(query);
      card.hidden = !matches;
      if (matches) visible++;
    });
    count.textContent = `${visible} of ${cards.length} benchmark families`;
    empty.hidden = visible !== 0;
  };
  search.addEventListener('input', filter);
  controls.addEventListener('change', filter);
  document.getElementById('benchmark-reset').addEventListener('click', () => {
    search.value = '';
    controls.querySelector('input[value="all"]').checked = true;
    filter();
    search.focus();
  });
  controls.hidden = false;
})();
