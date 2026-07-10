import ReactDOM from 'react-dom';

import {
  addComment,
  addReply,
  deleteComment,
  deleteReply,
  setFocusedComment,
  updateComment,
  updateReply,
} from './actions/comments';
import {
  CommentApp,
  CommentAppData,
  InitialComment,
  InitialCommentReply,
} from './main';
import { selectIsDirty } from './selectors';
import { newComment, newCommentReply } from './state/comments';
import { resetCommentAndReplyIds } from './utils/sequences';

const mention = (key: string, userId: string, label: string, start = 0) => ({
  key,
  user_id: userId,
  start,
  end: start + label.length,
  label,
});

const reply = (
  overrides: Partial<InitialCommentReply> = {},
): InitialCommentReply => ({
  pk: 11,
  user: '1',
  text: 'Original reply',
  mentions: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  deleted: false,
  ...overrides,
});

const comment = (overrides: Partial<InitialComment> = {}): InitialComment => ({
  pk: 1,
  user: '1',
  text: 'Original comment',
  mentions: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  replies: [],
  contentpath: 'body',
  position: '',
  deleted: false,
  resolved: false,
  ...overrides,
});

const data = (
  comments: InitialComment[],
  overrides: Partial<CommentAppData> = {},
): CommentAppData => ({
  comments,
  user: '1',
  authors: {
    '1': {
      name: 'Current user',
      avatar_url: '/avatar/current/',
      email: 'must-not-be-an-author@example.com',
      url: '/admin/users/1/',
    },
  },
  mentioned_users: {},
  mention_suggestions_url: '/admin/mentions/',
  ...overrides,
});

const byRemoteId = (app: CommentApp, remoteId: number | null) =>
  Array.from(app.store.getState().comments.comments.values()).find(
    (item) => item.remoteId === remoteId,
  );

beforeEach(() => {
  resetCommentAndReplyIds();
});

test('loads occurrence state and mentioned-user metadata as independent copies', () => {
  const ada = mention('ada', '7', '@Ada', 6);
  const initial = data(
    [
      comment({
        text: 'Hello @Ada',
        mentions: [ada],
        replies: [
          reply({
            text: 'Reply @Ada',
            mentions: [{ ...ada, key: 'reply-ada' }],
          }),
        ],
      }),
    ],
    { mentioned_users: { '7': { email: 'ada@example.com' } } },
  );
  const app = new CommentApp();

  app.loadData(initial);

  const loaded = byRemoteId(app, 1);
  const loadedReply = Array.from(loaded?.replies.values() || [])[0];
  expect(loaded?.mentions).toEqual([
    { key: 'ada', userId: '7', start: 6, end: 10, label: '@Ada' },
  ]);
  expect(loaded?.mentions).not.toBe(loaded?.originalMentions);
  expect(loaded?.mentions[0]).not.toBe(loaded?.originalMentions[0]);
  expect(loadedReply?.mentions).not.toBe(loadedReply?.originalMentions);
  expect(loadedReply?.mentions[0]).not.toBe(loadedReply?.originalMentions[0]);
  expect(app.store.getState().settings.mentionedUsers).toEqual({
    '7': { email: 'ada@example.com' },
  });
  expect(app.store.getState().settings.mentionedUsers).not.toBe(
    initial.mentioned_users,
  );
  expect(app.store.getState().settings.user).toEqual({
    id: '1',
    name: 'Current user',
    avatarUrl: '/avatar/current/',
  });
});

test('initial load reopens errored existing comments and replies only', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: 1,
        text: 'Rejected @Ada',
        mentions: [mention('comment-error', '7', '@Ada', 9)],
        mention_error: 'Comment mention error.',
        replies: [
          reply({
            pk: 11,
            text: 'Reply @Bea',
            mentions: [mention('reply-error', '8', '@Bea', 6)],
            mention_error: 'Reply mention error.',
          }),
          reply({ pk: 12, text: 'Unaffected reply' }),
        ],
      }),
      comment({ pk: 2, contentpath: 'summary', text: 'Unaffected comment' }),
    ]),
  );

  const errored = byRemoteId(app, 1);
  const erroredReply = Array.from(errored?.replies.values() || []).find(
    (item) => item.remoteId === 11,
  );
  const unaffectedReply = Array.from(errored?.replies.values() || []).find(
    (item) => item.remoteId === 12,
  );
  expect(errored).toMatchObject({
    mode: 'editing',
    text: 'Rejected @Ada',
    originalText: 'Rejected @Ada',
    newText: 'Rejected @Ada',
    mentionError: 'Comment mention error.',
  });
  expect(errored?.mentions).toEqual([
    {
      key: 'comment-error',
      userId: '7',
      start: 9,
      end: 13,
      label: '@Ada',
    },
  ]);
  expect(errored?.newMentions).toEqual(errored?.mentions);
  expect(errored?.newMentions).not.toBe(errored?.mentions);
  expect(erroredReply).toMatchObject({
    mode: 'editing',
    text: 'Reply @Bea',
    originalText: 'Reply @Bea',
    newText: 'Reply @Bea',
    mentionError: 'Reply mention error.',
  });
  expect(erroredReply?.newMentions).toEqual(erroredReply?.mentions);
  expect(erroredReply?.newMentions).not.toBe(erroredReply?.mentions);
  expect(unaffectedReply).toMatchObject({
    mode: 'default',
    text: 'Unaffected reply',
    newText: '',
  });
  expect(unaffectedReply?.mentionError).toBeUndefined();
  expect(byRemoteId(app, 2)).toMatchObject({
    mode: 'default',
    text: 'Unaffected comment',
    newText: '',
  });
  expect(byRemoteId(app, 2)?.mentionError).toBeUndefined();
  expect(selectIsDirty(app.store.getState())).toBe(false);
});

