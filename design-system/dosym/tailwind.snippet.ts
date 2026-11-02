// Палитры на CSS-переменных: тема меняет значения, классы (bg-brand-600/20) остаются.
const scale = (n: string) => Object.fromEntries([50,100,200,300,400,500,600,700,800,900,950]
  .map(s => [s, `rgb(var(--${n}-${s}) / <alpha-value>)`]));
// theme.extend.colors: { brand: scale("brand"), accent: scale("accent") }
