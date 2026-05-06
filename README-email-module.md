# alphawalk landing page email module

Files:
- `index-modular.html` — current landing page, with email submit logic moved out.
- `email-submit.js` — reusable DynamoDB email collection module.

Upload both files to the same folder on your website.

## Future design updates

When a teammate gives you a new `index.html`, keep or add this form structure:

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
