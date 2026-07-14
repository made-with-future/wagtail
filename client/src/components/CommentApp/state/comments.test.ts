import type { MentionOccurrence } from '../utils/mentions';
import { legacy_createStore as createStore } from 'redux';
import { basicCommentsState } from '../__fixtures__/state';
import * as actions from '../actions/comments';
import {
  Comment,
  CommentReply,
  CommentReplyUpdate,
  CommentUpdate,
  newComment,
  newCommentReply,
  reducer,
} from './comments';

const adaMention: MentionOccurrence = {
  key: 'mention-ada',
  userId: '7',
  start: 6,
  end: 10,
  label: '@Ada',
};

test('Initial comments state empty', () => {
  const state = createStore(reducer).getState();
  expect(state.focusedComment).toBe(null);
  expect(state.pinnedComment).toBe(null);
  expect(state.comments.size).toBe(0);
  expect(state.remoteCommentCount).toBe(0);
});

test('New comment added to state', () => {
  const commentToAdd: Comment = {
    contentpath: 'test_contentpath',
    position: '',
    localId: 5,
    annotation: null,
    remoteId: null,
    mode: 'default',
    deleted: false,
    author: { id: 1, name: 'test user' },
    date: 0,
    text: 'new comment',
    originalText: 'new comment',
    mentions: [],
    originalMentions: [],
    newMentions: [],
    newReply: '',
    newReplyMentions: [],
    newText: '',
    remoteReplyCount: 0,
    resolved: false,
    replies: new Map(),
  };
  const commentAction = actions.addComment(commentToAdd);
  const newState = reducer(basicCommentsState, commentAction);
  expect(newState.comments.get(commentToAdd.localId)).toBe(commentToAdd);
  expect(newState.remoteCommentCount).toBe(
    basicCommentsState.remoteCommentCount,
  );
});

test('Remote comment added to state', () => {
  const commentToAdd: Comment = {
    contentpath: 'test_contentpath',
    position: '',
    localId: 5,
    annotation: null,
    remoteId: 10,
    mode: 'default',
    deleted: false,
    resolved: false,
    author: { id: 1, name: 'test user' },
    date: 0,
    text: 'new comment',
    originalText: 'new comment',
    mentions: [],
    originalMentions: [],
    newMentions: [],
    newReply: '',
    newReplyMentions: [],
    newText: '',
    remoteReplyCount: 0,
    replies: new Map(),
  };
  const commentAction = actions.addComment(commentToAdd);
  const newState = reducer(basicCommentsState, commentAction);
  expect(newState.comments.get(commentToAdd.localId)).toBe(commentToAdd);
  expect(newState.remoteCommentCount).toBe(
    basicCommentsState.remoteCommentCount + 1,
  );
});

test('Existing comment updated', () => {
  const commentUpdate: CommentUpdate = {
    mode: 'editing',
  };
  const updateAction = actions.updateComment(1, commentUpdate);
  const newState = reducer(basicCommentsState, updateAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    expect(comment.mode).toBe('editing');
  }
});

test('Local comment deleted', () => {
  // Test that deleting a comment without a remoteId removes it from the state entirely
  const deleteAction = actions.deleteComment(4);
  const newState = reducer(basicCommentsState, deleteAction);
  expect(newState.comments.has(4)).toBe(false);
});

test('Local comment resolved', () => {
  // Test that resolving a comment without a remoteId removes it from the state entirely
  const resolveAction = actions.resolveComment(4);
  const newState = reducer(basicCommentsState, resolveAction);
  expect(newState.comments.has(4)).toBe(false);
});

test('Remote comment deleted', () => {
  // Test that deleting a comment without a remoteId does not remove it from the state, but marks it as deleted
  const deleteAction = actions.deleteComment(1);
  const newState = reducer(basicCommentsState, deleteAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    expect(comment.deleted).toBe(true);
  }
  expect(newState.focusedComment).toBe(null);
  expect(newState.pinnedComment).toBe(null);
  expect(newState.remoteCommentCount).toBe(
    basicCommentsState.remoteCommentCount,
  );
});