test('initial load retains errored null-PK comments and replies in hidden forms', () => {
  const app = new CommentApp();
  const commentsElement = document.createElement('div');
  const outputElement = document.createElement('div');
  document.body.append(commentsElement, outputElement);

  app.renderApp(
    commentsElement,
    outputElement,
    data([
      comment({
        pk: null,
        text: 'Unsaved @Ada',
        mentions: [mention('unsaved-comment', '7', '@Ada', 8)],
        mention_error: 'Unsaved comment error.',
        replies: [
          reply({
            pk: null,
            text: 'Unsaved reply @Bea',
            mentions: [mention('unsaved-reply', '8', '@Bea', 14)],
            mention_error: 'Unsaved reply error.',
          }),
        ],
      }),
    ]),
  );

  const unsaved = byRemoteId(app, null);
  const unsavedReply = Array.from(unsaved?.replies.values() || [])[0];
  expect(unsaved).toMatchObject({
    remoteId: null,
    mode: 'creating',
    text: 'Unsaved @Ada',
    originalText: 'Unsaved @Ada',
    newText: 'Unsaved @Ada',
    mentionError: 'Unsaved comment error.',
  });
  expect(unsaved?.newMentions).toEqual(unsaved?.mentions);
  expect(unsaved?.originalMentions).toEqual(unsaved?.mentions);
  expect(unsaved?.originalMentions).not.toBe(unsaved?.mentions);
  expect(unsavedReply).toMatchObject({
    remoteId: null,
    mode: 'editing',
    text: 'Unsaved reply @Bea',
    originalText: 'Unsaved reply @Bea',
    newText: 'Unsaved reply @Bea',
    mentionError: 'Unsaved reply error.',
  });
  expect(unsavedReply?.newMentions).toEqual(unsavedReply?.mentions);
  expect(unsavedReply?.originalMentions).toEqual(unsavedReply?.mentions);
  expect(unsavedReply?.originalMentions).not.toBe(unsavedReply?.mentions);
  expect(selectIsDirty(app.store.getState())).toBe(true);
  expect(
    (
      outputElement.querySelector(
        '#id_comments-TOTAL_FORMS',
      ) as HTMLInputElement
    ).value,
  ).toBe('1');
  expect(
    (outputElement.querySelector('#id_comments-0-id') as HTMLInputElement)
      .value,
  ).toBe('');
  expect(
    (outputElement.querySelector('#id_comments-0-mentions') as HTMLInputElement)
      .value,
  ).toBe(JSON.stringify([mention('unsaved-comment', '7', '@Ada', 8)]));
  expect(
    (
      outputElement.querySelector(
        '#id_comments-0-replies-0-mentions',
      ) as HTMLInputElement
    ).value,
  ).toBe(JSON.stringify([mention('unsaved-reply', '8', '@Bea', 14)]));

  ReactDOM.unmountComponentAtNode(commentsElement);
  ReactDOM.unmountComponentAtNode(outputElement);
  commentsElement.remove();
  outputElement.remove();
});

test('initial load keeps an errored null-PK comment without replies dirty', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: null,
        text: 'Unsaved @Ada',
        mentions: [mention('unsaved-comment', '7', '@Ada', 8)],
        mention_error: 'Unsaved comment error.',
      }),
    ]),
  );

  const unsaved = byRemoteId(app, null);
  expect(unsaved).toMatchObject({
    mode: 'creating',
    text: 'Unsaved @Ada',
    originalText: 'Unsaved @Ada',
    newText: 'Unsaved @Ada',
    mentionError: 'Unsaved comment error.',
    replies: new Map(),
  });
  expect(selectIsDirty(app.store.getState())).toBe(true);
});

test('success updates rebase state and clear processed removals and errors', () => {
  const app = new CommentApp();
  app.loadData(
    data([comment({ pk: 1 }), comment({ pk: 2, contentpath: 'summary' })]),
  );
  const removed = byRemoteId(app, 2);
  const kept = byRemoteId(app, 1);
  expect(removed).toBeDefined();
  expect(kept).toBeDefined();
  if (!removed || !kept) return;
  app.store.dispatch(
    setFocusedComment(kept.localId, {
      updatePinnedComment: true,
      forceFocus: true,
    }),
  );
  app.store.dispatch(updateComment(removed.localId, { deleted: true }));
  app.store.dispatch(
    updateComment(kept.localId, {
      mentionError: 'Old error',
      text: 'Submitted @Ada',
    }),
  );

  app.updateData(
    data(
      [
        comment({
          pk: 1,
          text: 'Saved @Ada',
          mentions: [mention('saved', '7', '@Ada', 6)],
        }),
      ],
      { mentioned_users: { '7': { email: 'ada@example.com' } } },
    ),
  );

  const rebased = byRemoteId(app, 1);
  expect(byRemoteId(app, 2)).toBeUndefined();
  expect(rebased).toMatchObject({
    text: 'Saved @Ada',
    originalText: 'Saved @Ada',
    mode: 'default',
  });
  expect(rebased?.mentions).toEqual(rebased?.originalMentions);
  expect(rebased?.mentions).not.toBe(rebased?.originalMentions);
  expect(rebased?.mentionError).toBeUndefined();
  expect(
    app.store
      .getState()
      .comments.comments.get(app.store.getState().comments.focusedComment || 0)
      ?.remoteId,
  ).toBe(1);
  expect(selectIsDirty(app.store.getState())).toBe(false);
});

