/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        midnight: {
          900: "#0f172a",
          800: "#16213d",
          700: "#1f2b53",
        },
        accent: {
          500: "#3b82f6",
          400: "#60a5fa",
        },
        success: {
          400: "#4ade80",
        },
        warning: {
          400: "#fbbf24",
        },
        danger: {
          400: "#f87171",
        },
      },
      boxShadow: {
        card: "0 12px 30px -12px rgba(15, 23, 42, 0.45)",
      },
      keyframes: {
        pulseIn: {
          '0%': { transform: 'scale(0.95)', opacity: '0' },
          '60%': { transform: 'scale(1.02)', opacity: '1' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        ticker: {
          '0%': { transform: 'translateY(16px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        pulseIn: 'pulseIn 0.55s ease-out',
        ticker: 'ticker 0.35s ease-out',
      },
    },
  },
  plugins: [],
}