test('Remote comment resolved', () => {
  // Test that resolving a comment without a remoteId does not remove it from the state, but marks it as resolved
  const resolveAction = actions.resolveComment(1);
  const newState = reducer(basicCommentsState, resolveAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    expect(comment.resolved).toBe(true);
  }
  expect(newState.focusedComment).toBe(null);
  expect(newState.pinnedComment).toBe(null);
  expect(newState.remoteCommentCount).toBe(
    basicCommentsState.remoteCommentCount,
  );
});

test('Comment focused', () => {
  const focusAction = actions.setFocusedComment(4, {
    updatePinnedComment: true,
    forceFocus: true,
  });
  const newState = reducer(basicCommentsState, focusAction);
  expect(newState.focusedComment).toBe(4);
  expect(newState.pinnedComment).toBe(4);
  expect(newState.forceFocus).toBe(true);
});

test('Invalid comment not focused', () => {
  const focusAction = actions.setFocusedComment(9000, {
    updatePinnedComment: true,
    forceFocus: true,
  });
  const newState = reducer(basicCommentsState, focusAction);
  expect(newState.focusedComment).toBe(basicCommentsState.focusedComment);
  expect(newState.pinnedComment).toBe(basicCommentsState.pinnedComment);
  expect(newState.forceFocus).toBe(false);
});

test('Reply added', () => {
  const reply: CommentReply = {
    localId: 10,
    remoteId: null,
    mode: 'default',
    author: { id: 1, name: 'test user' },
    date: 0,
    text: 'a new reply',
    originalText: 'a new reply',
    newText: '',
    mentions: [],
    originalMentions: [],
    newMentions: [],
    deleted: false,
  };
  const addAction = actions.addReply(1, reply);
  const newState = reducer(basicCommentsState, addAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    const stateReply = comment.replies.get(10);
    expect(stateReply).toBeDefined();
    if (stateReply) {
      expect(stateReply).toBe(reply);
    }
  }
});

test('Remote reply added', () => {
  const reply: CommentReply = {
    localId: 10,
    remoteId: 1,
    mode: 'default',
    author: { id: 1, name: 'test user' },
    date: 0,
    text: 'a new reply',
    originalText: 'a new reply',
    newText: '',
    mentions: [],
    originalMentions: [],
    newMentions: [],
    deleted: false,
  };
  const addAction = actions.addReply(1, reply);
  const newState = reducer(basicCommentsState, addAction);
  const originalComment = basicCommentsState.comments.get(1);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    const stateReply = comment.replies.get(reply.localId);
    expect(stateReply).toBeDefined();
    expect(stateReply).toBe(reply);
    if (originalComment) {
      expect(comment.remoteReplyCount).toBe(
        originalComment.remoteReplyCount + 1,
      );
    }
  }
});

test('Reply updated', () => {
  const replyUpdate: CommentReplyUpdate = {
    mode: 'editing',
  };
  const updateAction = actions.updateReply(1, 2, replyUpdate);
  const newState = reducer(basicCommentsState, updateAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    const reply = comment.replies.get(2);
    expect(reply).toBeDefined();
    if (reply) {
      expect(reply.mode).toBe('editing');
    }
  }
});

test('Local reply deleted', () => {
  // Test that the delete action deletes a reply that hasn't yet been saved to the db from the state entirely
  const deleteAction = actions.deleteReply(1, 3);
  const newState = reducer(basicCommentsState, deleteAction);
  const comment = newState.comments.get(1);
  expect(comment).toBeDefined();
  if (comment) {
    expect(comment.replies.has(3)).toBe(false);
  }
});

test('Remote reply deleted', () => {
  // Test that the delete action deletes a reply that has been saved to the db by marking it as deleted instead
  const deleteAction = actions.deleteReply(1, 2);
  const newState = reducer(basicCommentsState, deleteAction);
  const comment = newState.comments.get(1);
  const originalComment = basicCommentsState.comments.get(1);
  expect(comment).toBeDefined();
  expect(originalComment).toBeDefined();
  if (comment && originalComment) {
    expect(comment.remoteReplyCount).toBe(originalComment.remoteReplyCount);
    const reply = comment.replies.get(2);
    expect(reply).toBeDefined();
    if (reply) {
      expect(reply.deleted).toBe(true);
    }
  }
});

