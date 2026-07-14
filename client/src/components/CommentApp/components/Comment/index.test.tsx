import type { Store } from '../../state';
import { mount } from 'enzyme';
import React from 'react';
import { legacy_createStore as createStore } from 'redux';

import { reducer } from '../../state';
import {
  Comment,
  INITIAL_STATE as INITIAL_COMMENTS_STATE,
  newComment,
  newCommentReply,
} from '../../state/comments';
import { INITIAL_STATE as INITIAL_SETTINGS_STATE } from '../../state/settings';
import { LayoutController } from '../../utils/layout';
import CommentEditor from '../CommentEditor';
import CommentComponent from './index';

const ada = {
  key: 'ada',
  userId: '7',
  start: 6,
  end: 10,
  label: '@Ada',
};

const createCommentStore = (comment: Comment): Store =>
  createStore(reducer, {
    comments: {
      ...INITIAL_COMMENTS_STATE,
      comments: new Map([[comment.localId, comment]]),
      remoteCommentCount: comment.remoteId === null ? 0 : 1,
    },
    settings: {
      ...INITIAL_SETTINGS_STATE,
      user: { id: '1', name: 'Current user' },
      mentionedUsers: { '7': { email: 'ada@example.com' } },
    },
  } as any);

const renderComment = (comment: Comment) => {
  const store = createCommentStore(comment);
  const wrapper = mount(
    <CommentComponent
      store={store}
      layout={new LayoutController()}
      user={{ id: '1', name: 'Current user' }}
      comment={comment}
      isFocused
      forceFocus={false}
      isVisible
      mentionedUsers={{ '7': { email: 'ada@example.com' } }}
    />,
  );
  const refresh = () => {
    const current = store.getState().comments.comments.get(comment.localId);
    if (current) wrapper.setProps({ comment: current });
    wrapper.update();
    return current;
  };
  return { store, wrapper, refresh };
};

test('creates a comment with text and occurrences and uses the exact accessible label', () => {
  const comment = newComment('body', '', 1, null, null, 0, {
    mode: 'creating',
  });
  const { store, wrapper, refresh } = renderComment(comment);
  const editor = wrapper
    .find(CommentEditor)
    .filterWhere((node) => node.prop('label') === 'Add a comment');

  editor.invoke('onChange')('Hello @Ada', [ada]);
  refresh();
  wrapper.find('form').first().simulate('submit');

  expect(store.getState().comments.comments.get(1)).toMatchObject({
    mode: 'default',
    text: 'Hello @Ada',
    mentions: [ada],
  });
});

test('cancels a rejected null-PK comment by deleting it', () => {
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: null,
    mode: 'creating',
    text: 'Rejected @Ada',
    mentions: [ada],
  });
  comment.newText = comment.text;
  comment.newMentions = [{ ...ada }];
  comment.mentionError = 'Enter a valid mention list.';
  const { store, wrapper } = renderComment(comment);

  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .first()
    .simulate('click', { preventDefault: jest.fn() });

  expect(store.getState().comments.comments.has(1)).toBe(false);
});

test('cancel restores an existing rejected comment to its saved text and occurrences', () => {
  const savedMention = { ...ada, key: 'saved' };
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    text: 'Saved @Ada',
    mentions: [savedMention],
  });
  comment.mode = 'editing';
  comment.text = 'Rejected @Ada';
  comment.mentions = [{ ...ada, key: 'rejected' }];
  comment.newText = comment.text;
  comment.newMentions = comment.mentions.map((item) => ({ ...item }));
  comment.mentionError = 'Enter a valid mention list.';
  const { store, wrapper, refresh } = renderComment(comment);

  wrapper.find(CommentEditor).invoke('onChange')('Corrected @Ada', [
    { ...ada, key: 'corrected', start: 10, end: 14 },
  ]);
  refresh();
  expect(
    store.getState().comments.comments.get(1)?.mentionError,
  ).toBeUndefined();

  expect(wrapper.find(CommentEditor).prop('label')).toBe('Edit comment');
  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .first()
    .simulate('click', { preventDefault: jest.fn() });

  expect(store.getState().comments.comments.get(1)).toMatchObject({
    mode: 'default',
    text: 'Saved @Ada',
    mentions: [savedMention],
    newText: 'Saved @Ada',
    newMentions: [savedMention],
  });
});

