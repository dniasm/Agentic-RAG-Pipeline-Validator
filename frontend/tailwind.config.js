/** @type {import('tailwindcss').Config} */
// Colours are the style's tokens (src/index.css :root), so components never hard-code a hex value.
const token = (name) => `var(--${name})`;

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ground: token('ground'),
        surface: token('surface'),
        raised: token('raised'),
        active: token('active'),
        line: token('border'),
        rule: token('rule'),
        control: token('control'),
        ink: token('text'),
        muted: token('muted'),
        primary: token('primary'),
        hue: token('hue'),
        positive: token('positive'),
        negative: token('negative'),
        warning: token('warning'),
      },
      fontFamily: {
        sans: ['Geist', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        small: ['12px', '16px'],
        body: ['14px', '20px'],
        reading: ['15px', '24px'],
        section: ['16px', '24px'],
        title: ['24px', '30px'],
        kpi: ['30px', '36px'],
      },
      borderRadius: {
        card: '8px',
        control: '6px',
      },
    },
  },
  plugins: [],
};