test('new comments own independent copies of every mention occurrence', () => {
  const mentions = [adaMention];
  const comment = newComment('', '', 10, null, null, 0, { mentions });

  expect(comment.mentions).toEqual(mentions);
  expect(comment.originalMentions).toEqual(mentions);
  expect(comment.newMentions).toEqual([]);
  expect(comment.newReplyMentions).toEqual([]);
  expect(comment.mentions).not.toBe(mentions);
  expect(comment.originalMentions).not.toBe(mentions);
  expect(comment.originalMentions).not.toBe(comment.mentions);
  expect(comment.mentions[0]).not.toBe(mentions[0]);
  expect(comment.originalMentions[0]).not.toBe(comment.mentions[0]);
});

test('new replies own independent copies of every mention occurrence', () => {
  const mentions = [adaMention];
  const reply = newCommentReply(11, null, 0, { mentions });

  expect(reply.mentions).toEqual(mentions);
  expect(reply.originalMentions).toEqual(mentions);
  expect(reply.newMentions).toEqual([]);
  expect(reply.mentions).not.toBe(mentions);
  expect(reply.originalMentions).not.toBe(mentions);
  expect(reply.originalMentions).not.toBe(reply.mentions);
  expect(reply.mentions[0]).not.toBe(mentions[0]);
  expect(reply.originalMentions[0]).not.toBe(reply.mentions[0]);
});

test('equal comment editor updates preserve the message mention error', () => {
  const comment = newComment('', '', 10, null, null, 0, {
    remoteId: 10,
    text: 'Hello @Ada',
    mentions: [adaMention],
  });
  comment.mode = 'editing';
  comment.newText = comment.text;
  comment.newMentions = [{ ...adaMention }];
  comment.mentionError = 'Enter a valid mention list.';
  const state = {
    ...basicCommentsState,
    comments: new Map([[comment.localId, comment]]),
    remoteCommentCount: 1,
  };

  const equalText = reducer(
    state,
    actions.updateComment(comment.localId, { newText: comment.newText }),
  );
  const equalMentions = reducer(
    equalText,
    actions.updateComment(comment.localId, {
      newMentions: [{ ...adaMention }],
    }),
  );

  expect(equalMentions.comments.get(comment.localId)?.mentionError).toBe(
    'Enter a valid mention list.',
  );
});

test('only a semantic comment editor change clears its mention error', () => {
  const comment = newComment('', '', 10, null, null, 0, {
    remoteId: 10,
    text: 'Hello @Ada',
    mentions: [adaMention],
  });
  comment.mode = 'editing';
  comment.newText = comment.text;
  comment.newMentions = [{ ...adaMention }];
  comment.mentionError = 'Enter a valid mention list.';
  const state = {
    ...basicCommentsState,
    comments: new Map([[comment.localId, comment]]),
    remoteCommentCount: 1,
  };

  const changed = reducer(
    state,
    actions.updateComment(comment.localId, {
      newMentions: [{ ...adaMention, label: '@Grace' }],
    }),
  );

  expect(changed.comments.get(comment.localId)?.mentionError).toBeUndefined();
});

test('reply mention errors are isolated from sibling updates', () => {
  const first = newCommentReply(11, null, 0, {
    remoteId: 11,
    text: 'Hello @Ada',
    mentions: [adaMention],
  });
  first.mode = 'editing';
  first.newText = first.text;
  first.newMentions = [{ ...adaMention }];
  first.mentionError = 'Enter a valid mention list.';
  const sibling = newCommentReply(12, null, 0, {
    remoteId: 12,
    text: 'Sibling',
  });
  sibling.mentionError = 'Sibling error';
  const comment = newComment('', '', 10, null, null, 0, {
    remoteId: 10,
    replies: new Map([
      [first.localId, first],
      [sibling.localId, sibling],
    ]),
  });
  const state = {
    ...basicCommentsState,
    comments: new Map([[comment.localId, comment]]),
    remoteCommentCount: 1,
  };

  const changed = reducer(
    state,
    actions.updateReply(comment.localId, first.localId, {
      newText: 'Changed',
    }),
  );

  expect(
    changed.comments.get(comment.localId)?.replies.get(11)?.mentionError,
  ).toBeUndefined();
  expect(
    changed.comments.get(comment.localId)?.replies.get(12)?.mentionError,
  ).toBe('Sibling error');
});
