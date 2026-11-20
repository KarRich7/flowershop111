// Набор линейных иконок (в духе lucide): один размер и одна толщина линии по всему интерфейсу.
import type { ReactNode } from "react";

type P = { size?: number; className?: string };

function Svg({ size = 18, className, children }: P & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden className={className}>
      {children}
    </svg>
  );
}

export const XIcon = (p: P) => <Svg size={14} {...p}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
export const MenuIcon = (p: P) => <Svg {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Svg>;
export const PlusIcon = (p: P) => <Svg size={16} {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const MinusIcon = (p: P) => <Svg size={16} {...p}><path d="M5 12h14" /></Svg>;
export const CheckIcon = (p: P) => <Svg size={16} {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Svg>;
export const ArrowRightIcon = (p: P) => <Svg size={16} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>;
export const ExternalIcon = (p: P) => <Svg size={14} {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></Svg>;
export const SearchIcon = (p: P) => <Svg {...p}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></Svg>;
export const PinIcon = (p: P) => <Svg {...p}><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0113 0C18.5 15.4 12 21 12 21z" /><circle cx="12" cy="10" r="2.4" /></Svg>;
export const LocateIcon = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2.4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></Svg>;
export const TruckIcon = (p: P) => <Svg size={14} {...p}><path d="M3 6h11v10H3zM14 10h4l3 3v3h-7" /><circle cx="7" cy="17.5" r="1.8" /><circle cx="17.5" cy="17.5" r="1.8" /></Svg>;
export const PhoneIcon = (p: P) => <Svg size={14} {...p}><rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18.5h2" /></Svg>;
export const BellIcon = (p: P) => <Svg size={14} {...p}><path d="M6 16V11a6 6 0 0112 0v5l1.5 2h-15zM10 20.5a2 2 0 004 0" /></Svg>;
export const TrashIcon = (p: P) => <Svg size={16} {...p}><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" /></Svg>;
export const FlipIcon = (p: P) => <Svg size={18} {...p}><path d="M12 3v18M9 7L3.5 17H9zM15 7l5.5 10H15z" /></Svg>;
export const RotateLeftIcon = (p: P) => <Svg size={18} {...p}><path d="M4.5 9.5A8 8 0 1 1 4 14" /><path d="M4 4.5v5h5" /></Svg>;
export const RotateRightIcon = (p: P) => <Svg size={18} {...p}><path d="M19.5 9.5A8 8 0 1 0 20 14" /><path d="M20 4.5v5h-5" /></Svg>;
export const ShuffleIcon = (p: P) => <Svg size={16} {...p}><circle cx="12" cy="12" r="2" /><circle cx="12" cy="12" r="6" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2" /></Svg>;
export const BagIcon = (p: P) => <Svg {...p}><path d="M5 8h14l-1 12H6zM9 8V6.5a3 3 0 016 0V8" /></Svg>;
export const FlowerIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="9" r="2.2" />
    <path d="M12 6.8c0-2.5 3.4-3 3.4-.3 0 1.4-1.5 2.5-3.4 2.5M14.2 9c2.5 0 3 3.4.3 3.4-1.4 0-2.5-1.5-2.5-3.4M12 11.2c0 2.5-3.4 3-3.4.3 0-1.4 1.5-2.5 3.4-2.5M9.8 9c-2.5 0-3-3.4-.3-3.4 1.4 0 2.5 1.5 2.5 3.4M12 11.5V21M12 17c-2.5 0-4-1.5-4.5-3.5 2.5 0 4 1.5 4.5 3.5z" />
  </Svg>
);
export const HandIcon = (p: P) => <Svg size={16} {...p}><path d="M9 11V5.5a1.5 1.5 0 013 0V11M12 10V4.5a1.5 1.5 0 013 0V11M15 10.5V6.5a1.5 1.5 0 013 0V14a7 7 0 01-7 7h-.5a6 6 0 01-5-2.7L3.4 15a1.6 1.6 0 012.6-1.8L9 15.5V8a1.5 1.5 0 00-3 0" /></Svg>;

export function SendIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a.993.993 0 00-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" />
    </svg>
  );
}
