import Link from "next/link";
import { AboutCarousel } from "@/components/AboutCarousel";
import { serverGet } from "@/lib/api";
import type { AboutPage, ShopSettings } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("about", "/about");
}

export default async function AboutRoute() {
  const [about, s] = await Promise.all([serverGet<AboutPage>("/about"), serverGet<ShopSettings>("/settings/public")]);
  const title = about?.title || "О нас";
  const paragraphs = (about?.text || "")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return (
    <div className="container about-page">
      <div className="page-head">
        <h1>{title}</h1>
        {about?.lead && <p className="about-lead">{about.lead}</p>}
      </div>
      {about && about.photos.length > 0 && <AboutCarousel photos={about.photos} />}
      {paragraphs.length > 0 ? (
        <div className="about-text">
          {paragraphs.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      ) : (
        !about && <p className="muted">Не удалось загрузить страницу. Попробуйте обновить её чуть позже.</p>
      )}
      <div className="row about-cta">
        <Link className="btn" href="/bouquets">Смотреть букеты</Link>
        {s?.constructor_section_enabled !== false && <Link className="btn btn-ghost" href="/constructor">Собрать свой букет</Link>}
        <Link className="btn btn-ghost" href="/contacts">Контакты</Link>
      </div>
    </div>
  );
}
