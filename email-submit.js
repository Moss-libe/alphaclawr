/*
  alphawalk email collection module
  Keep this file when replacing index.html with a new design.

  Required HTML:

  <form class="hero-email-form">
    <input type="email" name="email">
    <button type="submit">...</button>
  </form>
*/

(function () {
  const API_URL = 'https://ctxcwa79ii.execute-api.us-east-1.amazonaws.com/prod/subscribe';

  const form = document.querySelector('.hero-email-form');
  if (!form) {
    console.error('Email form not found: .hero-email-form');
    return;
  }

  const emailInput = form.querySelector('input[type="email"], input[name="email"]');
  const submitBtn = form.querySelector('button[type="submit"]');

  function getToast() {
    let el = document.getElementById('emailSubmitToast');

    if (!el) {
      el = document.createElement('div');
      el.id = 'emailSubmitToast';
      el.className = 'email-submit-toast';
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }

    return el;
  }

  function showToast(message, type) {
    const el = getToast();

    const isSuccess = type === 'success';

    const title = isSuccess
      ? 'You’re on the walk.'
      : 'Submission paused';

    const icon = isSuccess
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.2 4.2L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M12 8v5M12 17h.01M10.3 4.7 2.8 18a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 4.7a2 2 0 0 0-3.4 0Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    el.className = 'email-submit-toast ' + (type || '');

    el.innerHTML =
      '<div class="email-toast-inner">' +
        '<div class="email-toast-icon">' + icon + '</div>' +
        '<div>' +
          '<p class="email-toast-title">' + title + '</p>' +
          '<p class="email-toast-message">' + message + '</p>' +
        '</div>' +
        '<button class="email-toast-close" type="button" aria-label="Close notification">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' +
        '</button>' +
      '</div>';

    const closeBtn = el.querySelector('.email-toast-close');

    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        el.classList.remove('show');
      }, { once: true });
    }

    requestAnimationFrame(function () {
      el.classList.add('show');
    });

    window.clearTimeout(showToast._timer);

    showToast._timer = window.setTimeout(function () {
      el.classList.remove('show');
    }, isSuccess ? 5200 : 6500);
  }

  function isValidEmail(email) {
    return /^[^\s@]+@([^\s@]+\.)+[^\s@]+$/.test(email);
  }

  form.addEventListener('submit', async function (event) {
    event.preventDefault();

    const email = (emailInput && emailInput.value
      ? emailInput.value
      : '')
      .trim()
      .toLowerCase();

    if (!email) {
      showToast('Please enter your email address.', 'error');
      return;
    }

    if (!isValidEmail(email)) {
      showToast('Please enter a valid email address.', 'error');
      return;
    }

    const originalHTML = submitBtn ? submitBtn.innerHTML : '';

    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.setAttribute('aria-busy', 'true');
      }

      const response = await fetch(API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email: email })
      });

      let data = {};

      const text = await response.text();

      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = { message: text };
      }

      if (response.ok) {
        showToast(
          data.message || 'Subscription successful! Thank you.',
          'success'
        );

        emailInput.value = '';
      } else {
        showToast(
          data.message || ('Server error (' + response.status + ').'),
          'error'
        );
      }
    } catch (error) {
      console.error('Fetch error:', error);

      showToast(
        'Unable to submit. Please check API Gateway, Lambda logs, and CORS.',
        'error'
      );
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.removeAttribute('aria-busy');
        submitBtn.innerHTML = originalHTML;
      }
    }
  });

  console.log('Email submit handler attached.');
})();