test('rejected hydration binds numeric primary keys independent of response order', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({ pk: 1, text: 'First' }),
      comment({ pk: 2, text: 'Second', contentpath: 'summary' }),
    ]),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 2,
        text: 'Rejected second',
        mention_error: 'Second error',
      }),
      comment({ pk: 1, text: 'Rejected first', mention_error: 'First error' }),
    ]),
  );

  expect(byRemoteId(app, 1)).toMatchObject({
    text: 'Rejected first',
    newText: 'Rejected first',
    originalText: 'First',
    mentionError: 'First error',
    mode: 'editing',
  });
  expect(byRemoteId(app, 2)).toMatchObject({
    text: 'Rejected second',
    newText: 'Rejected second',
    originalText: 'Second',
    mentionError: 'Second error',
    mode: 'editing',
  });
});

test('null reply lineage follows PK-bound parents across response reordering', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({ pk: 1, text: 'First' }),
      comment({ pk: 2, text: 'Second', contentpath: 'summary' }),
    ]),
  );
  const first = byRemoteId(app, 1);
  const second = byRemoteId(app, 2);
  expect(first).toBeDefined();
  expect(second).toBeDefined();
  if (!first || !second) return;
  const firstReply = newCommentReply(101, null, 0, {
    remoteId: null,
    text: 'First local reply',
  });
  const secondReply = newCommentReply(102, null, 0, {
    remoteId: null,
    text: 'Second local reply',
  });
  app.store.dispatch(addReply(first.localId, firstReply));
  app.store.dispatch(addReply(second.localId, secondReply));
  app.captureSubmittedPositions();

  app.hydrateRejectedData(
    data([
      comment({
        pk: 2,
        contentpath: 'summary',
        text: 'Second',
        replies: [
          reply({
            pk: null,
            text: 'Rejected second reply',
            mention_error: 'Second reply error',
          }),
        ],
      }),
      comment({
        pk: 1,
        text: 'First',
        replies: [
          reply({
            pk: null,
            text: 'Rejected first reply',
            mention_error: 'First reply error',
          }),
        ],
      }),
    ]),
  );

  expect(byRemoteId(app, 1)?.replies.get(firstReply.localId)).toMatchObject({
    text: 'Rejected first reply',
    mentionError: 'First reply error',
  });
  expect(byRemoteId(app, 2)?.replies.get(secondReply.localId)).toMatchObject({
    text: 'Rejected second reply',
    mentionError: 'Second reply error',
  });
});

test('rejected hydration keeps two null comments and replies positionally isolated', () => {
  const app = new CommentApp();
  app.loadData(data([comment({ pk: 1, replies: [reply({ pk: 11 })] })]));
  const parent = byRemoteId(app, 1);
  expect(parent).toBeDefined();
  if (!parent) return;

  const localReplyA = newCommentReply(101, null, 0, {
    remoteId: null,
    text: 'Local reply A',
  });
  const localReplyB = newCommentReply(102, null, 0, {
    remoteId: null,
    text: 'Local reply B',
  });
  app.store.dispatch(addReply(parent.localId, localReplyA));
  app.store.dispatch(addReply(parent.localId, localReplyB));

  const localCommentA = newComment('a', '', 201, null, null, 0, {
    remoteId: null,
    text: 'Local comment A',
  });
  const localCommentB = newComment('b', '', 202, null, null, 0, {
    remoteId: null,
    text: 'Local comment B',
  });
  app.store.dispatch(addComment(localCommentA));
  app.store.dispatch(addComment(localCommentB));
  app.captureSubmittedPositions();

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        replies: [
          reply({ pk: 11 }),
          reply({
            pk: null,
            text: 'Rejected reply A @Ada',
            mentions: [mention('reply-a', '7', '@Ada', 17)],
            mention_error: 'Reply A error',
          }),
          reply({
            pk: null,
            text: 'Rejected reply B @Bea',
            mentions: [mention('reply-b', '8', '@Bea', 17)],
            mention_error: 'Reply B error',
          }),
        ],
      }),
      comment({
        pk: null,
        contentpath: 'a',
        text: 'Rejected comment A @Ada',
        mentions: [mention('comment-a', '7', '@Ada', 19)],
        mention_error: 'Comment A error',
      }),
      comment({
        pk: null,
        contentpath: 'b',
        text: 'Rejected comment B @Bea',
        mentions: [mention('comment-b', '8', '@Bea', 19)],
        mention_error: 'Comment B error',
      }),
    ]),
  );

  const hydratedParent = byRemoteId(app, 1);
  expect(hydratedParent?.replies.get(101)).toMatchObject({
    text: 'Rejected reply A @Ada',
    newText: 'Rejected reply A @Ada',
    mentionError: 'Reply A error',
    mode: 'editing',
  });
  expect(hydratedParent?.replies.get(102)).toMatchObject({
    text: 'Rejected reply B @Bea',
    newText: 'Rejected reply B @Bea',
    mentionError: 'Reply B error',
    mode: 'editing',
  });
  expect(app.store.getState().comments.comments.get(201)).toMatchObject({
    text: 'Rejected comment A @Ada',
    newText: 'Rejected comment A @Ada',
    mentionError: 'Comment A error',
    mode: 'creating',
  });
  expect(app.store.getState().comments.comments.get(202)).toMatchObject({
    text: 'Rejected comment B @Bea',
    newText: 'Rejected comment B @Bea',
    mentionError: 'Comment B error',
    mode: 'creating',
  });
  expect(hydratedParent?.replies.get(101)?.originalText).toBe('Local reply A');
  expect(hydratedParent?.replies.get(102)?.originalText).toBe('Local reply B');
  expect(app.store.getState().comments.comments.get(201)?.originalText).toBe(
    'Local comment A',
  );
  expect(app.store.getState().comments.comments.get(202)?.originalText).toBe(
    'Local comment B',
  );
});

