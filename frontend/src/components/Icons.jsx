const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };

export const Logo = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 9v6M9 6.5v11M13 4v16M17 7.5v9M21 10.5v3" {...base} strokeWidth={2.2} />
  </svg>
);

export const UploadIcon = (p) => (
  <svg viewBox="0 0 56 56" aria-hidden="true" {...p}>
    <rect x="6" y="12" width="44" height="32" rx="7" {...base} />
    <path d="M23 22.5v11l9.5-5.5z" {...base} />
  </svg>
);

export const Arrow = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" {...base} />
  </svg>
);

export const Check = ({ size = 22, color = "var(--green)" }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
    <circle cx="12" cy="12" r="10" fill={color} />
    <path d="M7.5 12.3l3 3 6-6.3" fill="none" stroke="#000" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const Dot = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
    <circle cx="12" cy="12" r="9" fill="none" stroke="var(--hairline-strong)" strokeWidth="1.6" />
  </svg>
);

export const Play = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.5v9l7.5-4.5z" fill="currentColor" /></svg>
);

export const Pause = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z" fill="currentColor" /></svg>
);

export const Download = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="dl-icon">
    <path d="M12 4v11M7 10.5l5 5 5-5M5 19.5h14" {...base} />
  </svg>
);
