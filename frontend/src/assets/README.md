# assets

We don't write custom CSS — styling is Tailwind directly in the template. This directory exists only to import Tailwind and declare theme tokens.

## Do

A new token (color, spacing, font) goes in `@theme` in `main.css`:

```css
@theme {
  --color-brand: oklch(0.55 0.18 262);
}
```

That becomes usable as a `bg-brand`, `text-brand` etc. utility, usable in any template.

## Don't

Don't create a second `.css` file. Don't use `<style scoped>` in a component. If you feel the need for custom CSS, that's a sign a Tailwind utility or a token in `@theme` is missing — solve it there, not with loose CSS.

A Tailwind class is always literal and complete, in the template or the script:

```ts
// ✅
const classes = { primary: 'bg-blue-600 text-white' }

// ❌ — an interpolated string isn't detected by Tailwind's scanner
const classes = `bg-${color}-600 text-white`
```
