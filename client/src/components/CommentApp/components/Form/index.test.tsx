import { mount } from 'enzyme';
import React from 'react';

import { basicCommentsState } from '../../__fixtures__/state';
import { newComment, newCommentReply } from '../../state/comments';
import { serializeMentionOccurrences } from '../../utils/mentions';

import { CommentFormComponent, CommentFormSetComponent } from './index';

test('outputs canonical mention occurrences as JSON', () => {
  const comment = basicCommentsState.comments.get(1);
  expect(comment).toBeDefined();

  if (!comment) return;

  const wrapper = mount(
    <CommentFormComponent comment={comment} formNumber={0} prefix="comments" />,
  );

  expect(wrapper.find('input[name="comments-0-mentions"]').prop('value')).toBe(
    JSON.stringify(serializeMentionOccurrences(comment.mentions)),
  );
});

test('outputs canonical mentions for every unchanged comment and reply form', () => {
  const mention = {
    key: 'mention-ada',
    userId: '7',
    start: 6,
    end: 10,
    label: '@Ada',
  };
  const reply = newCommentReply(2, null, 0, {
    remoteId: 20,
    text: 'Reply @Ada',
    mentions: [{ ...mention, start: 6 }],
  });
  const unchanged = newComment('path', '', 1, null, null, 0, {
    remoteId: 10,
    text: 'Hello @Ada',
    mentions: [mention],
    replies: new Map([[reply.localId, reply]]),
  });
  const withoutMentions = newComment('path', '', 3, null, null, 0, {
    remoteId: null,
    text: 'No mentions',
  });

  const wrapper = mount(
    <CommentFormSetComponent
      comments={[unchanged, withoutMentions]}
      remoteCommentCount={1}
    />,
  );

  expect(wrapper.find('input[name="comments-0-mentions"]').prop('value')).toBe(
    JSON.stringify(serializeMentionOccurrences([mention])),
  );
  expect(
    wrapper.find('input[name="comments-0-replies-0-mentions"]').prop('value'),
  ).toBe(JSON.stringify(serializeMentionOccurrences(reply.mentions)));
  expect(wrapper.find('input[name="comments-1-mentions"]').prop('value')).toBe(
    '[]',
  );
});

test('preserves number and null primary keys in participating hidden forms', () => {
  const savedReply = newCommentReply(2, null, 0, {
    remoteId: 20,
    text: 'Saved reply',
  });
  const unsavedReply = newCommentReply(3, null, 0, {
    remoteId: null,
    text: 'Unsaved reply',
  });
  const saved = newComment('path', '', 1, null, null, 0, {
    remoteId: 10,
    text: 'Saved',
    replies: new Map([
      [savedReply.localId, savedReply],
      [unsavedReply.localId, unsavedReply],
    ]),
  });
  const unsaved = newComment('path', '', 4, null, null, 0, {
    remoteId: null,
    text: 'Unsaved',
  });

  const wrapper = mount(
    <CommentFormSetComponent
      comments={[saved, unsaved]}
      remoteCommentCount={1}
    />,
  );

  expect(wrapper.find('input[name="comments-0-id"]').prop('value')).toBe(10);
  expect(wrapper.find('input[name="comments-1-id"]').prop('value')).toBe('');
  expect(
    wrapper.find('input[name="comments-0-replies-0-id"]').prop('value'),
  ).toBe(20);
  expect(
    wrapper.find('input[name="comments-0-replies-1-id"]').prop('value'),
  ).toBe('');
});