test('cancel restores a confirmed comment baseline after a normal edit', () => {
  const savedMention = {
    ...ada,
    key: 'confirmed',
    start: 10,
    end: 14,
  };
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    mode: 'editing',
    text: 'Confirmed @Ada',
    mentions: [savedMention],
  });
  comment.newText = 'Draft @Ada';
  comment.newMentions = [{ ...ada, key: 'draft' }];
  const { store, wrapper } = renderComment(comment);

  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .first()
    .simulate('click', { preventDefault: jest.fn() });

  expect(store.getState().comments.comments.get(1)).toMatchObject({
    mode: 'default',
    text: 'Confirmed @Ada',
    mentions: [savedMention],
    newText: 'Confirmed @Ada',
    newMentions: [savedMention],
  });
});

test('adds and cancels new replies with text and occurrences together', () => {
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    text: 'Saved comment',
  });
  const { store, wrapper, refresh } = renderComment(comment);
  let editor = wrapper
    .find(CommentEditor)
    .filterWhere((node) => node.prop('label') === 'Add a reply');

  editor.invoke('onChange')('Reply @Ada', [
    { ...ada, start: 6, end: 10, key: 'reply-ada' },
  ]);
  refresh();
  wrapper.find('form').first().simulate('submit');

  let current = store.getState().comments.comments.get(1);
  const added = Array.from(current?.replies.values() || [])[0];
  expect(added).toMatchObject({
    text: 'Reply @Ada',
    mentions: [{ ...ada, start: 6, end: 10, key: 'reply-ada' }],
  });
  expect(current).toMatchObject({ newReply: '', newReplyMentions: [] });

  refresh();
  editor = wrapper
    .find(CommentEditor)
    .filterWhere((node) => node.prop('label') === 'Add a reply');
  editor.invoke('onChange')('Discard @Ada', [
    { ...ada, start: 8, end: 12, key: 'discard-ada' },
  ]);
  refresh();
  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .last()
    .simulate('click', {
      preventDefault: jest.fn(),
      stopPropagation: jest.fn(),
    });
  current = store.getState().comments.comments.get(1);
  expect(current).toMatchObject({ newReply: '', newReplyMentions: [] });
});

test('renders saved comment mentions as non-link snapshot text with metadata', () => {
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    text: 'Hello @Ada',
    mentions: [ada],
  });
  const { wrapper } = renderComment(comment);

  expect(wrapper.find('.comment__mention').text()).toBe('@Ada');
  expect(wrapper.find('.comment__mention').props()).toMatchObject({
    'data-mention-user-id': '7',
    'data-mention-email': 'ada@example.com',
  });
  expect(wrapper.find('.comment__mention').is('a')).toBe(false);
});

test('keeps comment and reply rejection errors isolated in their own editors', () => {
  const reply = newCommentReply(2, null, 0, {
    remoteId: 2,
    text: 'Reply @Ada',
    mentions: [{ ...ada, start: 6, end: 10, key: 'reply-ada' }],
  });
  reply.mode = 'editing';
  reply.newText = reply.text;
  reply.newMentions = reply.mentions.map((item) => ({ ...item }));
  reply.mentionError = 'Reply mention error';
  const comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    text: 'Hello @Ada',
    mentions: [ada],
    replies: new Map([[reply.localId, reply]]),
  });
  comment.mode = 'editing';
  comment.newText = comment.text;
  comment.newMentions = comment.mentions.map((item) => ({ ...item }));
  comment.mentionError = 'Comment mention error';
  const { wrapper } = renderComment(comment);
  const editors = wrapper.find(CommentEditor);

  expect(
    editors
      .filterWhere((node) => node.prop('label') === 'Edit comment')
      .prop('error'),
  ).toBe('Comment mention error');
  expect(
    editors
      .filterWhere((node) => node.prop('label') === 'Edit reply')
      .prop('error'),
  ).toBe('Reply mention error');
});
