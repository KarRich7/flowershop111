// Личные страницы (заказ, оплата, кабинет) не должны попадать в поиск
export const metadata = { robots: { index: false, follow: false } };

export default function PrivateLayout({ children }: { children: React.ReactNode }) {
  return children;
}
