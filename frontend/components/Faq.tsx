import Link from "next/link";
import type { ReactNode } from "react";
import { jsonLd } from "@/lib/seo";
import type { FaqBlock, ShopSettings } from "@/lib/types";

/* «Частые вопросы» на главной. Вопросы и ответы владелец меняет в админке (раздел «Частые вопросы»);
 * пока не менял — сервер отдаёт стандартные, собранные из настроек магазина.
 * Раскрывается без JavaScript (<details>). Для поисковиков добавлена разметка FAQPage (schema.org).
 *
 * Разметка ответа (HTML не принимается — только безопасный текст):
 *   пустая строка — новый абзац; «- » или «• » в начале строки — пункт списка;
 *   **жирный**; [текст](/delivery), [текст](https://…), [телефон](tel:+7…) — ссылка. */

const INLINE = /\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;
const SAFE_URL = /^(\/(?!\/)|https?:\/\/|tel:|mailto:)/i;
const BULLET = /^\s*[-•]\s+/;

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    if (m[1] !== undefined) out.push(<b key={`${key}-${i++}`}>{m[1]}</b>);
    else {
      const [label, href] = [m[2], m[3]];
      if (!SAFE_URL.test(href)) out.push(label);
      else if (href.startsWith("/")) out.push(<Link key={`${key}-${i++}`} href={href}>{label}</Link>);
      else if (/^https?:/i.test(href)) out.push(<a key={`${key}-${i++}`} href={href} target="_blank" rel="noopener noreferrer">{label}</a>);
      else out.push(<a key={`${key}-${i++}`} href={href}>{label}</a>);
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Текст ответа с простой разметкой → абзацы, списки, ссылки */
export function RichText({ text }: { text: string }) {
  const paras = text.replace(/\r/g, "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  return (
    <>
      {paras.map((p, pi) => {
        const lines = p.split("\n");
        const groups: { list: boolean; lines: string[] }[] = [];
        for (const line of lines) {
          const list = BULLET.test(line);
          const g = groups[groups.length - 1];
          if (g && g.list === list) g.lines.push(list ? line.replace(BULLET, "") : line);
          else groups.push({ list, lines: [list ? line.replace(BULLET, "") : line] });
        }
        return groups.map((g, gi) =>
          g.list ? (
            <ul key={`${pi}-${gi}`}>{g.lines.map((l, li) => <li key={li}>{inline(l, `${pi}-${gi}-${li}`)}</li>)}</ul>
          ) : (
            <p key={`${pi}-${gi}`}>
              {g.lines.map((l, li) => (
                <span key={li}>{li > 0 && <br />}{inline(l, `${pi}-${gi}-${li}`)}</span>
              ))}
            </p>
          ),
        );
      })}
    </>
  );
}

/** Тот же ответ простым текстом (для разметки поисковиков) */
export function plainText(text: string): string {
  return text
    .replace(INLINE, (_m, bold, label) => bold ?? label ?? "")
    .replace(/^\s*[-•]\s+/gm, "— ")
    .replace(/\s*\n\s*/g, " ")
    .trim();
}

export function Faq({ s, blocks }: { s: ShopSettings; blocks: FaqBlock[] }) {
  const shown = blocks.filter((b) => b.items.length);
  if (!shown.length) return null;
  const titled = shown.length > 1 || !!shown[0].title;
  const schema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: shown.flatMap((b) => b.items).map((it) => ({
      "@type": "Question",
      name: it.q,
      acceptedAnswer: { "@type": "Answer", text: plainText(it.a) },
    })),
  };
  return (
    <section className="section-sm" aria-labelledby="faq-title" id="faq">
      <div className="container faq">
        <div className="faq-head">
          <h2 id="faq-title">Частые вопросы</h2>
          <p className="muted">
            Не нашли ответ?{" "}
            {s.phone ? <>Позвоните <a href={`tel:${s.phone.replace(/[^\d+]/g, "")}`}>{s.phone}</a></> : "Напишите нам"}
            {s.telegram_url || s.vk_url ? " или напишите в мессенджер" : ""} — подскажем.
          </p>
        </div>
        <div data-testid="faq">
          {shown.map((b, bi) => (
            <div key={bi} className="faq-block">
              {titled && b.title && <h3 className="faq-block-title">{b.title}</h3>}
              <div className="faq-list">
                {b.items.map((it, ii) => (
                  <details key={ii} className="faq-item">
                    <summary>{it.q}</summary>
                    <div className="faq-a"><RichText text={it.a} /></div>
                  </details>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(schema)} />
    </section>
  );
}