test('rejected hydration does not shift null-PK state across canceled siblings', () => {
  const app = new CommentApp();
  app.loadData(data([comment({ pk: 1 })]));
  const parent = byRemoteId(app, 1);
  expect(parent).toBeDefined();
  if (!parent) return;

  const replyA = newCommentReply(101, null, 0, {
    remoteId: null,
    text: 'Local reply A',
  });
  const replyB = newCommentReply(102, null, 0, {
    remoteId: null,
    text: 'Local reply B',
  });
  app.store.dispatch(addReply(parent.localId, replyA));
  app.store.dispatch(addReply(parent.localId, replyB));

  const commentA = newComment('a', '', 201, null, null, 0, {
    remoteId: null,
    text: 'Local comment A',
  });
  const commentB = newComment('b', '', 202, null, null, 0, {
    remoteId: null,
    text: 'Local comment B',
  });
  app.store.dispatch(addComment(commentA));
  app.store.dispatch(addComment(commentB));
  app.captureSubmittedPositions();
  app.store.dispatch(deleteReply(parent.localId, replyA.localId));
  app.store.dispatch(deleteComment(commentA.localId));

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        replies: [
          reply({
            pk: null,
            text: 'Rejected reply A',
            mention_error: 'Reply A error',
          }),
          reply({
            pk: null,
            text: 'Rejected reply B',
            mention_error: 'Reply B error',
          }),
        ],
      }),
      comment({
        pk: null,
        contentpath: 'a',
        text: 'Rejected comment A',
        mention_error: 'Comment A error',
      }),
      comment({
        pk: null,
        contentpath: 'b',
        text: 'Rejected comment B',
        mention_error: 'Comment B error',
      }),
    ]),
  );

  const remainingComment = app.store
    .getState()
    .comments.comments.get(commentB.localId);
  const remainingReply = byRemoteId(app, 1)?.replies.get(replyB.localId);
  expect(remainingComment).toMatchObject({
    text: 'Rejected comment B',
    mentionError: 'Comment B error',
  });
  expect(remainingReply).toMatchObject({
    text: 'Rejected reply B',
    mentionError: 'Reply B error',
  });
  expect(app.store.getState().comments.comments.has(commentA.localId)).toBe(
    false,
  );
  expect(byRemoteId(app, 1)?.replies.has(replyA.localId)).toBe(false);
});

test('rejected hydration does not shift replaced null-PK comments or replies', () => {
  const app = new CommentApp();
  app.loadData(data([comment({ pk: 1 })]));
  const parent = byRemoteId(app, 1);
  expect(parent).toBeDefined();
  if (!parent) return;

  const replyA = newCommentReply(101, null, 0, {
    remoteId: null,
    text: 'Local reply A',
  });
  const replyB = newCommentReply(102, null, 0, {
    remoteId: null,
    text: 'Local reply B',
  });
  const commentA = newComment('a', '', 201, null, null, 0, {
    remoteId: null,
    text: 'Local comment A',
  });
  const commentB = newComment('b', '', 202, null, null, 0, {
    remoteId: null,
    text: 'Local comment B',
  });
  app.store.dispatch(addReply(parent.localId, replyA));
  app.store.dispatch(addReply(parent.localId, replyB));
  app.store.dispatch(addComment(commentA));
  app.store.dispatch(addComment(commentB));
  app.captureSubmittedPositions();

  app.store.dispatch(deleteReply(parent.localId, replyA.localId));
  app.store.dispatch(deleteComment(commentA.localId));
  const replyC = newCommentReply(103, null, 0, {
    remoteId: null,
    text: 'Replacement reply C',
  });
  const commentC = newComment('c', '', 203, null, null, 0, {
    remoteId: null,
    text: 'Replacement comment C',
  });
  app.store.dispatch(addReply(parent.localId, replyC));
  app.store.dispatch(addComment(commentC));

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        replies: [
          reply({
            pk: null,
            text: 'Rejected reply A',
            mention_error: 'Reply A error',
          }),
          reply({
            pk: null,
            text: 'Rejected reply B',
            mention_error: 'Reply B error',
          }),
        ],
      }),
      comment({
        pk: null,
        contentpath: 'a',
        text: 'Rejected comment A',
        mention_error: 'Comment A error',
      }),
      comment({
        pk: null,
        contentpath: 'b',
        text: 'Rejected comment B',
        mention_error: 'Comment B error',
      }),
    ]),
  );

  expect(app.store.getState().comments.comments.has(commentA.localId)).toBe(
    false,
  );
  expect(byRemoteId(app, 1)?.replies.has(replyA.localId)).toBe(false);
  expect(
    app.store.getState().comments.comments.get(commentB.localId),
  ).toMatchObject({
    text: 'Rejected comment B',
    mentionError: 'Comment B error',
  });
  expect(byRemoteId(app, 1)?.replies.get(replyB.localId)).toMatchObject({
    text: 'Rejected reply B',
    mentionError: 'Reply B error',
  });
  const replacementComment = app.store
    .getState()
    .comments.comments.get(commentC.localId);
  const replacementReply = byRemoteId(app, 1)?.replies.get(replyC.localId);
  expect(replacementComment).toMatchObject({
    text: 'Replacement comment C',
    originalText: 'Replacement comment C',
  });
  expect(replacementComment?.mentionError).toBeUndefined();
  expect(replacementReply).toMatchObject({
    text: 'Replacement reply C',
    originalText: 'Replacement reply C',
  });
  expect(replacementReply?.mentionError).toBeUndefined();
});

