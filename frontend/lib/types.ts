export type ProductType = "bouquet" | "flower" | "greenery" | "packaging" | "ribbon" | "card" | "addon";

export interface Product {
  id: number;
  slug: string;
  name: string;
  /** Фото для конструктора: бутон/ветка без фона или текстура упаковки */
  constructor_image?: string | null;
  type: ProductType;
  type_label: string;
  category: string;
  species: string;
  color: string;
  color_hex: string;
  short_description: string;
  price: number; // копейки
  available: number;
  in_stock: boolean;
  image: string | null;
  is_featured: boolean;
  made_to_order: boolean;
  inventory_item_id: number;
  unit: string;
}

export interface ProductDetail extends Product {
  description: string;
  images: { url: string; alt: string }[];
  height_cm: number | null;
  photo_credit: string;
  composition?: { name: string; quantity: number }[];
}

export interface Category {
  name: string;
  count: number;
  in_stock: number;
}

export interface ShopSettings {
  shop_name: string;
  tagline: string;
  logo: string | null;
  hero_image: string | null;
  city: string;
  address: string;
  phone: string;
  email: string;
  working_hours: string;
  telegram_url: string;
  vk_url: string;
  primary_color: string;
  accent_color: string;
  background_color: string;
  florist_fee: number;
  online_reservation_minutes: number;
  pickup_ready_minutes: number;
  min_custom_stems: number;
  max_custom_stems: number;
  preorder_threshold_days: number;
  /** Заказы принимаются не дальше чем на столько дней вперёд */
  max_order_days_ahead: number;
  /** Время на сборку до доставки: интервал доступен, если его конец не раньше чем через min_lead_minutes + 30 мин */
  min_lead_minutes: number;
  /** Разделы сайта, которые владелец может выключить в настройках */
  flowers_section_enabled: boolean;
  constructor_section_enabled: boolean;
  payment_test_mode: boolean;
  online_payment_enabled?: boolean;
  allow_cash_on_delivery: boolean;
  demo_notice?: boolean;
  free_delivery_from: number | null;
  maps: { yandex_api_key: string; geocoder: string | null; center: [number, number]; shop: [number, number] };
  bots: { telegram_connected: boolean; vk_connected: boolean; simulator_enabled: boolean };
  /** Вход покупателя через ботов: какие мессенджеры доступны; test_mode — кнопка тестового подтверждения;
   *  enabled=false — владелец убрал кнопку «Войти» в настройках */
  customer_login: { telegram: boolean; vk: boolean; test_mode: boolean; enabled?: boolean };
  /** Приём заказов: false — владелец временно закрыл заказы (витрина работает), orders_closed_message — что показать */
  orders_enabled?: boolean;
  orders_closed_message?: string;
  /** Заголовки и описания страниц для поисковиков, коды подтверждения Яндекса/Google, разметка организации */
  seo?: SeoSettings;
}

export type SeoPageKey = "home" | "bouquets" | "flowers" | "constructor" | "delivery" | "about" | "contacts" | "product";
export interface SeoSettings {
  site_url: string;
  pages: Record<SeoPageKey, { title: string; description: string }>;
  yandex_verification: string;
  google_verification: string;
  organization: Record<string, unknown>;
}

/** «Частые вопросы»: блоки с вопросами. Ответ — текст с простой разметкой (см. components/Faq.tsx) */
export interface FaqBlock {
  title: string;
  items: { q: string; a: string }[];
}

export interface QuoteLine {
  item_id: number;
  name: string;
  category: string;
  quantity: number;
  unit_price: number;
  total: number;
}

export interface CartItem {
  id: number;
  type: "product" | "custom_bouquet";
  product_id?: number;
  slug?: string;
  name: string;
  product_type?: ProductType;
  quantity: number;
  unit_price: number;
  total: number;
  available?: number;
  ok: boolean;
  image?: string | null;
  composition?: QuoteLine[];
  florist_fee?: number;
  card_text?: string;
  wishes?: string;
  error?: string;
  design?: Design;
}

export interface Cart {
  token: string;
  channel: string;
  items: CartItem[];
  items_total: number;
  count: number;
  problems: string[];
}

export type Ring = [number, number][];

export interface Zone {
  id: number;
  name: string;
  description: string;
  price: number;
  free_from: number | null;
  color: string;
  polygons: Ring[];
  is_active?: boolean;
  sort_order?: number;
}

export interface ZoneShort {
  id: number;
  name: string;
  price: number;
  free_from: number | null;
  color: string;
}

export interface GeoAddress {
  address: string;
  full_address: string;
  lat: number;
  lon: number;
  house: boolean;
  precision: string;
  zone: ZoneShort | null;
  token: string | null;
}

export interface Slot {
  id: number;
  label: string;
  start: string;
  end: string;
  remaining: number;
  available: boolean;
  reason: string;
}

export interface ConstructorOptions {
  flowers: Product[];
  greenery: Product[];
  packaging: Product[];
  ribbons: Product[];
  cards: Product[];
  florist_fee: number;
  min_stems: number;
  max_stems: number;
}

