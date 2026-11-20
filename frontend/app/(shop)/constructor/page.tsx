import Link from "next/link";
import { redirect } from "next/navigation";
import { ConstructorView } from "@/components/ConstructorView";
import { PhotoConstructorView } from "@/components/PhotoConstructorView";
import { serverGet } from "@/lib/api";
import type { ShopSettings } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("constructor", "/constructor");
}

export default async function ConstructorPage({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
  const photo = (await searchParams).mode === "photo";
  const s = await serverGet<ShopSettings>("/settings/public");
  if (s && !s.constructor_section_enabled) redirect("/bouquets");
  return (
    <div className="container">
      <div className="page-head cmode-head">
        <h1>Соберите букет сами</h1>
        <p className="muted lead">
          {photo
            ? "Выберите по фото цветы, бумагу и ленту — флорист сам продумает форму и соберёт букет. Цену посчитаем по сегодняшним остаткам и ценам."
            : "Перенесите цветы на букет и расставьте их как нравится. Флорист соберёт по вашему эскизу, а цену посчитаем по сегодняшним остаткам и ценам."}
        </p>
        <nav className="cmode" aria-label="Способ сборки букета">
          <Link href="/constructor" className={!photo ? "on" : ""} aria-current={!photo ? "page" : undefined} scroll={false}>
            <b>С эскизом</b>
            <span>Расставлю цветы сам</span>
          </Link>
          <Link href="/constructor?mode=photo" className={photo ? "on" : ""} aria-current={photo ? "page" : undefined} scroll={false}>
            <b>По фото</b>
            <span>Выберу цветы, бумагу и ленту — оформит флорист</span>
          </Link>
        </nav>
      </div>
      {photo ? <PhotoConstructorView /> : <ConstructorView />}
    </div>
  );
}
