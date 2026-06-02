# Static assets

Card faces and the felt table are drawn entirely with CSS/SVG (see
`css/styles.css` and `js/table.js` — `cardEl`). No external image assets are
downloaded or bundled, so the UI works fully offline and has no third-party
asset licensing to track.

If you later prefer photographic cards, drop an open-license deck (e.g. a CC0
SVG set) here as `cards/<CODE>.svg` (codes like `SA`, `HT`, `DK`, `back`) and
update `cardEl` in `js/table.js` to use `<img>` tags with a CSS fallback.
