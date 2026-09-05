/**
 * Block real WATI/outbound WhatsApp from the browser during E2E.
 * Fulfill send endpoints with a fake success so UI can proceed when needed.
 */
async function installWatiOutboundMocks(page, { capture = [] } = {}) {
  await page.route('**/api/whatsapp/**', async (route) => {
    const req = route.request();
    const method = req.method();
    const url = req.url();

    // Templates list — match before send heuristics (GET .../templates)
    if (method === 'GET' && /templates/i.test(url)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          templates: [
            {
              id: 'e2e-tpl-1',
              name: 'e2e_welcome',
              status: 'APPROVED',
              body: 'Hi {{1}}, welcome to {{2}}',
              custom_params: [
                { name: 'name', value: '' },
                { name: 'project', value: '' },
              ],
            },
          ],
        }),
      });
      return;
    }

    const isSend =
      method === 'POST'
      && (
        /\/send-attachment/i.test(url)
        || /\/send/i.test(url)
        || /\/brochure/i.test(url)
        || /\/pricing/i.test(url)
      );

    if (isSend) {
      let body = null;
      try {
        body = req.postDataJSON();
      } catch {
        // multipart FormData (attachments) — keep raw postData string/buffer marker
        body = req.postData() || { multipart: true };
      }
      capture.push({ url, method, body });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          mocked: true,
          message_id: `e2e-mock-${Date.now()}`,
          media_filename: /send-attachment/i.test(url) ? 'e2e-attach.pdf' : undefined,
        }),
      });
      return;
    }

    await route.continue();
  });
  return capture;
}

module.exports = { installWatiOutboundMocks };