test('rejection consumes null-PK lineage before a later response', () => {
  const app = new CommentApp();
  app.loadData(data([]));
  const submitted = newComment('a', '', 101, null, null, 0, {
    remoteId: null,
    text: 'Submitted A',
  });
  app.store.dispatch(addComment(submitted));
  app.captureSubmittedPositions();

  app.hydrateRejectedData(
    data([
      comment({
        pk: null,
        text: 'Rejected A',
        mention_error: 'A error',
      }),
    ]),
  );
  expect(app.store.getState().comments.comments.get(101)).toMatchObject({
    text: 'Rejected A',
    mentionError: 'A error',
  });

  app.store.dispatch(deleteComment(submitted.localId));
  const replacement = newComment('b', '', 102, null, null, 0, {
    remoteId: null,
    text: 'Replacement B',
  });
  app.store.dispatch(addComment(replacement));
  app.hydrateRejectedData(
    data([
      comment({
        pk: null,
        text: 'Late rejected A',
        mention_error: 'Late A error',
      }),
    ]),
  );

  expect(app.store.getState().comments.comments.get(102)).toMatchObject({
    text: 'Replacement B',
    originalText: 'Replacement B',
  });
  expect(
    app.store.getState().comments.comments.get(102)?.mentionError,
  ).toBeUndefined();
});

test('successful load clears old lineage before local IDs are reused', () => {
  const app = new CommentApp();
  app.loadData(data([]));
  const submitted = newComment('a', '', 1, null, null, 0, {
    remoteId: null,
    text: 'Submitted A',
  });
  app.store.dispatch(addComment(submitted));
  app.captureSubmittedPositions();

  app.updateData(data([]));
  const replacement = newComment('b', '', 1, null, null, 0, {
    remoteId: null,
    text: 'Replacement B',
  });
  app.store.dispatch(addComment(replacement));
  const rejectedReplacement = data([
    comment({
      pk: null,
      text: 'Rejected response',
      mention_error: 'Response error',
    }),
  ]);

  app.hydrateRejectedData(rejectedReplacement);
  expect(app.store.getState().comments.comments.get(1)).toMatchObject({
    text: 'Replacement B',
    originalText: 'Replacement B',
  });
  expect(
    app.store.getState().comments.comments.get(1)?.mentionError,
  ).toBeUndefined();

  app.captureSubmittedPositions();
  app.hydrateRejectedData(rejectedReplacement);
  expect(app.store.getState().comments.comments.get(1)).toMatchObject({
    text: 'Rejected response',
    mentionError: 'Response error',
  });
});

test('error-only rejection stays clean and replaces current mention metadata', () => {
  const ada = mention('ada', '7', '@Ada', 6);
  const app = new CommentApp();
  app.loadData(
    data([comment({ text: 'Hello @Ada', mentions: [ada] })], {
      mentioned_users: { '7': { email: 'old@example.com' } },
    }),
  );

  app.hydrateRejectedData(
    data(
      [
        comment({
          text: 'Hello @Ada',
          mentions: [{ ...ada }],
          mention_error: 'Enter a valid mention list.',
        }),
      ],
      { mentioned_users: { '7': { email: 'new@example.com' } } },
    ),
  );

  expect(selectIsDirty(app.store.getState())).toBe(false);
  expect(byRemoteId(app, 1)?.mentionError).toBe('Enter a valid mention list.');
  expect(app.store.getState().settings.mentionedUsers).toEqual({
    '7': { email: 'new@example.com' },
  });

  app.hydrateRejectedData(
    data(
      [
        comment({
          text: 'Hello @Ada',
          mentions: [{ ...ada }],
          mention_error: 'Enter a valid mention list.',
        }),
      ],
      { mentioned_users: {} },
    ),
  );
  expect(app.store.getState().settings.mentionedUsers).toEqual({});
  expect(selectIsDirty(app.store.getState())).toBe(false);
});