export interface LayoutPoint {
  item_id: number;
  x: number; // 0..1 внутри букета
  y: number;
  r: number;
  /** цветок отражён зеркально */
  f?: boolean;
}

export interface Composition {
  flowers: { item_id: number; quantity: number }[];
  greenery: { item_id: number; quantity: number }[];
  packaging_id: number | null;
  ribbon_id: number | null;
  card_id: number | null;
  card_text: string;
  wishes: string;
  layout?: LayoutPoint[];
  /** «Букет по фото»: оформление на усмотрение флориста, эскиза нет */
  florist_choice?: boolean;
}

/** Эскиз индивидуального букета (из корзины или заказа) */
export type Design = (Partial<Composition> & { items?: { id: number; name: string; species: string; color_hex: string; type: string; constructor_image?: string | null; image?: string | null }[] }) | null;

export interface Quote {
  composition: Composition;
  lines: QuoteLine[];
  stems: number;
  materials_total: number;
  florist_fee: number;
  unit_price: number;
  quantity: number;
  total: number;
}

export interface OrderItemPublic {
  name: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  type: string;
  composition: QuoteLine[] | null;
  design?: Design;
}

export interface OrderPublic {
  number: string;
  token: string;
  created_at: string;
  source: string;
  source_label: string;
  status: string;
  status_label: string;
  payment_status: string;
  payment_status_label: string;
  payment_method: string;
  payment_method_label: string;
  fulfillment: string;
  fulfillment_label: string;
  date: string | null;
  time_from: string | null;
  time_to: string | null;
  items_total: number;
  delivery_cost: number;
  total: number;
  contact_name: string;
  contact_phone: string;
  recipient_name: string;
  comment: string;
  card_text: string;
  is_preorder: boolean;
  requires_confirmation: boolean;
  reservation_expires_at: string | null;
  cancel_reason: string;
  items: OrderItemPublic[];
  history: { status: string; label: string; at: string }[];
  payment_url: string | null;
  /** Куда приходят уведомления по заказу (покупатель вошёл через бота) */
  notify_channels?: { channel: Messenger; label: string }[];
  shop: { address: string; phone: string; working_hours: string };
  /** Покупатель просил прислать фото букета перед отправкой */
  photo_before: boolean;
  photos: { id: number; url: string; at: string }[];
  delivery?: DeliveryInfo;
  pickup?: { address: string; ready_at: string | null };
}

export interface DeliveryInfo {
  address: string;
  apartment: string;
  zone: string;
  status: string;
  status_label: string;
  lat?: number | null;
  lon?: number | null;
  /** Покупатель не знал адрес — узнаём у получателя */
  ask_recipient: boolean;
  /** Адрес ещё не вписан флористом */
  address_pending: boolean;
  /** Сюрприз: не звонить получателю заранее */
  surprise: boolean;
  /** Не говорить, от кого букет */
  anonymous: boolean;
  [k: string]: unknown;
}

export interface PaymentInfo {
  amount: number;
  status: string;
  status_label: string;
  is_test: boolean;
  provider: string;
  order_number: string;
  order_token: string;
  order_status: string;
  order_status_label: string;
  expires_at: string | null;
  shop_name: string;
}

export interface BotButton {
  text: string;
  payload: string | null;
  url: string | null;
  request_contact: boolean;
  request_location?: boolean;
}

export interface BotMessage {
  text: string;
  photo: string | null;
  buttons: BotButton[][];
}

export interface AboutPhoto {
  id: number;
  url: string;
  caption: string;
  sort_order: number;
}

export interface AboutPage {
  title: string;
  lead: string;
  text: string;
  photos: AboutPhoto[];
}

export interface AdminCategory {
  id: number;
  kind: "bouquet" | "flower";
  kind_label: string;
  name: string;
  sort_order: number;
  products: number;
}

export interface AdminCategoryList {
  categories: AdminCategory[];
  without_category: number;
}

export type CropBox = { x: number; y: number; w: number; h: number };

// ------------------------------------------------------------------ покупатель (вход через Telegram/ВК)
export type Messenger = "telegram" | "vk";

export interface CustomerChannelInfo {
  channel: Messenger;
  label: string;
  username: string;
  display_name: string;
  test: boolean;
}

export interface CustomerOrder {
  number: string;
  token: string;
  created_at: string;
  status: string;
  status_label: string;
  total: number;
  source: string;
  source_label: string;
  fulfillment: string;
  fulfillment_label: string;
  date: string;
  items: string;
}

export interface CustomerProfile {
  id: number;
  name: string;
  phone: string;
  email: string;
  channels: CustomerChannelInfo[];
  last_delivery: { address: string; apartment: string; entrance: string; floor: string; recipient_name: string } | null;
  orders: CustomerOrder[];
}

export interface LoginStart {
  code: string;
  channel: Messenger;
  link: string;
  expires_in: number;
  test_mode: boolean;
}

export type LoginStatus =
  | { status: "pending"; expires_in: number; opened: boolean }
  | { status: "confirmed"; channel: Messenger; order_token: string | null }
  | { status: "expired" | "used" | "cancelled" };
