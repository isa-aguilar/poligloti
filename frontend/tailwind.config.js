/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      colors: {
        ink: {
          50: "#f7f7f8",
          100: "#eeeef1",
          200: "#d6d6dc",
          300: "#b1b0ba",
          400: "#8b8a93",
          500: "#6b6a75",
          600: "#4a4953",
          700: "#33323c",
          800: "#1e1d24",
          900: "#0b0a10",
        },
        accent: {
          500: "#6b5bff",
          600: "#5a48ff",
          700: "#4434ff",
        },
      },
    },
  },
  plugins: [],
};