test('rejected hydration preserves concurrent working state on no-error siblings', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({ pk: 1, text: 'Errored comment' }),
      comment({
        pk: 2,
        contentpath: 'summary',
        text: 'Sibling comment',
        replies: [reply({ pk: 22, text: 'Sibling reply' })],
      }),
    ]),
  );
  const sibling = byRemoteId(app, 2);
  const siblingReply = Array.from(sibling?.replies.values() || [])[0];
  expect(sibling).toBeDefined();
  expect(siblingReply).toBeDefined();
  if (!sibling || !siblingReply) return;
  app.store.dispatch(
    updateComment(sibling.localId, {
      mode: 'editing',
      newText: 'Concurrent comment draft @Ada',
      newMentions: [
        {
          key: 'comment-draft',
          userId: '7',
          start: 25,
          end: 29,
          label: '@Ada',
        },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(sibling.localId, siblingReply.localId, {
      mode: 'editing',
      newText: 'Concurrent reply draft @Ada',
      newMentions: [
        { key: 'reply-draft', userId: '7', start: 23, end: 27, label: '@Ada' },
      ],
    }),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        text: 'Errored comment @Ada',
        mentions: [mention('error', '7', '@Ada', 16)],
        mention_error: 'Comment error',
      }),
      comment({
        pk: 2,
        contentpath: 'summary',
        text: 'Sibling comment',
        replies: [reply({ pk: 22, text: 'Sibling reply' })],
      }),
    ]),
  );

  expect(byRemoteId(app, 1)?.mentionError).toBe('Comment error');
  expect(byRemoteId(app, 2)).toMatchObject({
    mode: 'editing',
    text: 'Sibling comment',
    newText: 'Concurrent comment draft @Ada',
    newMentions: [
      { key: 'comment-draft', userId: '7', start: 25, end: 29, label: '@Ada' },
    ],
  });
  expect(byRemoteId(app, 2)?.replies.get(siblingReply.localId)).toMatchObject({
    mode: 'editing',
    text: 'Sibling reply',
    newText: 'Concurrent reply draft @Ada',
    newMentions: [
      { key: 'reply-draft', userId: '7', start: 23, end: 27, label: '@Ada' },
    ],
  });
});

test('stale message errors preserve newer working comment and reply drafts', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: 1,
        text: 'Original comment',
        replies: [reply({ pk: 11, text: 'Original reply' })],
      }),
    ]),
  );
  const localComment = byRemoteId(app, 1);
  const localReply = Array.from(localComment?.replies.values() || [])[0];
  expect(localComment).toBeDefined();
  expect(localReply).toBeDefined();
  if (!localComment || !localReply) return;
  app.store.dispatch(
    updateComment(localComment.localId, {
      mode: 'editing',
      text: 'Submitted comment',
      mentions: [],
      newText: 'Concurrent @Ada',
      newMentions: [
        {
          key: 'comment-draft',
          userId: '7',
          start: 11,
          end: 15,
          label: '@Ada',
        },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(localComment.localId, localReply.localId, {
      mode: 'editing',
      text: 'Submitted reply',
      mentions: [],
      newText: 'Reply draft @Ada',
      newMentions: [
        { key: 'reply-draft', userId: '7', start: 12, end: 16, label: '@Ada' },
      ],
    }),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        text: 'Submitted comment',
        mention_error: 'Comment error',
        replies: [
          reply({
            pk: 11,
            text: 'Submitted reply',
            mention_error: 'Reply error',
          }),
        ],
      }),
    ]),
  );

  expect(byRemoteId(app, 1)).toMatchObject({
    mode: 'editing',
    text: 'Submitted comment',
    originalText: 'Original comment',
    newText: 'Concurrent @Ada',
    newMentions: [
      { key: 'comment-draft', userId: '7', start: 11, end: 15, label: '@Ada' },
    ],
    mentionError: 'Comment error',
  });
  expect(byRemoteId(app, 1)?.replies.get(localReply.localId)).toMatchObject({
    mode: 'editing',
    text: 'Submitted reply',
    originalText: 'Original reply',
    newText: 'Reply draft @Ada',
    newMentions: [
      { key: 'reply-draft', userId: '7', start: 12, end: 16, label: '@Ada' },
    ],
    mentionError: 'Reply error',
  });
});

