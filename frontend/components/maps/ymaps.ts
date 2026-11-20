// Загрузка JS API Яндекс Карт 2.1 (один раз на страницу).
// Ключ берётся из настроек магазина (YANDEX_MAPS_API_KEY на бэкенде); без ключа карта работает в демо-режиме.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type YMaps = any;

declare global {
  interface Window {
    ymaps?: YMaps;
    __ymapsLoad?: Promise<YMaps>;
  }
}

export function loadYmaps(apikey: string): Promise<YMaps> {
  if (typeof window === "undefined") return Promise.reject(new Error("ssr"));
  if (window.__ymapsLoad) return window.__ymapsLoad;
  const p = new Promise<YMaps>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("Карта не загрузилась: нет ответа от Яндекс Карт")), 15000);
    const done = () => {
      if (!window.ymaps) return reject(new Error("Карта не загрузилась"));
      window.ymaps.ready(() => {
        clearTimeout(timer);
        resolve(window.ymaps);
      });
    };
    if (window.ymaps) return done();
    const s = document.createElement("script");
    s.src = `https://api-maps.yandex.ru/2.1/?lang=ru_RU${apikey ? `&apikey=${encodeURIComponent(apikey)}` : ""}`;
    s.async = true;
    s.onload = done;
    s.onerror = () => {
      clearTimeout(timer);
      reject(new Error("Карта не загрузилась: Яндекс Карты недоступны"));
    };
    document.head.appendChild(s);
  });
  window.__ymapsLoad = p.catch((e) => {
    window.__ymapsLoad = undefined;
    throw e;
  });
  return window.__ymapsLoad;
}

export const zoneStyle = (color: string, active = false) => ({
  fillColor: color || "#3e5b36",
  fillOpacity: active ? 0.28 : 0.16,
  strokeColor: color || "#3e5b36",
  strokeOpacity: 0.85,
  strokeWidth: active ? 3 : 2,
});
