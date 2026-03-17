/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#060b14',
          900: '#0a0e1a',
          800: '#0f1628',
          700: '#141e38',
          600: '#1a2848',
        },
        cyan: {
          400: '#4FC3F7',
          500: '#29B6F6',
        },
        upset: '#FF8A65',
        correct: '#81C784',
        uncertain: '#CE93D8',
      },
      fontFamily: {
        display: ['"Bebas Neue"', '"Oswald"', 'system-ui', 'sans-serif'],
        headline: ['"Oswald"', 'system-ui', 'sans-serif'],
        body: ['"Space Grotesk"', '"Inter"', 'system-ui', 'sans-serif'],
        serif: ['"Libre Baskerville"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        sans: ['"Space Grotesk"', '"Inter"', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
