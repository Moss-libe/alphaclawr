# alphawalk landing page email module

This repo keeps the landing page static while routing email collection through
AWS API Gateway + Lambda + DynamoDB.

Files:
- `index.html` - current landing page.
- `email-submit.js` - reusable email collection module.
- `pricing.html`, `terms.html`, `disclosures.html`, `brand/` - supporting site pages/assets.

## Future design updates

When a teammate gives you a new `index.html`, keep or add at least one email form
using either of these classes:

```html
<form class="hero-form">
  <input type="email" name="email" placeholder="you@example.com" required>
  <button type="submit">Start free</button>
</form>
```

or:

```html
<form class="hero-email-form">
  <input type="email" name="email" placeholder="you@example.com" required>
  <button type="submit">Notify me</button>
</form>
```

Then add this before `</body>`:

```html
<div id="emailSubmitToast" class="email-submit-toast" aria-live="polite"></div>
<script src="./email-submit.js"></script>
```

The API endpoint is inside `email-submit.js`:

```js
const API_URL = "https://ctxcwa79ii.execute-api.us-east-1.amazonaws.com/prod/subscribe";
```

Only change this if API Gateway changes.
