const menuButton = document.querySelector('.header .burger');
const navigation = document.querySelector('.header .nav');
if (menuButton && navigation) {
  menuButton.addEventListener('click', () => {
    const isOpen = navigation.classList.toggle('open');
    menuButton.setAttribute('aria-expanded', String(isOpen));
  });
}

const catalog = document.querySelector('[data-catalog]');
if (catalog) {
  const tabs = [...document.querySelectorAll('[data-catalog-tabs] button')];
  const toolbar = document.querySelector('[data-catalog-toolbar]');
  const search = toolbar.querySelector('input[type="search"]');
  const sort = toolbar.querySelector('select');
  const empty = document.querySelector('[data-catalog-empty]');
  const cards = [...catalog.children];
  const normalize = (text) => text.toLocaleLowerCase('ru').replaceAll('ё', 'е');
  const url = new URL(window.location.href);
  const selected = url.searchParams.get('category') || '';
  let category = tabs.some((tab) => tab.dataset.category === selected) ? selected : '';

  function updateCatalog() {
    const query = normalize(search?.value.trim() || '');
    const direction = sort.value === 'price' ? 1 : sort.value === '-price' ? -1 : 0;
    const ordered = direction
      ? [...cards].sort((a, b) => direction * (Number(a.dataset.price) - Number(b.dataset.price)))
      : cards;
    let visible = 0;
    for (const card of ordered) {
      const matches = (!category || card.dataset.category === category)
        && normalize(card.dataset.search).includes(query);
      card.hidden = !matches;
      visible += Number(matches);
      catalog.append(card);
    }
    for (const tab of tabs) {
      const active = tab.dataset.category === category;
      tab.classList.toggle('on', active);
      tab.setAttribute('aria-pressed', String(active));
    }
    empty.hidden = visible > 0;
  }

  for (const tab of tabs) {
    tab.addEventListener('click', () => {
      category = tab.dataset.category;
      if (category) url.searchParams.set('category', category);
      else url.searchParams.delete('category');
      history.replaceState(null, '', url);
      updateCatalog();
    });
  }
  search?.addEventListener('input', updateCatalog);
  sort.addEventListener('change', updateCatalog);
  updateCatalog();
}

const carousel = document.querySelector('.about-carousel');
if (carousel) {
  const track = carousel.querySelector('.about-track');
  const dots = [...carousel.querySelectorAll('.about-dots button')];
  let current = 0;
  function goTo(index) {
    const next = (index + dots.length) % dots.length;
    track.scrollTo({ left: track.clientWidth * next, behavior: 'smooth' });
  }
  if (dots.length > 1) {
    carousel.querySelector('.about-arrow.prev').addEventListener('click', () => goTo(current - 1));
    carousel.querySelector('.about-arrow.next').addEventListener('click', () => goTo(current + 1));
    dots.forEach((dot, index) => dot.addEventListener('click', () => goTo(index)));
    track.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        goTo(current + (event.key === 'ArrowLeft' ? -1 : 1));
      }
    });
    track.addEventListener('scroll', () => {
      current = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
      dots.forEach((dot, index) => {
        dot.classList.toggle('on', index === current);
        dot.setAttribute('aria-current', String(index === current));
      });
    }, { passive: true });
  }
}

const gallery = document.querySelector('.pd-gallery');
if (gallery) {
  const mainPhoto = gallery.querySelector(':scope > img');
  const buttons = [...gallery.querySelectorAll('.pd-thumbs button')];
  for (const button of buttons) {
    button.addEventListener('click', () => {
      mainPhoto.src = button.querySelector('img').src;
      buttons.forEach((thumb) => thumb.classList.toggle('on', thumb === button));
    });
  }
}
