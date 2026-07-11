const { mkdir } = require('fs').promises;
const path = require('path');

const baselinePrefix = 'Mention baseline 😀\nReview with ';
const queryText = `${baselinePrefix}@adm`;
const selectedText = `${baselinePrefix}@admin@example.com`;
const insertedText = `${selectedText} `;
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const occurrenceForUser = (userId) => ({
  key: expect.stringMatching(uuidPattern),
  user_id: userId,
  start: 32,
  end: 50,
  label: '@admin@example.com',
});

const commentMentionInput =
  '#comments-output input[name^="comments-"][name$="-mentions"]:not([name*="-replies-"])';
const replyMentionInput =
  '#comments-output input[name^="comments-"][name*="-replies-"][name$="-mentions"]';

const occurrenceWithKey = (key, userId, overrides = {}) => ({
  key,
  user_id: userId,
  start: 32,
  end: 50,
  label: '@admin@example.com',
  ...overrides,
});

const getEditorText = (editorId) =>
  page.locator(`#${editorId}`).evaluate((editable) =>
    Array.from(editable.querySelectorAll('[data-block="true"]'))
      .map((block) => block.textContent)
      .join('\n'),
  );

const waitForEditorText = async (editorId, expected) => {
  await page.waitForFunction(
    ({ id, text }) => {
      const editable = document.getElementById(id);
      if (!editable) return false;
      return (
        Array.from(editable.querySelectorAll('[data-block="true"]'))
          .map((block) => block.textContent)
          .join('\n') === text
      );
    },
    { id: editorId, text: expected },
  );
};

const selectEditorRange = async (editorId, start, end) => {
  await page.evaluate(
    ({ id, rangeStart, rangeEnd }) => {
      const editable = document.getElementById(id);
      if (!editable) throw new Error(`Missing editor ${id}`);

      const blocks = Array.from(
        editable.querySelectorAll('[data-block="true"]'),
      );
      const resolveOffset = (target) => {
        let blockStart = 0;

        for (const [index, block] of blocks.entries()) {
          const blockLength = block.textContent.length;
          if (target <= blockStart + blockLength) {
            let remaining = target - blockStart;
            const walker = document.createTreeWalker(
              block,
              NodeFilter.SHOW_TEXT,
            );
            let node = walker.nextNode();
            while (node) {
              if (remaining <= node.data.length) {
                return { node, offset: remaining };
              }
              remaining -= node.data.length;
              node = walker.nextNode();
            }
            return { node: block, offset: block.childNodes.length };
          }
          blockStart += blockLength + (index === blocks.length - 1 ? 0 : 1);
        }

        throw new Error(`Offset ${target} is outside the editor`);
      };

      const from = resolveOffset(rangeStart);
      const to = resolveOffset(rangeEnd);
      const range = document.createRange();
      range.setStart(from.node, from.offset);
      range.setEnd(to.node, to.offset);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      editable.focus();
      document.dispatchEvent(new Event('selectionchange'));
    },
    { id: editorId, rangeStart: start, rangeEnd: end },
  );
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => resolve());
      }),
  );
};

const getEditorSelection = (editorId) =>
  page.evaluate((id) => {
    const editable = document.getElementById(id);
    if (!editable) throw new Error(`Missing editor ${id}`);
    const selection = window.getSelection();
    const blocks = Array.from(editable.querySelectorAll('[data-block="true"]'));

    const absoluteOffset = (node, offset) => {
      if (!node || !editable.contains(node)) return null;
      const element =
        node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      const block = element.closest('[data-block="true"]');
      const blockIndex = blocks.indexOf(block);
      if (blockIndex === -1) return null;

      const withinBlock = document.createRange();
      withinBlock.selectNodeContents(block);
      withinBlock.setEnd(node, offset);
      return (
        blocks
          .slice(0, blockIndex)
          .reduce((total, item) => total + item.textContent.length + 1, 0) +
        withinBlock.toString().length
      );
    };

    return {
      anchor: absoluteOffset(selection.anchorNode, selection.anchorOffset),
      focus: absoluteOffset(selection.focusNode, selection.focusOffset),
      collapsed: selection.isCollapsed,
      activeElementId: document.activeElement?.id || null,
    };
  }, editorId);

const getFocusedCommentWorkingValue = () =>
  page.evaluate(() => {
    const state = window.comments.commentApp.store.getState().comments;
    const comment = state.comments.get(state.focusedComment);
    if (!comment) throw new Error('No focused comment');
    return {
      text: comment.newText,
      mentions: comment.newMentions.map(
        ({ key, userId, start, end, label }) => ({
          key,
          user_id: userId,
          start,
          end,
          label,
        }),
      ),
    };
  });

