(() => {
  // 裝備大分類改成手風琴：展開新分類時，自動收起上一個分類。
  document.addEventListener('click', event => {
    const btn = event.target.closest('button[data-group]');
    if (!btn) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const name = decodeURIComponent(btn.dataset.group || '');
    if (!name) return;

    if (openItemGroups.has(name)) {
      openItemGroups.delete(name);
      for (const key of [...openItemSubgroups]) {
        if (key.startsWith(name + '::')) openItemSubgroups.delete(key);
      }
    } else {
      openItemGroups.clear();
      openItemSubgroups.clear();
      openItemGroups.add(name);
    }

    render();
  }, true);
})();
