// Injected into Amazon account-switcher/sign-in pages to identify the
// currently selected Amazon account email.

(() => {
  const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function findEmailInElement(selector) {
    for (const node of document.querySelectorAll(selector)) {
      const match = cleanText(node.textContent).match(EMAIL_RE);
      if (match) return match[0];
    }
    return '';
  }

  function extractAccountEmail() {
    const email = (
      findEmailInElement('[data-test-id="switchableAccounts"] .cvf-account-switcher-claim')
      || findEmailInElement('[data-test-id="switchableAccounts"]')
      || cleanText(document.body?.innerText || '').match(EMAIL_RE)?.[0]
      || ''
    );

    const accountName = cleanText(
      document.querySelector('[data-test-id="customerName"]')?.textContent
      || document.querySelector('.cvf-account-switcher-profile-details')?.textContent
      || ''
    );

    const bodyText = cleanText(document.body?.innerText || '');
    const issue = !email && /sign in|email or mobile phone number|enter your password/i.test(bodyText)
      ? 'Amazon is asking for sign-in before the account email can be detected.'
      : '';

    return { email, accountName, issue };
  }

  return extractAccountEmail();
})();