const getNewReplyWorkingValue = () =>
  page.evaluate(() => {
    const state = window.comments.commentApp.store.getState().comments;
    const comment = state.comments.get(state.focusedComment);
    if (!comment) throw new Error('No focused comment');
    return {
      text: comment.newReply,
      mentions: comment.newReplyMentions.map(
        ({ key, userId, start, end, label }) => ({
          key,
          user_id: userId,
          start,
          end,
          label,
        }),
      ),
    };
  });

const expectWorkingComment = async (editorId, text, mentions) => {
  await waitForEditorText(editorId, text);
  expect(await getEditorText(editorId)).toBe(text);
  expect(await getFocusedCommentWorkingValue()).toEqual({ text, mentions });
};

const readHiddenMentions = async (selector) => {
  const input = page.locator(selector);
  await input.first().waitFor({ state: 'attached' });
  expect(await input.count()).toBe(1);
  return JSON.parse(await input.inputValue());
};

const expectHiddenComment = async (occurrences) => {
  expect(await readHiddenMentions(commentMentionInput)).toEqual(occurrences);
};

const expectHiddenReply = async (occurrences) => {
  expect(await readHiddenMentions(replyMentionInput)).toEqual(occurrences);
};

const expectMentionMarkup = async (
  scope,
  userId,
  label = '@admin@example.com',
) => {
  const mention = scope.locator('.comment__mention');
  expect(await mention.count()).toBe(1);
  expect(await mention.textContent()).toBe(label);
  expect(await mention.getAttribute('data-mention-user-id')).toBe(userId);
  expect(await mention.getAttribute('data-mention-email')).toBe(
    'admin@example.com',
  );
};

const expectNoFormatting = async (scope) => {
  expect(
    await scope.locator('b, strong, i, em, u, .Draftail-Toolbar').count(),
  ).toBe(0);
};

const openMainCommentEditor = async (card) => {
  const header = card.locator('.comment-header').first();
  await header.locator('summary[aria-label="More actions"]').click();
  await header.getByRole('menuitem', { name: 'Edit', exact: true }).click();
  const editable = card.locator(
    '[contenteditable="true"][aria-label="Edit comment"]',
  );
  await editable.waitFor({ state: 'visible' });
  return editable.getAttribute('id');
};

const saveMainCommentEditor = async (card) => {
  await card
    .locator('form')
    .first()
    .getByRole('button', { name: 'Save', exact: true })
    .click();
  await card.locator('.comment__text').first().waitFor({ state: 'visible' });
};

const restoreMainCommentBaseline = async (card, occurrence) => {
  await openMainCommentEditor(card);
  await card
    .locator('form')
    .first()
    .getByRole('button', { name: 'Cancel', exact: true })
    .click();
  const text = card.locator('.comment__text').first();
  await text.waitFor({ state: 'visible' });
  expect(await text.textContent()).toBe(selectedText);
  await expectMentionMarkup(text, occurrence.user_id);
  await expectHiddenComment([occurrence]);
};

const openReplyEditor = async (reply) => {
  const header = reply.locator('.comment-header');
  await header.locator('summary[aria-label="More actions"]').click();
  await header.getByRole('menuitem', { name: 'Edit', exact: true }).click();
  const editable = reply.locator(
    '[contenteditable="true"][aria-label="Edit reply"]',
  );
  await editable.waitFor({ state: 'visible' });
  return editable.getAttribute('id');
};

const focusPersistedComment = async () => {
  const annotation = page
    .locator('[data-annotation]:not(#comment-icon)')
    .first();
  await annotation.waitFor({ state: 'visible' });
  await annotation.click();
  const card = page.locator('#comments .comment').first();
  await card.waitFor({ state: 'visible' });
  return card;
};

const waitForStableFrame = () =>
  page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(resolve);
      });
    });
  });

jest.setTimeout(120000);