test('stale errors do not replace newer locally saved comment and reply values', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: 1,
        text: 'Original comment',
        replies: [reply({ pk: 11, text: 'Original reply' })],
      }),
    ]),
  );
  const localComment = byRemoteId(app, 1);
  const localReply = Array.from(localComment?.replies.values() || [])[0];
  expect(localComment).toBeDefined();
  expect(localReply).toBeDefined();
  if (!localComment || !localReply) return;
  app.store.dispatch(
    updateComment(localComment.localId, {
      mode: 'default',
      text: 'Submitted @Ada',
      mentions: [
        {
          key: 'submitted-comment',
          userId: '7',
          start: 10,
          end: 14,
          label: '@Ada',
        },
      ],
      newText: 'Submitted @Ada',
      newMentions: [
        {
          key: 'submitted-comment',
          userId: '7',
          start: 10,
          end: 14,
          label: '@Ada',
        },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(localComment.localId, localReply.localId, {
      mode: 'default',
      text: 'Submitted reply @Ada',
      mentions: [
        {
          key: 'submitted-reply',
          userId: '7',
          start: 16,
          end: 20,
          label: '@Ada',
        },
      ],
      newText: 'Submitted reply @Ada',
      newMentions: [
        {
          key: 'submitted-reply',
          userId: '7',
          start: 16,
          end: 20,
          label: '@Ada',
        },
      ],
    }),
  );
  app.captureSubmittedPositions();

  app.store.dispatch(
    updateComment(localComment.localId, {
      mode: 'default',
      text: 'Newer @Bea',
      mentions: [
        {
          key: 'newer-comment',
          userId: '8',
          start: 6,
          end: 10,
          label: '@Bea',
        },
      ],
      newText: 'Newer @Bea',
      newMentions: [
        {
          key: 'newer-comment',
          userId: '8',
          start: 6,
          end: 10,
          label: '@Bea',
        },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(localComment.localId, localReply.localId, {
      mode: 'default',
      text: 'Newer reply @Bea',
      mentions: [
        {
          key: 'newer-reply',
          userId: '8',
          start: 12,
          end: 16,
          label: '@Bea',
        },
      ],
      newText: 'Newer reply @Bea',
      newMentions: [
        {
          key: 'newer-reply',
          userId: '8',
          start: 12,
          end: 16,
          label: '@Bea',
        },
      ],
    }),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        text: 'Submitted @Ada',
        mentions: [mention('submitted-comment', '7', '@Ada', 10)],
        mention_error: 'Old comment error',
        replies: [
          reply({
            pk: 11,
            text: 'Submitted reply @Ada',
            mentions: [mention('submitted-reply', '7', '@Ada', 16)],
            mention_error: 'Old reply error',
          }),
        ],
      }),
    ]),
  );

  expect(byRemoteId(app, 1)).toMatchObject({
    mode: 'default',
    text: 'Newer @Bea',
    originalText: 'Original comment',
    newText: 'Newer @Bea',
  });
  expect(byRemoteId(app, 1)?.mentionError).toBeUndefined();
  expect(byRemoteId(app, 1)?.replies.get(localReply.localId)).toMatchObject({
    mode: 'default',
    text: 'Newer reply @Bea',
    originalText: 'Original reply',
    newText: 'Newer reply @Bea',
  });
  expect(
    byRemoteId(app, 1)?.replies.get(localReply.localId)?.mentionError,
  ).toBeUndefined();
  expect(selectIsDirty(app.store.getState())).toBe(true);
});

test('no-error responses merge canonical content without replacing newer drafts', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: 1,
        text: 'Original comment',
        replies: [reply({ pk: 11, text: 'Original reply' })],
      }),
    ]),
  );
  const localComment = byRemoteId(app, 1);
  const localReply = Array.from(localComment?.replies.values() || [])[0];
  expect(localComment).toBeDefined();
  expect(localReply).toBeDefined();
  if (!localComment || !localReply) return;
  app.store.dispatch(
    updateComment(localComment.localId, {
      mode: 'editing',
      text: 'Submitted @Ada',
      mentions: [
        {
          key: 'submitted-comment',
          userId: '7',
          start: 10,
          end: 14,
          label: '@Ada',
        },
      ],
      newText: 'Concurrent @Bea',
      newMentions: [
        {
          key: 'comment-draft',
          userId: '8',
          start: 11,
          end: 15,
          label: '@Bea',
        },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(localComment.localId, localReply.localId, {
      mode: 'editing',
      text: 'Submitted reply @Ada',
      mentions: [
        {
          key: 'submitted-reply',
          userId: '7',
          start: 16,
          end: 20,
          label: '@Ada',
        },
      ],
      newText: 'Reply draft @Bea',
      newMentions: [
        { key: 'reply-draft', userId: '8', start: 12, end: 16, label: '@Bea' },
      ],
    }),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        text: 'Sanitized @Ada',
        mentions: [mention('sanitized-comment', '7', '@Ada', 10)],
        replies: [
          reply({
            pk: 11,
            text: 'Clean reply @Ada',
            mentions: [mention('sanitized-reply', '7', '@Ada', 12)],
          }),
        ],
      }),
    ]),
  );

  expect(byRemoteId(app, 1)).toMatchObject({
    mode: 'editing',
    text: 'Sanitized @Ada',
    originalText: 'Original comment',
    mentions: [
      {
        key: 'sanitized-comment',
        userId: '7',
        start: 10,
        end: 14,
        label: '@Ada',
      },
    ],
    newText: 'Concurrent @Bea',
    newMentions: [
      { key: 'comment-draft', userId: '8', start: 11, end: 15, label: '@Bea' },
    ],
  });
  expect(byRemoteId(app, 1)?.replies.get(localReply.localId)).toMatchObject({
    mode: 'editing',
    text: 'Clean reply @Ada',
    originalText: 'Original reply',
    mentions: [
      {
        key: 'sanitized-reply',
        userId: '7',
        start: 12,
        end: 16,
        label: '@Ada',
      },
    ],
    newText: 'Reply draft @Bea',
    newMentions: [
      { key: 'reply-draft', userId: '8', start: 12, end: 16, label: '@Bea' },
    ],
  });
});

