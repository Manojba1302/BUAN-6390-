/** One icon component, so stroke width and sizing stay consistent. */
import type { JSX } from "react";

const PATHS: Record<string, JSX.Element> = {
  logout: <><path d="M9 4H4v16h5" /><path d="M9 12h12m-4-4 4 4-4 4" /></>,
  send: <><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></>,
  history: <><path d="M3 11a9 9 0 1 1 2.6 7" /><path d="M3 4v7h7" /><path d="M12 7v5l3 2" /></>,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
  homeflow: <><path d="M3 11 12 3l9 8" /><path d="M5 10v10h5" /><path d="M19 10v10h-3" /><path d="M12 12v3c0 3 3 3 3 6" /><path d="M9 12h6" /></>,
  check: <path d="M20 6 9 17l-5-5" />,
  copy: <><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></>,
  alert: <><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>,
  info: <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>,
  spark: <><path d="M12 3v4" /><path d="M12 17v4" /><path d="M3 12h4" /><path d="M17 12h4" /><path d="m5.6 5.6 2.8 2.8" /><path d="m15.6 15.6 2.8 2.8" /><path d="m18.4 5.6-2.8 2.8" /><path d="m8.4 15.6-2.8 2.8" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></>,
  doc: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8" /><path d="M8 17h5" /></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-5-5L5 21" /></>,
  upload: <><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>,
  camera: <><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z" /><circle cx="12" cy="13" r="3.5" /></>,
  x: <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  back: <path d="m15 18-6-6 6-6" />,
  plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
  trash: <><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></>,
  eye: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></>,
  home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  wallet: <><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18" /><circle cx="17" cy="15" r="1.3" /></>,
  flag: <><path d="M4 21V4" /><path d="M4 4h12l-2 4 2 4H4" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  refresh: <><path d="M21 12a9 9 0 1 1-3-6.7" /><path d="M21 3v6h-6" /></>,
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  key: <><circle cx="8" cy="15" r="4" /><path d="m10.8 12.2 8.7-8.7" /><path d="m16 7 3 3" /><path d="m13.5 9.5 2 2" /></>,
  percent: <><circle cx="12" cy="12" r="9" /><path d="m8.5 15.5 7-7" /><circle cx="9" cy="9" r="1" /><circle cx="15" cy="15" r="1" /></>,
  coins: <><ellipse cx="9" cy="6" rx="6" ry="2.5" /><path d="M3 6v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V6" /><path d="M3 10v4c0 1.4 2.7 2.5 6 2.5" /><ellipse cx="15" cy="14" rx="6" ry="2.5" /><path d="M9 14v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4" /></>,
  homeDollar: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /><path d="M14 12c-.4-.7-1.1-1-2-1-1.1 0-2 .6-2 1.5 0 2 4 1.1 4 3.1 0 .9-.9 1.4-2 1.4-.9 0-1.6-.4-2-1" /><path d="M12 10v1M12 17v1" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  trend: <><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>,
  briefcase: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M3 13h18" /></>,
  laptop: <><rect x="4" y="5" width="16" height="11" rx="1.5" /><path d="M2 19h20" /></>,
};

export function Icon({ name, width = 2 }: { name: keyof typeof PATHS | string; width?: number }) {
  const body = PATHS[name] ?? PATHS.info;
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={width}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {body}
    </svg>
  );
}

/** Icon for each choice card, keyed by its label (values such as "Other" repeat across questions). */
export const CHOICE_ICON: Record<string, string> = {
  "Buy a home": "key", "Lower my rate": "percent", "Take cash out": "coins", "Home equity line": "homeDollar",
  "I will live here": "home", "Second home": "sun", "Investment": "trend",
  Employed: "briefcase", "Self-employed": "laptop", Retired: "user", "Not currently employed": "refresh", "Other situation": "chat",
};

export const CATEGORY_ICON: Record<string, string> = {
  paystub: "doc",
  w2: "doc",
  bank_statement: "wallet",
  drivers_license: "user",
  ssn_card: "flag",
};
