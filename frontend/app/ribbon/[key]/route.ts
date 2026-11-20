// PNG объёмной ленты для эскиза букета: /ribbon/wrap-satin-c9918f-0-v2.png
// Рендер детерминирован (components/bouquet/ribbon3d.ts), поэтому ответ кешируется навсегда.
import { deflateSync } from "node:zlib";
import { parseRibbonKey, renderRibbon } from "@/components/bouquet/ribbon3d";

export const runtime = "nodejs";

const CRC = new Int32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});
function crc32(b: Uint8Array) {
  let c = -1;
  for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
function chunk(type: string, data: Buffer) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function encodePng(rgba: Uint8ClampedArray, w: number, h: number) {
  const row = w * 4 + 1;
  const raw = Buffer.alloc(row * h);
  const src = Buffer.from(rgba.buffer, rgba.byteOffset, rgba.byteLength);
  for (let y = 0; y < h; y++) src.copy(raw, y * row + 1, y * w * 4, (y + 1) * w * 4);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // 8 бит на канал
  ihdr[9] = 6; // RGBA
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

const cache = new Map<string, Buffer>();

export async function GET(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const spec = key.endsWith(".png") ? parseRibbonKey(key.slice(0, -4)) : null;
  if (!spec) return new Response("Not found", { status: 404 });
  let png = cache.get(key);
  if (!png) {
    const r = renderRibbon(spec);
    png = encodePng(r.rgba, r.w, r.h);
    if (cache.size >= 300) cache.delete(cache.keys().next().value as string);
    cache.set(key, png);
  }
  return new Response(new Uint8Array(png), {
    headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=31536000, immutable" },
  });
}
