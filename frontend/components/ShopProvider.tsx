"use client";
import { createContext, useContext, type ReactNode } from "react";
import type { ShopSettings } from "@/lib/types";
import { CartProvider } from "./CartProvider";
import { CustomerProvider } from "./CustomerProvider";
import { ToastProvider } from "./Toast";

export const FALLBACK_SETTINGS: ShopSettings = {
  shop_name: "Цветы Урала",
  tagline: "Цветочный магазин",
  logo: null,
  hero_image: null,
  city: "Кондратово",
  address: "",
  phone: "",
  email: "",
  working_hours: "",
  telegram_url: "",
  vk_url: "",
  primary_color: "#3E5B36",
  accent_color: "#9C6FA0",
  background_color: "#FAF7F1",
  florist_fee: 30000,
  online_reservation_minutes: 15,
  pickup_ready_minutes: 60,
  min_custom_stems: 3,
  max_custom_stems: 30,
  preorder_threshold_days: 2,
  max_order_days_ahead: 30,
  min_lead_minutes: 120,
  flowers_section_enabled: true,
  constructor_section_enabled: true,
  allow_cash_on_delivery: false,
  free_delivery_from: 150000,
  maps: { yandex_api_key: "", geocoder: null, center: [57.98644, 56.11818], shop: [57.98644, 56.11818] },
  payment_test_mode: true,
  bots: { telegram_connected: false, vk_connected: false, simulator_enabled: false },
  customer_login: { telegram: false, vk: false, test_mode: false },
  orders_enabled: true,
  orders_closed_message: "",
};

const Ctx = createContext<ShopSettings>(FALLBACK_SETTINGS);
export const useShop = () => useContext(Ctx);

export function ShopProvider({ settings, children }: { settings: ShopSettings; children: ReactNode }) {
  return (
    <Ctx.Provider value={settings}>
      <ToastProvider>
        <CustomerProvider>
          <CartProvider>{children}</CartProvider>
        </CustomerProvider>
      </ToastProvider>
    </Ctx.Provider>
  );
}