test('rejected hydration merges sanitized no-error values for submitted messages', () => {
  const app = new CommentApp();
  app.loadData(
    data([
      comment({
        pk: 1,
        text: 'Hello @Ada',
        mentions: [mention('comment-ada', '7', '@Ada', 6)],
        replies: [
          reply({
            pk: 11,
            text: 'Reply @Ada',
            mentions: [mention('reply-ada', '7', '@Ada', 6)],
          }),
        ],
      }),
      comment({ pk: 2, contentpath: 'summary', text: 'Errored comment' }),
    ]),
  );
  const submitted = byRemoteId(app, 1);
  const submittedReply = Array.from(submitted?.replies.values() || [])[0];
  expect(submitted).toBeDefined();
  expect(submittedReply).toBeDefined();
  if (!submitted || !submittedReply) return;
  app.store.dispatch(
    updateComment(submitted.localId, {
      mode: 'default',
      text: 'Hello @Ada @Bea',
      mentions: [
        { key: 'comment-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
        { key: 'comment-bea', userId: '8', start: 11, end: 15, label: '@Bea' },
      ],
    }),
  );
  app.store.dispatch(
    updateReply(submitted.localId, submittedReply.localId, {
      mode: 'default',
      text: 'Reply @Ada @Bea',
      mentions: [
        { key: 'reply-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
        { key: 'reply-bea', userId: '8', start: 11, end: 15, label: '@Bea' },
      ],
    }),
  );

  app.hydrateRejectedData(
    data([
      comment({
        pk: 1,
        text: 'Hello @Ada @Bea',
        mentions: [mention('comment-ada', '7', '@Ada', 6)],
        replies: [
          reply({
            pk: 11,
            text: 'Reply @Ada @Bea',
            mentions: [mention('reply-ada', '7', '@Ada', 6)],
          }),
        ],
      }),
      comment({
        pk: 2,
        contentpath: 'summary',
        text: 'Errored comment @Ada',
        mentions: [mention('error', '7', '@Ada', 16)],
        mention_error: 'Comment error',
      }),
    ]),
  );

  expect(byRemoteId(app, 1)).toMatchObject({
    mode: 'default',
    text: 'Hello @Ada @Bea',
    newText: 'Hello @Ada @Bea',
    mentions: [
      { key: 'comment-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
    ],
    newMentions: [
      { key: 'comment-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
    ],
  });
  expect(byRemoteId(app, 1)?.replies.get(submittedReply.localId)).toMatchObject(
    {
      mode: 'default',
      text: 'Reply @Ada @Bea',
      newText: 'Reply @Ada @Bea',
      mentions: [
        { key: 'reply-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
      ],
      newMentions: [
        { key: 'reply-ada', userId: '7', start: 6, end: 10, label: '@Ada' },
      ],
    },
  );
});

test('rejected hydration skips missing and locally removed messages', () => {
  const app = new CommentApp();
  app.loadData(
    data([comment({ pk: 1 }), comment({ pk: 2, contentpath: 'summary' })]),
  );
  const removed = byRemoteId(app, 2);
  expect(removed).toBeDefined();
  if (!removed) return;
  app.store.dispatch(updateComment(removed.localId, { resolved: true }));

  app.hydrateRejectedData(
    data([
      comment({ pk: 2, text: 'Must not return', mention_error: 'Error' }),
      comment({ pk: 999, text: 'Missing locally', mention_error: 'Error' }),
    ]),
  );

  expect(byRemoteId(app, 2)).toMatchObject({
    text: 'Original comment',
    resolved: true,
  });
  expect(byRemoteId(app, 999)).toBeUndefined();
  expect(app.store.getState().comments.comments.size).toBe(2);
});

test('rejected unsaved comments remain in hidden form output while creating', () => {
  const app = new CommentApp();
  const commentsElement = document.createElement('div');
  const outputElement = document.createElement('div');
  document.body.append(commentsElement, outputElement);
  app.renderApp(commentsElement, outputElement, data([]));
  const local = newComment('body', '', 100, null, null, 0, {
    remoteId: null,
    mode: 'default',
    text: 'Rejected @Ada',
    mentions: [{ key: 'ada', userId: '7', start: 9, end: 13, label: '@Ada' }],
  });
  app.store.dispatch(addComment(local));
  app.captureSubmittedPositions();

  app.hydrateRejectedData(
    data([
      comment({
        pk: null,
        text: 'Rejected @Ada',
        mentions: [mention('ada', '7', '@Ada', 9)],
        mention_error: 'Enter a valid mention list.',
      }),
    ]),
  );

  expect(app.store.getState().comments.comments.get(100)?.mode).toBe(
    'creating',
  );
  expect(
    (
      outputElement.querySelector(
        'input[name="comments-0-mentions"]',
      ) as HTMLInputElement | null
    )?.value,
  ).toBe(JSON.stringify([mention('ada', '7', '@Ada', 9)]));

  app.store.dispatch(
    updateComment(local.localId, {
      newText: 'Corrected @Ada',
      newMentions: [
        { key: 'ada', userId: '7', start: 10, end: 14, label: '@Ada' },
      ],
    }),
  );
  expect(
    app.store.getState().comments.comments.get(100)?.mentionError,
  ).toBeUndefined();
  expect(
    outputElement.querySelector('input[name="comments-0-mentions"]'),
  ).not.toBeNull();

  app.captureSubmittedPositions();
  app.hydrateRejectedData(
    data([
      comment({
        pk: null,
        text: 'Rejected again @Ada',
        mentions: [mention('ada-again', '7', '@Ada', 15)],
        mention_error: 'Second mention error.',
      }),
    ]),
  );
  expect(app.store.getState().comments.comments.get(100)).toMatchObject({
    text: 'Rejected again @Ada',
    newText: 'Corrected @Ada',
    newMentions: [
      { key: 'ada', userId: '7', start: 10, end: 14, label: '@Ada' },
    ],
    mentionError: 'Second mention error.',
    mode: 'creating',
  });

  ReactDOM.unmountComponentAtNode(commentsElement);
  ReactDOM.unmountComponentAtNode(outputElement);
  commentsElement.remove();
  outputElement.remove();
});