describe('Comment mentions', () => {
  it('preserves accessible plain-text mentions through browser editing and persistence', async () => {
    await page.goto(`${TEST_ORIGIN}/admin/pages/add/demosite/standardpage/2/`, {
      waitUntil: 'load',
    });

    const form = page.locator('#page-edit-form');
    await form.evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'false');
    });

    const title = `Comment mentions browser ${Date.now()}`;
    await page.fill('#id_title', title);
    await page.locator('#id_title').blur();
    await page.waitForFunction(() => {
      const slug = document.querySelector('#id_slug');
      return slug && slug.value.startsWith('comment-mentions-browser-');
    });

    const addComment = page
      .locator('[data-component="add-comment-button"]')
      .first();
    await addComment.waitFor({ state: 'visible' });
    await addComment.click();

    let commentCard = page.locator('#comments .comment').first();
    const createEditor = commentCard.locator(
      '[contenteditable="true"][aria-label="Add a comment"]',
    );
    await createEditor.waitFor({ state: 'visible' });
    const createEditorId = await createEditor.getAttribute('id');
    expect(createEditorId).toMatch(/^comment-mention-editor-\d+$/);
    expect(await commentCard.locator('[contenteditable="true"]').count()).toBe(
      1,
    );
    expect(await commentCard.locator('textarea').count()).toBe(0);
    expect(await commentCard.locator('.Draftail-Toolbar').count()).toBe(0);
    expect(
      await commentCard
        .locator(
          '[name="BOLD"], [name="ITALIC"], [name="UNDERLINE"], [data-controller~="w-draftail"], .w-field--widget-rich_text_area',
        )
        .count(),
    ).toBe(0);

    expect(await createEditor.getAttribute('aria-label')).toBe('Add a comment');
    expect(await createEditor.getAttribute('role')).toBe('textbox');
    expect(await createEditor.getAttribute('aria-multiline')).toBe('true');
    expect(await createEditor.getAttribute('aria-autocomplete')).toBe('list');
    expect(await createEditor.getAttribute('aria-haspopup')).toBe('listbox');
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    expect(await createEditor.getAttribute('data-focus-target')).toBe('true');
    const descriptionId = await createEditor.getAttribute('aria-describedby');
    expect(descriptionId).toMatch(/^comment-description-\d+$/);
    expect(await page.locator(`#${descriptionId}`).count()).toBe(1);

    await createEditor.click();
    await page.keyboard.type('Mention baseline ');
    await page.keyboard.insertText('😀');
    await page.keyboard.press('Enter');
    await page.keyboard.type('Review with ');
    await expectWorkingComment(createEditorId, baselinePrefix, []);

    let releaseSuggestionResponse;
    const suggestionRelease = new Promise((resolve) => {
      releaseSuggestionResponse = resolve;
    });
    let markSuggestionHeld;
    const suggestionHeld = new Promise((resolve) => {
      markSuggestionHeld = resolve;
    });
    let createSuggestionUrl;
    let createSuggestionResults;
    await page.route(
      '**/comment-mention-suggestions/**',
      async (route) => {
        createSuggestionUrl = route.request().url();
        const response = await route.fetch();
        createSuggestionResults = (await response.json()).results;
        markSuggestionHeld();
        await suggestionRelease;
        await route.fulfill({ response });
      },
      { times: 1 },
    );

    await page.keyboard.type('@adm');
    await suggestionHeld;
    const createInput = commentCard.locator('.comment__mention-input');
    await createInput
      .locator('.comment__mention-status--loading')
      .waitFor({ state: 'visible' });
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    await expect(page).toPassAxeTests({
      include: '.comment--mode-creating .comment__mention-input',
    });

    const createSuggestion = new URL(createSuggestionUrl);
    expect(createSuggestion.pathname).toBe(
      '/admin/pages/add/demosite/standardpage/2/comment-mention-suggestions/',
    );
    expect(createSuggestion.searchParams.get('q')).toBe('adm');
    const adminSuggestion = createSuggestionResults.find(
      (suggestion) => suggestion.username === 'admin',
    );
    expect(adminSuggestion).toMatchObject({
      label: '@admin@example.com',
      email: 'admin@example.com',
      username: 'admin',
    });
    expect(typeof adminSuggestion.id).toBe('string');
    expect(adminSuggestion.id.length).toBeGreaterThan(0);
    const capturedUserId = adminSuggestion.id;
    const expectedOccurrence = occurrenceForUser(capturedUserId);
    releaseSuggestionResponse();

    const listbox = commentCard.locator('[role="listbox"]');
    await listbox.waitFor({ state: 'visible' });
    const firstOption = listbox.locator('[role="option"]').first();
    expect(await firstOption.textContent()).toContain('@admin@example.com');
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    const listboxId = await createEditor.getAttribute('aria-controls');
    const activeOptionId = await createEditor.getAttribute(
      'aria-activedescendant',
    );
    expect(listboxId).toBe(`${createEditorId}-suggestions`);
    expect(activeOptionId).toBe(`${createEditorId}-suggestion-0`);
    expect(await page.locator(`#${listboxId}`).getAttribute('role')).toBe(
      'listbox',
    );
    expect(await page.locator(`#${listboxId}`).getAttribute('aria-label')).toBe(
      'Mention suggestions',
    );
    expect(await page.locator(`#${activeOptionId}`).getAttribute('role')).toBe(
      'option',
    );
    expect(
      await page.locator(`#${activeOptionId}`).getAttribute('aria-selected'),
    ).toBe('true');
    await expect(page).toPassAxeTests({
      include: '.comment--mode-creating .comment__mention-input',
    });

    await page.keyboard.press('Escape');
    await page.waitForFunction(
      (id) =>
        !document.getElementById(id)?.hasAttribute('aria-controls') &&
        !document.getElementById(id)?.hasAttribute('aria-activedescendant'),
      createEditorId,
    );
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    expect(await listbox.count()).toBe(0);
    expect(await createEditor.getAttribute('aria-controls')).toBeNull();
    expect(await createEditor.getAttribute('aria-activedescendant')).toBeNull();
    await expect(page).toPassAxeTests({
      include: '.comment--mode-creating .comment__mention-input',
    });

    const noMatchQuery = '@no-such-wagtail-user-987654321';
    await selectEditorRange(createEditorId, 32, queryText.length);
    await page.keyboard.type(noMatchQuery);
    await createInput
      .locator('.comment__mention-status--empty')
      .waitFor({ state: 'visible' });
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    expect(await listbox.count()).toBe(0);
    await expect(page).toPassAxeTests({
      include: '.comment--mode-creating .comment__mention-input',
    });

    await selectEditorRange(
      createEditorId,
      32,
      baselinePrefix.length + noMatchQuery.length,
    );
    await page.keyboard.type('@adm');
    await listbox.waitFor({ state: 'visible' });
    const createCommentButton = commentCard
      .locator('form')
      .first()
      .getByRole('button', { name: 'Comment', exact: true });
    const createCommentButtonHandle = await createCommentButton.elementHandle();
    expect(createCommentButtonHandle).not.toBeNull();
    await page.keyboard.press('Tab');
    await page.waitForFunction(
      (button) => document.activeElement === button,
      createCommentButtonHandle,
    );
    expect(
      await createCommentButton.evaluate(
        (button) => document.activeElement === button,
      ),
    ).toBe(true);
    await listbox.waitFor({ state: 'detached' });
    await page.waitForFunction(
      (id) =>
        !document.getElementById(id)?.hasAttribute('aria-controls') &&
        !document.getElementById(id)?.hasAttribute('aria-activedescendant'),
      createEditorId,
    );
    expect(await createEditor.getAttribute('aria-expanded')).toBeNull();
    expect(await createEditor.getAttribute('aria-controls')).toBeNull();
    expect(await createEditor.getAttribute('aria-activedescendant')).toBeNull();
    expect(await listbox.count()).toBe(0);

    await page.waitForFunction(
      () =>
        window.comments.commentApp.store.getState().comments.focusedComment ===
        null,
    );
    await createEditor.click();
    await page.waitForFunction(
      () =>
        window.comments.commentApp.store.getState().comments.focusedComment !==
        null,
    );

    await selectEditorRange(
      createEditorId,
      queryText.length - 1,
      queryText.length,
    );
    await page.keyboard.press('Backspace');
    await page.keyboard.type('m');
    await expectWorkingComment(createEditorId, queryText, []);
    await listbox.waitFor({ state: 'visible' });
    await page.keyboard.press('Enter');

    const inserted = await getFocusedCommentWorkingValue();
    expect(inserted.text).toBe(insertedText);
    expect(inserted.mentions).toEqual([expectedOccurrence]);
    const occurrenceKey = inserted.mentions[0].key;
    const persistedOccurrence = occurrenceWithKey(
      occurrenceKey,
      capturedUserId,
    );
    await expectWorkingComment(createEditorId, insertedText, [
      persistedOccurrence,
    ]);
    await expectMentionMarkup(createEditor, capturedUserId);

    await page.keyboard.press('ControlOrMeta+Z');
    await expectWorkingComment(createEditorId, queryText, []);
    expect(await createEditor.locator('.comment__mention').count()).toBe(0);
    await page.keyboard.press('ControlOrMeta+Shift+Z');
    await expectWorkingComment(createEditorId, insertedText, [
      persistedOccurrence,
    ]);
    await expectMentionMarkup(createEditor, capturedUserId);

    const redoSelection = await getEditorSelection(createEditorId);
    expect(await getFocusedCommentWorkingValue()).toEqual({
      text: insertedText,
      mentions: [persistedOccurrence],
    });
    if (
      !redoSelection.collapsed ||
      redoSelection.anchor !== insertedText.length ||
      redoSelection.focus !== insertedText.length
    ) {
      await selectEditorRange(
        createEditorId,
        insertedText.length,
        insertedText.length,
      );
    }
    const beforeBackspace = {
      value: await getFocusedCommentWorkingValue(),
      selection: await getEditorSelection(createEditorId),
    };
    await page.keyboard.press('Backspace');
    await page.evaluate(
      () =>
        new Promise((resolve) => {
          requestAnimationFrame(() => resolve());
        }),
    );
    const afterBackspace = {
      value: await getFocusedCommentWorkingValue(),
      selection: await getEditorSelection(createEditorId),
    };
    expect({ beforeBackspace, afterBackspace }).toEqual({
      beforeBackspace: {
        value: { text: insertedText, mentions: [persistedOccurrence] },
        selection: {
          anchor: insertedText.length,
          focus: insertedText.length,
          collapsed: true,
          activeElementId: createEditorId,
        },
      },
      afterBackspace: {
        value: { text: selectedText, mentions: [persistedOccurrence] },
        selection: {
          anchor: selectedText.length,
          focus: selectedText.length,
          collapsed: true,
          activeElementId: createEditorId,
        },
      },
    });
    await expectWorkingComment(createEditorId, selectedText, [
      persistedOccurrence,
    ]);
    await commentCard
      .locator('form')
      .first()
      .getByRole('button', { name: 'Comment', exact: true })
      .click();
    const savedCommentText = commentCard.locator('.comment__text').first();
    await savedCommentText.waitFor({ state: 'visible' });
    expect(await savedCommentText.textContent()).toBe(selectedText);
    await expectHiddenComment([persistedOccurrence]);

    await page.evaluate(() => {
      const formElement = document.querySelector('#page-edit-form');
      const events = {};
      events.hydrate = new Promise((resolve) => {
        formElement.addEventListener(
          'w-autosave:hydrate',
          (event) => resolve({ url: event.detail.url }),
          { once: true },
        );
      });
      events.success = new Promise((resolve) => {
        formElement.addEventListener(
          'w-autosave:success',
          (event) => resolve({ response: event.detail.response }),
          { once: true },
        );
      });
      window.commentMentionsTask13Events = events;
    });
    const createPath = '/admin/pages/add/demosite/standardpage/2/';
    const createResponsePromise = page.waitForResponse((response) => {
      const request = response.request();
      return (
        request.method() === 'POST' &&
        new URL(request.url()).pathname === createPath
      );
    });
    const hydrateRequestPromise = page
      .waitForRequest(
        (request) =>
          new URL(request.url()).searchParams.get('_w_hydrate_create_view') ===
          '1',
      )
      .catch(() => null);

    await form.evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'true');
    });
    await page.evaluate(
      () =>
        new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        }),
    );
    await expectHiddenComment([persistedOccurrence]);
    await form.evaluate((element) => {
      element.dispatchEvent(
        new CustomEvent('w-unsaved:add', {
          bubbles: true,
          detail: { type: 'edits' },
        }),
      );
    });

    const createResponse = await createResponsePromise;
    const createResponseJson = await createResponse.json();
    expect({ ok: createResponse.ok(), response: createResponseJson }).toEqual({
      ok: true,
      response: expect.objectContaining({ success: true }),
    });
    expect(createResponseJson.success).toBe(true);
    expect(createResponseJson.comments.comments[0].mentions).toEqual([
      persistedOccurrence,
    ]);
    const hydrateEvent = await page.evaluate(
      () => window.commentMentionsTask13Events.hydrate,
    );
    const hydrateRequest = await hydrateRequestPromise;
    const successEvent = await page.evaluate(
      () => window.commentMentionsTask13Events.success,
    );
    expect(successEvent.response.url).toBe(createResponseJson.url);
    expect(hydrateEvent.url).toBe(createResponseJson.hydrate_url);

    const editUrl = new URL(createResponseJson.url, TEST_ORIGIN).href;
    const hydrateUrl = new URL(createResponseJson.hydrate_url, TEST_ORIGIN)
      .href;
    const expectedEditSuggestionUrl = new URL(
      'comment-mention-suggestions/?q=adm',
      editUrl,
    ).href;
    expect(hydrateRequest).not.toBeNull();
    expect(hydrateRequest.url()).toBe(hydrateUrl);
    await page.waitForFunction(
      (expected) =>
        document.querySelector('#page-edit-form').action === expected &&
        window.location.href === expected,
      editUrl,
    );
    expect(await form.getAttribute('action')).toBe(createResponseJson.url);
    expect(page.url()).toBe(editUrl);

    await form.evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'false');
    });
    commentCard = page.locator('#comments .comment').first();
    const hydratedCommentText = commentCard.locator('.comment__text').first();
    await hydratedCommentText.waitFor({ state: 'visible' });
    expect(await hydratedCommentText.textContent()).toBe(selectedText);
    await expectMentionMarkup(hydratedCommentText, capturedUserId);
    await expectHiddenComment([persistedOccurrence]);
    const postHydrationEditorId = await openMainCommentEditor(commentCard);
    const editSuggestionRequestPromise = page.waitForRequest(
      (request) => request.url() === expectedEditSuggestionUrl,
    );
    await selectEditorRange(
      postHydrationEditorId,
      selectedText.length,
      selectedText.length,
    );
    await page.keyboard.type(' @adm');
    const editSuggestionRequest = await editSuggestionRequestPromise;
    expect(editSuggestionRequest.url()).toBe(expectedEditSuggestionUrl);
    const postHydrationEditor = page.locator(`#${postHydrationEditorId}`);
    const postHydrationListbox = commentCard.locator('[role="listbox"]');
    await postHydrationListbox.waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    await postHydrationListbox.waitFor({ state: 'detached' });
    await page.waitForFunction(
      (id) =>
        !document.getElementById(id)?.hasAttribute('aria-controls') &&
        !document.getElementById(id)?.hasAttribute('aria-activedescendant'),
      postHydrationEditorId,
    );
    expect(await postHydrationEditor.getAttribute('aria-controls')).toBeNull();
    expect(
      await postHydrationEditor.getAttribute('aria-activedescendant'),
    ).toBeNull();
    await commentCard
      .locator('form')
      .first()
      .getByRole('button', { name: 'Cancel', exact: true })
      .click();

    await page.reload({ waitUntil: 'load' });
    commentCard = await focusPersistedComment();
    await page.locator('#page-edit-form').evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'false');
    });
    expect(
      await commentCard.locator('.comment__text').first().textContent(),
    ).toBe(selectedText);
    await expectMentionMarkup(
      commentCard.locator('.comment__text').first(),
      capturedUserId,
    );
    await expectHiddenComment([persistedOccurrence]);

    let editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await selectEditorRange(editorId, 32, 32);
    await page.keyboard.type('X');
    const beforeText = `${baselinePrefix}X@admin@example.com`;
    const beforeOccurrence = occurrenceWithKey(occurrenceKey, capturedUserId, {
      start: 33,
      end: 51,
    });
    await expectWorkingComment(editorId, beforeText, [beforeOccurrence]);
    await saveMainCommentEditor(commentCard);
    expect(
      await commentCard.locator('.comment__text').first().textContent(),
    ).toBe(beforeText);
    await expectHiddenComment([beforeOccurrence]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await selectEditorRange(editorId, 50, 50);
    await page.keyboard.type('!');
    const afterText = `${selectedText}!`;
    await expectWorkingComment(editorId, afterText, [persistedOccurrence]);
    await saveMainCommentEditor(commentCard);
    expect(
      await commentCard.locator('.comment__text').first().textContent(),
    ).toBe(afterText);
    await expectHiddenComment([persistedOccurrence]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await selectEditorRange(editorId, 33, 38);
    await page.keyboard.type('owner');
    const partialReplacementText = `${baselinePrefix}@owner@example.com`;
    await expectWorkingComment(editorId, partialReplacementText, []);
    expect(await page.locator(`#${editorId} .comment__mention`).count()).toBe(
      0,
    );
    await page.keyboard.press('ControlOrMeta+Z');
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await expectMentionMarkup(page.locator(`#${editorId}`), capturedUserId);
    await page.keyboard.press('ControlOrMeta+Shift+Z');
    await expectWorkingComment(editorId, partialReplacementText, []);
    expect(await page.locator(`#${editorId} .comment__mention`).count()).toBe(
      0,
    );
    await saveMainCommentEditor(commentCard);
    const savedPartialReplacement = commentCard
      .locator('.comment__text')
      .first();
    expect(await savedPartialReplacement.textContent()).toBe(
      partialReplacementText,
    );
    expect(
      await savedPartialReplacement.locator('.comment__mention').count(),
    ).toBe(0);
    await expectHiddenComment([]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await selectEditorRange(editorId, 32, 50);
    await page.keyboard.type('@reviewer@example.com');
    const wholeReplacementText = `${baselinePrefix}@reviewer@example.com`;
    await expectWorkingComment(editorId, wholeReplacementText, []);
    expect(await page.locator(`#${editorId} .comment__mention`).count()).toBe(
      0,
    );
    await saveMainCommentEditor(commentCard);
    const savedWholeReplacement = commentCard.locator('.comment__text').first();
    expect(await savedWholeReplacement.textContent()).toBe(
      wholeReplacementText,
    );
    expect(
      await savedWholeReplacement.locator('.comment__mention').count(),
    ).toBe(0);
    await expectHiddenComment([]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    await page
      .context()
      .grantPermissions(['clipboard-read', 'clipboard-write'], {
        origin: TEST_ORIGIN,
      });
    editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await page.evaluate(async () => {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/plain': new Blob([' pasted plain'], { type: 'text/plain' }),
          'text/html': new Blob([' <strong>pasted</strong> <em>plain</em>'], {
            type: 'text/html',
          }),
        }),
      ]);
    });
    await selectEditorRange(editorId, 50, 50);
    await page.keyboard.press('ControlOrMeta+V');
    const pastedText = `${selectedText} pasted plain`;
    await expectWorkingComment(editorId, pastedText, [persistedOccurrence]);
    await expectNoFormatting(page.locator(`#${editorId}`));
    await saveMainCommentEditor(commentCard);
    expect(
      await commentCard.locator('.comment__text').first().textContent(),
    ).toBe(pastedText);
    await expectHiddenComment([persistedOccurrence]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    editorId = await openMainCommentEditor(commentCard);
    await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
    await selectEditorRange(editorId, 50, 50);
    await page.keyboard.press('ControlOrMeta+B');
    await page.keyboard.press('ControlOrMeta+I');
    await page.keyboard.press('ControlOrMeta+U');
    await page.keyboard.type('!');
    await expectWorkingComment(editorId, afterText, [persistedOccurrence]);
    await expectNoFormatting(page.locator(`#${editorId}`));
    await saveMainCommentEditor(commentCard);
    await expectHiddenComment([persistedOccurrence]);
    await restoreMainCommentBaseline(commentCard, persistedOccurrence);

    await commentCard.click();
    const newReplyEditor = commentCard.locator(
      '[contenteditable="true"][aria-label="Add a reply"]',
    );
    await newReplyEditor.waitFor({ state: 'visible' });
    const newReplyEditorId = await newReplyEditor.getAttribute('id');
    const replyPrefix = 'Reply with ';
    const replyQueryText = `${replyPrefix}@adm`;
    const replySelectedText = `${replyPrefix}@admin@example.com`;
    await newReplyEditor.click();
    await page.keyboard.type(replyQueryText);
    const replyListbox = commentCard.locator('[role="listbox"]');
    await replyListbox.waitFor({ state: 'visible' });
    await replyListbox.locator('[role="option"]').first().click();
    await waitForEditorText(newReplyEditorId, `${replySelectedText} `);
    await page.keyboard.press('Backspace');
    await waitForEditorText(newReplyEditorId, replySelectedText);
    const replyWorking = await getNewReplyWorkingValue();
    expect(replyWorking.text).toBe(replySelectedText);
    expect(replyWorking.mentions).toEqual([
      {
        ...expectedOccurrence,
        start: replyPrefix.length,
        end: replySelectedText.length,
      },
    ]);
    const replyOccurrence = {
      ...replyWorking.mentions[0],
      key: replyWorking.mentions[0].key,
    };
    await commentCard
      .locator('form')
      .last()
      .getByRole('button', { name: 'Reply', exact: true })
      .click();
    let reply = commentCard.locator('.comment-reply').first();
    await reply.waitFor({ state: 'visible' });
    expect(await reply.locator('.comment__text').textContent()).toBe(
      replySelectedText,
    );
    await expectMentionMarkup(reply.locator('.comment__text'), capturedUserId);
    await expectHiddenReply([replyOccurrence]);

    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Save draft', exact: true }).click(),
    ]);
    commentCard = await focusPersistedComment();
    await page.locator('#page-edit-form').evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'false');
    });
    await expectHiddenComment([persistedOccurrence]);
    await expectMentionMarkup(
      commentCard.locator('.comment__text').first(),
      capturedUserId,
    );
    reply = commentCard.locator('.comment-reply').first();
    await reply.waitFor({ state: 'visible' });
    expect(await reply.locator('.comment__text').textContent()).toBe(
      replySelectedText,
    );
    await expectMentionMarkup(reply.locator('.comment__text'), capturedUserId);
    await expectHiddenReply([replyOccurrence]);

    let replyEditorId = await openReplyEditor(reply);
    await selectEditorRange(
      replyEditorId,
      replyPrefix.length + 1,
      replyPrefix.length + 6,
    );
    await page.keyboard.type('owner');
    await waitForEditorText(replyEditorId, `${replyPrefix}@owner@example.com`);
    expect(
      await page.locator(`#${replyEditorId} .comment__mention`).count(),
    ).toBe(0);
    await reply.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(await reply.locator('.comment__text').textContent()).toBe(
      replySelectedText,
    );
    await expectMentionMarkup(reply.locator('.comment__text'), capturedUserId);
    await expectHiddenReply([replyOccurrence]);

    replyEditorId = await openReplyEditor(reply);
    await selectEditorRange(
      replyEditorId,
      replySelectedText.length,
      replySelectedText.length,
    );
    await page.keyboard.type('!');
    const savedReplyText = `${replySelectedText}!`;
    await waitForEditorText(replyEditorId, savedReplyText);
    await reply.getByRole('button', { name: 'Save', exact: true }).click();
    expect(await reply.locator('.comment__text').textContent()).toBe(
      savedReplyText,
    );
    await expectMentionMarkup(reply.locator('.comment__text'), capturedUserId);
    await expectHiddenReply([replyOccurrence]);

    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Save draft', exact: true }).click(),
    ]);
    commentCard = await focusPersistedComment();
    await page.locator('#page-edit-form').evaluate((element) => {
      element.setAttribute('data-w-autosave-active-value', 'false');
    });
    await expectHiddenComment([persistedOccurrence]);
    await expectMentionMarkup(
      commentCard.locator('.comment__text').first(),
      capturedUserId,
    );
    const persistedReply = commentCard.locator('.comment-reply').first();
    expect(await persistedReply.locator('.comment__text').textContent()).toBe(
      savedReplyText,
    );
    await expectMentionMarkup(
      persistedReply.locator('.comment__text'),
      capturedUserId,
    );
    await expectHiddenReply([replyOccurrence]);

    replyEditorId = await openReplyEditor(persistedReply);
    await selectEditorRange(
      replyEditorId,
      replyPrefix.length,
      replySelectedText.length,
    );
    await page.keyboard.type('@reviewer@example.com');
    const replyWithoutOccurrence = `${replyPrefix}@reviewer@example.com!`;
    await waitForEditorText(replyEditorId, replyWithoutOccurrence);
    expect(
      await page.locator(`#${replyEditorId} .comment__mention`).count(),
    ).toBe(0);
    await persistedReply
      .getByRole('button', { name: 'Save', exact: true })
      .click();
    expect(await persistedReply.locator('.comment__text').textContent()).toBe(
      replyWithoutOccurrence,
    );
    await expectHiddenReply([]);

    await Promise.all([
      page.waitForNavigation({ waitUntil: 'load' }),
      page.getByRole('button', { name: 'Save draft', exact: true }).click(),
    ]);
    commentCard = await focusPersistedComment();
    await expectHiddenComment([persistedOccurrence]);
    await expectMentionMarkup(
      commentCard.locator('.comment__text').first(),
      capturedUserId,
    );
    const replyAfterRemoval = commentCard.locator('.comment-reply').first();
    expect(
      await replyAfterRemoval.locator('.comment__text').textContent(),
    ).toBe(replyWithoutOccurrence);
    expect(await replyAfterRemoval.locator('.comment__mention').count()).toBe(
      0,
    );
    await expectHiddenReply([]);

    const evidenceDirectory = process.env.COMMENT_MENTIONS_EVIDENCE_DIR;
    if (evidenceDirectory) {
      expect(page.viewportSize()).toEqual({ width: 1024, height: 768 });
      await mkdir(evidenceDirectory, { recursive: true });
      editorId = await openMainCommentEditor(commentCard);
      await expectWorkingComment(editorId, selectedText, [persistedOccurrence]);
      await selectEditorRange(editorId, 32, 50);
      await page.keyboard.type('@adm');
      await commentCard
        .locator('[role="listbox"]')
        .waitFor({ state: 'visible' });
      await expectWorkingComment(editorId, queryText, []);
      await waitForStableFrame();
      await page.screenshot({
        path: path.join(evidenceDirectory, 'autocomplete-open.png'),
      });

      await page.keyboard.press('Enter');
      await waitForEditorText(editorId, insertedText);
      await page.keyboard.press('Backspace');
      const evidenceValue = await getFocusedCommentWorkingValue();
      expect(evidenceValue.text).toBe(selectedText);
      expect(evidenceValue.mentions).toEqual([expectedOccurrence]);
      await expectMentionMarkup(page.locator(`#${editorId}`), capturedUserId);
      const evidenceListbox = commentCard.locator('[role="listbox"]');
      await evidenceListbox.waitFor({ state: 'detached' });
      expect(await evidenceListbox.count()).toBe(0);
      const evidenceSuggestionStatus = commentCard.locator(
        [
          '.comment__mention-status--loading',
          '.comment__mention-status--empty',
          '.comment__mention-status--error',
        ].join(', '),
      );
      await evidenceSuggestionStatus.waitFor({ state: 'detached' });
      expect(await evidenceSuggestionStatus.count()).toBe(0);
      await waitForStableFrame();
      await page.screenshot({
        path: path.join(evidenceDirectory, 'after-redesign.png'),
      });
    }
  });
});
