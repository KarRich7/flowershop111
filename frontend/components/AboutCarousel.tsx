"use client";

import { useEffect, useRef, useState } from "react";
import type { AboutPhoto } from "@/lib/types";

// Карусель фотографий: прокрутка с привязкой (scroll-snap), стрелки и точки.
// Работает и свайпом на телефоне, и колесом/тачпадом на компьютере.
export function AboutCarousel({ photos }: { photos: AboutPhoto[] }) {
  const track = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const onScroll = () => {
      const w = el.clientWidth || 1;
      setActive(Math.max(0, Math.min(photos.length - 1, Math.round(el.scrollLeft / w))));
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [photos.length]);

  const go = (i: number) => {
    const el = track.current;
    if (!el) return;
    const n = (i + photos.length) % photos.length;
    el.scrollTo({ left: n * el.clientWidth, behavior: "smooth" });
  };

  return (
    <div className="about-carousel" role="region" aria-roledescription="карусель" aria-label="Фотографии мастерской">
      <div
        className="about-track"
        ref={track}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") { e.preventDefault(); go(active + 1); }
          if (e.key === "ArrowLeft") { e.preventDefault(); go(active - 1); }
        }}
      >
        {photos.map((p, i) => (
          <figure className="about-slide" key={p.id} aria-label={`Фото ${i + 1} из ${photos.length}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={p.url} alt={p.caption || `Фото ${i + 1}`} loading={i === 0 ? "eager" : "lazy"} />
            {p.caption && <figcaption>{p.caption}</figcaption>}
          </figure>
        ))}
      </div>
      {photos.length > 1 && (
        <>
          <button type="button" className="about-arrow prev" aria-label="Предыдущее фото" onClick={() => go(active - 1)}>‹</button>
          <button type="button" className="about-arrow next" aria-label="Следующее фото" onClick={() => go(active + 1)}>›</button>
          <div className="about-dots">
            {photos.map((p, i) => (
              <button
                type="button"
                key={p.id}
                className={i === active ? "on" : ""}
                aria-label={`Показать фото ${i + 1}`}
                aria-current={i === active}
                onClick={() => go(i)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
