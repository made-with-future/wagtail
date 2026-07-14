import type { Store } from '../../state';
import { mount } from 'enzyme';
import React from 'react';
import { legacy_createStore as createStore } from 'redux';

import { reducer } from '../../state';
import {
  Comment,
  CommentReply,
  INITIAL_STATE as INITIAL_COMMENTS_STATE,
  newComment,
  newCommentReply,
} from '../../state/comments';
import { INITIAL_STATE as INITIAL_SETTINGS_STATE } from '../../state/settings';
import CommentEditor from '../CommentEditor';
import CommentReplyComponent from './index';

const ada = {
  key: 'ada',
  userId: '7',
  start: 6,
  end: 10,
  label: '@Ada',
};

const setup = (reply: CommentReply) => {
  const comment: Comment = newComment('body', '', 1, null, null, 0, {
    remoteId: 1,
    text: 'Parent',
    replies: new Map([[reply.localId, reply]]),
  });
  const store = createStore(reducer, {
    comments: {
      ...INITIAL_COMMENTS_STATE,
      comments: new Map([[comment.localId, comment]]),
      remoteCommentCount: 1,
    },
    settings: {
      ...INITIAL_SETTINGS_STATE,
      mentionedUsers: { '7': { email: 'ada@example.com' } },
    },
  } as any) as Store;
  const wrapper = mount(
    <CommentReplyComponent
      comment={comment}
      reply={reply}
      store={store}
      user={{ id: '1', name: 'Current user' }}
      isFocused
      mentionedUsers={{ '7': { email: 'ada@example.com' } }}
    />,
  );
  const refresh = () => {
    const nextComment = store.getState().comments.comments.get(1);
    const nextReply = nextComment?.replies.get(reply.localId);
    if (nextComment && nextReply) {
      wrapper.setProps({ comment: nextComment, reply: nextReply });
      wrapper.update();
    }
    return nextReply;
  };
  return { comment, store, wrapper, refresh };
};

test('edits and saves a reply with occurrences using the exact label', () => {
  const reply = newCommentReply(2, { id: '1', name: 'Current user' }, 0, {
    remoteId: 2,
    mode: 'editing',
    text: 'Saved reply',
  });
  reply.newText = reply.text;
  const { store, wrapper, refresh } = setup(reply);
  const editor = wrapper.find(CommentEditor);

  expect(editor.prop('label')).toBe('Edit reply');
  editor.invoke('onChange')('Reply @Ada', [ada]);
  refresh();
  wrapper.find('form').simulate('submit');

  expect(
    store.getState().comments.comments.get(1)?.replies.get(2),
  ).toMatchObject({
    mode: 'default',
    text: 'Reply @Ada',
    mentions: [ada],
  });
});

test('cancel restores a saved rejected reply to original text and occurrences', () => {
  const savedMention = { ...ada, key: 'saved' };
  const reply = newCommentReply(2, { id: '1', name: 'Current user' }, 0, {
    remoteId: 2,
    mode: 'editing',
    text: 'Saved @Ada',
    mentions: [savedMention],
  });
  reply.text = 'Rejected @Ada';
  reply.mentions = [{ ...ada, key: 'rejected' }];
  reply.newText = reply.text;
  reply.newMentions = reply.mentions.map((item) => ({ ...item }));
  reply.mentionError = 'Enter a valid mention list.';
  const { store, wrapper, refresh } = setup(reply);

  wrapper.find(CommentEditor).invoke('onChange')('Corrected @Ada', [
    { ...ada, key: 'corrected', start: 10, end: 14 },
  ]);
  refresh();
  expect(
    store.getState().comments.comments.get(1)?.replies.get(2)?.mentionError,
  ).toBeUndefined();

  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .simulate('click', { preventDefault: jest.fn() });

  expect(
    store.getState().comments.comments.get(1)?.replies.get(2),
  ).toMatchObject({
    mode: 'default',
    text: 'Saved @Ada',
    mentions: [savedMention],
    newText: 'Saved @Ada',
    newMentions: [savedMention],
  });
});

test('cancel restores a confirmed reply baseline after a normal edit', () => {
  const savedMention = {
    ...ada,
    key: 'confirmed',
    start: 10,
    end: 14,
  };
  const reply = newCommentReply(2, { id: '1', name: 'Current user' }, 0, {
    remoteId: 2,
    mode: 'editing',
    text: 'Confirmed @Ada',
    mentions: [savedMention],
  });
  reply.newText = 'Draft @Ada';
  reply.newMentions = [{ ...ada, key: 'draft' }];
  const { store, wrapper } = setup(reply);

  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .simulate('click', { preventDefault: jest.fn() });

  expect(
    store.getState().comments.comments.get(1)?.replies.get(2),
  ).toMatchObject({
    mode: 'default',
    text: 'Confirmed @Ada',
    mentions: [savedMention],
    newText: 'Confirmed @Ada',
    newMentions: [savedMention],
  });
});

test('cancel deletes a rejected null-PK reply', () => {
  const reply = newCommentReply(2, { id: '1', name: 'Current user' }, 0, {
    remoteId: null,
    mode: 'editing',
    text: 'Rejected @Ada',
    mentions: [ada],
  });
  reply.newText = reply.text;
  reply.newMentions = reply.mentions.map((item) => ({ ...item }));
  reply.mentionError = 'Enter a valid mention list.';
  const { store, wrapper } = setup(reply);

  wrapper
    .find('button')
    .filterWhere((node) => node.text() === 'Cancel')
    .simulate('click', { preventDefault: jest.fn() });

  expect(store.getState().comments.comments.get(1)?.replies.has(2)).toBe(false);
});

test('renders saved reply mentions as non-link snapshot text with metadata', () => {
  const reply = newCommentReply(2, null, 0, {
    remoteId: 2,
    text: 'Reply @Ada',
    mentions: [ada],
  });
  const { wrapper } = setup(reply);

  expect(wrapper.find('.comment__mention').text()).toBe('@Ada');
  expect(wrapper.find('.comment__mention').is('a')).toBe(false);
  expect(wrapper.find('.comment__mention').props()).toMatchObject({
    'data-mention-user-id': '7',
    'data-mention-email': 'ada@example.com',
  });
});
